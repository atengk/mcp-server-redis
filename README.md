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
    <img src="https://img.shields.io/badge/License-Apache_2.0-blue.svg?style=flat-square" alt="License" />
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

- ⚡ **原生 Redis CLI 命令网关 (`redis_execute_command`)**：
  - 单行原生命令语法交互（如 `"HGETALL user:1001"`、`"SET message 'hello world' EX 60"`），完全释放大模型对 300+ Redis 原生指令及模块（JSON、Search 等）的表达力；
  - 内置 POSIX 标准引号分词解析，原生支持带空格与特殊字符的复杂参数；
  - 智能 INFO 命令分节结构化与数值自适应推导，消除 60%+ 上下文 Token 浪费；
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
  - `redis_scan_keys`：内部自动循环迭代 `SCAN` 游标聚合返回，支持 `include_meta=True` 单次并发拉取类型与 TTL，规避 N+1 往返；
  - `redis_inspect_key`：单键多维诊断（类型、TTL/PTTL、内存占用字节及底层编码格式）；
  - 所有工具统一支持 `connection`（连接别名）与 `db`（0~15 逻辑库编号）参数，物理禁止在连接池上执行全局有状态 `SELECT` 指令。
- 🌐 **全 MCP 协议矩阵支持 (Tools + Resources + Prompts)**：
  - 挂载 `redis://{connection}/info`、`redis://{connection}/slowlog` 与客户端脱敏快照 `redis://{connection}/clients` 只读系统资源；
  - 提供 `redis_diagnose_memory`、`redis_analyze_slowlog` 与 `redis_troubleshoot_bigkeys` 标准排障 SOP 提示词模板。

---

## 🛠️ 4 个核心工具矩阵速查

| MCP 工具名称 | 核心参数契约 | 功能描述与安全门禁 |
| :--- | :--- | :--- |
| **`redis_execute_command`** | `(command="", commands=None, connection=None, db=None, confirm=False)` | **核心命令网关**：原生 Redis 命令执行通道。<br>• 80+ 只读白名单直接放行<br>• 写命令受双重写门禁管辖（`--allow-write`）<br>• `DEL`/`UNLINK` 强制要求 `confirm=True` 二次确认<br>• 永久物理阻断破坏性指令（`FLUSHALL`/`KEYS *` 等）<br>• 支持 `commands=[...]` 管道批处理（上限 20 条，全批次 Fail-Close 强校验）<br>• 阻塞式读取命令（`BLPOP` 等）超时自动安全收敛（0 秒改写为 2 秒，最大 5 秒）防假死<br>• `INFO` 命令自动智能结构化紧凑字典<br>• 超过 100 项大集合自动截断防 OOM |
| **`redis_list_connections`** | `()` | **连接实例检视**：查看所有已配置的 Redis 连接别名、脱敏 URL、数据库编号及默认连接标识。 |
| **`redis_scan_keys`** | `(pattern="*", limit=50, cursor=0, type=None, connection=None, db=None, include_meta=False)` | **聚合键扫描器**：非阻塞循环迭代底层游标聚合检索匹配键名，默认最多 50 条，单次硬上限 200 条，杜绝游标死循环。支持传入上一页 `cursor` 断点续翻，支持 `include_meta=True` 单次往返并发附带类型与 TTL。 |
| **`redis_inspect_key`** | `(key: str, connection=None, db=None)` | **单键多维诊断**：聚合获取目标键的类型、TTL/PTTL、内存占用（`MEMORY USAGE`）与底层存储编码。 |


---

## 💡 `redis_execute_command` 调用示例

### 1. 基础只读查询与带空格传参
```python
# 1. 查询字符串（支持带引号空格传参）
redis_execute_command(command="GET 'user:session:1001'")

# 2. 读取 Hash 散列全量字段
redis_execute_command(command="HGETALL user:profile:1001")

# 3. 分页读取 List 列表
redis_execute_command(command="LRANGE task_queue 0 19")

# 4. 探活当前实例
redis_execute_command(command="PING")
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
redis_execute_command(command="SET message 'Hello, Antigravity!' EX 60")

# 向 Hash 中写入字段
redis_execute_command(command="HSET user:profile:1001 status active")
```

