# ADR-0012: 游标续翻分页、阻塞超时收敛、空闲心跳与管道批处理网关 (Resilience, Pipeline and Safe Blocking Architecture)

- **状态**: 已采纳 (Accepted)
- **决策日期**: 2026-10-14

---

## 背景与问题陈述

在将服务部署到大模型长期会话（如 Claude Desktop / Cursor 长时间常驻）及海量键空间生产环境时，识别出以下关键可用性痛点与安全隐患：
1. **键空间扫描无法续翻**：`redis_scan_keys` 返回了 `cursor` 但未接收 `cursor` 参数，导致每次扫描均从 0 开始，海量键场景下模型无法翻查后续页面；
2. **阻塞式读取命令挂死 MCP 进程**：模型在执行消息队列读取（如 `BLPOP mylist 0`）时常使用 `0` 超时（无限期等待），导致底层异步 Socket 永久挂起，阻塞整个服务进程；
3. **桌面端长连接静默断连崩溃**：单机连接池未配置空闲探活与超时重试，常驻桌面会话闲置数小时后遭遇防火墙丢弃或服务端关闭时，偶发抛出 `ConnectionResetError`；
4. **单行命令多轮交互延迟过大**：多关联操作需模型发起多次 MCP 往返，严重拖慢推理响应速度。

---

## 决策内容

确立以下系统韧性与执行增强决策：

1. **游标续翻扫描 (Cursor-Resumable Scan)**：
   - `redis_scan_keys` 增补参数 `cursor: int = 0`；
   - 单机模式：依据传入游标恢复底层遍历，输出更新后的下一页游标；
   - 集群模式：分片集群无全局单一游标，若模型传入 `cursor > 0` 则优雅自适应返回当前批次并附加提示信息，避免报错崩溃。

2. **零超时阻塞指令主动安全防线 (Zero-Timeout Blocking Guard)**：
   - 在 `SecurityGuard` 中识别阻塞式读取命令（`BLPOP`, `BRPOP`, `BRPOPLPUSH`, `BLMOVE`, `BZPOPMIN`, `BZPOPMAX`）；
   - 对其超时参数实施安全范围收敛：若超时为 `0` 强制改写为 `2` 秒；若超时大于 `5` 秒强制限制为最大 `5` 秒；
   - 在执行信封中显式回传改写安全提示，杜绝进程挂死风险。

3. **连接池空闲心跳与自愈 (Connection Idle Heartbeat)**：
   - 在 `ConnectionRegistry` 单机连接池初始化中默认配置 `health_check_interval=30` 与 `retry_on_timeout=True`；
   - 静默消除 TCP 半开与空闲断开引发的偶发连接异常。

4. **管道批处理网关 (Pipeline Batch Gateway)**：
   - `redis_execute_command` 新增支持多命令列表参数 `commands: list[str] | None = None`（上限 20 条）；
   - **全批次前置强校验 (Fail-Close)**：若批次中有任一条命令命中破坏性阻断或未授权写门禁，整批直接拒绝执行；
   - **删除二次确认合并**：若批次包含 `DEL/UNLINK` 且未传 `confirm=True`，返回待确认拦截并汇总待删键名；
   - **底层单次 Pipeline 执行**：前置预检全部通过后，在单一底层 Pipeline 中执行并返回聚合信封 `{"total_commands": N, "results": [...]}`。

5. **大集合全量读取软提示**：
   - 在网关 Docstring 中提示模型对未知键空间优先使用 `HSCAN`/`SSCAN` 切片读取，规避 O(N) 巨型数据对 Redis 单线程主循环的阻塞。

---

## 影响与权衡

- **积极收益**：
  - 彻底打通海量数据扫描翻页链路；
  - 彻底规避大模型阻塞式命令导致 MCP 进程假死的灾难性隐患；
  - 极大增强桌面长连接会话的稳定性；
  - 多命令批处理将交互网络与推理延迟降低数倍。
- **潜在代价与权衡**：
  - 阻塞式命令超时被缩短至 2~5 秒，若队列无新数据会返回空结果，但避免了挂死。
