# ADR-0004: 工具动宾命名规范、双重写门禁与 JSON 结构化解析优化

- **状态**: 已采纳 (Accepted)
- **决策日期**: 2026-10-04

---

## 背景与问题陈述

在进入需求工单编写阶段前，我们对整套体系进行了冗余与一致性复盘，发现并确立了以下三个关键细节：
1. **工具动宾命名一致性**：文档中存在 `redis_slowlog_get` 与 `redis_get_slowlog`、`redis_del_keys` 与 `redis_delete_keys` 等命名分歧；
2. **多连接场景写权限冲突**：当全局启动参数 `--allow-write` 与配置文件中特定只读连接（如预发/生产库 `readonly: true`）并存时，缺乏严格的裁决机制；
3. **大模型读取 String 缓存的处理体验**：Redis 存储的文本中超 80% 为 JSON 序列化对象，纯文本返回需要大模型二次解析与转义，消耗过多 Token。

---

## 决策内容

1. **统一“前缀_动作_对象”动宾命名规范**：
   - 全局规范为英文标准动宾结构，降低大模型语义理解偏差：
     - `redis_list_connections`
     - `redis_get_slowlog`（统一弃用 `redis_slowlog_get`）
     - `redis_delete_keys`（统一弃用 `redis_del_keys`）
     - `redis_scan_keys`

2. **保留极轻量独立 `redis_key_ttl` 工具**：
   - 保留单独的 `redis_key_ttl` 工具，满足仅需快速检查键过期时间的高频低延迟调用场景，避免 `redis_key_inspect` 调用 `MEMORY USAGE` 造成的额外性能开销。

3. **实行双重写门禁 (Dual Write Gate)**：
   - 裁决原则：**全局 `--allow-write` 为真 且 目标连接配置 `readonly == false`**；
   - 任何一个条件不满足时，写操作即被坚决阻断；杜绝由于全局传了 `--allow-write` 而误操作预置只读保护库的风险。

4. **String 键值智能 JSON 探测与反序列化增强**：
   - `redis_get_string` 增加参数 `parse_json: bool = True`；
   - 当读取到的值为合法 JSON 文本时，返回结构中附带结构化解析对象 `json_data`，同时保留 `value: str` 原始文本。

---

## 影响与权衡

- **积极收益**：
  - 工具命名完全归一化，无任何文档歧义；
  - 生产只读库获得最高等级的配置级一票否决权，安全性极致稳健；
  - 大模型分析 JSON 缓存数据更加高效精准。
