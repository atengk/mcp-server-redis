# 需求规格说明书 (Spec): 生产可观测性、BigKey 防爆预检与云原生探活升级

- **关联工单**: [#21](https://github.com/atengk/mcp-server-redis/issues/21)
- **状态**: 就绪可执行 (`ready-for-agent`)
- **创建日期**: 2026-10-14
- **遵循决策**: [ADR-0013 (连接池超时基线、结构化审计日志、BigKey 内存防爆与云原生探活)](../adr/0013-production-observability-bigkey-defense-and-healthz.md)

---

## Problem Statement

在将 `mcp-server-redis` 部署于生产环境、企业合规审计与云原生（Kubernetes）编排中时，存在以下稳定性与运维痛点：
1. **连接池规格与套接字超时未设防**：单机与分片连接池默认使用无界连接池，且 `socket_timeout` 默认为 None。在网络波动或丢包时，异步连接可能无限期等待挂起，连接数膨胀打爆 Redis `maxclients`；
2. **缺乏结构化审计日志**：大模型执行写命令或排障命令时无法记录结构化审计轨迹（Audit Trail），无法满足企业合规审计要求；且如果在 `stdio` 协议管道模式下输出普通日志到 `stdout`，会直接破坏 MCP JSON-RPC 通信协议帧；
3. **巨型集合全量读取阻塞 Redis 主事件循环**：大模型经常下发 `HGETALL` 或 `SMEMBERS` 读取百万级集合，在到达序列化器切片截断前，已导致 Redis 单线程主循环严重锁死；
4. **缺少云原生健康检查探针**：SSE 传输模式下只有 `/sse` 和 `/messages`，没有返回 200 OK 的轻量 HTTP `/healthz` 路由，导致 K8s 的 Liveness / Readiness 探针无法优雅接入；
5. **DBA 排障缺少连接泄露与 BigKey 场景支撑**：资源缺少客户端连接列表，Prompts 缺少针对 BigKey 渐进式拆解排查的 SOP 引导模板。

---

## Solution

在坚持**零新增第三方外部依赖**的前提下，实施以下深度治理与增强：
1. **连接池与网络超时工业级默认基线**：
   - `ConnectionProfile` 默认：`max_connections=50`、`socket_connect_timeout=5.0`、`socket_timeout=10.0`；
   - 支持环境变量（`MCP_REDIS_MAX_CONNECTIONS`、`MCP_REDIS_SOCKET_TIMEOUT`、`MCP_REDIS_SOCKET_CONNECT_TIMEOUT`）动态覆盖；
2. **可插拔结构化审计跟踪器 (`core/audit.py`)**：
   - 记录每次命令执行的 `timestamp`、`connection`、`db`、`command`、`duration_ms`、`status` 与 `keys`；
   - STDIO 模式绝对物理隔离：若用户配置指定 `stdout`，强制安全重定向至 `sys.stderr` 或文件；
   - 敏感密码自动脱敏掩码（`AUTH ***`），不持久化长业务数据值；
3. **BigKey 无界读取防爆预检网关**：
   - 识别 `HGETALL`、`SMEMBERS`、`LRANGE 0 -1`、`ZRANGE 0 -1`、`ZREVRANGE 0 -1`；
   - 执行前先以 O(1) 指令（`HLEN`、`SCARD`、`LLEN`、`ZCARD`）探测集合大小；
   - 默认安全阈值 2,000 项（支持环境变量 `MCP_REDIS_MAX_UNBOUNDED_READ_ITEMS` 配置）；超限时返回结构化拦截信封，引导改用 `HSCAN`/`SSCAN`；
4. **SSE 云原生 `/healthz` 探活路由与 Dockerfile HEALTHCHECK**：
   - 在 SSE 模式下额外挂载 `/health` 与 `/healthz` 端点，结合底层 Redis `PING` 探活返回 200 或 503；
   - 在 `Dockerfile` 中配置基于 Python 标准库的 `HEALTHCHECK` 指令；
5. **资源与 Prompt 场景扩充**：
   - 新增资源 `redis://{connection}/clients` 与 `redis://clients`，清洗 `CLIENT LIST` 并对 IP 末段掩码（`192.168.1.***`）；
   - 新增 Prompt `redis_troubleshoot_bigkeys`，标准化 BigKey 采样、内存评估与渐进式切片优化 SOP。

---

## User Stories

1. 作为一个系统运维人员，我希望 MCP 服务默认启用合理的连接池上限（50）与套接字超时（10s），以便于在网络丢包或连接激增时不会耗尽 Redis 连接资源。
2. 作为一个安全合规管理员，我希望能够开启结构化审计日志，以便于实时追溯大模型操作 Redis 的每一条命令执行状态、耗时与键名。
3. 作为一个使用 stdio 协议运行的开发者，我希望开启审计日志时绝对不会向 stdout 输出非 JSON-RPC 字符，以便于杜绝 Claude Desktop 或 Cursor 通信崩溃。
4. 作为一个使用大模型的开发者，当模型不小心执行 `HGETALL big_hash`（包含 5 万个字段）时，我希望网关能自动进行 O(1) 预检并拦截，以便于防止 Redis 实例被模型直接打死。
5. 作为一个 DevOps 工程师，我希望在 K8s 中部署时能够通过 `http://<host>:8000/healthz` 进行健康检查，以便于准确感知容器和底层 Redis 的连通状态。
6. 作为一个 DBA，我希望通过 `redis://{connection}/clients` 资源直接检视连接列表，同时内网 IP 被自动掩码，以便于既能排查连接泄露又不暴露内网网络拓扑。
7. 作为一个 DBA，我希望通过 `redis_troubleshoot_bigkeys` Prompt 引导大模型，以便于自动化按标准流程对大 Key 进行采样诊断与切片拆分建议。

---

## Implementation Decisions

### 1. `ConnectionProfile` 超时与连接池参数
在 `src/mcp_server_redis/core/connection.py` 中更新 `ConnectionProfile`：
- `max_connections: int | None = 50`
- `socket_connect_timeout: float | None = 5.0`
- `socket_timeout: float | None = 10.0`
在 `src/mcp_server_redis/core/env.py` 中增加对应环境变量读取：
- `MCP_REDIS_MAX_CONNECTIONS`
- `MCP_REDIS_SOCKET_TIMEOUT`
- `MCP_REDIS_SOCKET_CONNECT_TIMEOUT`

### 2. `core/audit.py` 结构化审计记录器
新建 `src/mcp_server_redis/core/audit.py`：
- `AuditLogger` 类，支持 `log_execution(...)`
- 字段：`timestamp` (ISO8601), `connection`, `db`, `command` (脱敏), `duration_ms`, `status` (`success`/`rejected`/`error`), `keys`
- 在 `stdio` 传输模式下，若输出目标为 `stdout`，强制重定向至 `sys.stderr`

### 3. BigKey 防爆预检器
在 `src/mcp_server_redis/tools/command.py` 中增加 pre-execution 检查：
- 识别 `HGETALL key`, `SMEMBERS key`, `LRANGE key 0 -1`, `ZRANGE key 0 -1`, `ZREVRANGE key 0 -1`
- 对应探测命令：`HLEN`, `SCARD`, `LLEN`, `ZCARD`
- 阈值从环境变量 `MCP_REDIS_MAX_UNBOUNDED_READ_ITEMS`（默认 2000）获取
- 超限时返回错误信封：`{"command": cmd, "status": "error", "error_type": "BigKeyReadBlockedError", "message": ...}`

### 4. SSE `/healthz` 端点
在 `src/mcp_server_redis/server.py` 中：
- 自定义 `sse_app` 包装，挂载 `/health` 与 `/healthz` 端点
- 向默认连接发起 `PING` 探活（1s 超时）
- `Dockerfile` 添加 `HEALTHCHECK`

### 5. Resources 与 Prompts
在 `src/mcp_server_redis/resources.py` 中：
- 注册 `redis://{connection}/clients` 与 `redis://clients`
- 清洗 `CLIENT LIST` 并使用正则对 IP 末段掩码（`\d+\.\d+\.\d+\.\d+` -> `x.x.x.***`）
在 `src/mcp_server_redis/prompts.py` 中：
- 注册 `redis_troubleshoot_bigkeys` Prompt
