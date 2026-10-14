"""核心命令网关工具。

接收客户端原生单行 Redis 命令，负责安全分词、双重写门禁校验、破坏性阻断、
高危删除二次确认、Cluster 跨槽异常引导与执行结果信封包装。

@author Ateng
@since 2026-10-12
"""

import logging
import time
from typing import Any, Final

from redis.exceptions import ClusterCrossSlotError, RedisError, ResponseError

from mcp_server_redis.core.audit import AuditLogger
from mcp_server_redis.core.connection import ConnectionRegistry
from mcp_server_redis.core.env import resolve_max_unbounded_read_items_from_env
from mcp_server_redis.core.guard import SecurityGuard
from mcp_server_redis.core.serializer import SafeSerializer

logger = logging.getLogger(__name__)

# 最大管道批处理命令条数上限
MAX_PIPELINE_COMMANDS: Final[int] = 20

# 内部默认安全守卫单例（无状态保底只读）
_default_guard = SecurityGuard(allow_write=False)


def detect_unbounded_read(raw_tokens: list[str]) -> tuple[str, str, str] | None:
    """检查命令是否属于高危无界全量读取。

    返回 (probe_cmd, key, collection_type_name) 或 None。
    """
    if not raw_tokens or len(raw_tokens) < 2:
        return None

    verb = raw_tokens[0].upper()
    key = raw_tokens[1]

    if verb == "HGETALL":
        return ("HLEN", key, "Hash")
    if verb == "SMEMBERS":
        return ("SCARD", key, "Set")
    if verb == "LRANGE" and len(raw_tokens) >= 4:
        start, stop = raw_tokens[2], raw_tokens[3]
        if start == "0" and stop == "-1":
            return ("LLEN", key, "List")
    if verb in ("ZRANGE", "ZREVRANGE") and len(raw_tokens) >= 4:
        start, stop = raw_tokens[2], raw_tokens[3]
        if start == "0" and stop == "-1":
            return ("ZCARD", key, "Sorted Set (ZSet)")

    return None


async def check_unbounded_read_defense(
    client: Any,
    raw_tokens: list[str],
    max_items: int,
) -> str | None:
    """对无界全量读取执行 O(1) 基数探查防爆预检。

    若超过安全阈值，返回引导拦截提示；未超限或探查遇到异常时返回 None（放行）。
    """
    detection = detect_unbounded_read(raw_tokens)
    if not detection:
        return None

    probe_cmd, key, col_type = detection
    try:
        count = await client.execute_command(probe_cmd, key)
        if count is not None and isinstance(count, int) and count > max_items:
            verb = raw_tokens[0].upper()
            if verb == "HGETALL":
                guide = f"建议改用 'HSCAN {key} 0 COUNT 100' 进行渐进式分页切片读取"
            elif verb == "SMEMBERS":
                guide = f"建议改用 'SSCAN {key} 0 COUNT 100' 进行渐进式分页切片读取"
            elif verb == "LRANGE":
                guide = f"建议改用有界范围切片（例如 'LRANGE {key} 0 99'）按批次读取"
            else:
                guide = f"建议改用有界范围切片（例如 '{verb} {key} 0 99'）或 'ZSCAN {key} 0 COUNT 100' 渐进式读取"
            return (
                f"安全拦截：目标 {col_type} 键 '{key}' 包含 {count} 项元素，"
                f"超过了单次全量读取安全防爆阈值（{max_items} 项）。"
                f"为防止 Redis 单线程主事件循环锁死引发服务雪崩，禁止下发无界全量读取命令 '{verb}'。"
                f"{guide}。"
            )
    except (RedisError, OSError, TimeoutError) as exc:
        logger.debug("BigKey 预检探测异常 (%s %s): %s", probe_cmd, key, exc)
    return None