### 3. 高危删除二次确认工作流 (DEL / UNLINK)
```python
# 步骤 1：初次发起删除（confirm 默认为 False）
redis_execute_command(command="DEL cache:item1 cache:item2")
```
返回待确认结构体（**此时未执行物理删除**）：
```json
{
  "command": "DEL cache:item1 cache:item2",
  "status": "confirmation_required",
  "result": null,
  "data_type": "confirmation_required",
  "keys": ["cache:item1", "cache:item2"],
  "target_count": 2,
  "message": "该高危删除操作涉及 2 个键: ['cache:item1', 'cache:item2']。为防止非预期数据丢失，请在仔细核对后显式传入 confirm=True 确认执行。",
  "is_truncated": false,
  "total_count": 2
}
```
```python
# 步骤 2：向用户确认后，显式传入 confirm=True 执行真实删除
redis_execute_command(command="DEL cache:item1 cache:item2", confirm=True)
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

### 4. 智能 INFO 命令分节结构化与数值转换
直接执行 `INFO` 或 `INFO <section>`，服务端序列化器自动将上千行多段纯文本清洗转换为紧凑 JSON 字典，自动转换数值类型：
```python
# 获取内存分节紧凑字典
redis_execute_command(command="INFO memory")
```
返回结果：
```json
{
  "command": "INFO memory",
  "result": {
    "used_memory": 2097152,
    "used_memory_human": "2.00M",
    "used_memory_rss": 5242880,
    "mem_fragmentation_ratio": 1.25
  },
  "data_type": "dict",
  "is_truncated": false,
  "total_count": 4
}
```

### 5. 无状态多库与多连接切换
```python
# 切换到 3 号逻辑库执行只读检查
redis_execute_command(command="DBSIZE", db=3)

# 切换到 staging 连接别名上的 1 号库执行查询
redis_execute_command(command="GET app_config", connection="staging", db=1)
```

### 6. 多命令管道批处理 (`commands=[...]`)
通过 `commands` 传入多命令列表，在单一网络往返中通过底层 Redis Pipeline 批量下发（上限 20 条），大幅降低 LLM 多轮工具交互的推理延迟与网络开销。
全批次实施 **Fail-Close 前置强校验**：若任一条命令命中破坏性阻断或未授权写门禁，整批直接拒绝执行；若包含 `DEL/UNLINK` 且未传 `confirm=True`，合并返回包含待删键汇总的二次确认信封。
```python
# 单次往返管道批处理执行多命令
redis_execute_command(commands=["SET user:1 'Alice'", "GET user:1", "EXISTS user:1"])
```
返回的聚合信封示例：
```json
{
  "command": "PIPELINE",
  "status": "success",
  "total_commands": 3,
  "results": [
    { "command": "SET user:1 'Alice'", "result": "OK", "data_type": "string", "is_truncated": false, "total_count": null },
    { "command": "GET user:1", "result": "Alice", "data_type": "string", "is_truncated": false, "total_count": null },
    { "command": "EXISTS user:1", "result": 1, "data_type": "integer", "is_truncated": false, "total_count": null }
  ],
  "data_type": "pipeline",
  "is_truncated": false,
  "total_count": 3
}
```

### 7. 阻塞式命令超时主动安全防线 (`BLPOP` 等)
当模型调度阻塞式读取命令（如 `BLPOP queue 0`）时，零超时（无限等待）会导致底层异步 Socket 永久挂起、MCP 进程假死。
安全守卫自动执行**超时参数主动安全收敛**：超时为 0 强制安全改写为 2 秒，超时超过 5 秒强制截断为 5 秒，并在信封中回传说明信息：
```python
redis_execute_command(command="BLPOP task_queue 0")
```
返回结果示例：
```json
{
  "command": "BLPOP task_queue 0",
  "result": null,
  "data_type": "none",
  "message": "阻塞命令 'BLPOP' 超时设为 0（零超时无限等待），为防止 MCP 服务进程挂起假死，已主动安全收敛改写为 2 秒。",
  "is_truncated": false,
  "total_count": null
}
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
      "key_patterns": ["*"],
      "is_default": true
    },
    {
      "alias": "prod",
      "url": "redis://:***@prod.redis.internal:6379/0",
      "db": 0,
      "readonly": true,
      "description": "生产只读从库",
      "key_patterns": ["order:*", "user:*"],
      "is_default": false
    }
  ]
}
```

### 2. 聚合键扫描器与断点续翻 (`redis_scan_keys`)
支持常规扫描、`cursor` 断点续翻与 `include_meta=True` 复合元数据扫描，在单次往返中并发拿齐键类型与 TTL，彻底终结 N+1：
```python
# 1. 开启 include_meta=True 一站式扫描
res = redis_scan_keys(pattern="user:*", limit=10, include_meta=True)

# 2. 依据上一页返回的游标实现断点续翻分页
if res["is_truncated"] and res["cursor"] > 0:
    res_page2 = redis_scan_keys(pattern="user:*", limit=10, cursor=res["cursor"], include_meta=True)
```
返回结果：
```json
{
  "pattern": "user:*",
  "type": null,
  "count": 2,
  "keys": ["user:profile:1001", "user:profile:1002"],
  "entries": [
    { "key": "user:profile:1001", "type": "hash", "ttl": 3600 },
    { "key": "user:profile:1002", "type": "hash", "ttl": -1 }
  ],
  "cursor": 0,
  "is_truncated": false
}
```

### 3. 单键多维综合诊断 (`redis_inspect_key`)
```python
# 一站式单键多维诊断（类型、生命周期、内存占用与编码结构）
redis_inspect_key(key="user:profile:1001")
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

