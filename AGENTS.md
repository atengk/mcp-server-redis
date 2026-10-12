# mcp-server-redis 智能体工程规范 (AGENTS.md)

本文件是后续参与维护本代码库的所有 AI Agent 必须严格遵循的工程指导与设计不变量（Invariants）。

---

## 1. 项目定位与技术栈

`mcp-server-redis` 是专为大语言模型（LLM）打造的高性能、安全可控的生产级 Redis 模型上下文协议（Model Context Protocol, MCP）服务。

### 核心架构与角色职责
1. **协议接入层 (`server.py`)**：负责 FastMCP 实例初始化、CLI 参数解析、连接注册中心装配与统一工具注册；
2. **核心基础设施 (`core/`)**：
   - `connection.py`：自适应双模连接注册中心（`ConnectionRegistry`），负责单连接直连与多实例配置加载，支持无状态动态切库执行；
   - `guard.py`：安全守卫（`SecurityGuard`），物理切断高危指令（`FLUSHALL`/`KEYS *` 等），执行写权限检查与删除二次确认（`ConfirmationGuard`）；
   - `serializer.py`：数据安全序列化器（`SafeSerializer`），实现自适应 UTF-8 解码、二进制 Base64 转码与超长内容截断；
   - `audit.py`：审计日志与慢查询诊断采集。
3. **工具实现层 (`tools/`)**：
   - 统一采用 `redis_` 前缀，收敛为 4 个核心工具：
     - `command.py`：原生 Redis 命令执行网关（`redis_command`），集成命令分类裁决、双重写门禁与信封包装；
     - `instances.py`：多连接配置与实例检视（`redis_list_connections`）；
     - `keys.py`：聚合键扫描（`redis_scan_keys`）、单键多维诊断（`redis_key_inspect`）。

### 核心依赖栈
- Python `>=3.10`
- `mcp>=1.3.0`
- `redis>=5.0.0`
- `pydantic>=2.0.0`
- `pyyaml>=6.0`
- 包管理与工具链：`uv`、`ruff`、`mypy`、`pytest`

---

## 2. 工程质量与安全底线

1. **工业级只读防护与双重写门禁 (Dual Write Gate)**：
   - 默认全局强只读，写操作（SET、DEL、HSET 等）必须受启动参数 `--allow-write` 显式管控且目标连接配置 `readonly` 必须为 `false`；
   - 底层代码永久物理阻断破坏性指令：`FLUSHALL`、`FLUSHDB`、`SHUTDOWN`、`CONFIG`、`DEBUG` 与阻塞式 `KEYS *`。
2. **非阻塞安全聚合扫描**：
   - 键名扫描由内部聚合扫描器循环迭代底层 `SCAN` 游标，对外提供单次有限返回（默认最多 50 条，硬上限 200 条）。
3. **大集合切片与防 OOM 防御**：
   - 所有命令返回的大型集合类数据（Hash/List/Set/ZSet）强制实施元素数量截断（默认上限 100 项），并在信封中标记截断元数据。
4. **高危删除二次确认门禁**：
   - 删除操作（`DEL`/`UNLINK`）在 `redis_command` 中强制携带 `confirm: bool = False`，未确认时仅返回待确认结构体，传 `confirm=True` 方可执行物理删除。
5. **无状态动态切库**：
   - 每个工具统一支持 `connection: str = None` 与 `db: int = None` 参数，严禁在底层连接上执行有状态的 `SELECT <db>` 命令。
6. **自适应序列化与敏感信息脱敏**：
   - 字符串尝试 UTF-8 解码，非文本自动转码为 Base64，超长文本安全截断；密码在连接日志与配置概览中一律脱敏掩码。

---

## Agent skills

### Issue tracker

GitHub Issues（通过 `gh` CLI 交互）。详见 `docs/agents/issue-tracker.md`。

### Triage labels

遵循五大标准分流角色（`needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix`）。详见 `docs/agents/triage-labels.md`。

### Domain docs

采用单上下文布局（根目录 `CONTEXT.md` 与 `docs/adr/`）。详见 `docs/agents/domain.md`。
