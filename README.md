# mcp-server-redis

专为大语言模型（LLM）打造的生产级 Redis 模型上下文协议（Model Context Protocol, MCP）服务，基于 Python 与 FastMCP 构建。为大模型提供安全、可控、高内聚的键空间探查、多数据结构读写、内存与大 Key 分析、慢查询诊断与运维监控能力。

---

## 🌟 核心特性

- 🚀 **生产级 Redis 抽象支持**：基于高性能 `redis-py` 驱动与异步架构，支持 Standalone 单机实例、Sentinel 高可用及多 DB 库切换（0~15），内置稳定连接池管理。
- 🛡️ **生产级安全防护与非阻塞设计**：
  - **拒绝阻塞**：物理禁用会引发全实例卡顿的 `KEYS *` 命令，全面采用安全的非阻塞式 `SCAN` 游标迭代及受控数量限制；
  - **高危指令拦截**：底层物理拦截 `FLUSHALL`、`FLUSHDB`、`SHUTDOWN`、`CONFIG`、`DEBUG` 等破坏性指令；
  - **默认强只读守卫**：默认运行在严格只读模式下，写入与删除操作（SET/DEL/EXPIRE 等）必须通过启动参数显式授权 `--allow-write`。
- 📊 **全结构原生解析与采样**：
  - 覆盖 **String**、**Hash**、**List**、**Set**、**Sorted Set (ZSet)**、**Stream** 等核心数据结构；
  - 针对大集合具备深度采样与分页控制，杜绝一次性拉取海量元素导致客户端内存溢出（OOM）。
- 🔍 **大 Key、内存与生命周期探查**：
  - 提供 `MEMORY USAGE` 内存占用测算、对象编码（`OBJECT ENCODING`）探测；
  - 快速检视 Key 过期时间（TTL）、空闲时长与存在状态，辅助大模型进行缓存调优。
- ⏱️ **慢查询诊断与性能监控**：
  - 一键检索 `SLOWLOG` 慢日志记录，获取执行耗时、时间戳与参数详情；
  - 结构化提取 `INFO`（内存分配、命中率、连接数、持久化状态、主从同步）指标。

---

## 🛠️ 核心工具矩阵

| 领域模块 | 工具名称 | 参数契约 | 功能描述 |
| :--- | :--- | :--- | :--- |
| **实例探查** | `redis_ping` | `()` | 健康探活，验证 Redis 实例联通性与响应延迟 |
| | `redis_info` | `(section: str = None)` | 获取指定模块或全部系统运行时信息（Memory/Stats/Server/Clients） |
| | `redis_dbsize` | `()` | 获取当前数据库中存储的 Key 总量统计 |
| **键空间探查** | `redis_scan_keys` | `(match: str = "*", count: int = 50)` | 基于 `SCAN` 游标安全分页匹配键名，杜绝 `KEYS *` 阻塞实例 |
| | `redis_key_inspect` | `(key: str)` | 一站式获取 Key 的类型、TTL 过期时间、内存占用大小及底层编码 |
| | `redis_key_ttl` | `(key: str)` | 快速查询 Key 的生存剩余秒数（TTL / PTTL） |
| **数据读取** | `redis_get_string` | `(key: str)` | 安全读取 String 类型的字符串值 |
| | `redis_hash_get` | `(key: str, fields: list[str] = None)` | 读取 Hash 表的指定字段或批量全部字段（大表自动保护） |
| | `redis_list_range` | `(key: str, start: int = 0, stop: int = 49)` | 分页读取 List 列表指定范围的元素 |
| | `redis_set_members` | `(key: str, count: int = 50)` | 读取 Set 集合元素（支持采样限制） |
| | `redis_zset_range` | `(key: str, start: int = 0, stop: int = 49, withscores: bool = True)` | 按照排名或分数范围读取 Sorted Set 有序集合成员及分值 |
| **数据变更**<br>*(需 `--allow-write`)* | `redis_set_string` | `(key: str, value: str, ex: int = None, nx: bool = False)` | 写入或更新 String 键值，支持设置秒级过期时间 |
| | `redis_delete_keys` | `(keys: list[str], confirm: bool = False)` | 安全删除指定的单条或多条 Key，需显式确认防误删 |
| | `redis_expire_key` | `(key: str, seconds: int)` | 为指定 Key 设定或更新生存时间 |
| **运维与诊断** | `redis_get_slowlog` | `(count: int = 10)` | 获取最近慢查询日志记录，定位慢操作与高耗时命令 |
| | `redis_client_list` | `(limit: int = 20)` | 检视当前连接客户端列表及阻塞状态 |

---

## 📦 安装与快速运行

### 方式 1：使用 `uvx` 免安装直接运行（推荐）

无需在本地克隆代码或手动创建虚拟环境，使用现代 Python 包管理器 `uv` 即可直接拉取并启动：

```bash
# 默认只读模式运行（指向本地 Redis 实例）
uvx mcp-server-redis --url "redis://localhost:6379/0"

# 附带密码并启用数据写入变更权限
uvx mcp-server-redis --url "redis://:your_password@localhost:6379/0" --allow-write
```

### 方式 2：本地源码克隆与运行

```bash
# 克隆仓库
git clone https://github.com/atengk/mcp-server-redis.git
cd mcp-server-redis

# 使用 uv 同步依赖
uv sync

# 启动服务
uv run mcp-server-redis --url "redis://localhost:6379/0"
```

---

## 🔌 MCP 客户端接入配置

### 1. Claude Desktop 配置

在 Claude Desktop 配置文件（Windows: `%APPDATA%\Claude\claude_desktop_config.json`，macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`）中添加：

```json
{
  "mcpServers": {
    "redis": {
      "command": "uvx",
      "args": [
        "mcp-server-redis",
        "--url",
        "redis://localhost:6379/0"
      ]
    }
  }
}
```

### 2. 启用数据写入变更模式

若需允许大模型对 Redis 进行数据写入（SET）、删除（DEL）或设置过期时间（EXPIRE），请添加 `--allow-write` 参数：

```json
{
  "mcpServers": {
    "redis-write": {
      "command": "uvx",
      "args": [
        "mcp-server-redis",
        "--url",
        "redis://:your_secret_password@127.0.0.1:6379/0",
        "--allow-write"
      ]
    }
  }
}
```

### 3. Cursor / VS Code (Cline) 配置

在 `.cursor/mcp.json` 或 Cline 设置中配置：

```json
{
  "mcpServers": {
    "redis": {
      "command": "uvx",
      "args": [
        "mcp-server-redis"
      ],
      "env": {
        "REDIS_URL": "redis://localhost:6379/0"
      }
    }
  }
}
```

---

## 🔒 安全守卫机制

1. **强只读安全门禁 (Read-Only Guard)**：默认阻断一切产生状态变更的 Redis 命令，未传递 `--allow-write` 启动标志时调用写工具将直接抛出权限异常；
2. **高危操作物理切断**：不论是否开启写入权限，彻底禁用 `FLUSHALL`、`FLUSHDB`、`KEYS`、`CLUSTER RESET`、`SHUTDOWN` 等危险指令；
3. **海量数据安全截断**：针对大集合与大 Key 查询，强制应用单次条数截断，防止爆内存与网络过载；
4. **凭据安全脱敏**：在展示连接信息与日志输出时，自动隐藏密码与敏感鉴权 Token。

---

## 🤝 参与贡献

欢迎提交 Issue 与 Pull Request！详细规范请参阅 [贡献指南](./CONTRIBUTING.md)。

---

## 📄 开源许可证

本项目基于 [MIT 许可证](./LICENSE) 开源。