## 💬 生产排障与日常高频实用提示词 (Everyday Prompts & SOPs)

除了 4 个核心工具，服务还完整实现了 MCP 规范的 Resources 与 Prompts 原语，并针对大模型日常运维交互场景总结了开箱即用的高频实用提示词模版。

### 1. 只读系统快照资源 (Resources)
现代 MCP 客户端（如 Claude Desktop 或 Cursor）可在不产生工具调用的前提下直接注入只读上下文：
- `redis://{connection}/info` / `redis://info`：指定连接或默认连接的实时综合指标快照（MIME: `application/json`）；
- `redis://{connection}/slowlog` / `redis://slowlog`：指定连接或默认连接的最新 10 条慢查询日志切片；
- `redis://{connection}/clients` / `redis://clients`：指定连接或默认连接的活跃客户端连接列表（IP 末段自动脱敏，防止内网拓扑泄露）。

### 2. MCP 内置标准诊断 SOP 提示词 (Built-in Prompts)
在支持 MCP Prompts 的客户端（如 Claude Desktop、Cursor、Cherry Studio）中，输入 `/` 即可一键挂载以下标准化生产级运维排查 SOP：

| 内置 Prompt 名称 | 核心参数 | 排查诊断 SOP 工作流 |
| :--- | :--- | :--- |
| **`redis_diagnose_memory`** | `connection: str = "default"` | **内存瓶颈排查 SOP**：指引模型按「基线指标核对（`used_memory` / `mem_fragmentation_ratio`） ➔ 碎片率与 Swap 风险分析 ➔ 复合键采样（`include_meta=True` 规避 N+1） ➔ 单键精细诊断（`MEMORY USAGE` / `encoding`） ➔ 调优报告输出」闭环排查内存问题。 |
| **`redis_analyze_slowlog`** | `connection: str = "default"` | **慢查询优化分析 SOP**：指引模型按「拉取慢查（读取 `/slowlog` 资源或 `SLOWLOG GET 10`） ➔ 命令耗时与频次归类 ➔ O(N) 复杂指令与单线程阻塞根因定级 ➔ 分页切片与异步化建议」系统优化高耗时指令。 |
| **`redis_troubleshoot_bigkeys`** | `connection: str = "default"` | **BigKey 治理排障 SOP**：指引模型按「渐进式键采样（非阻塞 SCAN 替代 KEYS） ➔ 轻量 O(1) 基数探查（`HLEN`/`SCARD`/`LLEN`/`ZCARD`，严禁无界全量拉取） ➔ 单键内存与编码诊断 ➔ 渐进式分页切片替代 ➔ 异步 `UNLINK` 安全清理」系统治理巨型键。 |

### 3. 日常对话高频实用提示词模版 (Everyday Routine Prompts)

在日常与挂载了本 MCP 服务的 AI Agent 对话时，可直接复制并根据实际业务调整以下 6 大高频提示词：

#### 场景 1：日常键空间探查与数据检视
> **提示词**：  
> “请帮我检索当前 Redis 中所有以 `user:*` 为前缀的键，列出它们的数据类型、TTL 过期时间以及内存大小。注意：请使用非阻塞的聚合扫描工具，严禁使用阻塞式的 KEYS 命令。”

#### 场景 2：实例健康状态与内存碎片率巡检
> **提示词**：  
> “请对当前 Redis 实例进行一次全面的健康体检：  
> 1. 读取系统 INFO 信息，汇总已用内存（used_memory_human）、内存峰值和内存碎片率（mem_fragmentation_ratio）；  
> 2. 分析当前碎片率是否正常，评估是否存在内存严重碎片化或物理内存换页（Swap）风险；  
> 3. 查看连接的客户端数量并给出健康评估结论与调优建议。”

#### 场景 3：慢查询定位与性能优化建议
> **提示词**：  
> “请帮我抓取当前 Redis 最近的 10 条慢查询日志（Slowlog），分析耗时最长的是哪些命令、涉及的键名与耗时微秒数。针对耗时较高的操作，请指出其根本原因（如是否存在全量扫描、未切片读取或跨槽执行），并给出具体的优化替换方案。”

#### 场景 4：BigKey 安全探查与渐进式切片治理
> **提示词**：  
> “请帮我排查当前数据库中是否存在占用过大的 BigKey：  
> 1. 先通过扫描获取候选键集合；  
> 2. 针对集合类型键，先调用轻量 O(1) 指令（如 HLEN、LLEN、SCARD、ZCARD）检查其元素规模，严禁直接执行 HGETALL 或全量 SMEMBERS；  
> 3. 针对疑似大键诊断其 memory_usage 与底层 encoding 编码；  
> 4. 若集合元素超过 1000 项，请给出使用 HSCAN/SSCAN 渐进式分页切片读取的方案。”

