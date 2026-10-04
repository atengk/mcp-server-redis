# ADR-0003: 工具命名契约、二次确认门禁与数据安全序列化设计

- **状态**: 已采纳 (Accepted)
- **决策日期**: 2026-10-04

---

## 背景与问题陈述

经过三轮设计推演，服务已确立了双轨能力、自适应连接以及安全切片机制。在进入工程落地编码前，需要冻结以下三个关键协议契约：
1. **工具命名空间**：避免在多 MCP 混合注册场景下与其它服务产生同名冲突，同时保证大模型意图识别的高准确度；
2. **写操作防误删**：虽然 `--allow-write` 控制了写权限，但在授权环境下，大模型仍可能因理解偏差批量删除关键业务缓存；
3. **数据跨格式表现**：Redis 存储任意字节流（非 UTF-8 二进制）或超长大文本，若无防御性序列化机制，将导致 JSON 解析崩溃或上下文窗口耗尽。

---

## 决策内容

1. **扁平化 `redis_` 领域前缀命名空间**：
   - 所有对外暴露的 FastMCP 工具统一使用 `redis_` 作为前缀；
   - 保持命令意图单一明确，例如：
     - 实例与概览：`redis_list_connections`、`redis_ping`、`redis_info`、`redis_dbsize`
     - 键空间检索：`redis_scan_keys`、`redis_key_inspect`、`redis_key_ttl`
     - 数据结构读取：`redis_get_string`、`redis_hash_get`、`redis_list_range`、`redis_set_members`、`redis_zset_range`、`redis_stream_read`
     - 安全数据变更：`redis_set_string`、`redis_del_keys`、`redis_expire_key`
     - 运维诊断：`redis_slowlog_get`、`redis_client_list`

2. **双格式连接配置文件支持**：
   - 支持 YAML（`.yaml` / `.yml`）与 JSON（`.json`）双格式；
   - 配置模型包含 `default`（默认连接别名）及 `connections`（映射各环境连接 URL、默认 DB 与只读标记）；
   - 输出与日志中自动掩码脱敏密码。

3. **破坏性变更二次确认门禁 (Confirmation Guard)**：
   - 删除操作（`redis_del_keys`）强制包含布尔参数 `confirm: bool = False`；
   - 当 `confirm=False` 时，工具拦截物理删除，仅返回目标 Key 预估影响与确认提示；
   - 仅当模型在确认后显式传参 `confirm=True` 时，底层才执行真实 `DEL`。

4. **自适应数据安全序列化器 (Safe Serializer)**：
   - 优先尝试 UTF-8 解码为文本；
   - 包含非 UTF-8 字节的数据自动编码为 Base64 字符串，并附加元数据 `{ "is_binary": true }`；
   - 文本或 Base64 超过安全长度阈值（默认 4000 字符）时自动截断，附加 `{ "truncated": true, "total_length": ... }`。

---

## 影响与权衡

- **积极收益**：
  - 工具命名规范、无二义性，消除多 MCP 场景冲突；
  - 彻底规避大模型因幻觉误删全量键值的风险；
  - 健壮处理各类二进制序列化数据（Protobuf/MsgPack/图片/压缩包）而不会导致协议报错。
- **潜在代价与权衡**：
  - 删除操作需要额外的确认步骤，交互轮次增加一次，但极大提高了生产环境安全性。
