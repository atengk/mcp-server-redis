# 贡献指南 (Contributing Guide)

感谢你关注并愿意为 `mcp-server-redis` 项目贡献力量！为了保持高效协作与高质量的代码维护，请在提交代码前阅读以下规范。

---

## 1. 协作与分支模型

本项目遵循标准的 **GitHub Flow** 工作流：

1. **Fork 本仓库** 到你个人的 GitHub 账号；
2. **基于 `main` 分支拉取新的特性分支**：
   ```bash
   git checkout -b feat/your-feature-name
   # 或者缺陷修复分支
   git checkout -b fix/issue-description
   ```
3. 在本地完成修改，确保通过代码质检与测试用例；
4. 提交更改并推送到你的远程分支：
   ```bash
   git push origin feat/your-feature-name
   ```
5. 在 GitHub 上向本仓库的 `main` 分支发起 **Pull Request**。

---

## 2. 本地开发环境准备

本项目采用现代 Python 工具链 `uv` 进行依赖管理、代码格式化与虚拟环境维护：

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

3. **本地静态检查与测试套件**：
   ```bash
   uv run ruff check .          # 静态代码分析
   uv run ruff format --check .  # 代码排版检查
   uv run mypy .                 # 类型系统推断
   uv run pytest                 # 单元与集成测试套件
   ```

---

## 3. Commit 提交信息规范

本项目严格遵循 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/) 规范，统一采用以下格式：

```text
<type>(<scope>): <subject>
```

### 常用类型说明

| 类型 | 说明 | 示例 |
| :--- | :--- | :--- |
| `feat` | 新增功能或 MCP 工具 | `feat(cluster): 交付分片集群跨槽安全防御` |
| `fix` | 缺陷与 Bug 修复 | `fix(strings): 修复超长文本截断字节计算偏差` |
| `docs` | 仅文档更新或修改 | `docs: 完善快速开始与 Docker 接入指南` |
| `style` | 代码格式调整（空格、排版等，不影响逻辑） | `style: 格式化连接注册中心代码` |
| `refactor` | 代码重构（既非新增特性也非修复缺陷） | `refactor(core): 抽取公共连接池驱动管理` |
| `perf` | 性能优化与慢查询加速 | `perf(keys): 引入 asyncio 并发加速跨槽删除` |
| `test` | 增加或重构单元测试与集成测试 | `test: 补充集群模式 db=0 边界防御用例` |
| `build` | 构建系统、外部依赖或打包配置变动 | `build: 升级 redis 驱动依赖版本` |
| `ci` | CI/CD 流水线与 GitHub Actions 脚本修改 | `ci: 引入 Python 跨版本矩阵测试` |
| `chore` | 其他琐碎维护杂项（不改动源码与测试） | `chore: 更新 .editorconfig 规则` |
| `revert` | 恢复或回滚此前的某次历史提交 | `revert: feat(cluster): 回退非必要重试` |

---

## 4. Pull Request 流程与门禁

- **PR 标题校验**：CI 流水线包含语义化标题门禁，PR 标题必须符合 Conventional Commits 格式（如 `feat(transport): 引入 SSE 协议网关`）；
- **自检清单**：请按模版完整填写变更背景、解决的问题、关联 Issue（如 `close #12`）并勾选自检复选框；
- **绿灯保证**：必须保证 GitHub Actions CI 全部步骤（Ruff 质检、Mypy 检查、多版本 Pytest 矩阵）均为绿灯状态。

---

## 5. 架构不变量与安全红线

参与开发必须严格遵循以下生产安全底线：

1. **工业级只读防护与双重写门禁**：写操作必须显式受 `--allow-write` 与连接配置 `readonly=false` 双重管控；底层硬编码物理切断破坏性指令（`FLUSHALL`、`FLUSHDB`、`SHUTDOWN`、`CONFIG`、`DEBUG` 与阻塞式 `KEYS *`）；
2. **非阻塞安全扫描**：键扫描由内部聚合迭代底层 `SCAN` 游标，对外提供单次有限返回（默认最多 50 条，硬上限 200 条）；
3. **防 OOM 集合切片**：所有集合结构（Hash/List/Set/ZSet/Stream）读取强制要求分页与数量截断；
4. **高危删除二次确认**：删除操作（`redis_delete_keys`）强制携带 `confirm: bool = False`，未确认时仅返回受影响预估；
5. **协议管道纯净性**：所有日志流向 `sys.stderr`，严禁在控制台通过裸 `print` 向 `sys.stdout` 输出任何非 JSON-RPC 字符；
6. **代码注释三要素**：新建源码文件必须包含文件/类级标准注释，涵盖职责说明、`@author Ateng` 与当天真实系统日期 `@since YYYY-MM-DD`。

---

## 6. 许可证

参与贡献即代表你同意你的代码以 [MIT License](./LICENSE) 协议发布与授权。