#### 场景 5：多实例定向检索与数据比对
> **提示词**：  
> “我们配置了多套 Redis 实例。请帮我查询：  
> 1. 在 `user-cache` 实例中查找键 `session:token:1001` 的数据内容与剩余 TTL；  
> 2. 在 `order-cache` 实例中查找以 `order:1001:*` 开头的最新订单键；  
> 3. 比对两个实例中用户 ID 关联数据的状态是否一致。”

#### 场景 6：安全删除二次确认闭环
> **提示词**：  
> “请帮我清理过期的临时导出缓存键，前缀为 `temp:export:202610*`。  
> 核心安全要求：请先调用命令获取待删除的键清单与影响总数（此时不要加 confirm=True），向我列出确认清单；等我仔细核对并回复‘确认执行’后，你再显式传入 confirm=True 执行物理清理。”

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

### 方式 6：一键环境连通性自检与版本环境指纹 (`--doctor` / `--version`)

在配置客户端前，推荐使用 `--doctor` 进行四维全景环境体检（Python 依赖、配置文件、网络 RTT、写权限探针），提前发现潜在连通障碍：

```bash
# 1. 针对当前默认环境或 .env 进行一键自检（终端富文本卡片展示）
uvx atengk-mcp-server-redis --doctor

# 2. 检查指定远程 Redis 连接连通性与写权限隔离探针
uvx atengk-mcp-server-redis --url "redis://:password@remote.host:6379/0" --allow-write --doctor

# 3. 对多实例配置文件进行全量巡检并导出结构化 JSON 报告（CI/CD 流水线友好）
uvx atengk-mcp-server-redis --config ./connections.yaml --doctor --json

# 4. 查看详细服务版本与底层运行时环境指纹 (Python/mcp/redis-py/OS)
uvx atengk-mcp-server-redis --version
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

容器启动后，MCP 服务端将在宿主机 `http://localhost:8000/sse` 持续监听。各大支持远程 SSE 协议的 MCP 客户端（如 Cherry Studio、远程 Web AI 网关等）只需直接填写该 URL 即可挂载。同时可直接通过 `http://localhost:8000/healthz` 进行容器或云原生网关连通性探活。

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
  在分片集群中执行多键命令（如 `MGET`、`DEL` 多个跨槽键）若触发 `CROSSSLOT Keys in request don't hash to the same slot` 异常，`redis_execute_command` 自动捕获并输出结构化错误引导，明确提示大模型按单键分别执行。
- 🔍 **全节点聚合扫描 (`redis_scan_keys`)**：
  集群模式自适应切换至 `client.scan_iter` 机制，自动轮询遍历全部分片 Master 节点并聚合匹配键集合，受条数上限（默认 50，硬上限 200）安全截断保护。

---

## 🚀 Stdio、SSE 与 Streamable-HTTP 全模传输网关

本服务在应用层抽象了全模传输网关架构，一套代码兼顾本地终端进程间通信与分布式微服务网络暴露：

```
                    ┌────────────────────────────────────────────────────────┐
                    │               atengk-mcp-server-redis                  │
                    │                 (FastMCP 核心服务层)                   │
                    └───────────┬─────────────────┬──────────────────┬───────┘
                                │                 │                  │
               (默认模式)       │                 │ (--transport sse)│ (--transport streamable-http)
                                ▼                 ▼                  ▼
                    ┌──────────────────┐  ┌──────────────────┐ ┌────────────────────┐
                    │  标准 Stdio 管道  │  │   HTTP SSE 网关  │ │Streamable-HTTP 网关│
                    │  (JSON-RPC 流)   │  │  (:8000/sse 端点) │ │   (:8000/mcp 端点)  │
                    └─────────┬────────┘  └─────────┬────────┘ └─────────┬──────────┘
                                │                   │                    │
                                ▼                   ▼                    ▼
                     本地大模型客户端       远程 Web AI 网关      现代微服务 / 云原生集成
                     (Claude/Cursor/Cline)  (浏览器/反代接入)     (高性能流式低延迟 RPC)
```

1. **标准 Stdio 管道模式（默认）**：
   - 默认模式，日志严格绑定至 `sys.stderr`，绝不污染 stdout 协议流，100% 严格向后兼容所有现有客户端配置；
2. **HTTP Server-Sent Events (SSE) 服务端模式**：
   - 通过 `--transport sse`（或 `MCP_REDIS_TRANSPORT=sse`）激活，端点监听于 `/sse` 与 `/messages/`；
