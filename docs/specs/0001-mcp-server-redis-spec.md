# 需求规格说明书 (Spec): mcp-server-redis 生产级服务全功能落地

- **关联工单**: GitHub Issue (待发布)
- **状态**: 就绪可执行 (`ready-for-agent`)
- **创建日期**: 2026-10-04
- **遵循决策**: ADR-0001, ADR-0002, ADR-0003, ADR-0004

---

## 需求背景与问题陈述 (Problem Statement)

大语言模型（LLM）具备自主工具调用（Tool Calling）能力。但在将其引入 Redis 缓存与内存数据库交互时，面临以下痛点：
1. **指令破坏性与全库阻塞风险**：大模型偶发语义漂移或幻觉，调用全库阻塞命令 `KEYS *` 会引发 Redis 单线程引擎严重卡顿乃至全实例瘫痪；调用 `FLUSHALL`/`FLUSHDB` 则会导致灾难性数据清空。
2. **连接灵活性与环境隔离不足**：现有开源工具要么仅支持单个固定的连接串，要么配置繁琐，无法在同一会话中灵活、无状态地跨环境（开发库、预发只读库等）和跨逻辑库（DB 0~15）安全路由。
3. **海量数据读取引发 OOM**：Redis 中经常存在包含数万甚至数百万元素的大 Hash、大 List、大 Set 或大 Stream 消息流。未做切片防护的拉取会导致客户端内存溢出或瞬间打爆大模型的上下文窗口。
4. **二进制与长文本无法安全理解**：Redis 存储的 Protobuf、MessagePack、压缩包等非 UTF-8 二进制数据或数兆长文本，容易导致 JSON 序列化崩溃或报错。
5. **运维与诊断数据割裂**：排查性能瓶颈（慢查询 SLOWLOG、客户端会话状态、内存分配分布）往往需要离开大模型界面切换至 Redis 命令行。

---

## 核心解决方案 (Solution)

构建 `mcp-server-redis`——一个基于 Python 与 FastMCP 的生产级 Redis 模型上下文协议服务：
1. **双轨功能支持**：提供 18 个清晰直观的 `redis_` 动宾命名工具，覆盖“实例探查与连接”、“键空间检索”、“六大数据结构读写”、“受控变更与删除”以及“慢查询与运维诊断”。
2. **工业级只读防护与双重写门禁**：默认开启只读保护；写操作必须同时满足全局 `--allow-write` 启动参数且目标连接配置 `readonly: false`；底层物理永久阻断 `FLUSHALL`、`KEYS *` 等高危破坏性指令。
3. **聚合键扫描与集合切片守卫**：内部自动循环迭代 `SCAN` 游标，对外提供单次有限返回（默认 50，硬上限 200 条）；所有集合类型读取强制进行数量切片与分页，防范 OOM。
4. **高危删除二次确认门禁**：`redis_delete_keys` 强制携带 `confirm=False` 参数，未确认时仅返回预估影响，传 `confirm=True` 方可物理删除。
5. **自适应双模连接与无状态路由**：支持单个 `REDIS_URL` 开箱即用，同时支持 `--config` 载入 YAML/JSON 多实例配置；每个工具支持 `connection` 与 `db` 参数动态路由，禁止全局有状态 `SELECT`。
6. **自适应安全序列化与智能 JSON 探测**：优先 UTF-8 转码与 JSON 结构化解析，二进制自动转为 Base64，超长内容安全截断。

---

## 用户故事 (User Stories)

