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

**命令网关 (Command Gateway)**:
接收客户端原生 Redis 命令字符串，负责安全分词、前置门禁裁决并在目标实例上无状态执行的核心协议入口 (`redis_command`)。  
_避免使用_: 命令代理 (Command Proxy)、命令管道 (Command Pipeline)

**命令分类裁决器 (Command Classifier)**:
依据只读白名单、高危破坏性黑名单及变更操作集合，对原生 Redis 命令动词进行动态安全级别判决的分析核心。  
_避免使用_: 指令解析器 (Instruction Parser)、命令过滤器 (Command Filter)

**破坏性指令 (Destructive Commands)**:
在任何模式下均被底层代码永久物理切断的 Redis 原生高危指令集合（如 `FLUSHALL`、`FLUSHDB`、`KEYS *`、`SHUTDOWN`、`CONFIG`、`DEBUG` 等）。  
_避免使用_: 黑名单命令 (Blacklist Commands)、高危操作 (Dangerous Operations)

**二次确认门禁 (Confirmation Guard)**:
针对高危删除操作（`DEL`/`UNLINK`）施加的交互式安全门禁。必须显式传入 `confirm=True` 方可执行物理删除；未确认时仅返回目标待删除键列表及待确认提示。  
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

**分片集群自适应驱动 (Cluster Adaptive Driver)**:
基于协议头 `redis-cluster://` / `rediss-cluster://`、环境变量 `MCP_REDIS_CLUSTER` 或多实例配置 `cluster: true` 自动探测并装配的 `redis.asyncio.cluster.RedisCluster` 客户端驱动。自动遵循集群单库不变量（强制重置绑定 `db=0`）并完成生命周期释放。  
_避免使用_: 集群代理 (Cluster Proxy)、分片包装器 (Sharding Wrapper)

**跨槽安全防御 (Cross-Slot Guard)**:
针对 Redis Cluster 分布式哈希槽分布施加的防御机制。在物理删除（`redis_delete_keys`）与探活阶段将多键批处理安全降级为基于 `asyncio.gather` 的并发单键独立请求，物理切断 `CROSSSLOT` 跨槽异常崩溃风险并杜绝串行网络 N+1 开销；在键检索阶段通过 `scan_iter` 遍历全部分片节点聚合键集合。  
_避免使用_: 槽位重定向 (Slot Redirection)、跨槽补丁 (Cross-Slot Patch)

**双模传输网关 (Dual Transport Gateway)**:
在服务装配层建立的双协议传输抽象。默认以极简原生 Stdio 管道保证已有客户端配置的 100% 严格向后兼容，亦支持通过 `--transport sse`（及 `--host`、`--port`）切换为常驻 HTTP Server-Sent Events 服务端，满足微服务与远程大模型协作需求。  
_避免使用_: 网络代理 (Network Proxy)、协议转换器 (Protocol Converter)

**非 Root 生产容器 (Non-Root Production Container)**:
基于 `python:3.11-slim` 底座与 `uv` 极速多阶段构建的生产安全容器镜像。剥离包编译器，镜像体积严格收敛于 150MB 以内；运行阶段强制下沉为专有非 root 账户 `appuser` (UID: 10001) 并禁用交互 Shell，符合企业最小权限与合规审计基线。  
_避免使用_: 基础镜像 (Base Image)、默认容器 (Default Container)

**跨版本矩阵流水线 (Cross-Version Matrix Pipeline)**:
在持续集成（CI）层针对受支持的 Python 版本（3.10、3.11、3.12）并行执行依赖同步与完整测试套件的质量门禁。配合静态分析（Ruff）与类型推断（Mypy），确保代码在全生命周期内满足跨版本生态兼容性。  
_避免使用_: 单一测试脚本 (Single Test Script)、多版本构建器 (Multi-Version Builder)

