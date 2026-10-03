# mcp-server-redis 智能体工程规范 (AGENTS.md)

本文件是后续参与维护本代码库的所有 AI Agent 必须严格遵循的工程指导与设计不变量（Invariants）。

---

## 1. 项目定位与技术栈

`mcp-server-redis` 是专为大语言模型（LLM）打造的高性能、安全可控的 Redis 模型上下文协议（Model Context Protocol, MCP）服务。

### 核心架构与角色职责
1. **协议接入层 (`server.py`)**：负责 FastMCP 实例初始化、命令行参数解析及对外暴露 MCP 工具注册；
2. **核心基础设施 (`core/`)**：
   - `connection.py`：Redis 异步/同步连接池管理与生命周期调度；
   - `guard.py`：安全阻断守卫（物理拦截高危命令如 FLUSHALL/KEYS 等，执行参数安全校验）；
   - `audit.py`：审计日志与慢查询诊断采集。
3. **工具实现层 (`tools/`)**：
   - 按领域前缀模块化拆分（`info`、`keys`、`strings`、`hashes`、`lists`、`sets`、`zsets`、`diagnostic`）。

### 核心依赖栈
- Python `>=3.10`
- `mcp>=1.3.0`
- `redis>=5.0.0`
- `pydantic>=2.0.0`
- 包管理与工具链：`uv`、`ruff`、`mypy`、`pytest`

---

## 2. 工程质量与安全底线

1. **工业级只读防护 (Read-Only Guard)**：
   - 默认模式下严格禁止任何写操作与数据变更；
   - 写入操作（SET、DEL、EXPIRE 等）必须受 `--allow-write` 启动参数物理管控；
   - 物理阻断 `FLUSHALL`、`FLUSHDB`、`SHUTDOWN`、`CONFIG` 等全库级高危指令。
2. **非阻塞安全游标迭代**：
   - 严禁调用全库阻塞式 `KEYS *` 命令，一律采用 `SCAN` 分批游标迭代并限制单次返回最大条数。
3. **大 Key 与数据切片防御**：
   - 集合型数据结构（Hash/List/Set/ZSet）读取强制支持分页与切片限制，杜绝因拉取超大集合导致客户端内存溢出（OOM）。
4. **敏感信息脱敏**：
   - 在连接日志、异常输出与信息概览中，Redis 密码及鉴权凭证一律使用脱敏掩码。

---

## Agent skills

### Issue tracker

GitHub Issues（通过 `gh` CLI 交互）。详见 `docs/agents/issue-tracker.md`。

### Triage labels

遵循五大标准分流角色（`needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix`）。详见 `docs/agents/triage-labels.md`。

### Domain docs

采用单上下文布局（根目录 `CONTEXT.md` 与 `docs/adr/`）。详见 `docs/agents/domain.md`。
