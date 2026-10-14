# ADR-0015: 多数据库场景下的大模型感知路由与跨服务身份标识体系 (LLM Multi-Connection Dynamic Routing and Cross-Server Identification)

- **状态**: 已采纳 (Accepted)
- **决策日期**: 2026-10-14

---

## 背景与问题陈述

当在生产环境中接入 MCP 数据库服务时，大语言模型（LLM）面临两种典型的“多库多实例”识别与路由困境：

1. **跨 MCP 服务场景（客户端挂载多个独立数据库 MCP 进程）**：
   - 开发者可能在客户端配置中同时挂载多个 MCP 实例（如一个用户中心 Redis、一个订单交易 Redis、一个报表数据库）；
   - 若服务名称与系统说明完全同质化且工具命名相同，部分宿主（如 Claude Desktop / Cursor）可能引发工具冲突，且大模型无法从全局提示词中感知各个服务的专属业务边界。
2. **服务内多连接场景（单个 MCP 服务通过 connections.yaml 挂载多个实例）**：
   - 当前服务的 `redis_execute_command`、`redis_scan_keys` 等工具提供了 `connection: str = None` 参数；
   - 但在服务启动时，工具的静态 Schema 无法向大模型揭示“当前系统究竟有哪些连接可用，各自存储了什么业务数据，主键命名特征是什么”；
   - 大模型在未主动调用 `redis_list_connections` 之前处于盲人摸象状态，常常盲目走默认库或瞎猜别名，导致路由失真或调用报错。

---

## 决策内容

确立以下跨服务标识、动态 Schema 提示注入与自愈路由闭环设计：

### 1. 跨服务身份标识与业务指令体系 (`--server-name` & `--server-instructions`)
- **纯净服务名 (`--server-name`)**：
  - 对应环境变量 `MCP_REDIS_SERVER_NAME`，默认值为 `"mcp-server-redis"`；
  - 纯净传递给底层 `FastMCP(name=...)`，供 MCP 客户端做服务分组展示；
  - **设计不变量**：服务名变更**绝不侵入或篡改底层工具名**（始终保持标准的 `redis_execute_command`、`redis_scan_keys` 等），保障 Prompt 稳定性与兼容性。
- **全局系统指令 (`--server-instructions`)**：
  - 对应环境变量 `MCP_REDIS_SERVER_INSTRUCTIONS`，默认提供内置的高性能 Redis 最佳实践指南；
  - 允许开发者通过参数或环境变量显式注入当前服务的业务归属说明（如“本实例用于订单与库存热点缓存中心”），在 MCP 协议握手时直接作为系统 Instructions 赋能大模型。
- **参数决议优先级**：严格遵循 `CLI 显式参数 > MCP_REDIS_* 环境变量 > 本地 .env > 内置保底值`。

### 2. 连接模型扩展：支持键模式特征 (`key_patterns`)
- 在 `ConnectionProfile` 领域模型中新增可选字段：
  ```python
  key_patterns: list[str] = Field(default_factory=list)
  ```
- 允许在 `connections.yaml` 中为每个实例声明常见键前缀通配规则（如 `["token:*", "user:*"]` 或 `["order:*", "stock:*"]`），为大模型建立业务意图与物理实例之间的先验对应关系。

### 3. Tool Schema 动态连接提示注入 (Dynamic Connection Hints)
- 服务端启动装配工具时，根据实际解析的连接注册表（`ConnectionRegistry`），动态格式化 Markdown 列表，并无缝编译拼入各个工具的 `connection` 参数文档：
  - **多连接场景**：输出包含连接别名、`[默认]` 标识、`[只读]` 标识、描述（若有）与键模式（若有）的结构化清单；
  - **单连接优雅缺省**：若仅配置了单连接或未提供描述与模式，自适应精简提示“当前系统仅配置单连接 'default'，无需指定”，避免污染上下文。

### 4. 路由异常与自愈闭环信封 (Self-Healing Envelope)
- 当大模型传入了未知的 `connection` 别名时，底层不直接抛出导致 RPC 崩溃的粗暴异常，而是由命令网关与诊断工具统一捕获 `ConnectionNotFoundError`；
- 返回标准化的 `status: "error"` 信封，并在 `message` 中列出清晰的自愈指引与当前所有可用连接清单，驱动大模型根据自身意图直接自我修正并重新发起正确调用。

---

## 影响与权衡

- **积极收益**：
  - 大模型在首次看到 Tool 定义时即拥有全部数据库拓扑感知，零额外网络往返即可完成精准路由；
  - 结合 `key_patterns`，大模型可根据用户提示词中的 Key 特征（如 `user:1001`）自动选择正确的连接别名；
  - 跨服务参数与环境变量完全遵循项目统一的 `MCP_REDIS_` 前缀规范，与 Docker / K8s 云原生配置生态无缝契合。
- **潜在代价与权衡**：
  - 工具描述长度会有微量增加（每增加一个连接多约 30~50 字符），但在可控的连接数（通常 2~5 个）下对 LLM 上下文窗口的影响微乎其微。