3. **Streamable-HTTP 流式 HTTP 模式**：
   - 通过 `--transport streamable-http`（或 `MCP_REDIS_TRANSPORT=streamable-http`）激活，默认端点监听于 `/mcp`，支持高吞吐双向流式通信；
4. **HTTP 传输安全与访问令牌门禁 (`--auth-token`)**：
   - 在 HTTP 网关暴露于公网或跨节点网络时，推荐通过 `--auth-token`（或 `MCP_REDIS_AUTH_TOKEN`）配置轻量认证凭据（推荐 $\ge 16$ 字符高熵字符串，受 `--doctor` 复杂度审计）；
   - 支持标准 HTTP 标头 `Authorization: Bearer <token>` 与 URL 查询参数 `?token=<token>`，未授权请求直接拦截返回 HTTP 401 JSON；
   - **CORS 预检豁免**：鉴权中间件自动无感放行 HTTP `OPTIONS` 跨源预检请求，杜绝浏览器跨源协商因未携带 Header 被误拒。
5. **DNS 重绑定与跨源攻击防御 (`--allowed-hosts`)**：
   - 遵循 **安全默认原则 (Safe-by-Default)**，默认监听绑定于本地回环地址 `127.0.0.1`；
   - 底层强制启用 `TransportSecuritySettings` 校验 Host 标头与 Origin，防止恶意外网页面通过浏览器发起跨源伪造攻击；
   - 容器或远程部署绑定 `--host 0.0.0.0` 时，可通过 `--allowed-hosts`（或 `MCP_REDIS_ALLOWED_HOSTS`，逗号切分）精确声明反向代理域名（如 `mcp.example.com`）；
   - **生产环境最佳实践**：公网环境下强烈建议通过 Nginx / Caddy / Envoy 反向代理终结 TLS（HTTPS/WSS），并在私有 VPC 或内网安全组中隔离 Redis 服务端。
6. **云原生健康探活路由与防击穿缓存 (`/health` 与 `/healthz`)**：
   - 在任何 HTTP 模式（SSE 或 Streamable-HTTP）下，服务端自动挂载 `/health` 与 `/healthz` HTTP GET 探活端点（豁免鉴权）；
   - 内置 **2.0 秒内存短时状态缓存与并发双检锁**：在抵御公网与高频监控探活时避免频繁冲击底层 Redis 造成连接池耗尽；
   - 结合底层 Redis `PING` 探活与 1.0 秒保底超时，精准适配 Kubernetes Liveness / Readiness 探针及负载均衡健康切流：
     - **健康正常 (HTTP 200)**：`{"status": "healthy", "version": "2.2.0", "redis": "ok"}`
     - **连接异常 (HTTP 503)**：`{"status": "unhealthy", "version": "2.2.0", "redis": "error", "error": "..."}`
7. **生产反向代理加固与 Nginx 配置样例 (TLS 终结、流式无缓冲与 URL 日志脱敏)**：
   - 针对浏览器原生 `EventSource` 必须依赖 `?token=...` 的场景，反向代理应在落盘访问日志前自动对敏感凭据掩码，防止日志中心泄密；
   - 针对 SSE 与 Streamable-HTTP 必须关闭代理缓冲（`proxy_buffering off`），并保持长超时连接。

```nginx
# Nginx 生产加固配置参考 (TLS 终结 + 流式无缓冲 + Token 访问日志脱敏)
http {
    # 提取并脱敏 URL 中的 token 查询参数
    map $args $loggable_args {
        "~(.*)(?:token|auth_token)=[^&]+(.*)"  "$1token=***$2";
        default                                $args;
    }

    log_format masked_combined '$remote_addr - $remote_user [$time_local] '
                               '"$request_method $uri?$loggable_args $server_protocol" '
                               '$status $body_bytes_sent "$http_referer" '
                               '"$http_user_agent"';

    server {
        listen 443 ssl http2;
        server_name mcp.example.com;

        ssl_certificate     /etc/ssl/certs/mcp.example.com.crt;
        ssl_certificate_key /etc/ssl/private/mcp.example.com.key;
        ssl_protocols       TLSv1.2 TLSv1.3;

        # 采用脱敏格式输出访问日志
        access_log /var/log/nginx/mcp_access.log masked_combined;

        location / {
            proxy_pass http://127.0.0.1:8000;

            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header Connection "";

            # 关键：针对 SSE 与 Streamable-HTTP 关闭缓冲，确保分块流式实时直达
            proxy_buffering off;
            proxy_cache off;
            chunked_transfer_encoding on;

            # 保持长连接活跃，防止流式通道被中间网关闲置超时切断
            proxy_read_timeout 3600s;
            proxy_send_timeout 3600s;
        }

        # 探活接口专用轻量路由
        location /healthz {
            proxy_pass http://127.0.0.1:8000/healthz;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
        }
    }
}
```

