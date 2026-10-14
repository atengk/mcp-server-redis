# 需求规格说明书 (Spec): CLI 运维增强套件（--help 分组、--version 环境指纹与 --doctor 全景自检）

- **关联工单**: [#22](https://github.com/atengk/mcp-server-redis/issues/22)
- **状态**: 就绪可执行 (`ready-for-agent`)
- **创建日期**: 2026-10-14
- **遵循决策**: [ADR-0014 (CLI 运维增强套件)](../adr/0014-cli-diagnostics-doctor-and-version.md)

---

## Problem Statement

在将 `mcp-server-redis` 配置至 Claude Desktop、Cursor 等客户端或 Docker/Kubernetes 编排时，存在以下可维护性与交互痛点：
1. **排障反馈链路过长**：当连接串格式错误、内网防火墙不可达、认证密码错误或从库只读时，宿主大模型往往只能得到宽泛的超时或异常，无法快速探知真实原因；
2. **缺乏环境指纹上下文**：提交 Issue 或跨环境部署时无法一键获取版本号与底层运行时依赖（Python、mcp、redis-py 等）状态；
3. **命令行帮助信息杂乱**：所有 CLI 参数平铺排列，缺乏分组引导与典型场景示例。

---

## Solution

在坚持**零新增第三方外部依赖**与**100% 向后兼容**的前提下，实施以下深度建设：
1. **CLI 参数逻辑分组与场景示例**：
   - 优化 `build_argument_parser`，将参数归为连接配置、安全权限、服务传输、运维诊断四大组；
   - 在 CLI epilog 中提供典型实战启动与排障示例；
2. **`--version` / `-v` 增强型环境指纹**：
   - 打印格式包含版本号、Python 解释器版本、操作系统平台与关键依赖（`mcp`、`redis`、`pydantic`、`yaml`）的版本号；
3. **独立自检核心模块 (`src/mcp_server_redis/core/doctor.py`)**：
   - 实现 `DoctorRunner` 与 `DoctorReport`；
   - **四维诊断探针**：
     - 环境与依赖：Python >= 3.10 及核心依赖包版本探查；
     - 配置与凭据：`.env` 加载状态、环境变量有效性、`--config` 配置文件语法；
     - 网络与连通性：并发探测所有连接实例，执行 `PING` 测算 RTT 耗时，抓取 `INFO server` 确认版本与架构；
     - 读写门禁与隔离写探针：确认只读或写权限；若为写模式使用 `__mcp_doctor_probe_{uuid4}__`（5 秒 TTL）写入比对并立即删除，确保绝对零残留；
4. **终端双模呈现与 POSIX 退出码**：
   - 默认输出直观 Unicode 终端诊断卡片；
   - 传入 `--json` 时导出纯净结构化 JSON，便于 CI/CD 自动化流水线集成；
   - 全部通过退出码为 0，任一关键项失败退出码为 1。

---

## User Stories

1. 作为一个初次使用该 MCP 的开发者，我希望能直接执行 `atengk-mcp-server-redis --doctor`，以快速验证本地配置与远端 Redis 的连通性，而无需先在客户端配置调试。
2. 作为一个开源用户，当遇到 Bug 时，我希望能通过 `atengk-mcp-server-redis --version` 一键提取包含 Python、操作系统与驱动版本的环境指纹贴入 Issue。
3. 作为一个 DevOps 工程师，我希望在 CI/CD 中通过 `atengk-mcp-server-redis --doctor --json` 检查各 Redis 实例是否在线，并在异常时捕获非零退出码阻断流水线。

---

## Implementation Decisions

### 1. `src/mcp_server_redis/core/doctor.py`
- 定义 `DoctorCheckItem` (name, status: "ok"|"warn"|"fail", message, details)
- 定义 `DoctorReport` (items, overall_status: "healthy"|"degraded"|"unhealthy", duration_ms)
- `DoctorRunner.run(...) -> DoctorReport`:
  - 检查 Python 与依赖；
  - 检查配置与环境变量；
  - 检查连接与 PING 延迟；
  - 检查读写门禁与写探针；
- `format_terminal_report(report: DoctorReport) -> str`
- `format_json_report(report: DoctorReport) -> str`

### 2. `src/mcp_server_redis/server.py`
- `build_argument_parser` 中增加 `--version` / `-v` (`action="version"` 输出增强指纹)
- 增加 `--doctor` (flag) 与 `--json` (flag)
- 使用 `add_argument_group` 分类参数并配置 `epilog`
- 在 `main()` 中前置拦截 `--doctor` 标志，调用 `DoctorRunner` 并按需返回退出码 0 或 1。
