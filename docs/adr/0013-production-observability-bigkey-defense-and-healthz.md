# ADR-0013: 连接池超时基线、结构化审计日志、BigKey 内存防爆与云原生探活 (Production Observability, BigKey In-Flight Defense and Healthz)

- **状态**: 已采纳 (Accepted)
- **决策日期**: 2026-10-14

---

## 背景与问题陈述

在推进生产落地、企业合规审计与云原生（Kubernetes）部署过程中，识别出以下深层治理与防御诉求：
1. **连接池与网络超时缺乏工业级默认基线**：连接池默认无界膨胀，套接字超时未设防，发生网络静默丢包时会话可能无限挂起；
2. **缺乏结构化命令审计日志**：大模型对数据库的操作在金融与合规场景下必须具备可追溯的审计记录（Audit Trail），且 STDIO 模式下严禁日志输出污染标准输出管道；
3. **无界集合全量读取阻塞 Redis 主事件循环**：当模型调度 `HGETALL` 或 `SMEMBERS` 读取百万级 BigKey 时，数据在到达 Python 切片序列化器之前就已导致 Redis 单线程严重卡死；
4. **容器编排缺少标准化探针接口**：SSE 传输模式下缺少轻量级 HTTP `/healthz` 探活路由，无法精准配合 K8s Readiness/Liveness 切流探测；
5. **DBA 诊断场景仍缺客户端泄露排查与 BigKey 调优 SOP**。

---

## 决策内容

确立以下生产级深度治理与防护决策：

1. **连接池规格与套接字超时默认基线 (Connection Pool Sizing & Timeouts)**：
   - 保底默认：单连接池 `max_connections=50`、`socket_connect_timeout=5.0s`、`socket_timeout=10.0s`；
   - 开放环境变量（`MCP_REDIS_MAX_CONNECTIONS`、`MCP_REDIS_SOCKET_TIMEOUT`、`MCP_REDIS_SOCKET_CONNECT_TIMEOUT`）与配置文件覆盖通道。

2. **可插拔结构化命令审计日志 (Structured Audit Trail)**：
   - 引入专用审计记录模块（`core/audit.py`），以单行 JSONL 格式输出 `timestamp`、`connection`、`db`、`command`、`duration_ms`、`status` 与 `keys`；
   - **STDIO 管道绝对物理隔离**：运行在 stdio 模式时若指定输出到 stdout，强制重定向至 `sys.stderr`，绝不污染 JSON-RPC 通信帧；
   - **机密字段自动掩码**：对 `AUTH` 命令密码一律脱敏为 `***`，不持久化大段业务值数据。

3. **巨型集合全量读取防爆预检 (BigKey In-Flight Defense)**：
   - 对 `HGETALL`、`SMEMBERS`、`LRANGE 0 -1`、`ZRANGE 0 -1`、`ZREVRANGE 0 -1` 等无界全量读取命令，网关在下发前先通过 O(1) 指令（`HLEN`、`SCARD`、`LLEN`、`ZCARD`）探测集合大小；
   - 默认安全阈值设为 2,000 项（支持通过 `MCP_REDIS_MAX_UNBOUNDED_READ_ITEMS` 动态配置）；
   - 若基数超限，立即安全拦截并返回引导信封，明确提示当前项数并推荐改用 `HSCAN`/`SSCAN` 切片读取，彻底杜绝打崩 Redis 单线程。

4. **SSE 云原生探活路由与容器健康检查 (Kubernetes Healthz & Probes)**：
   - 在 SSE 传输模式下自动挂载 `/health` 与 `/healthz` 轻量 HTTP 端点；
   - 发起带 1.0s 超时的默认 Redis `PING` 探活：健康返回 HTTP 200，断连返回 HTTP 503；
   - `Dockerfile` 同步配置使用 Python 标准库探测的 `HEALTHCHECK` 指令。

5. **诊断资源与 Prompt 矩阵扩充**：
   - 新增只读资源：`redis://{connection}/clients` 与 `redis://clients`，清洗 `CLIENT LIST` 并对 IP 末段脱敏（如 `192.168.1.***`）；
   - 新增排障 Prompt：`redis_troubleshoot_bigkeys`，标准化大 Key 采样、内存评估与渐进式迁移调优 SOP。

---

## 影响与权衡

- **积极收益**：
  - 彻底规避网络丢包挂起与连接数无界膨胀风险；
  - 满足企业安全团队对大模型操作数据库的审计合规硬指标；
  - 在执行源头彻底杜绝 BigKey 全量拉取对 Redis 主循环的卡死风险；
  - 真正实现开箱即用的 K8s 云原生部署探活能力。
- **潜在代价与权衡**：
  - 对特定无界读取命令在执行前增加了 1 次耗时 < 1ms 的 O(1) 基数探查 RTT，用于换取主线程安全。