async def redis_execute_command(
    registry: ConnectionRegistry,
    command: str = "",
    commands: list[str] | None = None,
    guard: SecurityGuard | None = None,
    connection: str | None = None,
    db: int | None = None,
    confirm: bool = False,
    audit_logger: AuditLogger | None = None,
    max_unbounded_read_items: int | None = None,
) -> dict[str, Any]:
    """执行单行原生 Redis 命令行操作或多命令管道批处理（核心命令网关）。

    支持原生语法分词（如 'GET key', 'SET key "hello world"', 'HGETALL user:1001'）。
    支持通过 'commands' 传入列表执行管道批处理（单次上限 20 条），将多命令在单一网络往返中批量下发。
    底层物理拦截破坏性指令（FLUSHALL/KEYS 等），实施 Fail-Close 阶梯写门禁与 DEL/UNLINK 二次确认机制。
    自动对阻塞式读取命令（如 BLPOP/BRPOP）的安全超时进行收敛（0 秒改写为 2 秒，>5 秒截断为 5 秒），杜绝进程挂死。
    针对 HGETALL/SMEMBERS/LRANGE/ZRANGE 等无界全量读取执行 O(1) 探查预检，防止 Redis 单线程锁死。
    大集合返回结果自动安全截断（上限 100 项），防止客户端内存溢出与上下文爆炸。

    Args:
        registry: 连接注册中心实例
        command: 原生 Redis 命令行字符串（与 commands 二选一）
        commands: 原生 Redis 命令行列表（用于管道批处理，上限 20 条）
        guard: 安全守卫单例（可选，缺省使用默认只读守卫）
        connection: 目标连接别名（可选，缺省为默认连接）
        db: 逻辑库编号（可选，0~15）
        confirm: 是否确认执行高危删除操作（仅对 DEL/UNLINK 生效）
        audit_logger: 结构化审计记录器实例（可选）
        max_unbounded_read_items: 无界全量读取安全阈值（可选，缺省读取环境变量或默认 2000）

    Returns:
        dict[str, Any]: 统一信封结果字典，包含 command/results, result, data_type, is_truncated 等元数据

    Raises:
        DestructiveCommandError: 命中破坏性指令时抛出
        ReadOnlyModeError: 全局未授权写操作时抛出
        ReadOnlyConnectionError: 目标连接为只读配置时抛出
        ValueError: 命令为空、参数冲突或分词语法错误时抛出
    """
    start_time = time.perf_counter()
    active_guard = guard or _default_guard
    profile = registry.get_profile(alias=connection)
    effective_alias = connection or (profile.alias if profile else "default")
    effective_db = db if db is not None else (profile.db if profile else 0)
    effective_max_unbounded = (
        max_unbounded_read_items
        if max_unbounded_read_items is not None
        else resolve_max_unbounded_read_items_from_env()
    )

    # 参数合法性与二选一校验
    has_single = bool(command and command.strip())
    has_batch = commands is not None

    if has_single and has_batch:
        raise ValueError("不能同时传入 'command' 和 'commands' 参数，请二选一。")
    if not has_single and not has_batch:
        raise ValueError("命令不能为空，必须提供有效的 'command' 或 'commands' 参数。")

    # ================= 管道批处理模式 =================
    if commands is not None:
        if not commands:
            raise ValueError("传入的 'commands' 批处理列表不能为空。")
        if len(commands) > MAX_PIPELINE_COMMANDS:
            raise ValueError(
                f"管道批处理单次最多支持 {MAX_PIPELINE_COMMANDS} 条命令，当前传入: {len(commands)}"
            )

        # 1. 全批次前置 Fail-Close 强校验（任一命令命中阻断或无写权限则整批拒绝）
        try:
            verdicts = [active_guard.verify_command(cmd, profile) for cmd in commands]
        except Exception as exc:
            if audit_logger:
                duration_ms = (time.perf_counter() - start_time) * 1000
                audit_logger.log(
                    command="PIPELINE",
                    connection=effective_alias,
                    db=effective_db,
                    duration_ms=duration_ms,
                    status="rejected",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
            raise

        # 2. 高危删除二次确认合并检查
        if not confirm:
            unconfirmed_keys: list[str] = []
            for v in verdicts:
                if v.requires_confirmation:
                    unconfirmed_keys.extend(v.keys)
            if unconfirmed_keys:
                logger.info(
                    "管道批处理拦截到高危删除命令，涉及 %d 个键，等待显式二次确认",
                    len(unconfirmed_keys),
                )
                message = (
                    f"管道批处理包含高危删除操作，共涉及 {len(unconfirmed_keys)} 个键: {unconfirmed_keys}。"
                    "为防止非预期数据丢失，请在仔细核对后显式传入 confirm=True 确认执行。"
                )
                if audit_logger:
                    duration_ms = (time.perf_counter() - start_time) * 1000
                    audit_logger.log(
                        command="PIPELINE",
                        connection=effective_alias,
                        db=effective_db,
                        duration_ms=duration_ms,
                        status="confirmation_required",
                        keys=unconfirmed_keys,
                    )
                return {
                    "command": "PIPELINE",
                    "commands": commands,
                    "status": "confirmation_required",
                    "result": None,
                    "data_type": "confirmation_required",
                    "keys": unconfirmed_keys,
                    "target_count": len(unconfirmed_keys),
                    "message": message,
                    "is_truncated": False,
                    "total_count": len(unconfirmed_keys),
                }

        # 3. 获取客户端并进行 BigKey 防爆预检，然后在底层单个 Pipeline 中批量下发
        client = registry.get_client(alias=connection, db=db)
        for v in verdicts:
            guide_msg = await check_unbounded_read_defense(
                client, v.raw_tokens, effective_max_unbounded
            )
            if guide_msg:
                if audit_logger:
                    duration_ms = (time.perf_counter() - start_time) * 1000
                    audit_logger.log(
                        command="PIPELINE",
                        connection=effective_alias,
                        db=effective_db,
                        duration_ms=duration_ms,
                        status="rejected",
                        keys=v.keys,
                        error_type="BigKeyReadBlockedError",
                        error_message=guide_msg,
                    )
                return {
                    "command": "PIPELINE",
                    "commands": commands,
                    "status": "error",
                    "error_type": "BigKeyReadBlockedError",
                    "result": guide_msg,
                    "data_type": "error",
                    "message": guide_msg,
                    "is_truncated": False,
                    "total_count": None,
                }

        try:
            async with client.pipeline(transaction=False) as pipe:
                for v in verdicts:
                    pipe.execute_command(*v.raw_tokens)
                raw_results = await pipe.execute(raise_on_error=False)
        except (ResponseError, ClusterCrossSlotError) as exc:
            err_msg = str(exc)
            is_cross_slot = (
                isinstance(exc, ClusterCrossSlotError)
                or "CROSSSLOT" in err_msg.upper()
                or "HASH TO THE SAME SLOT" in err_msg.upper()
            )
            if is_cross_slot:
                logger.warning("Redis Cluster 管道跨槽执行拦截: %s", err_msg)
                guide_msg = (
                    f"Redis Cluster 管道批处理跨槽执行失败: '{err_msg}'。"
                    "在分片集群模式下，管道涉及的键位于不同的哈希槽（Hash Slot）。"
                    "请将命令拆分为单键操作逐一执行，或使用包含相同哈希标签（如 {tag}）的键名。"
                )
                if audit_logger:
                    duration_ms = (time.perf_counter() - start_time) * 1000
                    audit_logger.log(
                        command="PIPELINE",
                        connection=effective_alias,
                        db=effective_db,
                        duration_ms=duration_ms,
                        status="error",
                        error_type="CrossSlotError",
                        error_message=guide_msg,
                    )
                return {
                    "command": "PIPELINE",
                    "commands": commands,
                    "status": "error",
                    "error_type": "CrossSlotError",
                    "result": guide_msg,
                    "data_type": "error",
                    "message": guide_msg,
                    "is_truncated": False,
                    "total_count": None,
                }
            if audit_logger:
                duration_ms = (time.perf_counter() - start_time) * 1000
                audit_logger.log(
                    command="PIPELINE",
                    connection=effective_alias,
                    db=effective_db,
                    duration_ms=duration_ms,
                    status="error",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
            raise
        except Exception as exc:
            if audit_logger:
                duration_ms = (time.perf_counter() - start_time) * 1000
                audit_logger.log(
                    command="PIPELINE",
                    connection=effective_alias,
                    db=effective_db,
                    duration_ms=duration_ms,
                    status="error",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
            raise

        # 4. 序列化各个命令的结果并封装聚合信封
        serialized_results: list[dict[str, Any]] = []
        any_error = False
        clamped_notes: list[str] = []

        for cmd_str, v, raw_res in zip(commands, verdicts, raw_results):
            if v.clamped_message:
                clamped_notes.append(v.clamped_message)

            if isinstance(raw_res, Exception):
                any_error = True
                item_dict = {
                    "command": cmd_str,
                    "status": "error",
                    "error_type": type(raw_res).__name__,
                    "result": str(raw_res),
                    "data_type": "error",
                    "message": str(raw_res),
                    "is_truncated": False,
                    "total_count": None,
                }
            else:
                serialized = SafeSerializer.serialize_result(raw_res, command=cmd_str)
                item_dict = serialized.to_dict()

            if v.clamped_message and "message" not in item_dict:
                item_dict["message"] = v.clamped_message

            serialized_results.append(item_dict)

        envelope: dict[str, Any] = {
            "command": "PIPELINE",
            "status": "error" if any_error else "success",
            "total_commands": len(commands),
            "results": serialized_results,
            "data_type": "pipeline",
            "is_truncated": False,
            "total_count": len(serialized_results),
        }
        if clamped_notes:
            envelope["message"] = "；".join(clamped_notes)

        if audit_logger:
            duration_ms = (time.perf_counter() - start_time) * 1000
            all_keys = [k for v in verdicts for k in v.keys]
            audit_logger.log(
                command="PIPELINE",
                connection=effective_alias,
                db=effective_db,
                duration_ms=duration_ms,
                status="error" if any_error else "success",
                keys=all_keys,
            )

        return envelope

    # ================= 单命令网关模式 =================
    # 1. 语法分词、破坏性阻断与阶梯双重写门禁判定
    try:
        verdict = active_guard.verify_command(command, profile)
    except Exception as exc:
        if audit_logger:
            duration_ms = (time.perf_counter() - start_time) * 1000
            audit_logger.log(
                command=command,
                connection=effective_alias,
                db=effective_db,
                duration_ms=duration_ms,
                status="rejected",
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
        raise

    # 2. 高危删除二次确认防御（未确认时返回结构化确认信封，遵循 Envelope Shape 规范）
    if verdict.requires_confirmation and not confirm:
        logger.info("拦截到高危删除命令 (%s)，等待显式二次确认", command)
        message = (
            f"该高危删除操作涉及 {len(verdict.keys)} 个键: {verdict.keys}。"
            "为防止非预期数据丢失，请在仔细核对后显式传入 confirm=True 确认执行。"
        )
        if audit_logger:
            duration_ms = (time.perf_counter() - start_time) * 1000
            audit_logger.log(
                command=command,
                connection=effective_alias,
                db=effective_db,
                duration_ms=duration_ms,
                status="confirmation_required",
                keys=verdict.keys,
            )
        return {
            "command": command,
            "status": "confirmation_required",
            "result": None,
            "data_type": "confirmation_required",
            "keys": verdict.keys,
            "target_count": len(verdict.keys),
            "message": message,
            "is_truncated": False,
            "total_count": len(verdict.keys),
        }

    # 3. 获取无状态路由客户端并执行 BigKey 防爆预检
    client = registry.get_client(alias=connection, db=db)
    guide_msg = await check_unbounded_read_defense(
        client, verdict.raw_tokens, effective_max_unbounded
    )
    if guide_msg:
        if audit_logger:
            duration_ms = (time.perf_counter() - start_time) * 1000
            audit_logger.log(
                command=command,
                connection=effective_alias,
                db=effective_db,
                duration_ms=duration_ms,
                status="rejected",
                keys=verdict.keys,
                error_type="BigKeyReadBlockedError",
                error_message=guide_msg,
            )
        return {
            "command": command,
            "status": "error",
            "error_type": "BigKeyReadBlockedError",
            "result": guide_msg,
            "data_type": "error",
            "message": guide_msg,
            "is_truncated": False,
            "total_count": None,
        }

    try:
        raw_result = await client.execute_command(*verdict.raw_tokens)
    except (ResponseError, ClusterCrossSlotError) as exc:
        err_msg = str(exc)
        is_cross_slot = (
            isinstance(exc, ClusterCrossSlotError)
            or "CROSSSLOT" in err_msg.upper()
            or "HASH TO THE SAME SLOT" in err_msg.upper()
        )
        if is_cross_slot:
            logger.warning("Redis Cluster 跨槽执行拦截: %s", err_msg)
            guide_msg = (
                f"Redis Cluster 跨槽执行失败: '{err_msg}'。"
                "在分片集群模式下，多键命令涉及的键位于不同的哈希槽（Hash Slot）。"
                "请将命令拆分为单键操作逐一执行，或使用包含相同哈希标签（如 {tag}）的键名。"
            )
            if audit_logger:
                duration_ms = (time.perf_counter() - start_time) * 1000
                audit_logger.log(
                    command=command,
                    connection=effective_alias,
                    db=effective_db,
                    duration_ms=duration_ms,
                    status="error",
                    keys=verdict.keys,
                    error_type="CrossSlotError",
                    error_message=guide_msg,
                )
            return {
                "command": command,
                "status": "error",
                "error_type": "CrossSlotError",
                "result": guide_msg,
                "data_type": "error",
                "message": guide_msg,
                "is_truncated": False,
                "total_count": None,
            }
        if audit_logger:
            duration_ms = (time.perf_counter() - start_time) * 1000
            audit_logger.log(
                command=command,
                connection=effective_alias,
                db=effective_db,
                duration_ms=duration_ms,
                status="error",
                keys=verdict.keys,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
        raise
    except Exception as exc:
        if audit_logger:
            duration_ms = (time.perf_counter() - start_time) * 1000
            audit_logger.log(
                command=command,
                connection=effective_alias,
                db=effective_db,
                duration_ms=duration_ms,
                status="error",
                keys=verdict.keys,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
        raise

    # 4. 结果安全序列化与信封模型包装
    serialized = SafeSerializer.serialize_result(raw_result, command=command)
    res_dict = serialized.to_dict()
    if verdict.clamped_message:
        res_dict["message"] = verdict.clamped_message

    if audit_logger:
        duration_ms = (time.perf_counter() - start_time) * 1000
        audit_logger.log(
            command=command,
            connection=effective_alias,
            db=effective_db,
            duration_ms=duration_ms,
            status="success",
            keys=verdict.keys,
        )

    return res_dict


# 库内向后兼容别名
redis_command = redis_execute_command


def register_command_tools(
    server: Any,
    registry: ConnectionRegistry,
    guard: SecurityGuard | None = None,
    audit_logger: AuditLogger | None = None,
    max_unbounded_read_items: int | None = None,
) -> None:
    """向 FastMCP 服务端挂载核心命令网关工具。

    Args:
        server: FastMCP 服务端实例
        registry: 连接注册中心单例
        guard: 安全守卫单例
        audit_logger: 结构化审计记录器实例
        max_unbounded_read_items: 无界全量读取安全阈值
    """
    active_guard = guard or _default_guard

    @server.tool(name="redis_execute_command")  # type: ignore[untyped-decorator]
    async def _tool_execute_command(
        command: str = "",
        commands: list[str] | None = None,
        connection: str | None = None,
        db: int | None = None,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """执行单行原生 Redis 命令或多命令管道批处理（核心命令网关）。

        支持单行原生 Redis 语法与标准引号分词（如 'GET key', 'SET key "hello world"'）。
        支持通过 'commands' 传入命令列表执行管道批处理（上限 20 条），在单一网络往返中批量极速执行。
        内置破坏性指令物理阻断（FLUSHALL/KEYS 等）、Fail-Close 阶梯写门禁与高危删除二次确认保护。
        自动对阻塞式读取指令（BLPOP/BRPOP 等）的安全超时进行收敛改写，彻底杜绝服务假死。
        针对 HGETALL/SMEMBERS/LRANGE/ZRANGE 等无界全量读取执行 O(1) 探查预检，防止 Redis 单线程锁死。
        大集合返回结果自动安全切片截断（上限 100 项），防止客户端内存溢出与上下文爆炸。

        提示：在生产环境中读取大型 Hash/Set/ZSet 数据时，推荐优先使用 HSCAN/SSCAN/ZSCAN 等渐进式切片命令，
        避免使用 HGETALL/SMEMBERS 等全量 O(N) 命令阻塞 Redis 单线程主循环。

        Args:
            command: 原生 Redis 命令行字符串（如 'GET user:1001'，与 commands 二选一）
            commands: 原生 Redis 命令行列表（用于单往返管道批处理执行，上限 20 条）
            connection: 目标连接别名（可选，缺省使用默认连接）
            db: 逻辑库编号（可选，0~15，集群模式下忽略并绑定 db=0）
            confirm: 是否确认执行高危删除操作（仅对 DEL/UNLINK 命令生效，未确认时返回待确认详情）

        Returns:
            dict[str, Any]: 统一信封结果字典，包含 command, result, data_type, is_truncated 等元数据
        """
        return await redis_execute_command(
            registry=registry,
            command=command,
            commands=commands,
            guard=active_guard,
            connection=connection,
            db=db,
            confirm=confirm,
            audit_logger=audit_logger,
            max_unbounded_read_items=max_unbounded_read_items,
        )
