# 更新日志 (Changelog)

本项目遵循 [Semantic Versioning (语义化版本 2.0.0)](https://semver.org/lang/zh-CN/) 规范。

---

## [1.0.0] - 2026-10-04

### 🌟 首发生产级特性 (Production Release)

`atengk-mcp-server-redis` 是专为大语言模型（LLM）打造的高性能、安全可控的生产级 Redis 模型上下文协议（Model Context Protocol, MCP）服务。

#### 1. 核心架构与连接管理
- **自适应双模连接注册中心 (`ConnectionRegistry`)**：支持从单一 `MCP_REDIS_URL` 环境变量/启动参数构建默认连接，亦支持从 `--config` 加载多实例 YAML/JSON 连接档案配置；
- **全维度环境变量与配置分级决议**：
  - 原生支持系统级、用户级、客户端级环境变量与本地 `.env` 探测加载；
  - 规范统一采用 `MCP_REDIS_` 严格专属命名空间，彻底隔离宿主机环境污染；
  - 支持整串 `MCP_REDIS_URL` 及离散参数（`MCP_REDIS_HOST`、`MCP_REDIS_PORT`、`MCP_REDIS_PASSWORD`、`MCP_REDIS_DB`、`MCP_REDIS_USERNAME` 等）；
  - 自动对密码特殊字符（如 `@`, `:`, `/`）执行 URL Percent-Encoding 编码转义，消除解析分裂；
  - 支持 `MCP_REDIS_CONFIG` 映射配置文件路径；
  - 支持写权限双通道决议：正向开启 `MCP_REDIS_ALLOW_WRITE=true` 与反向只读解除 `MCP_REDIS_READ_ONLY=false`；
- **无状态多库动态路由**：支持跨命令传递 `connection`（连接别名）与 `db`（0~15 逻辑库编号），物理禁止在底层连接上执行全局有状态 `SELECT` 指令；
- **凭据掩码安全脱敏**：对外连接清单 (`redis_list_connections`) 及日志输出中自动将密码脱敏为 `***`，彻底杜绝凭据泄漏。

#### 2. 生产级安全防护体系
- **工业级强只读门禁**：默认全局只读，写操作必须由启动标志 `--allow-write` 显式授权且目标连接 `readonly` 必须为 `false`（双重写门禁）；
- **破坏性指令物理切断**：物理拦截并阻断 `FLUSHALL`、`FLUSHDB`、`SHUTDOWN`、`CONFIG`、`DEBUG` 及阻塞式 `KEYS *`；
- **高危删除二次确认门禁**：`redis_delete_keys` 强制携带 `confirm: bool = False`，未确认时仅返回受影响预估，传 `confirm=True` 方可执行物理删除；
- **集合切片守卫**：五大复杂集合（Hash、List、Set、ZSet、Stream）全量读操作施加强制切片截断与最大条数保护，彻底防范 OOM 崩溃。

#### 3. 智能序列化与数据自适应
- **自适应 UTF-8 / Base64 转码**：字符串自动解码，非文本二进制自动转为 Base64 并标明 `is_binary: True`；
- **智能 JSON 探测 (Smart JSON Parsing)**：遇到合法 JSON 文本自动转换为结构化字典/列表对象（`json_data`），大幅削减大模型二次处理开销；
- **超长文本截断**：长文本/Base64 超出阈值安全截断并附带 `is_truncated: True` 及原始总长度。

#### 4. 全套 18 个生产级 MCP 工具矩阵
- **实例与连接 (2)**：`redis_list_connections`、`redis_ping`
- **键空间检索与诊断 (3)**：`redis_scan_keys`、`redis_key_inspect`、`redis_key_ttl`
- **字符串读写与删除门禁 (4)**：`redis_get_string`、`redis_set_string`、`redis_expire_key`、`redis_delete_keys`
- **五大复杂集合与流 (5)**：`redis_hash_get`、`redis_list_range`、`redis_set_members`、`redis_zset_range`、`redis_stream_read`
- **运维性能诊断 (4)**：`redis_info`、`redis_dbsize`、`redis_get_slowlog`、`redis_client_list`

#### 5. CLI 与分发
- PyPI 官方包名：`atengk-mcp-server-redis`；
- 双 CLI 命令别名：`atengk-mcp-server-redis` 与 `mcp-server-redis`，支持 `uvx atengk-mcp-server-redis` 免安装直接运行。