```bash
# 启动 HTTP Streamable-HTTP 网关，配置安全访问令牌并仅允许特定域名访问
uvx atengk-mcp-server-redis --transport streamable-http --host 0.0.0.0 --port 8000 --auth-token "YOUR_SECRET_TOKEN" --allowed-hosts "mcp.example.com"

# 验证云原生探活健康检查 (无需 Token 自动放行，具备 2.0s 内存防击穿缓存)
curl -i http://localhost:8000/healthz
```

---

## 💻 CLI 命令行参数完整参考 (CLI Arguments Reference)

`atengk-mcp-server-redis` 命令行工具内置标准 POSIX 规范的参数解析器，通过 `--help` 输出清晰的四大逻辑功能分组。所有关键参数均支持对应的 `MCP_REDIS_*` 环境变量映射，遵循「CLI 命令行参数 > 系统/用户级环境变量 > .env 文件 > 保底默认值」的优先级决议准则。

### 1. 基础连接配置 (Connection Options)
| 命令行参数 | 对应环境变量 | 默认值 | 作用与用法示例 |
| :--- | :--- | :--- | :--- |
| `--url <str>` | `MCP_REDIS_URL` | - | 单个 Redis 连接 URL，支持单机免密、带密、SSL/TLS (`rediss://`) 及集群 (`redis-cluster://`) 协议头。示例：`--url "redis://:pass@localhost:6379/0"` |
| `--config <path>` | `MCP_REDIS_CONFIG` | - | 多实例连接配置文件路径，支持 YAML 与 JSON 格式。示例：`--config ./connections.yaml` |
| `--cluster` | `MCP_REDIS_CLUSTER` | `false` | 强制激活 Redis Cluster 分片集群连接模式，启用单库 (db=0) 防御与跨槽并发防御 |

### 2. 安全与权限控制 (Security & Permissions)
| 命令行参数 | 对应环境变量 | 默认值 | 作用与用法示例 |
| :--- | :--- | :--- | :--- |
| `--allow-write` | `MCP_REDIS_ALLOW_WRITE` | `false` | 显式开启数据写权限。默认全局强只读，写操作受启动参数与连接 `readonly: false` 双重门禁管控 |
| `--audit-log <target>` | `MCP_REDIS_AUDIT_LOG` | - | 结构化命令审计日志输出目标，支持 `'stderr'`、`'stdout'` 或具体文件路径（在 stdio 传输模式下自动重定向至 stderr 防协议污染） |
| `--auth-token <token>` | `MCP_REDIS_AUTH_TOKEN` | - | HTTP 传输层鉴权访问凭据，拦截未授权访问（支持 `Authorization: Bearer <token>` 与 `?token=<token>`，豁免探活端点） |

### 3. 服务与网络传输 (Transport & Server)
| 命令行参数 | 对应环境变量 | 默认值 | 作用与用法示例 |
| :--- | :--- | :--- | :--- |
| `--transport <stdio\|sse\|streamable-http>` | `MCP_REDIS_TRANSPORT` | `stdio` | 传输协议模式。`stdio` 适合本地客户端，`sse` 适合 Web AI 网关，`streamable-http` 适合现代化流式高并发微服务 RPC |
| `--host <ip>` | `MCP_REDIS_SERVER_HOST` | `127.0.0.1` | HTTP 网关监听绑定的主机 IP 地址（安全默认监听本地回环，容器/远程可显式声明 `0.0.0.0`） |
| `--port <port>` | `MCP_REDIS_SERVER_PORT` | `8000` | HTTP 网关服务端监听绑定的 HTTP 端口号 |
| `--allowed-hosts <hosts>` | `MCP_REDIS_ALLOWED_HOSTS` | - | HTTP 传输层允许的主机标头白名单（逗号分隔多主机规则，防御 DNS 重绑定与跨源攻击） |
| `--log-level <level>` | `MCP_REDIS_LOG_LEVEL` | `INFO` | 运行时日志级别，可选 `DEBUG`、`INFO`、`WARNING`、`ERROR`（日志一律输出至 stderr 杜绝污染） |
| `--server-name <name>` | `MCP_REDIS_SERVER_NAME` | `mcp-server-redis` | MCP 协议握手层声明的服务实例名称，供宿主客户端区分多 MCP 服务实例（底层工具名保持物理稳定不变） |
| `--server-instructions <text>` | `MCP_REDIS_SERVER_INSTRUCTIONS` | 内置指导 | 向大模型注入的全局系统级业务指导与拓扑边界说明 |

