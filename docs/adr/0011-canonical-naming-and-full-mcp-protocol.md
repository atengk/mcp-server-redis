# ADR-0011: 规范动宾工具契约、无别名纯净暴露与全 MCP 协议矩阵 (Canonical Tooling and Full MCP Protocol Matrix)

- **状态**: 已采纳 (Accepted)
- **决策日期**: 2026-10-14

---

## 背景与问题陈述

在 v2.0 确立的混合命令网关架构（ADR-0010）运行良好，但在深入实践与协议演进中识别出以下关键优化空间：
1. **工具命名规范性与纯净度**：历史工具名 `redis_command`（纯名词）与 `redis_key_inspect`（对象-动作语序）违背了 ADR-0004 确立的“前缀_动作_对象（Prefix_Verb_Object）”统一动宾规范。同时，若引入过多别名（Aliases）会污染大模型可用工具列表，增加模型意图漂移概率；
2. **实例状态探查的 Token 浪费**：模型通过 `redis_execute_command("INFO")` 探查实例运行状态时，Redis 原生返回数百行非结构化纯文本（消耗 1500~2000 Tokens），对上下文窗口极不经济；
3. **键空间探查的 N+1 往返风暴**：模型排查业务 Key 空间时，通常需要同时获知 Key 的数据类型与过期时间。先调用 `redis_scan_keys` 再逐键调用 `redis_inspect_key` 会引发严重的多轮工具调用与网络往返延迟；
4. **MCP 协议形态单一**：服务仅实现了 FastMCP 的 `tools` 维度，未利用 MCP 规范中的 `resources`（只读系统快照）与 `prompts`（标准化运维排查模版），限制了在现代 MCP 客户端（如 Cursor、Claude Desktop）中的原生体验。

---

## 决策内容

确立以下核心架构与协议优化决策：

1. **规范动宾契约与无别名纯净暴露 (Canonical Tools & No-Alias Registration)**：
   - 全局收敛为 4 个严格遵循动宾规范的核心 MCP 工具：
     - `redis_execute_command`：核心命令网关（原 `redis_command` 升级）；
     - `redis_inspect_key`：单键多维诊断（原 `redis_key_inspect` 升级）；
     - `redis_scan_keys`：聚合非阻塞键空间扫描；
     - `redis_list_connections`：多连接配置与实例检视；
   - 协议暴露层面：**坚决不注册历史别名工具**，工具列表严格保持 4 个，保证大模型可用工具上下文纯净，杜绝同义工具干扰；内部模块名统一对齐为 `tools/connections.py`；
   - Python 代码层面：模块内提供 `redis_command = redis_execute_command` 与 `redis_key_inspect = redis_inspect_key` 符号兼容映射，保障库内既有代码平滑过渡。

2. **命令网关层智能 INFO 结构化器 (Smart INFO Parser)**：
   - 在 `SafeSerializer` 中对 `INFO [section]` 执行结果实施智能语义解析；
   - 将多段式纯文本清洗为分 Section 的嵌套字典，对整型与浮点型数值自动推导为 `int` / `float`，剔除冗余注释与空行；单参数如 `INFO memory` 时直接返回平铺紧凑字典，Token 消耗降低 60% 以上。

3. **双字段兼顾的轻量复合元数据扫描 (Metadata-Enriched Scan)**：
   - `redis_scan_keys` 新增参数 `include_meta: bool = False`；
   - 默认（`False`）：维持原有字符串列表契约；
   - 启用（`True`）：在内部利用 `asyncio.gather` 并发批量拉取匹配 Key 的 `TYPE` 与 `TTL`，并在返回结构中增加 `entries: [{"key": ..., "type": ..., "ttl": ...}, ...]` 列表，同时保留 `keys: list[str]`，以零破坏性消除大模型 N+1 调用风暴。

4. **坚守零外部依赖红线 (Zero-New-Deps Invariant)**：
   - 坚决不引入任何额外第三方依赖（如 `orjson` 或向量库）；完全依托 Python 标准库与现有 `redis-py`、`pydantic` 2.x、`mcp` 依赖栈，保持生产级超低维护面与跨平台纯粹性。

5. **全 MCP 协议矩阵挂载 (Tools + Resources + Prompts)**：
   - **只读快照资源 (Resources)**：
     - `redis://{connection}/info` 及 `redis://info`：实例综合健康与关键运行指标快照；
     - `redis://{connection}/slowlog` 及 `redis://slowlog`：最新慢查询日志快照（上限 10 条）；
   - **诊断引导提示词 (Prompts)**：
     - `redis_diagnose_memory`：标准化内存泄漏、碎片率及大 Key 排查 SOP；
     - `redis_analyze_slowlog`：标准化慢查询抓取与高耗时指令优化排查 SOP。

---

## 影响与权衡

- **积极收益**：
  - 工具命名达到 100% 工业级规范统一，对外无同义别名冗余干扰；
  - 终结了模型读取 `INFO` 的巨大 Token 消耗与扫描键后的 N+1 工具往返；
  - 全面激活 MCP Resources 与 Prompts，使服务成为首个功能完备的生产级 Redis MCP 中枢；
  - 严格保持依赖零新增，保障系统轻量化。
- **潜在代价与权衡**：
  - 移除了外部工具别名注册，依赖原 `redis_command` 或 `redis_key_inspect` 工具名的旧会话需刷新以采用新规范动宾名称。
