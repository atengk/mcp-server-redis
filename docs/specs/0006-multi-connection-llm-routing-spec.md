# 需求规格说明书 (Spec): 多数据库场景下的大模型感知路由与跨服务身份标识体系

- **状态**: 就绪可执行 (`ready-for-agent`)
- **创建日期**: 2026-10-14
- **遵循决策**: [ADR-0015 (多数据库场景下的大模型感知路由与跨服务身份标识体系)](../adr/0015-multi-connection-llm-routing-and-server-identification.md)

---

## Problem Statement

当大模型面对多数据库场景时，存在两类典型路由与协同瓶颈：
1. **多 MCP 服务挂载时身份同质化**：
   在客户端中同时配置多个 Redis MCP 实例时，若服务名称与说明相同，大模型无法得知各自归属的业务域（如会话缓存 vs 订单缓存），且可能发生工具命名冲突；
2. **单 MCP 服务内多连接缺乏先验拓扑感知**：
   在基于 `connections.yaml` 配置了多个连接别名时，工具 Schema 未在参数中显式揭示可用别名列表、默认库、只读状态与键特征（`key_patterns`），大模型未主动探查前无法精准路由，常因盲猜别名导致操作失败。

---

## Solution

在坚持**零破坏性变更**与**统一环境变量规范 (`MCP_REDIS_`)** 的前提下，实施以下深度落地：

1. **跨服务身份标识与业务指令体系**：
   - CLI 新增 `--server-name`（默认读取 `MCP_REDIS_SERVER_NAME`，保底 `"mcp-server-redis"`），纯净传给 FastMCP 实例，不篡改工具名；
   - CLI 新增 `--server-instructions`（默认读取 `MCP_REDIS_SERVER_INSTRUCTIONS`），传递给 FastMCP 实例的 `instructions` 参数，赋能大模型全局业务边界理解。
2. **连接档案领域模型扩展**：
   - `ConnectionProfile` 新增 `key_patterns: list[str] = Field(default_factory=list)`；
   - 支持在 YAML 配置中声明每个实例的主键通配规则（如 `["token:*", "session:*"]`）。
3. **Tool Schema 动态连接提示注入 (Dynamic Connection Hints)**：
   - `ConnectionRegistry` 新增 `format_connection_hint_for_llm()`；
   - 在 `register_command_tools` 与 `register_key_tools` 中，将渲染出的 Markdown 清单无缝拼入各工具的 `connection` 参数说明；
   - 具备优雅缺省能力：单连接或未设置键模式时自适应精简提示。
4. **异常自愈闭环信封 (Self-Healing Error Envelope)**：
   - `ConnectionRegistry` 新增 `format_not_found_message(alias: str)`；
   - 工具层统一拦截 `ConnectionNotFoundError`，返回标准化的 `status: "error"` 信封与全量可用连接指引，引导大模型自动重试纠错。

---

## User Stories

1. 作为一个架构师，我在客户端同时接入了 `order-redis` 和 `user-redis` 两个 MCP 进程，我希望能通过 `--server-name` 和 `--server-instructions` 清晰标识每个服务，让大模型准确识别当前会话该与哪个服务通信。
2. 作为一个使用多实例 `connections.yaml` 的开发者，我希望在让大模型查询 `order:1001` 时，大模型直接在工具 Schema 中看到 `order-cache` 匹配 `order:*`，自动传入 `connection="order-cache"` 而无需我反复提醒。
3. 作为一个大模型开发者，如果不小心传错了一个不存在的连接别名，我希望收到的不是崩溃异常，而是包含所有可用别名的友好提示，以便我立即自我修正。
