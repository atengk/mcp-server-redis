# ADR-0009: 开源工程化模版集成与现代自动化流水线架构

- **状态**: 已采纳 (Accepted)
- **决策日期**: 2026-10-04

---

## 背景与问题陈述

随着 `atengk-mcp-server-redis` 达到 v1.0.0 生产级成熟度，项目由早期单体开发逐步转入开放、协作与多通道分发阶段。为了实现长效敏捷迭代与高标准的工程质量管控，面临以下挑战：
1. **持续集成 (CI) 门禁缺失**：此前缺乏自动化的 PR 规范与代码质检机制，依赖本地手动执行检查，存在人为遗漏风险；
2. **多版本生态兼容缺乏防御**：项目声明支持 Python 3.10、3.11 与 3.12，但在持续演进中缺乏自动化跨版本矩阵验证；
3. **发版流程割裂**：此前依赖独立的 `publish.yml`，且发布日志需要手动维护，未能实现打 Tag 自动生成日志、挂载资产、PyPI 分发与容器镜像构建的一体化；
4. **协作规范与工程配置离散**：缺少标准化的 Issue/PR 模板、统一编辑器格式规范（EditorConfig）与严格的跨平台换行符归一化（Git Attributes）。

为此，我们引入并深度集成了通用开源模版 `atengk/oss-template` 的优秀工程实践。

---

## 决策内容

经过两轮设计树前沿评测与权衡，确立以下全套开源工程化架构方案：

1. **基于 `uv` 的现代化 CI 流水线 (`.github/workflows/ci.yml`)**：
   - **PR 标题语义门禁**：采用 `amannn/action-semantic-pull-request@v5` 严格拦截不符合 Conventional Commits 规范的 PR；
   - **静态质检基线**：在 Python 3.11 环境下执行 `uv run ruff check .`、`uv run ruff format --check .` 与 `uv run mypy .`；
   - **跨版本矩阵测试**：配置 `matrix: { python-version: ["3.10", "3.11", "3.12"] }`，依托 `astral-sh/setup-uv@v5` 缓存并发运行 `uv run pytest`，20 秒内完成全量回归。

2. **Tag 驱动的 All-in-One 自动化发版流水线 (`.github/workflows/release.yml`)**：
   - **统一入口**：推送 `v*` Tag 或手动调度作为唯一定义发版触发点；
   - **提交提取与自动化日志**：引入 `git-cliff-action@v4` 解析 `.cliff.toml`，自动提取自上一版本以来的提交记录并按类型分类，生成结构化 Release 变更说明；
   - **资产打包与挂载**：`uv build` 产出 Wheel 与源码包，由 `softprops/action-gh-release@v2` 自动创建 Release 并上传产物；
   - **自动化 PyPI 发布**：复用既有的 `secrets.PYPI_API_TOKEN`，在 Release 成功后无缝将制品推送到官方 PyPI，安全清理并下线冗余的独立 `publish.yml`；
   - **多架构 GHCR 镜像分发**：登录 GitHub Container Registry，使用 QEMU 与 Docker Buildx 自动构建 `linux/amd64` 与 `linux/arm64` 生产镜像，并推送至 `ghcr.io/atengk/mcp-server-redis`，打标为版本号与 `latest`。

3. **工程协作与跨平台环境规范**：
   - **`.editorconfig`**：统一 IDE/编辑器缩进策略（Python 4 空格，YAML/JSON/Markdown 2 空格）与 UTF-8 编码；
   - **强化版 `.gitattributes`**：全量推行文本文件跨平台 `eol=lf` 归一化，彻底杜绝 Windows CRLF 导致 Linux 脚本崩溃；
   - **社区模版套件**：引入针对 Redis MCP 服务端深度定制的 `bug_report.md`、`feature_request.md` 与带有安全自检清单的 `PULL_REQUEST_TEMPLATE.md`；
   - **融合版贡献指南 (`CONTRIBUTING.md`)**：融合 Conventional Commits 对照表与 GitHub Flow，并固化 Redis 只读/跨槽/二次确认核心安全红线。

4. **开源契约不变量**：
   - **许可证隔离**：严格保持本项目原有的 **MIT License**，绝不被模版默认的 Apache 2.0 冲刷。

---

## 影响与权衡

- **积极收益**：
  - **交付效率与一致性飞跃**：发版流程从手动 5 步收敛为单一 `git push origin vX.Y.Z`，全自动化完成 Release、PyPI、GHCR 镜像三大渠道分发；
  - **社区协作与代码健康度保障**：规范化 PR 标题与自动化矩阵质检将缺陷拦截于代码合入之前；
  - **免维护变更日志**：`git-cliff` 规范提取消除了手动书写版本变更的遗漏与负担。
- **潜在代价与权衡**：
  - 发版流水线引入了多架构 Docker 镜像构建，耗时约 2~3 分钟，但通过 `gha` 缓存与 QEMU 模拟保证了跨平台广泛兼容性。