**多架构容器镜像分发 (Multi-Arch Container Distribution)**:
在版本发布阶段通过 Docker Buildx 与 QEMU 自动化构建并推送至 GitHub Container Registry (`ghcr.io`) 的双架构（amd64 与 arm64）官方镜像服务。  
_避免使用_: 容器备份 (Container Backup)、镜像仓库 (Image Registry)

**自动化变更提取器 (Automated Changelog Extractor)**:
基于 `git-cliff` 与 Conventional Commits 提交历史，在版本打标时自动化解析提交范围、过滤非规范提交并结构化生成 Release 笔记与发行日志的工具组件。  
_避免使用_: 日志生成脚本 (Log Script)、版本总结器 (Version Summarizer)

**规范动宾契约 (Canonical Verb-Object Contract)**:
严格遵循“前缀_动作_对象”语序的标准化 MCP 工具契约，消除自然语言意图歧义，并为历史工具名提供无缝兼容别名。  
_避免使用_: 动作乱序 (Arbitrary Ordering)、松散命名 (Loose Naming)

**智能 INFO 结构化器 (Smart INFO Parser)**:
在命令网关序列化层将 Redis 原生非结构化多段文本自动转为分节紧凑字典的解析单元。  
_避免使用_: 文本清洗脚本 (Text Cleaner)、正则转换器 (Regex Converter)

**轻量复合元数据扫描 (Metadata-Enriched Scan)**:
在单次键空间扫描迭代中并行附加类型与过期时间元数据的复合查询模式，规避大模型连续发起多轮诊断的 N+1 交互瓶颈。  
_避免使用_: 批量诊断器 (Batch Inspector)、深度检索 (Deep Search)

**只读快照资源 (Readonly Snapshot Resource)**:
遵循 `redis://{connection}/{resource}` 统一资源标识符挂载的 MCP 只读上下文切片，供模型开箱即用注入系统状态。  
_避免使用_: 静态数据源 (Static Data Source)、资源文件 (Resource File)

**诊断引导提示词 (Diagnostic Guided Prompt)**:
向大模型客户端预置的标准运维与排障排查工作流模板，指导大模型以最少指令高效闭环排查业务异常。  
_避免使用_: 快捷指令 (Shortcuts)、聊天模板 (Chat Template)

**游标续翻扫描 (Cursor-Resumable Scan)**:
允许客户端显式传入上轮迭代游标以无缝续查后续键空间的非阻塞分页模式，彻底解决海量键无法获取第二页的断层问题。  
_避免使用_: 伪分页 (Pseudo Paging)、偏移量翻页 (Offset Paging)

**零超时阻塞防线 (Zero-Timeout Blocking Guard)**:
针对 `BLPOP`/`BRPOP` 等阻塞式读取指令实施的主动防御，将无限挂起超时期（0）与超长超时强制收敛至安全短时阈值，规避 MCP 工作进程被永久锁死。  
_避免使用_: 进程挂起 (Process Hang)、无限等待 (Infinite Wait)

**连接空闲心跳 (Connection Idle Heartbeat)**:
在连接池生命周期内开启的周期性后台探活与超时重试机制，杜绝长连接常驻会话遭遇防火墙丢弃或服务端关闭时的静默断连崩溃。  
_避免使用_: 死连接 (Dead Connection)、半开连接 (Half-Open Socket)

**管道批处理网关 (Pipeline Batch Gateway)**:
在单次 MCP 工具调用中通过 Redis Pipeline 打包顺序执行多条命令并聚合返回执行信封的高性能执行通道，大幅压缩大模型多命令交互轮次。  
_避免使用_: 多轮往返 (Multi-Roundtrip)、顺序串行调度 (Sequential Dispatch)

**结构化命令审计日志 (Structured Audit Trail)**:
在命令网关与写门禁层以单行 JSONL 格式输出的命令执行审计追溯记录，保障金融与生产级合规性，在 stdio 模式下具备严格的物理管道防污染隔离。  
_避免使用_: 控制台打印 (Console Print)、杂乱日志 (Unstructured Log)

