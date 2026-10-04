# atengk-mcp-server-redis

<p align="center">
  <a href="https://github.com/atengk/mcp-server-redis/actions/workflows/ci.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/atengk/mcp-server-redis/ci.yml?branch=main&label=CI&style=flat-square" alt="CI Status" />
  </a>
  <a href="https://github.com/atengk/mcp-server-redis/releases">
    <img src="https://img.shields.io/github/v/release/atengk/mcp-server-redis?style=flat-square" alt="GitHub Release" />
  </a>
  <a href="https://pypi.org/project/atengk-mcp-server-redis/">
    <img src="https://img.shields.io/pypi/v/atengk-mcp-server-redis?style=flat-square" alt="PyPI Version" />
  </a>
  <a href="./LICENSE">
    <img src="https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square" alt="License" />
  </a>
  <a href="./CONTRIBUTING.md">
    <img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=flat-square" alt="PRs Welcome" />
  </a>
  <a href="https://modelcontextprotocol.io/">
    <img src="https://img.shields.io/badge/MCP-2024--11--05-green.svg?style=flat-square" alt="MCP Protocol" />
  </a>
</p>

专为大语言模型（LLM）打造的高性能、安全可控的生产级 Redis 模型上下文协议（Model Context Protocol, MCP）服务，基于 Python 与 FastMCP 构建。

为大模型提供工业级强只读防护、双重写门禁、单键多维诊断、全数据结构防 OOM 切片读取、慢查询审计与运维诊断能力。

---

## 🌟 核心特性

- 🛡️ **生产级双重安全防护体系 (Dual Write Gate)**：
  - **默认强只读守卫**：默认全局只读，写操作（SET / DEL / EXPIRE）必须受启动参数 `--allow-write` 显式管控且目标连接 `readonly` 必须为 `false`；
  - **高危指令物理阻断**：底层硬编码物理切断 `FLUSHALL`、`FLUSHDB`、`SHUTDOWN`、`CONFIG`、`DEBUG` 及阻塞式 `KEYS *`；
  - **高危删除二次确认门禁**：`redis_delete_keys` 强制携带 `confirm: bool = False`，未确认时仅返回受影响预估，传 `confirm=True` 方可执行物理删除；
  - **凭据掩码自动脱敏**：对外连接清单及日志输出中自动将 Redis 密码脱敏为 `***`，杜绝凭据泄露。
- 📊 **非阻塞聚合与全数据结构切片防御**：
  - **非阻塞安全聚合扫描**：内部自动循环迭代 `SCAN` 游标聚合返回，默认最多 50 条，单次硬上限 200 条；
  - **集合切片防 OOM 防御**：覆盖 **String**、**Hash**、**List**、**Set**、**Sorted Set (ZSet)**、**Stream** 六大结构，全部查询强制实施数量与跨度截断；
  - **智能 JSON 探测 (Smart JSON Parsing)**：遇到合法 JSON 文本自动转换为结构化字典/列表对象（`json_data`），大幅削减大模型二次处理开销；
  - **二进制自适应转码**：非文本二进制数据自动转换为 Base64 编码并标明 `is_binary: True`，绝不发生解码崩溃。
- 🔍 **大 Key、内存占用与生命周期诊断**：
  - 一站式获取 Key 的类型、存活时间（TTL / PTTL）、内存占用大小（`MEMORY USAGE`）与底层编码格式（`OBJECT ENCODING`）；
  - 提供轻量级独立 TTL 探查工具，无额外计算开销。
- ⏱️ **运维指标采集与慢日志审计**：
  - 支持按模块提取 Redis 原生 `INFO` 运行时性能指标；
  - 格式化提取并截断展示 `SLOWLOG` 慢日志明细与当前连接客户端 `CLIENT LIST`。
- 🌐 **无状态多库动态路由**：
  - 支持单连接直连与多环境 YAML 配置文件加载；
  - 每个工具统一支持 `connection`（连接别名）与 `db`（0~15 逻辑库编号）参数，物理禁止在连接池上执行全局有状态 `SELECT` 指令。

---

## 🛠️ 18 个核心工具矩阵速查

