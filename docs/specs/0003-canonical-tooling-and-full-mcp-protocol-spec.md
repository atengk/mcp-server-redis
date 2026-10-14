# 需求规格说明书 (Spec): 规范动宾工具契约、无别名纯净暴露与全 MCP 协议矩阵升级

- **关联工单**: [#20](https://github.com/atengk/mcp-server-redis/issues/20)
- **状态**: 就绪可执行 (`ready-for-agent`)

- **创建日期**: 2026-10-14
- **遵循决策**: [ADR-0011 (规范动宾工具契约、无别名纯净暴露与全 MCP 协议矩阵)](../adr/0011-canonical-naming-and-full-mcp-protocol.md)

---

## Problem Statement

在大语言模型（LLM）通过模型上下文协议（MCP）操作与诊断 Redis 实例时，当前服务存在以下痛点：
1. **工具命名不一致与提示词歧义**：历史工具名称采用了名词（`redis_command`）或对象-动词乱序（`redis_key_inspect`），偏离了工业级标准的“前缀_动作_对象（Prefix_Verb_Object）”动宾规范，且如果注册同义别名会污染工具列表，引发大模型选工具时的意图漂移；
2. **实例状态分析的 Token 严重浪费**：模型通过命令网关下发 `INFO` 探查 Redis 整体健康状态时，返回数百行非结构化纯文本注释与指标，单次往返消耗 1500~2000 Tokens，严重挤占模型有限的上下文窗口；
3. **键空间诊断的 N+1 往返延迟**：在探查匹配特定模式的键时，模型通常需要同时获知键的类型与 TTL；目前模型必须先通过 `redis_scan_keys` 拿到键名，再发起多轮单键诊断调用，造成显著的 N+1 工具往返开销；
4. **MCP 协议形态单一**：服务仅提供了 `tools` 维度能力，尚未挂载 MCP 规范的 `resources`（只读系统快照）与 `prompts`（标准化排障工作流），限制了现代 MCP 客户端的原生集成体验。

---

## Solution

在坚守零新增第三方依赖（Zero-New-Deps）与工业级双重写门禁的前提下，对服务端进行协议契约标准化与全矩阵能力升级：
1. **统一动宾工具契约与无别名纯净暴露**：
   - 将核心工具收敛且规范重命名为 4 个：`redis_execute_command`、`redis_inspect_key`、`redis_scan_keys`、`redis_list_connections`；
   - 对外绝不注册同义别名工具，保持模型可用工具列表绝对精简纯净；内部连接模块对齐重构为 `tools/connections.py`；
2. **命令网关层智能 INFO 结构化器**：
   - 在序列化层透明拦截并解析 `INFO [section]` 执行结果，自动清洗并转换为按 Section 分层的嵌套紧凑字典，自适应推导 `int` 与 `float` 数值类型，减少 60%+ 的 Token 消耗；
3. **轻量复合元数据扫描（消除 N+1）**：
   - `redis_scan_keys` 新增 `include_meta: bool = False` 参数；启用时内部并发拉取并返回键的基础类型（`type`）与过期时间（`ttl`），以双字段兼容信封格式（同时包含 `keys: list[str]` 与 `entries: list[dict]`）彻底切断 N+1 往返；
4. **全 MCP 协议矩阵挂载（Resources + Prompts）**：
   - 挂载 `redis://{connection}/info` 与 `redis://{connection}/slowlog` 两个高频只读快照资源；
   - 挂载 `redis_diagnose_memory` 与 `redis_analyze_slowlog` 两个生产级排障引导 Prompt 模板。

---

## User Stories

1. 作为一个 AI Agent，我希望通过统一且语义明确的动宾工具 `redis_execute_command` 下发原生 Redis 命令，以便于遵循标准的动作-对象认知模型。
2. 作为一个 AI Agent，我希望通过 `redis_inspect_key` 工具获取单个键的多维元数据，以便于符合规范的动宾调用直觉。
3. 作为一个 AI Agent，在获取工具列表（`tools/list`）时，我希望看到数量严格受控且无同义别名的 4 个核心工具，以便于杜绝工具选择混乱和意图漂移。
4. 作为一个使用旧版本代码的开发者，我希望在 Python 模块内部直接调用 `redis_command` 或 `redis_key_inspect` 时能够平滑映射至新规范函数，以便于保证库内调用的源码级向后兼容。
5. 作为一个 AI Agent，当在 `redis_execute_command` 中执行 `INFO` 命令时，我希望收到按 Section 分组且数值自动转换为数字类型的紧凑 JSON 字典，以便于低成本且精准地分析 Redis 运行状态。
6. 作为一个 AI Agent，当在 `redis_execute_command` 中执行特定分节命令（如 `INFO memory`）时，我希望收到仅包含该分节指标的平铺紧凑字典，以便于最小化上下文消耗。
7. 作为一个 AI Agent，当在 `redis_scan_keys` 中传入 `include_meta=True` 时，我希望一次性获得每个匹配键的键名、数据类型与过期时间，以便于免除后续循环调用单键诊断工具的 N+1 开销。
8. 作为一个既有系统集成者，当 `redis_scan_keys` 开启 `include_meta=True` 时，我希望返回的 `keys` 字段依然保持为纯字符串列表（同时新增 `entries` 复合列表），以便于已有依赖 `keys` 的代码逻辑不会出现类型错误。
9. 作为一个既有系统集成者，当 `redis_scan_keys` 保持默认 `include_meta=False` 时，我希望它的返回结构与性能开销与原版本完全一致，以便于零成本平滑运行。
10. 作为一个使用现代 MCP 客户端（如 Claude Desktop 或 Cursor）的用户，我希望直接读取 `redis://{connection}/info` 资源，以便于在不触发工具调用的前提下将当前 Redis 实例指标作为只读上下文注入 Prompt。
11. 作为一个使用现代 MCP 客户端的用户，我希望直接读取 `redis://{connection}/slowlog` 资源，以便于快速检视最近 10 条高耗时命令。
12. 作为一个使用现代 MCP 客户端的用户，我希望在未指定连接别名时直接访问 `redis://info` 或 `redis://slowlog`，系统自动绑定并呈现默认连接的快照。
13. 作为一个运维人员，我希望在客户端中触发预置的 `redis_diagnose_memory` Prompt，以便于引导大模型按照“内存指标核对 -> 碎片率分析 -> 大 Key 扫描 -> 优化建议”的标准化 SOP 进行自动化诊断。
14. 作为一个运维人员，我希望在客户端中触发预置的 `redis_analyze_slowlog` Prompt，以便于引导大模型按照“拉取慢查快照 -> 高频命令特征归类 -> 提出索引与分片调优策略”的标准化 SOP 执行排查。
15. 作为一个系统维护人员，我希望服务端在引入以上全部增强的同时保持零新增第三方依赖，以便于杜绝供应链安全隐患与跨平台编译问题。

---

## Implementation Decisions

### 1. 工具命名与协议纯净度
- 对外暴露工具严格限定为 4 个规范动宾名称：
  - `redis_execute_command`
  - `redis_inspect_key`
  - `redis_scan_keys`
  - `redis_list_connections`
- 服务装配层坚决不注册 `redis_command` 与 `redis_key_inspect` 别名工具，彻底保持 MCP 工具列表精简纯净；
- 原连接检视模块重命名为标准名词 `connections.py`，导出 `register_connection_tools` 与 `redis_list_connections`；
- Python 模块层导出符号兼容别名：`redis_command = redis_execute_command`，`redis_key_inspect = redis_inspect_key`。

### 2. 智能 INFO 结构化器 (Smart INFO Parser)
- 序列化核心新增 INFO 文本解析逻辑。当命令网关执行的命令动词为 `INFO` 且返回纯文本时自动触发；
- 解析规则：
  - 自动跳过 `#` 开头的注释行与空行；
  - 遇到 `# <Section>` 时创建对应的小写分组键；
  - 针对 `key:value` 键值对，若值可转为整型或浮点型，转换为数值类型；否则保留为字符串；
  - 若调用时传入了具体的分节参数（如 `INFO memory`），直接返回该节的平铺字段字典；若未传参数则返回按节嵌套的分层字典。

### 3. 轻量复合元数据扫描 (Metadata-Enriched Scan)
- `redis_scan_keys` 新增布尔参数 `include_meta: bool = False`；
- 内部调度机制：
  - 扫描获取到当前批次的有效键后，若 `include_meta=True`，使用并发协程（如 `asyncio.gather`）并发获取每个键的 `TYPE` 与 `TTL`；
  - 单键并发查询在单机与 Redis Cluster 模式下均安全运作（单键命令不跨槽，杜绝 `CROSSSLOT` 风险）；
- 返回信封格式：
  - 始终包含 `keys: list[str]` 字符串列表；
  - 当 `include_meta=True` 时，额外附加 `entries: list[dict[str, Any]]`，每个字典项包含 `{"key": str, "type": str, "ttl": int}`。

### 4. MCP Resources 挂载
- 注册只读资源 URI 模式：
  - `redis://{connection}/info` 与缺省别名 `redis://info`（返回 JSON 格式实例状态）；
  - `redis://{connection}/slowlog` 与缺省别名 `redis://slowlog`（返回最近至多 10 条慢日志快照）；
- 资源处理函数严格保持无状态与只读，直接调用底层 `ConnectionRegistry` 路由执行。

### 5. MCP Prompts 挂载
- 注册诊断提示词模板：
  - `redis_diagnose_memory(connection: str = None)`：输出系统引导词与排查步骤指引；
  - `redis_analyze_slowlog(connection: str = None)`：输出慢日志分析 SOP 引导。

### 6. 依赖克制策略
- 严禁向 `pyproject.toml` 添加任何新外部运行依赖，全部能力均基于标准库与现有依赖栈实现。

---

## Testing Decisions

### 什么是好测试
- 仅测试外部可观察的行为（External Behavior）、返回数据模型（Schema & Envelope）与契约一致性，不测试内部私有变量或实现细节；
- 重点覆盖边界情况：空键空间、键不存在、非法数据类型过滤、Cluster 模式兼容性、数值类型自动推导精度、以及 `include_meta` 打开与关闭时的一致性。

### 测试范围与模块
- **命令网关与 INFO 序列化**：验证 `redis_execute_command` 在执行普通命令、高危破坏性命令、DEL 二次确认、跨槽错误、以及 `INFO` 分节解析时的正确性；
- **键空间扫描与复合元数据**：验证 `redis_scan_keys` 在 `include_meta=False` 与 `include_meta=True` 下的信封形态、并发 TTL/Type 探查及截断状态；
- **单键诊断规范化**：验证 `redis_inspect_key` 对存在键与不存在键的多维诊断输出；
- **连接管理与模块导出**：验证 `redis_list_connections` 与 `tools/connections.py` 模块的元数据脱敏；
- **服务装配与 MCP 协议契约**：验证服务暴露的工具严格为 4 个（无别名注册），验证 Resources 与 Prompts 的挂载与执行。

### 参考先例 (Prior Art)
- `tests/test_command.py`：测试网关门禁与执行信封；
- `tests/test_serializer.py`：测试数据截断与安全编码；
- `tests/test_keys.py`：测试聚合扫描游标与大 Key 探查；
- `tests/test_server.py`：测试 FastMCP 装配与 CLI 生命周期。

---

## Out of Scope

- 不引入任何外部二进制/C 扩展加速库（如 `orjson`）；
- 不在此版本引入专有向量数据库扩展（如 RedisVL）；
- 不支持全量大 Key 阻塞式扫描采样（如全库 `MEMORY USAGE` 遍历），只在扫描结果集内并发获取轻量元数据（`TYPE` 和 `TTL`）；
- 不支持在客户端通过 MCP 写入操作修改连接配置；
- 不暴露历史工具别名至 MCP 注册表。

---

## Further Notes

- 本次变更属于大版本规范演进，完全对齐 [ADR-0011](../adr/0011-canonical-naming-and-full-mcp-protocol.md)；
- 实施完成后需同步更新 `README.md` 与相关文档中工具名称与用法示例。