### 4. 运维诊断与信息 (Diagnostics & Info)
| 命令行参数 | 对应环境变量 | 默认值 | 作用与用法示例 |
| :--- | :--- | :--- | :--- |
| `--doctor` | - | `false` | 执行生产环境连通性、配置语义与隔离写权限四维健康自检探针并退出（零生产污染，成功返回 0，失败返回 1） |
| `--json` | - | `false` | 配合 `--doctor` 参数时以结构化 JSON 格式输出自检报告，便于 CI/CD 流水线与自动化测试脚本解析 |
| `-v`, `--version` | - | - | 输出详细服务版本号与底层运行时环境指纹（Python / OS / mcp / redis-py / pydantic / pyyaml）并退出 |
| `-h`, `--help` | - | - | 显示按四大逻辑分组归类的命令行帮助信息与典型场景使用示例 |

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
| `MCP_REDIS_TRANSPORT` | `stdio` | 传输协议模式。可选 `stdio`、`sse` 或 `streamable-http`（大小写不敏感） |
| `MCP_REDIS_SERVER_HOST` | `127.0.0.1` | HTTP 网关绑定的监听主机地址（安全默认监听本地回环） |
| `MCP_REDIS_SERVER_PORT` | `8000` | HTTP 网关绑定的 HTTP 监听端口 |
| `MCP_REDIS_SERVER_NAME` | `mcp-server-redis` | MCP 协议服务实例名称标识（映射 `--server-name`） |
| `MCP_REDIS_SERVER_INSTRUCTIONS` | 内置指导 | 向大模型注入的全局系统级业务指导指令（映射 `--server-instructions`） |

### 3. 安全权限与网络治理
| 环境变量名 | 默认值 | 作用与用法示例 |
| :--- | :--- | :--- |
| `MCP_REDIS_ALLOW_WRITE` | `false` | 正向显式授权写权限。值为 `true`、`1`、`yes`、`on` 时开启写操作 |
| `MCP_REDIS_READ_ONLY` | `true` | 反向只读控制。显式设为 `false`、`0`、`no`、`off` 时解除只读并开启写权限 |
| `MCP_REDIS_AUTH_TOKEN` | - | HTTP 传输层轻量访问认证凭据（支持 Bearer Token 与 URL 查询参数；映射 `--auth-token`） |
| `MCP_REDIS_ALLOWED_HOSTS` | - | HTTP 传输层允许的主机标头白名单（逗号分隔多主机规则，防御 DNS 重绑定；映射 `--allowed-hosts`） |
| `MCP_REDIS_LOG_LEVEL` | `INFO` | 运行时日志输出级别。支持 `DEBUG`、`INFO`、`WARNING`、`ERROR`（日志严格绑定至 stderr） |
| `MCP_REDIS_CONNECT_TIMEOUT` | `5.0` | Socket 连接超时保底时间（秒），防止节点宕机网络挂死，亦支持别名 `MCP_REDIS_SOCKET_CONNECT_TIMEOUT` |
| `MCP_REDIS_SOCKET_TIMEOUT` | `10.0` | Socket 指令执行超时保底时间（秒），亦支持别名 `MCP_REDIS_TIMEOUT` |
| `MCP_REDIS_MAX_CONNECTIONS` | `50` | 单个连接池最大并发连接数上限，防止异常网络重试打满 Redis 连接 |
| `MCP_REDIS_AUDIT_LOG` | - | 结构化命令审计日志输出目标（'stderr'、'stdout' 或文件路径，stdio 传输模式下自动重定向至 stderr 杜绝协议污染） |
| `MCP_REDIS_MAX_UNBOUNDED_READ_ITEMS` | `2000` | 高危无界全量读取（HGETALL/SMEMBERS 等）元素上限防爆阈值，超过自动拦截 |
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
    key_patterns: ["*"]
    db: 0

  user-cache:
    url: "redis://:stage_pass@user.redis.internal:6379/0"
    readonly: false
    description: "用户中心会话与 Token 缓存"
    key_patterns: ["token:*", "user:*", "session:*"]
    db: 0

  order-cache:
    url: "redis://:prod_pass@order.redis.internal:6379/0"
    readonly: true
    description: "订单与库存热点从库（绝对只读保护）"
    key_patterns: ["order:*", "stock:*"]
    db: 0
