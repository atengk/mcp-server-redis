# ADR-0014: CLI 运维增强套件（--help 逻辑分组、--version 环境指纹与 --doctor 全景自检） (CLI Diagnostics Suite: Grouped Help, Environment Fingerprint Version, and Comprehensive Doctor)

- **状态**: 已采纳 (Accepted)
- **决策日期**: 2026-10-14

---

## 背景与问题陈述

在将 `mcp-server-redis` 交付给开发者、DBA 与云原生运维使用时，命令行交互体验存在以下易用性与排障痛点：
1. **缺乏一键开箱自检工具**：当大模型接入失败时，问题可能源自 Python 依赖缺失、YAML 连接配置语法错误、Redis 网络不可达、ACL 用户密码错误或试图向只读从库写入。目前必须启动完整服务并在宿主软件（如 Claude Desktop）报错后从深层日志分析，排障链路极长；
2. **缺乏标准版本与环境指纹展示**：缺少 `--version` / `-v` 参数，开发者在提交 Issue 或进行环境审计时难以快速获取运行架构与依赖库版本上下文；
3. **命令行帮助信息未经归类**：随着连接池、写权限、审计日志、传输网关等多项生产级参数的加入，原生 `--help` 变成单一长列表，缺乏功能分类与典型场景示例，新手上手成本高。

---

## 决策内容

确立以下 CLI 体验与自检套件设计决策：

1. **平铺 Flag 模式与 100% 向后兼容 (Flat Flag Model)**：
   - 绝不引入强制多级子命令（如 `atengk-mcp-server-redis run`），避免破坏既有 `claude_desktop_config.json` 与容器编排配置；
   - 保持平铺参数标志，新增 `--version`/`-v`、`--doctor` 与 `--json`（配合 doctor 结构化导出）。

2. **`--version` 增强版环境指纹 (Environment Fingerprint)**：
   - 打印格式包含版本号、Python 解释器版本、操作系统平台及关键依赖包（`mcp`、`redis`、`pydantic`、`yaml`）的具体版本；
   - 便于在 Issue 模板和运维工单中一键复制精确运行上下文。

3. **`--help` 逻辑分组与典型场景示例 (Grouped Help & Epilog)**：
   - 将参数划分为四大逻辑分组：
     1. `基础连接配置 (Connection Options)`：`--url`, `--config`, `--cluster`；
     2. `安全与权限控制 (Security & Permissions)`：`--allow-write`, `--audit-log`；
     3. `服务与网络传输 (Transport & Server)`：`--transport`, `--host`, `--port`, `--log-level`；
     4. `运维诊断与信息 (Diagnostics & Info)`：`--doctor`, `--json`, `--version`, `--help`；
   - 在底端追加典型使用场景实战示例（默认只读启动、开启写权限、多实例配置加载、健康自检）。

4. **架构解耦与独立诊断模块 (`core/doctor.py`)**：
   - 严格遵循单一职责，新建 `src/mcp_server_redis/core/doctor.py`，封装 `DoctorRunner` 与 `DoctorReport`；
   - `server.py` 仅作为 CLI 参数解析的薄层调度入口，杜绝上帝文件。

5. **`--doctor` 四维深度全景诊断 (Four-Dimensional Diagnostics)**：
   - **维度 1（运行时环境）**：检查 Python 版本（>=3.10）及核心运行时依赖（`mcp`、`redis`、`pydantic`、`yaml`）；
   - **维度 2（配置解析）**：检查 `.env` 文件探测结果、环境变量合法性及多实例配置文件的解析完整度；
   - **维度 3（网络连通与延迟）**：并发巡检所有连接（单连接或配置文件中的全量连接档案），发送 `PING` 并测算精确往返延迟（RTT ms），读取 `INFO server` 提取 Redis 版本号与集群架构；
   - **维度 4（权限防护与写探针）**：确认生效的门禁状态；若开启写操作，采用 `__mcp_doctor_probe_{uuid4}__` 临时 Key 配合 5 秒双保险 TTL 发起安全写入校验并立即物理清理，绝对零脏数据残留。

6. **双模渲染与标准退出码 (Rendering & Exit Codes)**：
   - 终端默认输出美观高可读的富文本卡片；
   - 支持 `--doctor --json` 输出标准 JSON 诊断报告，赋能 CI/CD 流水线与自动化运维脚本；
   - 退出码遵循 POSIX 规范：全部项正常返回 `0`，存在任意不可达或关键校验失败返回 `1`。

---

## 影响与权衡

- **积极收益**：
  - 开发者在配置 MCP 前可直接运行 `atengk-mcp-server-redis --doctor` 提前 1 秒探明配置与网络问题，将排障时间从小时级降低至秒级；
  - 增强型版本指纹极大降低社区技术支持与 Issue 沟通成本；
  - 逻辑分组的 `--help` 显著提高初次使用与参数查阅的直观性。
- **潜在代价与权衡**：
  - 增加了约 300~400 行专职自检代码，但通过模块独立化（`core/doctor.py`）将其与协议运行时物理隔离，零运行时额外性能损耗。
