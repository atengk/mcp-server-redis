# mcp-server-redis 统一语言与领域模型 (CONTEXT.md)

生产级 Redis 模型上下文协议（MCP）服务，专为大语言模型提供安全可控的键值探查、数据读写与运维诊断能力。

---

## 统一语言 (Ubiquitous Language)

**连接档案 (Connection Profile)**:
描述单个目标 Redis 实例的连接实体，包含连接 URL、连接别名 (Alias)、数据库编号 (DB 0~15)、是否只读 (`readonly: bool`) 等配置属性。  
_避免使用_: 数据源 (Data Source)、DB 配置 (DB Config)、实例定义 (Instance Spec)

**连接注册中心 (Connection Registry)**:
自适应双模连接管理核心，支持从单个 `MCP_REDIS_URL` 环境变量/CLI 参数自动构造默认连接，亦支持从 `--config` 配置文件（YAML / JSON）批量加载多连接实例并维护其连接池生命周期。  
_避免使用_: 连接池管理器 (Pool Manager)、引擎工厂 (Engine Factory)

**连接配置文件 (Connection Config)**:
遵循声明式规范的外部配置文件（支持 `.yaml`、`.yml` 或 `.json`），定义默认连接别名 (`default`) 以及各目标实例的连接档案映射字典。  
_避免使用_: 启动清单 (Startup Manifest)、配置字典 (Config Dict)

**无状态多库路由 (Stateless Routing)**:
每个 MCP 工具统一接受 `connection`（连接别名）与 `db`（0~15 逻辑库编号）可选参数。操作在获取连接池时以无状态方式绑定目标库执行，严禁在连接上执行全局有状态 `SELECT` 命令，规避多会话并发串库。  
_避免使用_: 动态切库 (Dynamic DB Switch)、会话上下文 (Session Context)

**双重写门禁 (Dual Write Gate)**:
严格的阶梯式写操作鉴权逻辑。执行任何数据修改操作的前提是：全局启动参数包含 `--allow-write` **且** 目标连接档案的 `readonly` 标记为 `false`。两者缺一不可，任一条件不满足即视作绝对只读。  
_避免使用_: 单一授权 (Single Auth)、强制覆盖 (Force Override)

**安全守卫 (Security Guard)**:
在 Redis 命令调度前执行拦截的安全防线。负责双重写门禁判决，并物理阻断破坏性指令。  
_避免使用_: 过滤器 (Filter)、安全拦截器 (Interceptor)、检查器 (Checker)

**破坏性指令 (Destructive Commands)**:
在任何模式下均被底层代码永久物理切断的 Redis 原生高危指令集合（如 `FLUSHALL`、`FLUSHDB`、`KEYS *`、`SHUTDOWN`、`CONFIG`、`DEBUG` 等）。  
_避免使用_: 黑名单命令 (Blacklist Commands)、高危操作 (Dangerous Operations)

**二次确认门禁 (Confirmation Guard)**:
针对高危删除操作（`redis_delete_keys`）施加的交互式安全门禁。必须显式传入 `confirm=True` 方可执行物理删除；未确认时仅返回目标影响预估及待确认提示。  
_避免使用_: 交互式弹窗 (Interactive Prompt)、删除检查器 (Delete Verifier)

**聚合键扫描器 (Aggregated Key Scanner)**:
对 Redis 原生非阻塞式 `SCAN` 游标的高级封装。在服务内部自动循环迭代游标，支持 `pattern` 模式通配与 `type` 类型过滤，在累积收集达到请求数量（默认 50，硬上限 200）或遍历终止后聚合返回，对外隐藏底层游标交互复杂度。  
_避免使用_: 全库检索 (Full Keys Search)、游标分页器 (Cursor Pager)

**集合切片守卫 (Collection Slicing Guard)**:
对复杂集合类型（Hash、List、Set、ZSet 以及 Stream 消息流）在读取时施加的物理安全切片防护。强制设置条数上限（默认 50，硬上限 200），严禁全量一次性拉取海量元素导致客户端内存溢出（OOM）。  
_避免使用_: 数据分页器 (Data Pager)、限流器 (Rate Limiter)

**大 Key 探查器 (BigKey Inspector)**:
调用 `MEMORY USAGE` 与 `OBJECT ENCODING` 探查单 Key 字节大小、内存占用及底层编码结构的安全诊断单元。  
_避免使用_: 内存分析器 (Memory Profiler)、大对象捕获器 (Big Object Hunter)

**慢日志采集器 (Slowlog Collector)**:
提取 Redis 原生 `SLOWLOG GET` 指令数据，并按格式输出执行耗时、时间戳及关联参数的诊断组件。  
_避免使用_: 性能监视器 (APM)、慢查探测器 (Slow Query Tracker)

**智能 JSON 探测 (Smart JSON Parsing)**:
针对 String 类型的自动反序列化增强。当键值为合法 JSON 时自动解析为结构化字典/列表，同时保留原始文本，减少大模型二次处理开销。  
_避免使用_: 动态反序列化 (Dynamic Deserializer)、对象映射器 (Object Mapper)

**安全序列化器 (Safe Serializer)**:
将 Redis 驱动返回的二进制 `bytes`、时间戳及结构体安全转码为标准 JSON 对象的处理层。优先进行 UTF-8 文本解码与 JSON 探测，遇二进制数据自动转为 Base64 编码并标明 `is_binary: True`，遇超长内容自动执行长度截断并标明 `truncated: True` 与原始字节长度。  
_避免使用_: 数据格式化工具 (Data Formatter)、JSON 转换器 (JSON Dumper)

**分发包名 (Distribution Package Name)**:
发布至 PyPI 官方制品库的标准包名 `atengk-mcp-server-redis`，与内部模块路径 `mcp_server_redis` 形成清晰解耦，规避公共生态命名冲突。  
_避免使用_: 注册前缀 (Registry Prefix)、项目全称 (Project Fullname)

**双 CLI 别名 (Dual CLI Aliases)**:
同时挂载在 `[project.scripts]` 下的 `atengk-mcp-server-redis`（对齐 `uvx` 默认查找契约）与 `mcp-server-redis`（支持本地快速调用），两者均指向同一协议启动入口 `mcp_server_redis:main`。  
_避免使用_: 快捷方式 (Shortcuts)、命令行冗余 (Command Redundancy)

**分级配置决议器 (Configuration Hierarchy Resolver)**:
按“CLI 显式参数 > 系统/用户级环境变量 > 离散连接参数 > 本地 .env 文件 > 默认保底值”对连接串、配置文件路径与写权限开关进行优先级裁决的配置核心。  
_避免使用_: 参数读取器 (Param Reader)、环境覆盖器 (Env Overrider)

**离散参数组装器 (Discrete Parameters Synthesizer)**:
将 `MCP_REDIS_HOST`、`MCP_REDIS_PORT`、`MCP_REDIS_PASSWORD`、`MCP_REDIS_DB` 等零散字段安全拼装为标准 Redis URL，并自动对密码中的特殊字符执行 Percent-Encoding 编码的防御单元。  
_避免使用_: URL 拼接函数 (URL Concatenator)、连接串生成器 (URL Generator)