```

启动命令：
```bash
uvx atengk-mcp-server-redis --config ./connections.yaml --allow-write
```

> **大模型智能感知与自愈路由**：
> 1. **动态 Schema 注入**：启动加载配置文件后，服务端会自动将各连接别名、只读属性、业务描述与 `key_patterns` 编译进所有 MCP 工具的 `connection` 参数文档。大模型在接收任务时（如“查询 order:1001 的状态”）无需手动探查即可根据前缀特征自动选用 `order-cache`；
> 2. **异常自愈引导**：当大模型传入了未知的连接别名时，服务不会直接崩溃抛错，而是返回标准化的错误信封并列出所有可用别名清单，驱动大模型自我纠错并重试；
> 3. **安全注意**：即使启动时指定了 `--allow-write`，在配置文件中被标记为 `readonly: true` 的连接（如上述 `order-cache`）仍将受到物理写保护，绝对拒绝任何数据变更！

---

## 🔒 深度安全防御体系

```
                       ┌──────────────────────────────────────┐
                       │   大模型发起 redis_execute_command   │
                       └──────────────────┬───────────────────┘
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
                            • INFO 命令智能分节结构化
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
| **`confirmation_required`**<br>`status: confirmation_required` | 调用 `DEL` 或 `UNLINK` 命令时未显式传入 `confirm=True`。 | 属于正常安全二次确认拦截。大模型/调用方需在核对 `keys` 列表后，再次调用 `redis_execute_command(..., confirm=True)`。 |
| **`DestructiveCommandError`**<br>`物理切断破坏性高危指令...` | 尝试执行破坏性删库或阻塞指令（`FLUSHALL`、`FLUSHDB`、`KEYS *`、`SHUTDOWN`、`CONFIG` 等）。 | 底层永久物理拦截，无法通过任何参数绕过。请改用键前缀安全扫描 `redis_scan_keys` 或单键操作。 |
| **`CrossSlotError`**<br>`Redis Cluster 跨槽执行拦截...` | 在分片集群中执行跨越不同哈希槽的多键命令（如 `MGET {user1}:a {user2}:b`）。 | 遵循语义化引导，将多键指令拆分为针对单一键或相同哈希标签（`{hash_tag}`）的多次独立单键命令。 |
| **`BigKeyReadBlockedError`**<br>`安全拦截：目标 ... 超过了单次全量读取安全防爆阈值...` | 发起无界全量读取指令（`HGETALL`、全量 `SMEMBERS`、`LRANGE 0 -1`、`ZRANGE 0 -1` 等），目标集合元素数量超出防爆上限（默认 2000 项）。 | 改用渐进式分页切片指令，如 `HSCAN <key> 0 COUNT 100`、`SSCAN`、`ZSCAN` 或有界切片 `LRANGE <key> 0 99`；亦可通过环境变量 `MCP_REDIS_MAX_UNBOUNDED_READ_ITEMS` 调高安全防爆阈值。 |
| **`ConnectionNotFoundError`**<br>`指定的连接别名 '...' 不存在...` | 工具调用时传入了未在配置文件或命令行中声明的目标连接别名（`connection` 参数）。 | 服务端自动返回包含全部可用连接清单与业务描述的自愈引导信封，请根据信封提示选用正确的连接别名重新调用，或缺省使用默认连接。 |
| **`ConnectionError`**<br>`Error connecting to host...` | Redis 端口未开放、网络不可达、防火墙拦截或连接超时。 | 使用 `Test-NetConnection` 或 `nc -zv` 验证网络链路，检查密码是否包含特殊字符（推荐使用离散环境变量配置）。 |

---

## ⚠️ 边界约束与不支持操作 (Limitations & Out-of-Scope)

作为专为大语言模型打造的单次请求/响应 MCP 协议网关，以下 Redis 场景超出了本工具的设计范畴：

1. **阻塞式长订阅（Pub/Sub Streaming）**：
   - 不支持 `SUBSCRIBE` / `PSUBSCRIBE`。MCP 工具基于非流式单次同步响应范式，长连接事件推送应由专用的 MQ 消费者或微服务长连接处理。
2. **跨请求有状态事务（Multi-Request Transactions）**：
   - 不支持跨请求的 `MULTI` / `EXEC` / `WATCH` 会话。每次 `redis_execute_command` 均为独立的无状态操作，底层连接池在并发复用时不保持会话级事务状态。
3. **永久挂起阻塞式命令（Zero-Timeout Blocking Commands）**：
   - 执行 `BLPOP`、`BRPOP`、`BZPOPMIN` 等阻塞式读取时，**严禁将超时参数设为 `0`**（无限阻塞等待），否则会导致服务工作进程被永久挂起。建议传入短超时参数（如 `BLPOP mylist 1`）。
4. **服务运行态配置动态篡改**：
   - `CONFIG SET`、`CONFIG REWRITE` 属于底层永久硬阻断范畴，严禁在大模型会话中篡改 Redis 服务运行配置。

---

## 🤝 参与贡献

我们欢迎社区贡献！如果您发现了缺陷或有功能建议：

1. 提交 [GitHub Issues](https://github.com/atengk/mcp-server-redis/issues) 与查阅 [行为准则](./CODE_OF_CONDUCT.md)；
2. 查阅 [贡献指南](./CONTRIBUTING.md)、[安全政策](./SECURITY.md) 与 [智能体工程规范](./AGENTS.md)；
3. 克隆代码后在本地终端执行 `git config core.hooksPath .githooks` 激活提交守护；
4. 发起 Pull Request。

---

## 📄 开源许可证

本项目基于 [Apache License 2.0](./LICENSE) 协议开源。
