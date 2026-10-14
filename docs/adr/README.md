# 架构决策记录 (Architecture Decision Records)

本文档目录用于记录 `mcp-server-redis` 项目的重要架构决策与技术选型演进。

---

## 命名与组织规范

- 采用四位递增编号与短横线小写命名，例如：`0001-fastmcp-architecture.md`、`0002-read-only-guardrail.md`；
- 每个 ADR 文件推荐包含以下核心章节：
  1. **标题与元数据**：状态（提议 / 已采纳 / 已废止 / 被取代）、决策日期；
  2. **背景与问题陈述**：面临的工程挑战或需求约束；
  3. **决策结果**：选定方案及关键技术细节；
  4. **影响与权衡**：带来的收益、成本与潜在局限。

---

## 决策记录索引

| 编号 | 架构决策主题 | 状态 | 决策日期 |
| :--- | :--- | :--- | :--- |
| [ADR-0001](./0001-core-architecture-and-security-model.md) | 生产级 Redis MCP 服务端核心架构与双重安全门禁模型 | 已采纳 | 2026-10-04 |
| [ADR-0002](./0002-data-slicing-and-stateless-routing.md) | 全数据结构防 OOM 切片保护与无状态多库路由策略 | 已采纳 | 2026-10-04 |
| [ADR-0003](./0003-tool-namespace-confirmation-and-serialization.md) | 工具命名空间收敛、高危删除二次确认门禁与数据自适应序列化 | 已采纳 | 2026-10-04 |
| [ADR-0004](./0004-tool-naming-dual-gate-and-json-parsing.md) | 统一前缀工具命名、双重写门禁鉴权与智能 JSON 探测反序列化 | 已采纳 | 2026-10-04 |
| [ADR-0005](./0005-distribution-package-naming-and-publishing.md) | 制品分发包命名规范、双 CLI 入口映射与 PyPI 发布集成策略 | 已采纳 | 2026-10-04 |
| [ADR-0006](./0006-environment-variable-configuration-hierarchy.md) | 环境变量配置分级决议、离散参数组装与安全加载策略 | 已采纳 | 2026-10-04 |
| [ADR-0007](./0007-redis-cluster-and-cross-slot-architecture.md) | Redis Cluster 分片集群自适应驱动、单一数据库约束与跨槽安全防御 | 已采纳 | 2026-10-04 |
| [ADR-0008](./0008-docker-and-dual-transport-architecture.md) | 生产级容器化构建策略与常驻 SSE 双模传输网关架构 | 已采纳 | 2026-10-04 |
| [ADR-0009](./0009-oss-engineering-template-integration.md) | 开源工程化模版集成与现代自动化流水线架构 | 已采纳 | 2026-10-04 |
| [ADR-0010](./0010-hybrid-command-gateway-architecture.md) | 混合命令网关架构与协议工具精简设计 | 已采纳 | 2026-10-12 |
| [ADR-0011](./0011-canonical-naming-and-full-mcp-protocol.md) | 规范动宾工具契约、无别名纯净暴露与全 MCP 协议矩阵 | 已采纳 | 2026-10-14 |
| [ADR-0012](./0012-resilience-pipeline-and-safe-blocking.md) | 游标续翻分页、阻塞超时收敛、空闲心跳与管道批处理网关 | 已采纳 | 2026-10-14 |
| [ADR-0013](./0013-production-observability-bigkey-defense-and-healthz.md) | 连接池超时基线、结构化审计日志、BigKey 内存防爆与云原生探活 | 已采纳 | 2026-10-14 |
| [ADR-0014](./0014-cli-diagnostics-doctor-and-version.md) | CLI 运维增强套件（--help 逻辑分组、--version 环境指纹与 --doctor 全景自检） | 已采纳 | 2026-10-14 |
| [ADR-0015](./0015-multi-connection-llm-routing-and-server-identification.md) | 多数据库场景下的大模型感知路由与跨服务身份标识体系 | 已采纳 | 2026-10-14 |