| 领域分类 | MCP 工具名称 | 核心参数契约 | 功能描述 |
| :--- | :--- | :--- | :--- |
| **实例与连接** | `redis_list_connections` | `()` | 查看所有已配置的 Redis 连接别名、脱敏 URL 及当前默认连接 |
| | `redis_ping` | `(connection=None, db=None)` | 健康探活，度量网络往返延迟 (RTT) 与服务状态 |
| | `redis_info` | `(section=None, connection=None, db=None)` | 结构化获取系统运行指标（server/memory/stats/clients 等） |
| | `redis_dbsize` | `(connection=None, db=None)` | 查询指定数据库中存储的键总数规模 |
| **键空间探查** | `redis_scan_keys` | `(pattern="*", limit=50, type=None, connection=None, db=None)` | 智能聚合扫描匹配键名，循环迭代游标并支持类型过滤与条数上限 |
| | `redis_key_inspect` | `(key: str, connection=None, db=None)` | 一站式综合诊断单键：类型、TTL、内存占用字节及底层编码 |
| | `redis_key_ttl` | `(key: str, connection=None, db=None)` | 轻量低延迟查询单个键的存活剩余时间 |
| **数据读取** | `redis_get_string` | `(key: str, parse_json=True, connection=None, db=None)` | 读取字符串键值（支持智能 JSON 解析与二进制 Base64 转码） |
| | `redis_hash_get` | `(key: str, fields=None, count=50, connection=None, db=None)` | 读取 Hash 字典指定字段或分页安全采样（大表切片防御） |
| | `redis_list_range` | `(key: str, start=0, stop=49, connection=None, db=None)` | 分页切片读取 List 列表元素（单次最大跨度上限 100） |
| | `redis_set_members` | `(key: str, count=50, connection=None, db=None)` | 采样读取 Set 集合元素（支持数量安全截断） |
| | `redis_zset_range` | `(key: str, start=0, stop=49, withscores=True, connection=None, db=None)` | 读取 Sorted Set 成员及分值（单次上限 200） |
| | `redis_stream_read` | `(key: str, count=20, connection=None, db=None)` | 逆序采样读取 Stream 消息流最新消息（单次上限 100） |
| **数据变更**<br>*(需 `--allow-write`)* | `redis_set_string` | `(key: str, value: str, ex=None, nx=False, connection=None, db=None)` | 写入或更新 String 键值，支持秒级 TTL 与互斥写入 |
| | `redis_expire_key` | `(key: str, seconds: int, connection=None, db=None)` | 为指定键设定或更新秒级生存时间 |
| | `redis_delete_keys` | `(keys: list[str]\|str, confirm=False, connection=None, db=None)` | 安全物理删除键，**强制要求 `confirm=True` 二次确认防误删** |
| **运维与诊断** | `redis_get_slowlog` | `(count=10, connection=None, db=None)` | 检索最新慢查询日志，格式化提取耗时、时间戳与大命令截断 |
| | `redis_client_list` | `(limit=20, connection=None, db=None)` | 检视当前连接客户端列表、空闲时长及阻塞状态 |

---

## 📦 安装与快速运行

### 方式 1：使用 `uvx` 免安装直接运行（强烈推荐）

无需手动配置 Python 环境或克隆仓库，借助现代化 Python 工具链 `uv` 即可直接拉取并启动：

```bash
# 默认只读模式运行（指向本地 Redis 实例）
uvx atengk-mcp-server-redis --url "redis://localhost:6379/0"

# 附带密码并开启数据写入变更权限
uvx atengk-mcp-server-redis --url "redis://:your_password@localhost:6379/0" --allow-write

# 加载多环境多实例配置文件
uvx atengk-mcp-server-redis --config /path/to/connections.yaml
```

### 方式 2：使用 `pip` 安装运行

```bash
pip install atengk-mcp-server-redis

# 启动服务
atengk-mcp-server-redis --url "redis://localhost:6379/0"
```

### 方式 3：源码本地克隆与开发运行

```bash
git clone https://github.com/atengk/mcp-server-redis.git
cd mcp-server-redis

# 使用 uv 同步依赖
uv sync

# 本地执行
uv run atengk-mcp-server-redis --url "redis://localhost:6379/0"
```

### 方式 4：使用 Docker 容器化运行

