# 需求规格说明书 (Spec): 升级 Apache-2.0 开源协议与集成 oss-template 现代化工程套件

- **状态**: 就绪可执行 (`ready-for-agent`)
- **创建日期**: 2026-10-14
- **遵循决策**: [ADR-0016 (升级 Apache-2.0 开源协议与集成 oss-template 现代化工程套件)](../adr/0016-apache-license-and-oss-template-integration.md)

---

## Problem Statement

随着项目在云原生微服务与生产级大模型生态中的广泛应用，原有的开源工程底座面临以下治理与交付挑战：
1. **法务与专利防御薄弱**：原有 MIT 协议缺乏显式的专利授权与防专利反诉条款，难以满足企业级生产合规标准；
2. **CI 算力浪费与反馈缓慢**：缺少动态并发控制与路径变更过滤，微小的 Markdown 文档调整依然需要排队执行耗时的 Python 多版本全量测试；
3. **发版安全缺乏前置强校验**：发版缺少质量熔断门禁与不可变 SHA-256 校验和清单，存在坏包外溢风险；
4. **本地规范与社区治理资产缺位**：缺少本地 Git 提交守门钩子、行为准则、安全披露政策及依赖自动化审计。

---

## Solution

深度集成通用开源模板 `atengk/oss-template` 的标准化工程套件：

1. **开源协议合规升级**：
   - 全面迁移至 **Apache License 2.0**，完善专利授权保护；
   - 同步更新 `LICENSE`、`pyproject.toml`、`README.md` 与 `CONTRIBUTING.md`。
2. **CI/CD 现代化流水线重构**：
   - 引入动态并发控制（`concurrency: cancel-in-progress`），PR 重复提交秒级取消陈旧构建；
   - 引入内部短路直通网关（`dorny/paths-filter@v3`），纯文档修改秒级放行并直出 Step Summary；
   - 增加发版前置全量质量门禁（`gate-test`）与产物 SHA-256 校验清单（`checksums.txt`）；
   - 保留 `astral-sh/setup-uv@v5` 极速依赖同步与 Python 跨版本兼容性矩阵。
3. **本地提交守护与工程辅助脚本**：
   - 引入原生 `.githooks/commit-msg` 钩子，本地守门 Conventional Commits；
   - 引入交互式提交助手 `scripts/commit.sh` 与发版防呆脚本 `scripts/release.sh`（自动自增 `pyproject.toml` 与 `server.py` 版本号）。
4. **社区治理资产矩阵完备**：
   - 引入 `CODE_OF_CONDUCT.md`（行为准则）、`SECURITY.md`（安全政策与 GitHub Advisories 报告通道）；
   - 配置 `.github/CODEOWNERS`、`.github/dependabot.yml` 与 `.github/ISSUE_TEMPLATE/config.yml`。

---

## User Stories

1. 作为一个开源项目维护者，我希望每次发布新版本时都能自动经过发版前置门禁测试并生成不可变产物哈希清单，以便于保障下游用户获取的包安全无篡改。
2. 作为一个代码贡献者，我希望修改文档时 CI 流水线能秒级短路直通，避免漫长的单测等待，从而加速 PR 合流。
3. 作为一个企业级架构师，我希望使用的 MCP 服务拥有明确的 Apache-2.0 专利授权保障，以便于安心引入企业生产基础设施。
4. 作为一个日常开发者，我希望在本地执行 `git commit` 时有原生脚本自动拦截非规范的提交信息，以便于团队保持干净整洁的 Git 提交历史。
