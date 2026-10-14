"""MCP 诊断引导提示词模块。

挂载内存瓶颈排查 (redis_diagnose_memory)、慢查询优化分析 (redis_analyze_slowlog)
与 BigKey 渐进式治理排障 (redis_troubleshoot_bigkeys) 标准排查模版。

@author Ateng
@since 2026-10-14
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def register_prompts(server: Any) -> None:
    """向 FastMCP 服务端挂载生产级排障诊断 Prompts 模板。

    @param server FastMCP 服务端实例
    """

    @server.prompt(
        name="redis_diagnose_memory",
        description="标准化内存泄漏、碎片率及大 Key 排查诊断 SOP 模版",
    )  # type: ignore[untyped-decorator]
    def _prompt_diagnose_memory(connection: str = "default") -> str:
        return (
            f"你是一名资深 Redis 专家，正在协助排查连接别名为 '{connection}' 的 Redis 实例内存瓶颈。\n"
            "请按以下标准化排查 SOP 依次推进诊断：\n"
            "1. 【指标基线核对】：调用 `redis_execute_command` 执行 `INFO memory`（或读取对应资源），提取 `used_memory_human`、`used_memory_peak_human`、`maxmemory_human` 及 `mem_fragmentation_ratio`（内存碎片率）。\n"
            "2. 【碎片率分析】：若碎片率 > 1.5 说明存在严重内存碎片，评估是否需配置 `activedefrag yes`；若碎片率 < 1.0 说明发生物理内存交换（Swap），需发出紧急告警。\n"
            "3. 【键空间采样】：调用 `redis_scan_keys` 配合 `include_meta=True` 检索当前库键空间，找出可能存在的大集合或无 TTL 长期驻留键。\n"
            "4. 【单键精细诊断】：针对疑似高危键调用 `redis_inspect_key` 诊断其 `memory_usage`、`encoding` 底层结构与 `ttl`。\n"
            "5. 【输出调优报告】：汇总内存消耗成因，并提供针对性的过期策略优化、编码压缩建议或驱逐策略（maxmemory-policy）调整方案。"
        )

    @server.prompt(
        name="redis_analyze_slowlog",
        description="标准化慢查询日志抓取与高耗时指令优化分析 SOP 模版",
    )  # type: ignore[untyped-decorator]
    def _prompt_analyze_slowlog(connection: str = "default") -> str:
        return (
            f"你是一名资深 Redis 专家，正在针对连接别名为 '{connection}' 的 Redis 实例分析高耗时慢查询。\n"
            "请按以下标准化排查 SOP 依次推进诊断：\n"
            "1. 【抓取慢查样本】：读取 `redis://{connection}/slowlog` 资源或调用 `redis_execute_command` 执行 `SLOWLOG GET 10`，获取近期高耗时命令。\n"
            "2. 【命令耗时归类】：统计每条慢日志的执行耗时（duration 以微秒为单位）、涉及命令动词及参数，分析慢查发生的频率与时间分布。\n"
            "3. 【根因定级】：\n"
            "   - 若包含 O(N) 复杂命令（如 `KEYS`、全量 `HGETALL`、全量 `SMEMBERS`、跨槽大范围集合运算），标记高危并提供分页切片替代方案（如改用 `HSCAN`/`SSCAN`）；\n"
            "   - 若包含大单键数据变更（如巨型 String 的 `SET` 或巨型集合的 `DEL`），指出其可能阻塞 Redis 单线程主事件循环，建议改用异步 `UNLINK`；\n"
            "4. 【输出优化措施】：针对分析出的慢命令，给出具体的架构调优方案、BigKey 拆分建议或 `slowlog-log-slower-than` 阈值调优建议。"
        )

    @server.prompt(
        name="redis_troubleshoot_bigkeys",
        description="标准化 BigKey 识别、基数探查、内存评估与渐进式切片优化 SOP 模版",
    )  # type: ignore[untyped-decorator]
    def _prompt_troubleshoot_bigkeys(connection: str = "default") -> str:
        return (
            f"你是一名资深 Redis 专家，正在针对连接别名为 '{connection}' 的 Redis 实例排查与治理大 Key (BigKey)。\n"
            "请按以下标准化排查 SOP 依次推进诊断：\n"
            "1. 【全局采样识别】：调用 `redis_scan_keys` 配合 `match='*'` 并开启 `include_meta=True` 进行渐进式采样扫描（严禁下发阻塞式 `KEYS *`），获取疑似体积过大的键候选集。\n"
            "2. 【轻量 O(1) 基数探查】：针对候选键，根据其数据类型下发轻量 O(1) 探查指令（Hash 用 `HLEN`，Set 用 `SCARD`，List 用 `LLEN`，ZSet 用 `ZCARD`），确认其所含元素总数；严禁直接对未知大小的集合执行无界全量读取（如 `HGETALL`、`SMEMBERS` 或全量 `LRANGE 0 -1`）。\n"
            "3. 【内存占用与编码诊断】：调用 `redis_inspect_key` 检查目标键的 `memory_usage`（字节大小）、`encoding`（底层编码结构）以及 `ttl`（过期时间），评估其是否构成物理内存瓶颈。\n"
            "4. 【安全切片读取方案】：\n"
            "   - 对于 Hash：推荐指导客户端改用 `HSCAN <key> <cursor> COUNT 100` 分页迭代；\n"
            "   - 对于 Set：推荐指导客户端改用 `SSCAN <key> <cursor> COUNT 100` 分页迭代；\n"
            "   - 对于 List：推荐指导客户端改用有界范围切片（如 `LRANGE <key> 0 99`）；\n"
            "   - 对于 ZSet：推荐指导客户端改用 `ZSCAN <key> <cursor> COUNT 100` 或 `ZRANGE <key> 0 99` 分页切片；\n"
            "5. 【安全清理与生命周期治理】：若需要清理巨型 BigKey，严禁直接使用同步 `DEL`（会严重阻塞 Redis 单线程事件循环），必须指导改用异步非阻塞删除 `UNLINK`（可在 `redis_execute_command` 中使用 `UNLINK <key>` 配合 `confirm=True` 执行）。"
        )