```bash
# 瞬态交互运行（stdio 管道）
docker run -i --rm -e MCP_REDIS_URL="redis://host.docker.internal:6379/0" atengk/mcp-server-redis:1.0.0 --transport stdio

# 常驻后台 HTTP SSE 服务端（暴露 8000 端口）
docker-compose up -d
```

---

## 🔌 MCP 客户端通用集成配置

本服务遵循标准 MCP (Model Context Protocol) 规范。以下为**通用标准配置格式**，可直接复制并粘贴至任何支持标准 stdio 的 MCP 客户端配置文件中（包括 **Claude Desktop**、**Cursor**、**Cline**、**Windsurf**、**Cherry Studio**、**Antigravity** 等）：

### 1. 通用标准只读配置 (推荐)

适用绝大多数日常探查、知识库检索与只读诊断场景：

```json
{
  "mcpServers": {
    "redis": {
      "command": "uvx",
      "args": [
        "atengk-mcp-server-redis",
        "--url",
        "redis://localhost:6379/0"
      ]
    }
  }
}
```

> **提示**：若连接带密码的远程 Redis 实例，请将 URL 设置为 `redis://:你的密码@主机:端口/0`。

### 2. 通用读写配置 (允许数据变更)

若需允许大模型对 Redis 进行数据写入（SET）、删除（DEL）或设置过期时间（EXPIRE），添加 `--allow-write` 启动参数：

```json
{
  "mcpServers": {
    "redis-writable": {
      "command": "uvx",
      "args": [
        "atengk-mcp-server-redis",
        "--url",
        "redis://:your_password@127.0.0.1:6379/0",
        "--allow-write"
      ]
    }
  }
}
```

### 3. 使用环境变量提供连接配置

您也可以通过客户端的 `env` 节点注入环境变量，无需在启动命令行中暴露凭据：

#### 方式 A：单一连接串 (`MCP_REDIS_URL`)
```json
{
  "mcpServers": {
    "redis": {
      "command": "uvx",
      "args": [
        "atengk-mcp-server-redis"
      ],
      "env": {
        "MCP_REDIS_URL": "redis://:your_password@10.0.0.1:6379/0",
        "MCP_REDIS_ALLOW_WRITE": "true"
      }
    }
  }
}
```

#### 方式 B：离散参数配置（推荐，特殊字符密码免转义）
当密码中包含 `@`、`:`、`/` 等特殊字符时（如 `Admin@123`），使用离散环境变量由服务底层自动进行 URL 转义编码，无需手动编写 `%40`：
```json
{
  "mcpServers": {
    "redis": {
      "command": "uvx",
      "args": [
        "atengk-mcp-server-redis"
      ],
      "env": {
        "MCP_REDIS_HOST": "103.236.97.210",
        "MCP_REDIS_PORT": "63730",
        "MCP_REDIS_PASSWORD": "Admin@123",
        "MCP_REDIS_DB": "0",
        "MCP_REDIS_ALLOW_WRITE": "true"
      }
    }
  }
}
```

### 4. 使用 Docker 容器挂载 (免安装本地环境)

若希望在没有 Python 环境的宿主机上直接通过容器提供 MCP 能力：

```json
{
  "mcpServers": {
    "redis-docker": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "-e",
        "MCP_REDIS_URL=redis://host.docker.internal:6379/0",
        "-e",
        "MCP_REDIS_ALLOW_WRITE=true",
        "atengk/mcp-server-redis:1.0.0",
        "--transport",
        "stdio"
      ]
    }
  }
}
```

---

## 🐳 Docker 容器化运行与微服务编排

本项目提供工业级轻量化标准容器制品与单服务编排清单，全面兼顾本地终端调试与微服务常驻运行。

### 核心镜像安全基线
- **极速精简多阶段构建**：基于 `python:3.11-slim` 底座与 `uv` 高速依赖预缓存，完全剥离包编译器，产出镜像体积严格 $< 150\text{MB}$；
- **非 Root 生产安全账号**：容器内以专有非 root 账户 `appuser` (UID: `10001`, GID: `10001`) 运行，并锁定登录 Shell（`/usr/sbin/nologin`），满足企业最小权限与容器合规审计；
- **开箱即用常驻网关**：默认入口命令为 `atengk-mcp-server-redis`，默认暴露端口 `8000` 并以 HTTP SSE 传输网关模式常驻运行。

