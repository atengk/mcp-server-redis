# ADR-0005: PyPI 分发包命名、双 CLI 别名与自动化发布流水线

- **状态**: 已采纳 (Accepted)
- **决策日期**: 2026-10-04

---

## 背景与问题陈述

随着项目完成全套 18 个生产级 MCP 工具与端到端测试，准备向开源社区与 PyPI 分发发布首发正式版 `v1.0.0`。在发布准备阶段面临以下设计决策：
1. **PyPI 仓库命名冲突**：官方 PyPI 仓库中 `mcp-server-redis` 包名已被他人占位注册，直接发布会导致命名冲突失败；
2. **`uvx` 与 CLI 运行体验**：现代 MCP 客户端（如 Claude Desktop、Cursor、Cline）普遍推荐使用 `uvx <package-name>` 免安装直接运行。若 `package-name` 与 CLI 命令不一致，用户需显式指定 `--from` 参数，增加配置复杂度；
3. **内部代码重构成本**：若将内部所有包路径与导入机械式重命名为 `atengk_mcp_server_redis`，会导致内部导入冗长繁琐并产生大范围破坏性重构；
4. **发布自动化与凭据安全**：需基于安全隔离的 GitHub Actions 完成 PyPI 自动发布，杜绝手动本地打包上传带来的凭据泄漏风险。

---

## 决策内容

经过设计推演，确立以下架构决议：

1. **PyPI 官方分发包名确立为 `atengk-mcp-server-redis`**：
   - 采用带有作者组织前缀的独立命名空间 `atengk-mcp-server-redis`，彻底解决 PyPI 根包名冲突。

2. **双 CLI 脚本别名注册 (Dual CLI Aliases)**：
   - 在 `pyproject.toml` 的 `[project.scripts]` 中同时挂载两个入口命令：
     - `atengk-mcp-server-redis = "mcp_server_redis:main"`：使 `uvx atengk-mcp-server-redis` 默认命令无需额外参数即可开箱即用；
     - `mcp-server-redis = "mcp_server_redis:main"`：保持本地简短输入命令与向下兼容。

3. **内部源码命名空间维持 `src/mcp_server_redis`**：
   - 内部代码模块目录维持 `src/mcp_server_redis`（导入语句保持清晰优雅的 `import mcp_server_redis`）；
   - 在 `pyproject.toml` 中通过 `tool.hatch.build.targets.wheel.packages = ["src/mcp_server_redis"]` 指明打包映射；
   - FastMCP 协议握手内的服务名维持 `mcp-server-redis`。

4. **基于 GitHub Actions Release 事件驱动自动构建发布**：
   - 配置流水线 `.github/workflows/publish.yml`，由 GitHub Release 发布事件（`on: release: types: [published]`）触发；
   - 基于 `uv build` 打包构建标准 sdist 与 wheel，通过 `pypa/gh-action-pypi-publish` 使用 `PYPI_API_TOKEN` 安全发布至 PyPI。

---

## 影响与权衡

- **积极收益**：
  - 彻底规避 PyPI 命名冲突，首发版本以正式版 `v1.0.0` 顺畅出海；
  - 内部代码免受大范围重构扰动，保持极简清晰的架构与单测；
  - `uvx` 用户获得最自然的调用体验：`uvx atengk-mcp-server-redis --url "..."`；
  - 自动化流水线杜绝人工发版失误，形成不可篡改的 Release 版本闭环。
- **潜在代价与权衡**：
  - 分发包名（`atengk-mcp-server-redis`）与内部顶级 Python 模块名（`mcp_server_redis`）略有差异，遵循如 `beautifulsoup4 -> bs4`、`Pillow -> PIL` 的成熟 Python 生态惯例。