1. 作为一个开发者，我希望通过单条 `REDIS_URL` 命令行参数或环境变量直接启动 MCP 服务，以便于在本地单机开发时免配置快速开箱即用。
2. 作为一个多环境运维人员，我希望通过 `--config` 载入 `connections.yaml` 或 `connections.json` 配置文件，以便于大模型在同一会话中管理多个 Redis 实例。
3. 作为一个 AI Agent，我希望调用 `redis_list_connections` 工具，以便于获知当前所有可用的 Redis 连接别名、脱敏连接信息与默认连接。
4. 作为一个 AI Agent，我希望调用 `redis_ping` 工具，以便于快速验证目标 Redis 实例的连通性与网络响应延迟。
5. 作为一个开发者，我希望调用 `redis_info` 并可选指定 `section`（如 memory, clients, stats），以便于获取 Redis 运行时的系统性能指标。
6. 作为一个 AI Agent，我希望调用 `redis_dbsize`，以便于获知目标数据库中当前存储的键总数规模。
7. 作为一个 AI Agent，我希望调用 `redis_scan_keys` 并传入匹配通配符模式与类型过滤，以便于安全检索匹配的键名列表，而不会由于底层阻塞命令导致实例卡死。
8. 作为一个 AI Agent，我希望调用 `redis_key_inspect` 工具，以便于一站式获取单个 Key 的类型、TTL 过期时间、内存占用大小与底层编码方式。
9. 作为一个 AI Agent，我希望调用轻量级的 `redis_key_ttl` 工具，以便于低延迟检测特定键的存活剩余时间，而无需承担计算内存占用的额外开销。
10. 作为一个 AI Agent，我希望调用 `redis_get_string` 读取字符串键值，当值为 JSON 文本时自动获取解析后的结构化数据，以便于在上下文中更高效理解与推理业务数据。
11. 作为一个 AI Agent，当读取存放了非 UTF-8 二进制数据的键时，我希望 `redis_get_string` 自动转码为 Base64 并标明 `is_binary: true`，以便于避免编码异常并保留完整字节信息。
12. 作为一个 AI Agent，当读取超长文本或二进制内容时，我希望内容被安全截断并附带截断元数据，以便于防止过大输出打爆上下文窗口或导致内存溢出。
13. 作为一个 AI Agent，我希望调用 `redis_hash_get` 读取 Hash 表的指定字段或批量分页采样，以便于安全检视哈希映射内容且不会因百万字段大表导致 OOM。
14. 作为一个 AI Agent，我希望调用 `redis_list_range` 分页读取列表元素，并且切片跨度受最大上限保护，以便于安全探查队列两端或特定区间的列表数据。
15. 作为一个 AI Agent，我希望调用 `redis_set_members` 读取 Set 集合元素并在数量超限时进行安全采样截断，以便于安全分析标签或集合成员。
16. 作为一个 AI Agent，我希望调用 `redis_zset_range` 按照排名或分数读取有序集合成员及分值，以便于排查排行榜或延时队列数据。
17. 作为一个 AI Agent，我希望调用 `redis_stream_read` 逆序采样读取 Stream 消息流最新记录，以便于诊断排查异步事件队列积压情况。
18. 作为一个开发者，在未显式开启 `--allow-write` 时，我希望所有写入、修改、删除或过期设置操作均被安全拦截并提示只读保护，以便于杜绝非预期的意外写操作。
19. 作为一个开发者，当在配置文件中将某连接标记为 `readonly: true` 时，我希望即使全局启动时传递了 `--allow-write`，该连接上的写操作依然被严格拦截，以便于绝对保护生产数据。
20. 作为一个 AI Agent，在写授权开启时，我希望调用 `redis_set_string` 写入或更新字符串并可选指定过期时间与 NX 互斥参数，以便于完成测试数据写入与缓存预热。
21. 作为一个 AI Agent，当调用 `redis_delete_keys` 时若未传递 `confirm=True`，我希望工具仅返回待删除影响预估与确认提示，以便于提醒人类或经过确认后再物理删除。
22. 作为一个 AI Agent，当在二次调用中传入 `confirm=True` 时，我希望执行物理删除并返回成功删除的键数量，以便于可靠完成键清理任务。
23. 作为一个 AI Agent，我希望调用 `redis_expire_key` 为键设置生存秒数，以便于安全调整缓存生命周期。
24. 作为一个 AI Agent，我希望调用 `redis_get_slowlog` 获取最新慢查询日志列表，以便于快速定位耗时最长的慢操作与参数特征。
25. 作为一个 AI Agent，我希望调用 `redis_client_list` 检视当前连接客户端列表及阻塞状态，以便于诊断慢连接与资源竞争情况。
26. 作为一个开发者，无论处于何种模式，我希望任何调用 `FLUSHALL`、`FLUSHDB`、`KEYS *`、`SHUTDOWN`、`CONFIG` 的尝试均在底层代码中被物理切断并抛出阻断异常，以便于为生产系统提供最高级别的安全兜底。