### 使用 docker-compose 常驻部署 (SSE 模式)

工程根目录预置了生产级 [docker-compose.yml](./docker-compose.yml)：

```bash
# 后台常驻启动 MCP SSE 服务端
docker-compose up -d

# 检视实时服务日志
docker-compose logs -f
```

容器启动后，MCP 服务端将在宿主机 `http://localhost:8000/sse` 持续监听。各大支持远程 SSE 协议的 MCP 客户端（如 Cherry Studio、远程 Web AI 网关等）只需直接填写该 URL 即可挂载。

> [!TIP]
> **宿主机网络互通**：`docker-compose.yml` 内建了 `host.docker.internal:host-gateway` 跨平台解析，容器内配置 `MCP_REDIS_URL=redis://host.docker.internal:6379/0` 即可直接连通 Linux、macOS 或 Windows 宿主机上运行的外部 Redis 服务。

---

## 🌐 Redis Cluster 分片集群接入指南

服务全面内建对 Redis Cluster 分片集群（基于 16384 哈希槽架构）的原生自适应识别与驱动治理。

### 1. 协议头与连接配置

系统自适应探测以下任意一种集群配置方式并自动激活 `RedisCluster` 驱动：
- **专用协议头**：连接 URL 采用 `redis-cluster://` 或 `rediss-cluster://`（如 `redis-cluster://cluster.internal:6379`）；
- **环境变量**：注入 `MCP_REDIS_CLUSTER=true`；
- **CLI 命令行**：启动时显式附带 `--cluster` 参数；
- **多实例配置**：在 YAML 连接档案中声明 `cluster: true`。

```bash
# 命令行启动集群只读模式
uvx atengk-mcp-server-redis --url "redis-cluster://10.0.0.1:6379"

# 环境变量启动集群并开启写权限
uvx atengk-mcp-server-redis --url "redis://10.0.0.1:6379" --cluster --allow-write
```

### 2. 生产级集群不变量与安全防御

- 🛡️ **单一数据库 (DB 0) 强制防御契约**：
  Redis Cluster 规范物理移除了多逻辑库概念，仅支持 0 号库。当调用工具时误传 `db=1~15` 或 URL 中含有 `/<db>` 路径，服务底层自动执行**深度防御**：物理剥除 URL 中的路径，自动记录审计告警并重置绑定至 `db=0`，绝不因切库异常抛出 `ResponseError: SELECT is not allowed in cluster mode` 导致会话中断。
- 🛡️ **跨槽 (Cross-Slot) 安全防御与并发提速**：
  在分片集群中，批量键操作若分散在不同槽位会触发原生 Redis 崩溃报错（`CROSSSLOT Keys in request don't hash to the same slot`）。本服务构建了严密的多键安全屏障：
  - **物理删除 (`redis_delete_keys`)**：底层检测到集群模式或捕获到 `CROSSSLOT` 异常时，自动将批处理安全收敛为基于 `asyncio.gather` 的并发单键独立请求，在彻底阻断跨槽崩溃的同时消除了串行网络 N+1 开销；
  - **探活安全降级**：未确认删除前的 Pipeline 批量探活若发生集群异常，自动降级为并发逐键存在性探测。
- 🔍 **全节点聚合扫描 (`redis_scan_keys`)**：
  集群模式自适应切换至 `client.scan_iter` 机制，自动轮询遍历全部分片 Master 节点并聚合匹配键集合，受条数上限（默认 50，硬上限 200）安全截断保护。

---

## 🚀 Stdio 与 SSE 双模传输网关

本服务在应用层抽象了双模传输网关架构，一套代码兼顾本地终端进程间通信与分布式微服务网络暴露：

```
                    ┌─────────────────────────────────────────┐
                    │       atengk-mcp-server-redis           │
                    │         (FastMCP 核心服务层)            │
                    └───────────┬─────────────────┬───────────┘
                                │                 │
               (默认模式)       │                 │  (--transport sse)
                                ▼                 ▼
                    ┌──────────────────┐   ┌──────────────────┐
                    │  标准 Stdio 管道  │   │  HTTP SSE 网关   │
                    │  (JSON-RPC 流)   │   │  (:8000/sse 端点)│
                    └─────────┬────────┘   └─────────┬────────┘
                              │                      │
                              ▼                      ▼
                     本地大模型客户端        远程 AI 网关 / 云原生微服务
                     (Claude/Cursor/Cline)   (Web 客户端 / 局域网协同)
```

