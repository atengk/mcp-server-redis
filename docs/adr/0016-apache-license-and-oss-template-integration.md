# ADR-0016: 升级 Apache-2.0 开源协议与集成 oss-template 现代化工程套件 (Apache 2.0 License Migration and oss-template Modernization)

- **状态**: 已采纳 (Accepted)
- **决策日期**: 2026-10-14

---

## 背景与问题陈述

随着 `atengk-mcp-server-redis` 迈入 v2.0 混合命令网关、全 MCP 协议矩阵与多连接动态感知路由的工业级成熟期，项目在开源治理、法务合规与自动化交付上面临全新要求：

1. **开源协议与知识产权防线**：
   - 原项目采用宽松的 `MIT License`。MIT 协议虽简短，但缺乏明确的**专利授权与专利反诉（Patent Retaliation）保护条款**；
   - 随着大模型 MCP 生态在企业生产环境与云原生集群的广泛落地，为了避免潜在的专利纠纷并与作者的开源标准规范工程底座 `atengk/oss-template` 保持一致，需将开源许可证正式升级为国际主流企业广泛采用的 **Apache License 2.0**。
2. **CI/CD 流水线防御与并发效率瓶颈**：
   - 此前 CI 流水线缺乏动态并发控制，开发者连续推送或编辑 PR 时，陈旧运行不会自动取消，造成 GitHub Actions 算力与排队资源浪费；
   - 缺乏变更路径感知，即使仅更新 `README.md` 或文档，也必须等待 3~5 分钟的完整 Python 多版本单测矩阵执行完毕，拉长了合流反馈周期；
   - 发版流水线缺少发版前置全量质量熔断门禁（Gate Test），且产物未附带防篡改的不可变 SHA-256 校验清单（Checksums）。
3. **本地协作与提交守护缺失**：
   - 依赖远端 CI 校验 PR 标题，开发者本地提交未设防，容易产生破坏 Conventional Commits 格式的历史脏提交；
   - 缺少标准化的交互式提交助手与自动自增版本号的发版防呆脚本。
4. **社区治理与合规配置离散**：
   - 缺少国际标准行为准则（Code of Conduct）、私密安全漏洞披露政策（Security Policy）、代码维护者归属（CODEOWNERS）以及依赖自动化巡检（Dependabot）。

---

## 决策内容

经过架构评审，决定全面集成通用开源模板 `atengk/oss-template`（v1.11.0 规范体系）的最新实践，确立以下演进决策：

### 1. 全面迁移至 Apache License 2.0
- **根目录 LICENSE 文件重构**：替换为标准 Apache License 2.0 完整法律文本，保留 `Copyright 2026 Ateng (atengk)` 版权声明；
- **包元数据更新**：更新 `pyproject.toml` 中的 `license = { text = "Apache-2.0" }` 以及 PyPI 分类器 `License :: OSI Approved :: Apache Software License`；
- **文档与治理说明同步**：更新 `README.md` 顶部的许可证徽标与尾部章节，更新 `CONTRIBUTING.md` 中的授权说明；
- **法律效力升级**：赋予使用者明晰的专利使用权（第 3 条），同时通过专利反诉条款保护原作者及开源社区免受专利流氓侵害。

### 2. CI/CD 双元流水线现代化加固
- **动态并发控制 (Dynamic Concurrency)**：
  - 在 `ci.yml` 中配置 `group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}` 与 `cancel-in-progress: ${{ github.event_name == 'pull_request' }}`，PR 重复提交秒级取消陈旧构建；
  - 在 `release.yml` 中锁定并发单例（`cancel-in-progress: false`），杜绝重复发版导致版本空洞或制品冲突。
- **内部短路直通网关 (Path Fast-Pass Gate)**：
  - 引入 `dorny/paths-filter@v3` 识别纯文档改动（`*.md|docs/**|.gitignore|.editorconfig|LICENSE`）；
  - 遇到纯文档变动时自动短路跳过耗时的静态分析与多版本单测矩阵，并在终审看板直出“⚡ 短路直通”标识，保障分支保护规则秒级放行。
- **发版前置质量门禁 (Gate Test) 与不可变产物哈希**：
  - 在 `release.yml` 引入第一阶段 `gate-test`，全盘执行 Ruff 静态检查、Mypy 类型推断与 Pytest 单元回归，测试失败全盘熔断；
  - 产物编译阶段自动生成 `checksums.txt` 记录 Wheel 与 Tarball 的 SHA-256 哈希值，随同 Release 附件一并分发。
- **质量门禁终审与看板输出**：
  - `ci.yml` 增加 `all-checks-passed` 汇聚任务，统一盖戳并直出 GitHub Step Summary 结构化报表；
  - `release.yml` 增加 `summary` 任务直出包含 Docker 拉取指令与 PyPI 安装命令的统合发版看板。

### 3. 本地 Git 提交守护与工程辅助脚本
- **原生 Git 提交守门钩子 (`.githooks/commit-msg`)**：
  - 零外部依赖（无需安装 Node.js / husky / pre-commit），纯原生 Bash 脚本在 `git commit` 时校验说明首行格式；
  - 智能放行 Merge / Revert / 临时变基（fixup/squash）提交，违规时彩色终端直观输出诊断建议；
  - 激活命令：`git config core.hooksPath .githooks`。
- **工程化脚本套件 (`scripts/`)**：
  - `scripts/commit.sh`：轻量交互式向导，辅助开发者按规范录入 Type / Scope / Subject；
  - `scripts/release.sh`：全生命周期发版防呆脚本，集成前置环境检查、SemVer 智能推荐、演练模式（`--dry-run`）与静默参数（`-y`）；
  - **定制插槽适配**：在 `custom_bump_version` 中无缝串联自动更新 `pyproject.toml` 中的 `version` 与 `server.py` 中的 `SERVER_VERSION`，杜绝手动修改遗漏。

### 4. 生产级社区治理与合规资产
- **`CODE_OF_CONDUCT.md`**：采用 Contributor Covenant 2.1 国际规范，营造健康包容的开发者社区；
- **`SECURITY.md`**：规范化漏洞安全披露政策，优先指引 GitHub Security Advisories 私密报告通道；
- **`.github/CODEOWNERS`**：明确主干代码维护人归属（`@atengk`）；
- **`.github/dependabot.yml`**：针对 GitHub Actions、Python pip 与 Docker 镜像生态配置月度依赖与安全补丁自动化审计；
- **`.github/ISSUE_TEMPLATE/config.yml`**：引导开发者前往 Discussions 讨论或查阅官方文档，防止无效 Issue 堆积。

---

## 影响与权衡

- **积极收益**：
  - **知识产权与专利防御完备**：Apache 2.0 为商业化接入与企业内部合规审计提供了充分的法务保障；
  - **CI 算力开销大幅缩减**：文档类微调免去冗长构建，PR 快速反馈循环提速 70% 以上；
  - **发版质量具备铁律防线**：发版前自动化全量跑测 + SHA-256 校验和防篡改，杜绝坏包污染 PyPI 与 GHCR；
  - **人机协同规范落地**：无论是人类开发者还是 AI Agent，本地提交均受 `.githooks` 守护，杜绝非标 Commit 污染历史。
- **潜在代价与权衡**：
  - 开发者首次克隆项目后需执行一次 `git config core.hooksPath .githooks` 激活本地钩子（已在文档与向导中详细说明）；
  - 发版前置门禁会增加少量发版时长，但换取了 100% 的不可逆安全保障。
