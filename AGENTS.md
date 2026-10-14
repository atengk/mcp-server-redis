# mcp-server-redis 智能体工程规范 (AGENTS.md)

本文件是后续参与维护本代码库的所有 AI Agent 必须严格遵循的工程指导与设计不变量（Invariants）。

---

## 1. 项目定位与技术栈

`mcp-server-redis` 是专为大语言模型（LLM）打造的高性能、安全可控的生产级 Redis 模型上下文协议（Model Context Protocol, MCP）服务。

### 核心架构与角色职责
1. **协议接入层 (`server.py`)**：负责 FastMCP 实例初始化、CLI 参数解析、连接注册中心装配、全协议矩阵挂载与统一工具注册；
2. **核心基础设施 (`core/`)**：
   - `connection.py`：自适应双模连接注册中心（`ConnectionRegistry`），负责单连接直连与多实例配置加载，支持无状态多库路由；
   - `guard.py`：安全守卫（`SecurityGuard`），物理切断高危指令（`FLUSHALL`/`KEYS *` 等），执行写权限检查与删除二次确认（`ConfirmationGuard`）；
   - `serializer.py`：数据安全序列化器（`SafeSerializer`），实现自适应 UTF-8 解码、二进制 Base64 转码、超长内容截断与 INFO 分节结构化；
   - `audit.py`：结构化命令审计日志（`AuditLogger`），支持单行 JSONL 输出与 Stdio 模式管道防污染；
   - `doctor.py`：全景自检诊断器（`DoctorRunner`），负责依赖、配置、网络 RTT 与 5s TTL 隔离写探针四维检测；
   - `env.py`：环境变量探测、分级决议器（`ServerConfig`）与离散连接参数安全组装。
3. **工具与协议实现层 (`tools/` / `resources.py` / `prompts.py`)**：
   - 统一规范动宾契约，收敛为 4 个核心工具：
     - `command.py`：原生 Redis 命令执行网关（`redis_execute_command`），集成命令分类裁决、双重写门禁、BigKey 源头防爆预检与信封包装；
     - `instances.py` / `connections.py`：多连接配置与实例检视（`redis_list_connections`）；
     - `keys.py`：聚合键扫描（`redis_scan_keys`）、单键多维诊断（`redis_inspect_key`）。
   - 全 MCP 协议矩阵支撑：
     - `resources.py`：挂载系统只读快照（`info`、`slowlog`、`clients` 客户端脱敏快照）；
     - `prompts.py`：预置生产级标准排障 SOP 提示词（内存诊断、慢查优化、BigKey 治理）。

### 核心依赖栈
- Python `>=3.10`
- `mcp>=1.3.0`
- `redis>=5.0.0`
- `pydantic>=2.0.0`
- `pyyaml>=6.0`
- 包管理与工程工具链：`uv`、`ruff`、`mypy`、`pytest`、`git-cliff` 与原生提交守门钩子（`.githooks/commit-msg`）

---

## 2. 工程质量与安全底线

1. **工业级只读防护与双重写门禁 (Dual Write Gate)**：
   - 默认全局强只读，写操作（SET、DEL、HSET 等）必须受启动参数 `--allow-write` 显式管控且目标连接配置 `readonly` 必须为 `false`；
   - 底层代码永久物理阻断破坏性指令：`FLUSHALL`、`FLUSHDB`、`SHUTDOWN`、`CONFIG`、`DEBUG` 与阻塞式 `KEYS *`。
2. **非阻塞安全聚合扫描与游标续翻 (Cursor-Resumable Scan)**：
   - 键名扫描由内部聚合扫描器循环迭代底层 `SCAN` 游标，对外提供单次有限返回（默认最多 50 条，硬上限 200 条），支持传入上一页 `cursor` 断点续查。
3. **大集合切片与防 OOM 防御 (Collection Slicing Guard)**：
   - 所有命令返回的大型集合类数据（Hash/List/Set/ZSet）强制实施元素数量截断（默认上限 100 项），并在信封中标记截断元数据。
4. **巨型集合源头防爆预检与超时安全收敛 (BigKey Defense & Safe Timeout)**：
   - `HGETALL`、`SMEMBERS` 等无界全量读取在下发前通过 O(1) 指令探查集合大小，超过阈值（默认 2000 项）物理拦截；
   - `BLPOP`、`BRPOP` 等阻塞读取命令强制将 0 秒无限等待改写为安全超时（默认 2 秒，最大 5 秒），杜绝进程挂死。
5. **高危删除二次确认门禁 (Confirmation Guard)**：
   - 删除操作（`DEL`/`UNLINK`）在 `redis_execute_command` 中强制携带 `confirm: bool = False`，未确认时仅返回待确认结构体，传 `confirm=True` 方可执行物理删除。
6. **无状态动态切库与集群单库约束 (Stateless Routing & Single-DB Constraint)**：
   - 每个工具统一支持 `connection: str = None` 与 `db: int = None` 参数，严禁在底层连接上执行有状态的 `SELECT <db>` 命令；
   - Redis Cluster 模式下强制重置绑定 `db=0`，并对多键操作执行跨槽并发安全防御。
7. **自适应序列化与敏感信息脱敏 (Safe Serialization & Masking)**：
   - 字符串尝试 UTF-8 解码与智能 JSON 探测，非文本自动转码为 Base64，超长文本安全截断；密码与客户端内网 IP 末段在日志与概览中一律脱敏掩码。
8. **多连接大模型动态感知路由与自愈信封 (Dynamic Hints & Self-Healing)**：
   - 服务装配时根据多实例配置动态将连接别名、只读属性、业务描述与键模式通配规则（`key_patterns`）编译注入 Tool Schema 的 `connection` 参数文档；
   - 大模型误传不存在的连接别名时，自动拦截 `ConnectionNotFoundError` 并返回包含可用别名清单的标准化自愈信封，驱动自我纠错。
9. **跨服务身份标识与工具名物理稳定 (Server Identification)**：
   - 跨服务身份标识（`--server-name` 与 `--server-instructions`）纯净传给 FastMCP 实例，专用于宿主客户端识别服务身份与注入系统指导；
   - 底层所有核心 MCP 工具名称（`redis_execute_command` 等）始终保持严格的物理稳定性，绝不随意添加前缀或动态篡改。
10. **全景环境体检与隔离写探针 (Doctor Diagnostic Runner)**：
    - `--doctor` 独立运行于协议之外；写权限探针必须使用纳秒级 UUID 隔离键（`__mcp_doctor_probe_{uuid}__`）、5 秒 TTL 与即时物理清理机制，严禁污染生产数据。
11. **规范提交守护与开源协议不变量 (Commit Guard & Apache-2.0 License)**：
    - 开发者与 AI Agent 本地提交均受 `.githooks/commit-msg` 守门约束，必须严格遵循 Conventional Commits 语义化规范；
    - 项目整体遵循 Apache License 2.0 协议，享有显式专利授权与专利反诉防御，严禁将专有闭源或冲突许可证代码混入本代码库。

---

## Agent skills

### Issue tracker

GitHub Issues（通过 `gh` CLI 交互）。详见 `docs/agents/issue-tracker.md`。

### Triage labels

遵循五大标准分流角色（`needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix`）。详见 `docs/agents/triage-labels.md`。

### Domain docs

采用单上下文布局（根目录 `CONTEXT.md` 与 `docs/adr/`）。详见 `docs/agents/domain.md`。
