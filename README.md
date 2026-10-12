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

采用 **v2.0 混合命令网关架构（Hybrid Command Gateway）**，将工具集高度收敛为 4 个核心工具，为大模型提供原生 Redis 命令行交互、双重写门禁、高危删除二次确认、大集合防 OOM 截断与单键多维诊断能力。

> 💡 **版本更新日志 (Changelog)**：  
> 每一个正式版本的详细变动明细、关联 Issue 与贡献者致谢均由 `git-cliff` 自动维护，可直接前往 [GitHub Releases](https://github.com/atengk/mcp-server-redis/releases) 查看最新记录。

---

## 🌟 核心特性

- ⚡ **原生 Redis CLI 命令网关 (`redis_command`)**：
  - 单行原生命令语法交互（如 `"HGETALL user:1001"`、`"SET message 'hello world' EX 60"`），完全释放大模型对 300+ Redis 原生指令及模块（JSON、Search 等）的表达力；
  - 内置 POSIX 标准引号分词解析，原生支持带空格与特殊字符的复杂参数；
  - 统一输出自解释执行信封（`command`、`result`、`data_type`、`is_truncated`、`total_count`）。
- 🛡️ **生产级双重安全防护体系 (Dual Write Gate)**：
  - **默认强只读守卫**：内置 80+ 常用只读命令白名单（`GET`、`HGET`、`LRANGE`、`SMEMBERS`、`TTL` 等），无论何种模式均安全放行；
  - **严格写权限阶梯管控**：所有变更命令（包括未知模块扩展指令）必须同时满足启动参数 `--allow-write` 显式开启且目标连接配置 `readonly: false`；
  - **高危破坏性指令物理硬阻断**：底层代码永久物理切断 `FLUSHALL`、`FLUSHDB`、`SHUTDOWN`、`CONFIG`、`DEBUG` 及阻塞式 `KEYS *`，杜绝删库瘫痪风险；
  - **凭据掩码自动脱敏**：对外连接清单及日志输出中自动将 Redis 密码脱敏为 `***`，杜绝凭据泄露。
- ⚠️ **高危删除二次确认门禁 (Confirmation Guard)**：
  - `DEL` 与 `UNLINK` 命令强制执行二次确认拦截机制；
  - 未传 `confirm=True` 时不触发物理删除，而是返回待确认结构体（包含待删除键清单及安全操作提示）；
  - 仅在显式传入 `confirm=True` 后方才下发物理删除并返回影响键数量。
- 📦 **大集合切片防 OOM 与数据自适应序列化**：
  - 命令返回的大型集合类数据（Hash / List / Set / ZSet）超过 100 项时自动执行元素切片截断并标记元数据，防止 Python 进程内存溢出与模型上下文撑爆；
  - 遇到合法 JSON 文本自动转换为结构化字典/列表对象（`json_data`）；
  - 非文本二进制数据自动转换为 Base64 编码并标明 `is_binary: True`，绝不发生解码崩溃；超长文本内容安全截断。
- 🔍 **核心探查辅助工具与无状态动态路由**：
  - `redis_list_connections`：一站式查阅多实例连接配置、连接别名与只读状态；
  - `redis_scan_keys`：内部自动循环迭代 `SCAN` 游标聚合返回，避免大模型手动迭代游标造成死循环；
  - `redis_key_inspect`：单键多维诊断（类型、TTL/PTTL、内存占用字节及底层编码格式）；
  - 所有工具统一支持 `connection`（连接别名）与 `db`（0~15 逻辑库编号）参数，物理禁止在连接池上执行全局有状态 `SELECT` 指令。
- 🌐 **集群跨槽 (Cross-Slot) 异常优雅降级**：
  - 自动识别 Redis Cluster 跨槽执行冲突并转换为语义化提示，引导大模型自动拆分为单键重试。

---

## 🛠️ 4 个核心工具矩阵速查

| MCP 工具名称 | 核心参数契约 | 功能描述与安全门禁 |
| :--- | :--- | :--- |
| **`redis_command`** | `(command: str, connection=None, db=None, confirm=False)` | **核心命令网关**：原生 Redis 命令执行通道。<br>• 80+ 只读白名单直接放行<br>• 写命令受双重写门禁管辖（`--allow-write`）<br>• `DEL`/`UNLINK` 强制要求 `confirm=True` 二次确认<br>• 永久物理阻断破坏性指令（`FLUSHALL`/`KEYS *` 等）<br>• 超过 100 项大集合自动截断防 OOM |
| **`redis_list_connections`** | `()` | **连接实例检视**：查看所有已配置的 Redis 连接别名、脱敏 URL、数据库编号及默认连接标识。 |
| **`redis_scan_keys`** | `(pattern="*", limit=50, type=None, connection=None, db=None)` | **聚合键扫描器**：非阻塞循环迭代底层游标聚合检索匹配键名，默认最多 50 条，单次硬上限 200 条，杜绝游标死循环。 |
| **`redis_key_inspect`** | `(key: str, connection=None, db=None)` | **单键多维诊断**：聚合获取目标键的类型、TTL/PTTL、内存占用（`MEMORY USAGE`）与底层存储编码。 |

---

## 💡 `redis_command` 调用示例

### 1. 基础只读查询与带空格传参
```python
# 1. 查询字符串（支持带引号空格传参）
redis_command(command="GET 'user:session:1001'")

# 2. 读取 Hash 散列全量字段
redis_command(command="HGETALL user:profile:1001")

# 3. 分页读取 List 列表
redis_command(command="LRANGE task_queue 0 19")

# 4. 探活当前实例
redis_command(command="PING")
```

返回的标准信封结构示例：
```json
{
  "command": "HGETALL user:profile:1001",
  "result": {
    "name": "Alice",
    "role": "admin"
  },
  "data_type": "dict",
  "is_truncated": false,
  "total_count": null
}
```

### 2. 数据写入与修改（需 `--allow-write`）
```python
# 写入字符串并设置 60 秒过期时间
redis_command(command="SET message 'Hello, Antigravity!' EX 60")

# 向 Hash 中写入字段
redis_command(command="HSET user:profile:1001 status active")
```

### 3. 高危删除二次确认工作流 (DEL / UNLINK)
```python
# 步骤 1：初次发起删除（confirm 默认为 False）
redis_command(command="DEL cache:item1 cache:item2")
```
返回待确认结构体（**此时未执行物理删除**）：
```json
{
  "status": "confirmation_required",
  "command": "DEL cache:item1 cache:item2",
  "keys": ["cache:item1", "cache:item2"],
  "target_count": 2,
  "message": "高危删除操作需要确认。请核对目标键名并在确认后传入 confirm=True 执行物理删除。",
  "data_type": "confirmation_required",
  "is_truncated": false,
  "total_count": null
}
```
```python
# 步骤 2：向用户确认后，显式传入 confirm=True 执行真实删除
redis_command(command="DEL cache:item1 cache:item2", confirm=True)
```
返回删除影响结果：
```json
{
  "command": "DEL cache:item1 cache:item2",
  "result": 2,
  "data_type": "integer",
  "is_truncated": false,
  "total_count": null
}
```

### 4. 无状态多库与多连接切换
```python
# 切换到 3 号逻辑库执行只读检查
redis_command(command="DBSIZE", db=3)

# 切换到 staging 连接别名上的 1 号库执行查询
redis_command(command="GET app_config", connection="staging", db=1)
```

---

## 🔍 核心探查辅助工具调用与返回示例

### 1. 检视全部连接实例 (`redis_list_connections`)
```python
redis_list_connections()
```
返回结果（敏感凭据自动脱敏掩码）：
```json
{
  "default": "local",
  "total": 2,
  "connections": [
    {
      "alias": "local",
      "url": "redis://:***@localhost:6379/0",
      "db": 0,
      "readonly": false,
      "description": "本地开发实例",
      "is_default": true
    },
    {
      "alias": "prod",
      "url": "redis://:***@prod.redis.internal:6379/0",
      "db": 0,
      "readonly": true,
      "description": "生产只读从库",
      "is_default": false
    }
  ]
}
```

### 2. 聚合键扫描器 (`redis_scan_keys`)
```python
# 检索前缀匹配键（支持类型过滤，内部自动遍历游标防死循环）
redis_scan_keys(pattern="user:*", limit=10, type="hash")
```
返回结果：
```json
{
  "pattern": "user:*",
  "type": "hash",
  "count": 2,
  "keys": ["user:profile:1001", "user:profile:1002"],
  "cursor": 0,
  "is_truncated": false
}
```

### 3. 单键多维综合诊断 (`redis_key_inspect`)
```python
# 一站式单键多维诊断（类型、生命周期、内存占用与编码结构）
redis_key_inspect(key="user:profile:1001")
```
返回结果：
```json
{
  "key": "user:profile:1001",
  "exists": true,
  "type": "hash",
  "ttl": 3600,
  "pttl": 3600000,
  "memory_usage": 184,
  "encoding": "listpack"
}
```

---

## 📦 安装与快速运行

### 方式 1：使用 `uvx` 免安装直接运行（强烈推荐）

借助现代化 Python 工具链 `uv` 即可直接拉取并启动：

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
docker run -i --rm -e MCP_REDIS_URL="redis://host.docker.internal:6379/0" ghcr.io/atengk/mcp-server-redis:latest --transport stdio

# 常驻后台 HTTP SSE 服务端（暴露 8000 端口）
docker-compose up -d
```

### 方式 5：使用官方 MCP Inspector 进行本地可视化调试

无需配置大模型 GUI 客户端，直接借助 Anthropic / Model Context Protocol 官方调试工具在浏览器中可视化交互调试全部 4 个工具：

```bash
# 启动本地 Inspector 探针（自动打开浏览器调试界面）
npx @modelcontextprotocol/inspector uvx atengk-mcp-server-redis --url "redis://localhost:6379/0"
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

若需允许大模型对 Redis 进行数据写入与删除，添加 `--allow-write` 启动参数：

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
        "ghcr.io/atengk/mcp-server-redis:latest",
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
- **官方 GHCR 多架构镜像**：由 GitHub Actions CI/CD 流水线自动化构建并发布至 GitHub Container Registry（`ghcr.io/atengk/mcp-server-redis:latest`），原生支持 `linux/amd64` 与 `linux/arm64` 双架构；
- **极速精简多阶段构建**：基于 `python:3.11-slim` 底座与 `uv` 高速依赖预缓存，完全剥离包编译器，产出镜像体积严格 $< 150\text{MB}$；
- **非 Root 生产安全账号**：容器内以专有非 root 账户 `appuser` (UID: `10001`, GID: `10001`) 运行，并锁定登录 Shell（`/usr/sbin/nologin`），满足企业最小权限与容器合规审计；
- **开箱即用常驻网关**：默认入口命令为 `atengk-mcp-server-redis`，默认暴露端口 `8000` 并以 HTTP SSE 传输网关模式常驻运行。

### 使用 docker-compose 常驻部署 (SSE 模式)

工程根目录预置了生产级 [docker-compose.yml](./docker-compose.yml)。编排清单**默认拉取官方 GHCR 预编译镜像**，无需本地安装编译环境，亦可将单个文件复制至生产服务器直接运行：

```bash
# 1. (可选) 基于模板初始化本地环境参数
cp .env.example .env

# 2. 后台常驻启动 MCP SSE 服务端 (自动拉取官方 GHCR 镜像)
docker-compose up -d

# 3. 检视实时服务日志
docker-compose logs -f
```

容器启动后，MCP 服务端将在宿主机 `http://localhost:8000/sse` 持续监听。各大支持远程 SSE 协议的 MCP 客户端（如 Cherry Studio、远程 Web AI 网关等）只需直接填写该 URL 即可挂载。

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
- 🛡️ **跨槽 (Cross-Slot) 异常优雅降级**：
  在分片集群中执行多键命令（如 `MGET`、`DEL` 多个跨槽键）若触发 `CROSSSLOT Keys in request don't hash to the same slot` 异常，`redis_command` 自动捕获并输出结构化错误引导，明确提示大模型按单键分别执行。
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

> 💡 **快速配置**：项目根目录提供了开箱即用的配置模板 [`.env.example`](./.env.example)，执行 `cp .env.example .env` 并按需微调即可快速完成本地或容器环境初始化。

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
                       │   大模型发起 redis_command    │
                       └──────────────┬───────────────┘
                                      │
                                      ▼
                         [ 破坏性指令物理切断拦截器 ] ────► 命中 FLUSHALL/KEYS* 等 ──► 抛出 DestructiveCommandError 物理阻断
                                      │ (安全通过)
                                      ▼
                           [ 命令分类裁决器 Classifier ]
                                /             \
                     (只读白名单 80+ 命令)    (非只读命令 / 模块扩展命令)
                              │                     │
                              │                     ▼
                              │             [ 双重写门禁检测 ]
                              │             1. CLI --allow-write 是否启用？
                              │             2. 目标连接 readonly 是否为 false？
                              │                     │ (任一不满足即拦截)
                              │                     ▼
                              │            [ 删除二次确认门禁 ]
                              │            命中 DEL / UNLINK 且 confirm==False？
                              │             ├── 是 ──► 返回待确认结构体 (终止执行)
                              │             └── 否 (confirm==True)
                              │                     │
                              ▼                     ▼
                      ┌──────────────────────────────┐
                      │   下发底层 Redis 异步指令    │
                      └──────────────┬───────────────┘
                                     │
                                     ▼
                         [ 集合切片守卫与安全序列化 ]
                        • 大集合超过 100 项自动截断
                        • UTF-8 / Base64 自适应转码
                                     │
                                     ▼
                         [ 统一结果信封包装输出 ]
```

1. **破坏性指令物理切断**：硬编码阻断 `FLUSHALL`、`FLUSHDB`、`SHUTDOWN`、`CONFIG`、`DEBUG` 及阻塞式 `KEYS *`；
2. **闭环白名单与双重写门禁**：80+ 只读命令白名单放行，其余命令由双重写门禁严格把关；
3. **删除二次确认门禁**：`DEL`/`UNLINK` 命令在未传 `confirm=True` 时拦截物理执行，向调用方输出待确认影响清单；
4. **防 OOM 自动集合切片**：大集合结果自动截断至 100 项，并在元数据中断言截断状态；
5. **敏感凭据自动脱敏**：连接日志与配置查询中密码一律掩码输出。

---

## 🚨 常见拦截与错误排查指南 (Troubleshooting)

| 异常现象 / 响应特征 | 触发原因 | 推荐解决排查方式 |
| :--- | :--- | :--- |
| **`ReadOnlyModeError`**<br>`服务处于只读保护模式...` | 在未传 `--allow-write` 的全局只读模式下尝试执行写操作（如 `SET`、`HSET`、`LPUSH` 等）。 | 若需写权限，在服务启动命令中显式追加 `--allow-write`（或环境变量 `MCP_REDIS_ALLOW_WRITE=true`）。 |
| **`ReadOnlyConnectionError`**<br>`目标连接配置为只读...` | 虽然开启了全局 `--allow-write`，但在多实例配置中目标连接档案被显式标明 `readonly: true`。 | 检查 `connections.yaml`，确认是否需要在该特定环境开启写操作；若为生产保护从库，严禁修改。 |
| **`confirmation_required`**<br>`status: confirmation_required` | 调用 `DEL` 或 `UNLINK` 命令时未显式传入 `confirm=True`。 | 属于正常安全二次确认拦截。大模型/调用方需在核对 `keys` 列表后，再次调用 `redis_command(..., confirm=True)`。 |
| **`DestructiveCommandError`**<br>`物理切断破坏性高危指令...` | 尝试执行破坏性删库或阻塞指令（`FLUSHALL`、`FLUSHDB`、`KEYS *`、`SHUTDOWN`、`CONFIG` 等）。 | 底层永久物理拦截，无法通过任何参数绕过。请改用键前缀安全扫描 `redis_scan_keys` 或单键操作。 |
| **`CrossSlotError`**<br>`Redis Cluster 跨槽执行拦截...` | 在分片集群中执行跨越不同哈希槽的多键命令（如 `MGET {user1}:a {user2}:b`）。 | 遵循语义化引导，将多键指令拆分为针对单一键或相同哈希标签（`{hash_tag}`）的多次独立单键命令。 |
| **`ConnectionError`**<br>`Error connecting to host...` | Redis 端口未开放、网络不可达、防火墙拦截或连接超时。 | 使用 `Test-NetConnection` 或 `nc -zv` 验证网络链路，检查密码是否包含特殊字符（推荐使用离散环境变量配置）。 |

---

## ⚠️ 边界约束与不支持操作 (Limitations & Out-of-Scope)

作为专为大语言模型打造的单次请求/响应 MCP 协议网关，以下 Redis 场景超出了本工具的设计范畴：

1. **阻塞式长订阅（Pub/Sub Streaming）**：
   - 不支持 `SUBSCRIBE` / `PSUBSCRIBE`。MCP 工具基于非流式单次同步响应范式，长连接事件推送应由专用的 MQ 消费者或微服务长连接处理。
2. **跨请求有状态事务（Multi-Request Transactions）**：
   - 不支持跨请求的 `MULTI` / `EXEC` / `WATCH` 会话。每次 `redis_command` 均为独立的无状态操作，底层连接池在并发复用时不保持会话级事务状态。
3. **永久挂起阻塞式命令（Zero-Timeout Blocking Commands）**：
   - 执行 `BLPOP`、`BRPOP`、`BZPOPMIN` 等阻塞式读取时，**严禁将超时参数设为 `0`**（无限阻塞等待），否则会导致服务工作进程被永久挂起。建议传入短超时参数（如 `BLPOP mylist 1`）。
4. **服务运行态配置动态篡改**：
   - `CONFIG SET`、`CONFIG REWRITE` 属于底层永久硬阻断范畴，严禁在大模型会话中篡改 Redis 服务运行配置。

---

## 🤝 参与贡献

我们欢迎社区贡献！如果您发现了缺陷或有功能建议：

1. 提交 [GitHub Issues](https://github.com/atengk/mcp-server-redis/issues)；
2. 查阅 [贡献指南](./CONTRIBUTING.md) 与 [智能体工程规范](./AGENTS.md)；
3. 发起 Pull Request。

---

## 📄 开源许可证

本项目基于 [MIT 许可证](./LICENSE) 开源。