---

## 实现决策 (Implementation Decisions)

1. **模块职责拆分与伴生结构**：
   - 装配入口 (`server.py`)：FastMCP 实例装配、CLI 参数解析（`--url`、`--config`、`--allow-write`）、连接注册中心初始化与统一工具挂载；
   - 核心基础设施 (`core/`)：
     - `connection.py`（连接注册中心 `ConnectionRegistry`）：管理自适应双模连接，提供动态获取指定 DB 连接池的方法，支持脱敏展示；
     - `guard.py`（安全守卫 `SecurityGuard`）：物理阻断破坏性指令，执行双重写门禁校验与删除二次确认检查；
     - `serializer.py`（安全序列化器 `SafeSerializer`）：自适应 UTF-8 / Base64 转码、JSON 结构化探测与长文本安全截断；
     - `audit.py`：审计日志记录与统一异常封装；
   - 工具实现层 (`tools/`)：
     - `instances.py`：`redis_list_connections`、`redis_ping`、`redis_info`、`redis_dbsize`
     - `keys.py`：`redis_scan_keys`、`redis_key_inspect`、`redis_key_ttl`
     - `strings.py`：`redis_get_string`、`redis_set_string`
     - `hashes.py`：`redis_hash_get`
     - `lists.py`：`redis_list_range`
     - `sets.py`：`redis_set_members`
     - `zsets.py`：`redis_zset_range`
     - `streams.py`：`redis_stream_read`
     - `admin.py`：`redis_delete_keys`、`redis_expire_key`、`redis_get_slowlog`、`redis_client_list`
2. **统一语言与 ADR 决策约束**：
   - 严格遵循 `CONTEXT.md` 统一语言与避用词汇约定；
   - 严格遵循 ADR-0001 至 ADR-0004 既定架构决策。

---

## 测试决策与接缝设计 (Testing Decisions & Seams)

- **单一高阶测试接缝 (Highest Single Seam)**：
  - 测试接缝确立在 **FastMCP 工具执行层 (Tool Execution Boundary)**；
  - 编写端到端单元测试与集成测试，直接以工具参数契约调用已注册的 `redis_*` 函数；
  - 底层使用基于内存的 mock / `fakeredis` 测试夹具或隔离的本地 Redis 实例验证；
  - 仅验证外部可见的返回值结构、序列化结果与安全守卫异常抛出，绝不耦合内部私有私有辅助函数实现细节。
- **核心测试矩阵**：
  1. 安全守卫测试：物理阻断破坏性指令测试、只读模式拦截测试、双重写门禁测试、未确认删除拦截测试；
  2. 智能聚合扫描与切片测试：超量 Key 扫描分页上限截断测试、各集合类型越界截断测试；
  3. 序列化与编码测试：合法 JSON 解析测试、二进制 Base64 转码测试、超长文本截断测试；
  4. 多连接与无状态切库测试：单连接构造、YAML 配置加载解析、动态切库 (db=1) 隔离性验证。

---

## 范围外边界 (Out of Scope)

1. Redis Cluster 原生集群分片与槽位迁移管理（暂聚焦单机/主从架构）；
2. 动态修改 Redis 服务端系统配置（如 `CONFIG SET`、修改密码）；
3. Redis 模块生态（RedisBloom 布隆过滤器、RediSearch 全文搜索、RedisGraph 图数据库等专业模块暂不纳入本次核心矩阵）；
4. Redis 事务管道交互（MULTI/EXEC）与 Pub/Sub 订阅监听长连接。

---

## 补充说明 (Further Notes)

- 遵循 `AGENTS.md` 中的代码质量与工程规范（代码注释 `@author Ateng`、`@since 2026-10-04`，空安全、异常防御、无状态单例）。
- 全部发布完成后，工单打上 `ready-for-agent` 标签，供后续编码 Agent 独立领单实施。
