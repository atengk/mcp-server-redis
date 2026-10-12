# 需求规格说明书 (Spec): mcp-server-redis 混合命令网关重构与协议工具精简

- **关联工单**: [#14](https://github.com/atengk/mcp-server-redis/issues/14)
- **子任务工单**:
  - [#15](https://github.com/atengk/mcp-server-redis/issues/15) `feat: 核心安全守卫升级与命令分类裁决器` (Blocked by: None)
  - [#16](https://github.com/atengk/mcp-server-redis/issues/16) `feat: 结果序列化增强与大集合切片截断守卫` (Blocked by: None)
  - [#17](https://github.com/atengk/mcp-server-redis/issues/17) `feat: redis_command 核心网关端到端实现与信封包装` (Blocked by: #15, #16)
  - [#18](https://github.com/atengk/mcp-server-redis/issues/18) `refactor: 协议工具集精简收敛与 15 个遗留专有工具下线` (Blocked by: #17)
  - [#19](https://github.com/atengk/mcp-server-redis/issues/19) `docs: 工程配置、使用文档与 README 全面同步升级` (Blocked by: #18)
- **状态**: 就绪可执行 (`ready-for-agent`)
- **创建日期**: 2026-10-12
- **遵循决策**: ADR-0010 (混合命令网关架构与协议工具精简)

---

## 问题陈述 (Problem Statement)

在大语言模型（LLM）通过模型上下文协议（MCP）与 Redis 交互时，当前 v1.x 版本按 Redis 数据结构（String, Hash, List, Set, ZSet, Stream 等）拆分出 18 个专有 RPC 工具的做法存在显著局限：
1. **指令集覆盖严重不足与工具无限膨胀**：Redis 官方拥有 300 多个核心命令及丰富的扩展模块。现有的 18 个工具仅覆盖了少量只读场景，写操作严重缺失；若为每个命令手写包装工具，工具链将无限膨胀；
2. **提示词上下文消耗巨大与工具选择漂移**：18 个工具的 JSON Schema 定义每轮会话消耗数千 Token，且工具过多时大模型容易发生选择紊乱或参数错位；
3. **束缚大模型原生能力**：大模型具备卓越的 Redis 原生命令行编写能力，过度的专用工具封装反而阻碍了大模型执行复杂的原生操作。

---

## 解决方案 (Solution)

将服务从“多数据结构专用 RPC 模式”全面重构升级为“混合命令网关模式 (Hybrid Command Gateway Pattern)”，将对外暴露的工具集大幅精简至 **4 个**：
1. **核心命令网关 (`redis_command`)**：接收单行原生 Redis 命令行输入，内置安全分词、多层安全门禁裁决与结果信封包装，无缝释放 99% 的 Redis 命令能力；
2. **保留 3 个不可替代的高价值探查工具**：
   - `redis_list_connections`：多连接配置与实例发现；
   - `redis_scan_keys`：内部游标自动循环迭代的非阻塞聚合键扫描（避免大模型手动写游标产生死循环）；
   - `redis_key_inspect`：聚合单键类型、TTL、编码与内存占用的一体化诊断；
3. **企业级安全闭环防线**：
   - 物理阻断破坏性指令（`FLUSHALL`、`FLUSHDB`、`SHUTDOWN`、`CONFIG`、`DEBUG`、`KEYS *`）；
   - 阶梯式双重写门禁（内置只读命令白名单放行，所有写命令及未知/扩展命令均须全局 `--allow-write` 且连接 `readonly: false`）；
   - 删除二次确认机制（`DEL`/`UNLINK` 命令未传 `confirm=True` 时返回友好待确认信封，确认后执行物理删除）；
   - 结果安全序列化与集合条数截断（大集合元素超出上限截断并标记元数据，防范 OOM 与上下文爆炸）；
4. **升级语义化主版本至 2.0.0**，彻底清理废弃的 15 个专有数据结构工具。

---

## 用户故事 (User Stories)

1. 作为一个 AI Agent，我希望调用 `redis_command` 工具并传入原生命令字符串（如 `"HGETALL user:1001"`），以便于使用我最熟悉的 Redis 语法直接操作数据。
2. 作为一个 AI Agent，我希望在 `redis_command` 中传入包含引号或空格的复杂参数（如 `"SET greeting 'hello world' EX 60"`），以便于正确传递带空格的文本内容。
3. 作为一个 AI Agent，当目标命令成功执行后，我希望收到包含执行命令、数据结果、推导类型与截断状态的信封结构（Envelope），以便于明确掌握返回数据的完整性。
4. 作为一个运维人员，在未开启 `--allow-write` 启动参数时，我希望任何尝试通过 `redis_command` 执行写入或修改命令（如 `SET`、`HSET`、`LPUSH` 等）的行为均被安全拦截并提示只读保护，以便于保护生产数据不被篡改。
5. 作为一个运维人员，当在配置文件中将某个连接档案明确配置为 `readonly: true` 时，我希望即使全局传入了 `--allow-write`，该连接上的写命令依然被绝对拦截，以便于实现细粒度环境隔离。
6. 作为一个安全管理员，我希望无论在何种配置或授权下，任何尝试调用 `FLUSHALL`、`FLUSHDB`、`SHUTDOWN`、`CONFIG`、`DEBUG` 或阻塞式 `KEYS *` 的原生命令均在服务底层被永久物理切断并抛出阻断异常，以便于杜绝毁灭性删库与全实例瘫痪风险。
7. 作为一个 AI Agent，当调用包含 `DEL` 或 `UNLINK` 的删除命令且未传入 `confirm=True` 时，我希望收到结构化的待确认响应（包含待删除键名、提示信息），以便于我向人类用户核实后再执行物理删除。
8. 作为一个 AI Agent，当人类确认并显式传入 `confirm=True` 后，我希望 `redis_command` 能够真正下发物理删除并返回删除影响数量，以便于可靠完成清理任务。
9. 作为一个 AI Agent，当执行返回超大数据集的命令（如对包含数万项的集合执行 `HGETALL` 或 `LRANGE 0 -1`）时，我希望服务端自动对结果项数进行安全切片截断并标记元数据，以便于防止 Python 进程内存溢出或大模型上下文窗口耗尽。
10. 作为一个 AI Agent，当执行返回二进制数据（如图片或序列化字节流）的命令时，我希望返回结果自动转码为 Base64 并标明 `is_binary: true`，以便于防止协议 JSON 序列化崩溃。
11. 作为一个 AI Agent，当执行返回超长文本的命令时，我希望文本内容在超出长度阈值时被安全截断并附带原始字节大小，以便于安全展示摘要数据。
12. 作为一个多实例环境的使用者，我希望在调用 `redis_command` 时通过可选参数 `connection` 指定连接别名，以便于无状态地在多个 Redis 实例间切换。
13. 作为一个使用者，我希望在调用 `redis_command` 时通过可选参数 `db` 指定逻辑库编号（0~15），以便于在单机实例上动态切库且不破坏底层连接池的有状态会话。
14. 作为一个开发者，当连接目标为 Redis Cluster 分片集群时，若执行多键命令触发 `CROSSSLOT` 跨槽异常，我希望收到语义清晰的引导提示，以便于大模型自动调整为单键拆分执行。
15. 作为一个 AI Agent，我希望调用 `redis_list_connections` 工具，以便于在单次调用中获知当前服务配置的全部 Redis 连接别名、地址脱敏信息与只读状态。
16. 作为一个 AI Agent，我希望调用 `redis_scan_keys` 工具，以便于在无需手动循环游标的前提下安全聚合检索匹配的键名列表，避免死循环。
17. 作为一个 AI Agent，我希望调用 `redis_key_inspect` 工具，以便于一站式获知目标键的类型、TTL、编码与内存占用。
18. 作为一个大模型客户端，我希望当前服务的 MCP 工具定义列表仅有 4 个核心工具，以便于大幅减少系统提示词 Token 消耗并降低工具选择错误率。
19. 作为一个开发者，在服务启动时我希望能够在日志中明确看到服务版本为 2.0.0，且仅挂载了混合命令网关模式下的 4 个核心工具。

---

## 实现决策 (Implementation Decisions)

1. **核心架构与工具集收敛**：
   - 废弃并彻底移除 15 个专有数据结构与运维工具（包括原 `strings.py`、`hashes.py`、`lists.py`、`sets.py`、`zsets.py`、`streams.py`、`admin.py` 中的专有实现）；
   - 对外工具暴露收敛为 4 个：`redis_command`、`redis_list_connections`、`redis_scan_keys`、`redis_key_inspect`；
   - 版本跃迁为 `2.0.0`。

2. **命令网关模块构建**：
   - 实现原生命令分词处理，采用标准 POSIX 引号解析规则，安全拆分命令动词与后续参数；
   - 提取首个命令动词作为鉴权对象，统一转为大写处理。

3. **安全守卫增强（命令分类器 Command Classifier）**：
   - **破坏性黑名单**：永久物理拦截 `FLUSHALL`、`FLUSHDB`、`SHUTDOWN`、`CONFIG`、`DEBUG`、`KEYS`；
   - **只读白名单**：建立常用 80+ 个无副作用命令集合（`GET`、`HGET`、`LRANGE`、`SMEMBERS`、`ZRANGE`、`TTL` 等），只读与写模式下均直接放行；
   - **闭环阶梯写门禁 (Fail-Close)**：所有不在只读白名单中的命令（包括已知修改命令与未知模块扩展命令），必须通过双重写门禁（全局 `--allow-write` 且连接 `readonly: false`）方可放行；
   - **删除确认拦截**：对 `DEL` 与 `UNLINK` 命令，若 `confirm=False`，提取待删除键名列表并拦截执行，返回结构化待确认信封；仅在 `confirm=True` 时执行。

4. **安全序列化与防 OOM 截断增强**：
   - 针对命令返回的 Python 复杂结构（列表、集合、字典）：
     - 列表/集合超过最大元素阈值（默认 100 项）时自动截断切片；
     - 字典项数超过阈值时进行键值对切片；
     - 并在信封元数据中记录 `is_truncated: true`、`total_count` 等信息；
   - 递归保证二进制数据自动转码 Base64，长文本安全截断。

5. **执行结果信封包装器 (Envelope Shape)**：
   - 统一输出结构定义：
     ```python
     {
         "command": str,  # 原始执行命令
         "result": Any,  # 序列化后的安全结果
         "data_type": str,  # 结果推导类型（string, integer, list, dict, none 等）
         "is_truncated": bool,  # 是否发生截断
         "total_count": int | None,  # 若发生集合截断，标明原始条数
     }
     ```

6. **集群跨槽异常优雅降级**：
   - 捕获 `redis.exceptions.ResponseError` 中的 `CROSSSLOT` 错误，转换为语义化说明，引导大模型按单键重试。

---

## 测试决策 (Testing Decisions)

1. **测试缝定位 (Testing Seam)**：
   - **最高层单一集成测试缝**：基于 FastMCP 协议接口 `app.call_tool(name, arguments)`。
   - 理由：所有的外部调用均通过 MCP 协议入口进入，通过单一协议调用缝可以 100% 验证从分词、安全守卫裁决、命令执行、序列化到信封包装的端到端行为，避免测试实现细节。
2. **测试模块覆盖**：
   - 编写 `test_command.py` 专门验证命令网关行为：
     - 只读命令执行与参数解析；
     - 未开启写权限时的写命令拦截；
     - 只读连接配置时的写命令拦截；
     - 破坏性黑名单命令的物理拦截；
     - 未知/扩展命令在只读模式下的安全拦截与写模式下的放行；
     - `DEL` 未确认时的待确认结构体返回与确认后的真实删除；
     - 大集合返回结果的项数截断与元数据断言；
     - 集群模式下 `CROSSSLOT` 友好异常包装；
     - 单机无状态动态切库 (`db=...`)。
   - 更新 `test_server.py`：断言已注册工具数量收敛为 4 个，版本号为 `2.0.0`。
3. **测试既有参考 (Prior Art)**：
   - 参考现有的 `test_guard.py`、`test_serializer.py` 与 `test_server.py` 的测试范式，使用 Mock 客户端与真实 FastMCP 协议实例。

---

## 范围外说明 (Out of Scope)

1. **有状态会话与事务 (MULTI/EXEC)**：
   - 不在此次支持范围内。每次 `redis_command` 均为独立的单次请求，不支持跨请求持久化有状态事务或交互式交互会话。
2. **Pub/Sub 实时长订阅**：
   - Redis 原生 `SUBSCRIBE` 属于阻塞长连接流式协议，超出 MCP 工具一次性请求/响应范式，由专门的 Transport 或未来协议扩展支持。
3. **动态服务配置修改**：
   - `CONFIG SET`、`CONFIG GET` 依然属于物理阻断范围，禁止在大模型会话中变更 Redis 基础配置。

---

## 附加说明 (Further Notes)

- 本 Spec 实施后，原有 v1.x 工具彻底废止，所有旧单测中针对 15 个具体专有工具的用例将被精简，并替换为 `test_command.py` 中的端到端测试，代码库整体体量将大幅缩减，维护性显著提升。
