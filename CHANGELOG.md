# 更新日志 (Changelog)

本项目遵循 [Semantic Versioning (语义化版本 2.0.0)](https://semver.org/lang/zh-CN/) 规范。

---

## [1.0.1] - 2026-10-04

### 🚀 现代化开源工程套件与 CI/CD 流水线 (Engineering Integration)

- **持续集成 (CI)**：
  - 引入 `.github/workflows/ci.yml`，集成 Conventional Commits PR 标题语义化校验门禁；
  - 接入基于 `uv` 的极速代码质检（Ruff 规范检查、Ruff 格式化自检与 Mypy 静态类型推断）；
  - 配置 Python `["3.10", "3.11", "3.12"]` 跨版本矩阵并行测试，保障多版本生态绝对健壮性。
- **自动化发版流水线 (Release)**：
  - 引入 All-in-One 自动化流水线 `.github/workflows/release.yml`，推送 `v*` Tag 自动触发；
  - 引入 `git-cliff` 自动根据提交历史提取结构化变更日志（`.cliff.toml`）；
  - 自动化构建并挂载 Python Wheel 与 Tarball 发行物至 GitHub Release；
  - 自动化发布包至 PyPI 官方中心仓库并下线旧版独立 `publish.yml`；
  - 自动化构建 `linux/amd64` 与 `linux/arm64` 双架构生产镜像并推送到 GitHub Container Registry (`ghcr.io/atengk/mcp-server-redis`)。
- **协作规范与工程基线**：
  - 引入 `.editorconfig` 统一跨 IDE 编码与排版规范；
  - 强化 `.gitattributes` 全局推行跨平台文本 `eol=lf` 归一化；
  - 引入结构化社区模版：`bug_report.md`、`feature_request.md` 与包含安全红线检查的 `PULL_REQUEST_TEMPLATE.md`；
  - 融合版 `CONTRIBUTING.md` 贡献指南与 README 开源徽章组；
  - 沉淀架构决策记录 `ADR-0009: 开源工程化模版集成与现代自动化流水线架构`。

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

#### 5. Redis Cluster 分片集群支持与跨槽安全防御
- **协议自适应识别与连接串净化**：原生识别 `redis-cluster://` 与 `rediss-cluster://` 协议头，物理剥除 URL 尾部路径，支持 `MCP_REDIS_CLUSTER=true` 与多实例 `cluster: true` 双模激活；
- **单一逻辑库 (DB 0) 强制防御契约**：严格遵循集群单库约束，检测到非 0 库请求自动告警并重置绑定至 `db=0`，绝不因切库异常抛出 `ResponseError` 导致会话崩溃；
- **跨槽 (Cross-Slot) 安全防御与并发提速**：`redis_delete_keys` 在集群模式与 `CROSSSLOT` 异常时自动采用 `asyncio.gather` 并发单键独立删除，彻底阻断跨槽崩溃并杜绝串行网络 N+1 延迟；探活异常自动降级为并发逐键安全探测；
- **集群全节点聚合遍历扫描**：`redis_scan_keys` 自适应调用 `client.scan_iter` 遍历全部分片 Master 节点并聚合键列表，支持安全截断。

#### 6. Stdio 与 SSE 双模传输网关
- **双协议传输抽象**：默认保持纯粹原生 Stdio 管道交互，100% 严格向后兼容所有已有 AI 客户端；
- **HTTP Server-Sent Events (SSE) 服务端**：新增 `--transport [stdio|sse]`、`--host`（默认 `0.0.0.0`）与 `--port`（默认 `8000`），支持以微服务常驻网络形态对外暴露端点 `/sse`。

#### 7. 生产级容器化套件与常驻编排
- **多阶段极速构建 (`Dockerfile`)**：基于 `python:3.11-slim` 与 `ghcr.io/astral-sh/uv:latest` 分层缓存构建，产出镜像严格小于 150MB；
- **非 Root 生产安全基线**：专有系统账号 `appuser` (UID/GID: `10001`) 运行，锁定登录 Shell（`/usr/sbin/nologin`），满足企业合规审计；
- **单服务常驻编排 (`docker-compose.yml`)**：默认以 SSE 模式常驻运行并映射 `8000:8000` 端口，预置 `host.docker.internal:host-gateway` 跨平台直连宿主机外部 Redis。

#### 8. 网络超时防御与运行时日志调控
- **生产级超时兜底**：注入默认 `socket_connect_timeout=3.0s` 与 `socket_timeout=5.0s`，支持环境变量自定义调控；集群驱动开启 3 次故障重试；
- **动态日志分级**：支持 `--log-level` 与 `MCP_REDIS_LOG_LEVEL` 动态调节日志级别（DEBUG/INFO/WARNING/ERROR），输出流严格绑定至 `sys.stderr`，杜绝污染 stdout 协议流。

#### 9. CLI 与分发
- PyPI 官方包名：`atengk-mcp-server-redis`；
- 双 CLI 命令别名：`atengk-mcp-server-redis` 与 `mcp-server-redis`，支持 `uvx atengk-mcp-server-redis` 免安装直接运行。
