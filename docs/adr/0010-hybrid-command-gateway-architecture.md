# ADR-0010: 混合命令网关架构与协议工具精简 (Hybrid Command Gateway Architecture)

- **状态**: 已采纳 (Accepted)
- **决策日期**: 2026-10-12

---

## 背景与问题陈述

在 v1.x 版本中，服务采用了面向 Redis 数据结构细粒度封装的专用 RPC 模式（共暴露 18 个独立工具，如 `redis_get_string`、`redis_hash_get`、`redis_list_range` 等）。随着生产实践推进，该架构暴露了以下核心瓶颈：
1. **指令集扩展危机**：Redis 拥有 300+ 核心命令及丰富的扩展模块（JSON、Search 等）。专用工具仅覆盖了极小只读子集，且写操作覆盖严重缺失；若为每个命令实现独立工具，工具链将无限膨胀；
2. **上下文 Token 浪费与模型意图漂移**：18 个工具的 JSON Schema 占据了大量提示词 Token，且过多的细粒度工具容易导致大模型在多工具编排时产生工具选择混乱；
3. **大模型表达力受限**：大模型天生具备极高的 Redis CLI 原生语法生成能力，生硬的高层 RPC 封装反而剥夺了大模型灵活使用 Redis 命令的能力。

---

## 决策内容

确立以下核心架构重构决策，从 v2.0 起正式生效：

1. **混合精简网关模式 (Hybrid Command Gateway Pattern)**：
   - 彻底移除冗余的 15 个专用数据结构与运维工具（`strings.py`、`hashes.py`、`lists.py`、`sets.py`、`zsets.py`、`streams.py`、`admin.py` 中的专有工具）；
   - 对外暴露工具严格收敛为 **4 个**：
     - `redis_command`：核心命令网关，接收原生命令字符串并在目标实例上安全执行；
     - `redis_list_connections`：多连接配置与实例探活；
     - `redis_scan_keys`：内部游标非阻塞聚合扫描（避免大模型手动迭代游标造成死循环）；
     - `redis_key_inspect`：单键多维诊断（聚合类型、编码、TTL、内存占用）。

2. **闭环命令分类裁决器 (Command Classifier)**：
   - **破坏性指令黑名单**（`FLUSHALL`、`FLUSHDB`、`SHUTDOWN`、`CONFIG`、`DEBUG`、`KEYS *`）：任何模式下永久物理硬编码阻断；
   - **只读白名单**（`GET`、`HGET`、`LRANGE`、`SMEMBERS`、`TTL` 等 80+ 常见只读指令）：在只读模式与写模式下均放行；
   - **变更操作与未知/模块命令**（Fail-Close）：所有非只读命令与未知/扩展模块命令统一纳入双重写门禁管辖，必须满足全局 `--allow-write` 且目标连接 `readonly: false` 方可执行；
   - **高危删除二次确认 (Confirmation Guard)**：`DEL` / `UNLINK` 命令未传 `confirm=True` 时不触发物理删除，而是返回待确认结构体；传 `confirm=True` 时执行真实删除。

3. **双层防 OOM 与集合截断守卫 (Collection Slicing Guard)**：
   - 在 Docstring 层面明确指引大模型优先使用切片/分页命令；
   - 在 `SafeSerializer` 层对命令执行返回的大型字典与列表施加元素上限截断（默认截断至 100 项），并在信封元数据中断言截断状态，防止客户端内存溢出及上下文撑爆。

4. **无状态路由与单行分词**：
   - `redis_command` 接收单行命令字符串 `command: str`，服务端使用 `shlex` 进行安全分词；
   - 统一支持可选的 `connection: str = None` 与 `db: int = None` 参数，严格保持底层无状态切库。

---

## 影响与权衡

- **积极收益**：
  - 工具数量减少 77%（从 18 个骤降到 4 个），单次会话 Prompt Token 消耗大幅降低；
  - 释放 100% 的原生 Redis 表达能力，全面支持各类组合命令与数据变更；
  - 维持工业级只读防护与高危破坏性指令物理切断底线，安全可控性不打折扣。
- **潜在代价与权衡**：
  - 彻底移除了 v1.x 的专用数据结构工具，属于破坏性变更（Breaking Change），版本号提升至 2.0.0。
