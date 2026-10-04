## 变更说明
<!-- 请简要说明此 PR 解决的问题、新增的 Redis MCP 能力或重构的模块 -->

## 关联 Issue
- 修复/关联: close #

## 变更类型
<!-- 请在符合项的括号内填入 x，例如 [x] -->
- [ ] `feat`: 新增功能 / 新增 MCP 工具
- [ ] `fix`: 缺陷修复 / 安全阻断拦截
- [ ] `docs`: 文档变动 / ADR 架构决策更新
- [ ] `style`: 代码格式调整（不影响业务逻辑）
- [ ] `refactor`: 代码重构（非新功能、非修复）
- [ ] `perf`: 性能优化 / 慢查询优化
- [ ] `test`: 补全或重构测试用例
- [ ] `ci`: CI/CD 流水线与 GitHub Actions 脚本修改
- [ ] `chore`: 构建配置、依赖或工具链变动

## 自检清单
- [ ] PR 标题与提交信息符合 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/) 规范
- [ ] 本地已通过全部测试及代码检查：`uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy .`、`uv run pytest`
- [ ] 如有新增/修改功能，已补充对应单元测试与集成测试
- [ ] 新建源文件均包含文件级作者与日期注释（`@author Ateng`, `@since YYYY-MM-DD`）
- [ ] 严格遵守安全防御底线：杜绝阻塞式命令（`KEYS *`、`FLUSHALL` 等），集合操作严格分页截断，删除操作强制二次确认
- [ ] 严格遵守协议隔离：标准日志输出至 `sys.stderr`，绝不污染 Stdio JSON-RPC 通信管道
- [ ] 如涉及 API 或配置变更，已同步更新相关文档与统一语言（`README.md` / `CONTEXT.md`）