1. **标准 Stdio 管道模式（默认）**：
   - 默认模式，日志严格绑定至 `sys.stderr`，绝不污染 stdout 协议流，100% 严格向后兼容所有现有客户端配置；
2. **HTTP Server-Sent Events (SSE) 服务端模式**：
   - 通过 `--transport sse`（或 `MCP_REDIS_TRANSPORT=sse`）激活；
   - 支持 `--host`（默认 `0.0.0.0`）与 `--port`（默认 `8000`）自定义监听绑定。

```bash
# 启动 HTTP SSE 网关监听于 0.0.0.0:8000
uvx atengk-mcp-server-redis --transport sse --host 0.0.0.0 --port 8000
```

---

## 🌍 环境变量完整参考 (Environment Variables)

服务原生支持**系统级、用户级、客户端级环境变量**以及当前工作目录下的 **`.env` 文件**。所有变量统一遵循严格的 `MCP_REDIS_` 前缀规范，杜绝环境污染。

### 1. 连接与认证配置
| 环境变量名 | 默认值 | 作用与用法示例 |
| :--- | :--- | :--- |
| `MCP_REDIS_URL` | - | 完整 Redis 连接 URL（如 `redis://:pass@host:6379/0` 或 `redis-cluster://node:6379`）。若显式提供，优先级高于离散变量 |
| `MCP_REDIS_HOST` | `localhost` | Redis 主机名或 IP 地址（如 `103.236.97.210`） |
| `MCP_REDIS_PORT` | `6379` | Redis 端口号（如 `6379` 或 `63730`） |
| `MCP_REDIS_PASSWORD` | - | Redis 访问凭据。**支持任意特殊字符明文，底层自动 URL 编码防截断** |
| `MCP_REDIS_DB` | `0` | 默认逻辑数据库编号（`0~15`） |
| `MCP_REDIS_USERNAME` | - | ACL 认证用户名（可选） |

### 2. 集群与传输网关配置
| 环境变量名 | 默认值 | 作用与用法示例 |
| :--- | :--- | :--- |
| `MCP_REDIS_CLUSTER` | `false` | 激活 Redis Cluster 分片集群模式。取值为 `true`、`1`、`yes`、`on` 时生效 |
| `MCP_REDIS_TRANSPORT` | `stdio` | 传输协议模式。可选 `stdio` 或 `sse`（大小写不敏感） |
| `MCP_REDIS_SERVER_HOST` | `0.0.0.0` | SSE 传输网关绑定的监听主机地址 |
| `MCP_REDIS_SERVER_PORT` | `8000` | SSE 传输网关绑定的 HTTP 监听端口 |

### 3. 安全权限与网络治理
| 环境变量名 | 默认值 | 作用与用法示例 |
| :--- | :--- | :--- |
| `MCP_REDIS_ALLOW_WRITE` | `false` | 正向显式授权写权限。值为 `true`、`1`、`yes`、`on` 时开启写操作 |
| `MCP_REDIS_READ_ONLY` | `true` | 反向只读控制。显式设为 `false`、`0`、`no`、`off` 时解除只读并开启写权限 |
| `MCP_REDIS_LOG_LEVEL` | `INFO` | 运行时日志输出级别。支持 `DEBUG`、`INFO`、`WARNING`、`ERROR`（日志严格绑定至 stderr） |
| `MCP_REDIS_CONNECT_TIMEOUT` | `3.0` | Socket 连接超时保底时间（秒），防止节点宕机网络挂死 |
| `MCP_REDIS_SOCKET_TIMEOUT` | `5.0` | Socket 指令执行超时保底时间（秒），亦支持别名 `MCP_REDIS_TIMEOUT` |
| `MCP_REDIS_CONFIG` | - | 多实例连接配置文件路径（映射 `--config` 参数） |

