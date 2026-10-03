# 贡献指南 (Contributing Guide)

感谢您对 `mcp-server-redis` 项目的关注与支持！我们欢迎并鼓励社区贡献者参与代码完善、文档改进、测试补充及新功能设计。

---

## 🛠️ 开发环境准备

本项目采用现代 Python 包管理工具 `uv` 进行依赖管理与虚拟环境维护：

1. **安装 uv**：
   ```bash
   # Windows (PowerShell)
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

   # macOS / Linux
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **克隆仓库与同步依赖**：
   ```bash
   git clone https://github.com/atengk/mcp-server-redis.git
   cd mcp-server-redis
   uv sync --all-extras
   ```

---

## 🌿 分支与开发工作流

1. **Fork 本仓库** 到您的个人 GitHub 空间；
2. **基于 `main` 分支拉取开发分支**：
   ```bash
   git checkout -b feat/your-feature-name
   # 或
   git checkout -b fix/your-bug-fix
   ```
3. **本地开发与测试**：
   - 编写单元测试与集成测试；
   - 运行静态检查与代码格式化：
     ```bash
     uv run ruff check .
     uv run ruff format .
     uv run mypy .
     ```
4. **提交代码 (Commit)**：
   遵循 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/) 规范：
   - `feat(scope): 描述新特性`
   - `fix(scope): 修复特定问题`
   - `docs(scope): 文档变动`
   - `refactor(scope): 代码重构`
   - `test(scope): 测试用例变更`
5. **发起 Pull Request (PR)**：
   提交 PR 至主仓库的 `main` 分支，清晰说明变更原因、实现细节与自测结果。

---

## 🛡️ 代码与设计原则

- **严格安全防御**：严禁引入全局阻塞命令（如 `KEYS *`、`FLUSHALL`、`FLUSHDB`），一律采用非阻塞式游标迭代（如 `SCAN`）或带有最大返回限制的受控查询；
- **读写权限隔离**：涉及数据修改（如写入、删除、过期时间设置）的工具必须具备独立权限开关或参数确认机制；
- **自解释与文档注释**：新建源码文件需标明作者与日期说明，核心公共函数提供规范的参数与返回值说明；
- **向后兼容**：对外工具契约（Tool Schema）保持稳定与向后兼容，防范破坏客户端已有提示词编排。

---

## 📄 许可证

参与贡献即代表您同意您的代码以 [MIT License](./LICENSE) 协议发布与授权。