**巨型集合防爆预检 (BigKey In-Flight Defense)**:
针对 `HGETALL`、`SMEMBERS` 等无界全量读取命令在下发前通过 O(1) 指令探查集合大小的源头防爆机制，防止百万级 BigKey 阻塞 Redis 单线程主循环。  
_避免使用_: 事后截断 (Post-Fetch Slicing)、内存爆破 (Memory Blowup)

**云原生探活路由 (Cloud-Native Healthz Probe)**:
在 SSE 模式下挂载的轻量 HTTP `/health` 与 `/healthz` 端点，结合底层 Redis PING 探活，精准配合 Kubernetes 的 Liveness 与 Readiness 探针切流。  
_避免使用_: 端口盲测 (Blind Port Check)、虚拟探针 (Dummy Probe)

**客户端快照脱敏 (Client List Desensitization)**:
提取 Redis `CLIENT LIST` 时对内网客户端 IP 地址末段自动掩码并结构化展示运行状态的脱敏处理机制，防止内网拓扑嗅探。  
_避免使用_: 裸 IP 暴露 (Raw IP Exposure)、文本原样倾泻 (Raw Text Dumping)

**Doctor 自检诊断器 (Doctor Diagnostic Runner)**:
独立于协议运行时、面向开发者与运维提供的一键式环境、配置、网络连通与写权限深度体检组件，支持终端富文本卡片与 CI/CD 结构化 JSON 双模输出。  
_避免使用_: 测试脚本 (Test Script)、连通探针 (Simple Ping)

**环境指纹 (Environment Fingerprint)**:
CLI 版本查询时输出的包含服务版本、Python 解释器版本、操作系统平台与关键底层依赖库（mcp、redis、pydantic、yaml）版本摘要的精确运行时标识。  
_避免使用_: 裸版本号 (Raw Version)、字符串版本 (String Version)

**隔离写探针 (Isolated Write Probe)**:
自检诊断器在验证实际写权限时使用的纳秒级 UUID 隔离键（`__mcp_doctor_probe_{uuid}__`）、5 秒双保险 TTL 校验与即时物理清理机制，杜绝生产脏数据残留。  
_避免使用_: 脏写测试 (Dirty Write)、业务键覆盖 (Business Key Overwrite)

**服务标识 (Server Name)**:
MCP 协议握手层声明的服务实例名称（通过 `--server-name` 与 `MCP_REDIS_SERVER_NAME` 配置）。专用于多 MCP 服务挂载时供宿主客户端识别服务身份，底层工具名称始终保持稳定不变量。  
_避免使用_: 服务别名 (Server Alias)、工具前缀 (Tool Prefix)

**系统指令 (Server Instructions)**:
通过 MCP 协议握手直接向大语言模型注入的系统级业务指导与拓扑边界说明（通过 `--server-instructions` 与 `MCP_REDIS_SERVER_INSTRUCTIONS` 配置），明确该 MCP 服务的业务职责与规范。  
_避免使用_: 提示词模板 (Prompt Template)、聊天前置词 (Chat Prefix)

**动态连接提示 (Dynamic Connection Hints)**:
服务启动装配工具时根据实际加载的连接注册表动态编译拼入 Tool Schema（`connection` 参数说明）的连接拓扑结构，消除大模型的盲查猜测并实现零额外往返意图匹配。  
_避免使用_: 静态文档 (Static Doc)、固定说明 (Hardcoded Hints)

**键模式规则 (Key Patterns)**:
在多连接配置档案中声明的业务键前缀通配特征列表（`key_patterns`），为大模型根据输入键名自动路由至匹配物理库提供先验线索。  
_避免使用_: 键正则 (Key Regex)、路由标签 (Routing Tags)

**自愈引导信封 (Self-Healing Envelope)**:
当大模型传入不存在的连接别名时返回的标准化错误信封，主动反馈全量可用连接清单与业务描述，驱动大模型自我纠错并自主重试。  
_避免使用_: 裸异常抛出 (Raw Exception Throwing)、静默降级 (Silent Fallback)