### 配置优先级裁决顺序 (Precedence)
1. **最高优先级**：CLI 命令行参数（`--url` / `--config` / `--allow-write`）；
2. **次高优先级**：系统/用户/客户端级环境变量整串（`MCP_REDIS_CONFIG`、`MCP_REDIS_URL`）；
3. **中间优先级**：离散环境变量自动组装（`MCP_REDIS_HOST` + `MCP_REDIS_PORT` + `MCP_REDIS_PASSWORD`...）；
4. **本地兜底**：当前工作目录下的 `.env` 文件（安全补充，绝不覆盖操作系统已存在变量）；
5. **系统保底**：`redis://localhost:6379/0`，全局只读模式。

---

## ⚙️ 多实例配置指南 (`--config`)

对于需要同时管理开发、测试、生产只读等多套 Redis 实例的场景，可通过 `--config` 指定 YAML 或 JSON 配置文件。

参考配置模板 [connections.example.yaml](./connections.example.yaml)：

```yaml
default: "local"

connections:
  local:
    url: "redis://localhost:6379/0"
    readonly: false
    description: "本地开发实例（读写）"
    db: 0

  staging:
    url: "redis://:stage_pass@staging.redis.internal:6379/1"
    readonly: false
    description: "预发布环境"
    db: 1

  prod-readonly:
    url: "redis://:prod_pass@prod.redis.internal:6379/0"
    readonly: true
    description: "生产环境从库（绝对只读保护）"
    db: 0
```

启动命令：
```bash
uvx atengk-mcp-server-redis --config ./connections.yaml --allow-write
```

> **安全注意**：即使启动时指定了 `--allow-write`，在配置文件中被标记为 `readonly: true` 的连接（如上述 `prod-readonly`）仍将受到物理写保护，绝对拒绝任何数据变更！

---

## 🔒 深度安全防御体系

```
                       ┌──────────────────────────────┐
                       │   大模型发起 MCP 工具调用     │
                       └──────────────┬───────────────┘
                                      │
                                      ▼
                        [ 破坏性指令物理切断拦截器 ] ────► 命中 FLUSHALL/KEYS* 等 ──► 抛出 SecurityException 物理阻断
                                      │ (安全通过)
                                      ▼
                             [ 操作类型判定 ]
                              /              \
                   (读操作 / 诊断)          (写操作: SET/DEL/EXPIRE)
                            /                  \
                           ▼                    ▼
                    [ 集合切片守卫 ]      [ 双重写门禁检测 ]
                 (强制条数与跨度截断)      1. CLI --allow-write 是否启用？
                           │              2. 目标连接 readonly 是否为 false？
                           │                    │ (任一不满足即拦截)
                           │                    ▼
                           │             [ 高危删除二次确认 ]
                           │             (redis_delete_keys 校验 confirm==True)
                           │                    │
                           ▼                    ▼
                     ┌──────────────────────────────┐
                     │   执行底层 Redis 异步指令    │
                     └──────────────┬───────────────┘
                                    │
                                    ▼
                         [ 安全序列化与数据自适应 ]
                       (UTF-8 / Base64 / 智能 JSON)
```

1. **双重写门禁 (Dual Write Gate)**：写操作必须同时满足 `--allow-write` 启动授权与连接档案 `readonly: false`，双保险防止误触写命令；
2. **物理切断高危指令**：底层硬编码阻断破坏性与全库阻塞命令，绝无旁路执行可能；
3. **删除二次确认门禁**：`redis_delete_keys` 在未传 `confirm=True` 时仅作为探针返回待删除预估，必须由用户/大模型二次确认后才执行删除；
4. **防 OOM 强制切片**：复杂集合全系强制分页与最大条数截断，防止海量元素打爆宿主内存与传输上下文；
5. **凭据安全脱敏**：所有外显接口与日志全面屏蔽明文密码。

---

## 🤝 参与贡献

我们欢迎社区贡献！如果您发现了缺陷或有功能建议：

1. 提交 [GitHub Issues](https://github.com/atengk/mcp-server-redis/issues)；
2. 查阅 [贡献指南](./CONTRIBUTING.md) 与 [智能体工程规范](./AGENTS.md)；
3. 发起 Pull Request。

---

## 📄 开源许可证

本项目基于 [MIT 许可证](./LICENSE) 开源。
