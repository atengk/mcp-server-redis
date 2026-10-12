"""核心命令网关工具。

接收客户端原生单行 Redis 命令，负责安全分词、双重写门禁校验、破坏性阻断、
高危删除二次确认、Cluster 跨槽异常引导与执行结果信封包装。

@author Ateng
@since 2026-10-12
"""

import logging
from typing import Any

from redis.exceptions import ClusterCrossSlotError, ResponseError

from mcp_server_redis.core.connection import ConnectionRegistry
from mcp_server_redis.core.guard import SecurityGuard
from mcp_server_redis.core.serializer import SafeSerializer

logger = logging.getLogger(__name__)

# 内部默认安全守卫单例（无状态保底只读）
_default_guard = SecurityGuard(allow_write=False)


async def redis_command(
    registry: ConnectionRegistry,
    command: str,
    guard: SecurityGuard | None = None,
    connection: str | None = None,
    db: int | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """执行单行原生 Redis 命令行操作（核心命令网关）。

    支持原生语法分词（如 'GET key', 'SET key "hello world"', 'HGETALL user:1001'）。
    底层物理拦截破坏性指令（FLUSHALL/KEYS 等），实施 Fail-Close 阶梯写门禁与 DEL/UNLINK 二次确认机制。
    大集合返回结果自动安全截断（上限 100 项），防止客户端内存溢出。

    Args:
        registry: 连接注册中心实例
        command: 原生 Redis 命令行字符串
        guard: 安全守卫单例（可选，缺省使用默认只读守卫）
        connection: 目标连接别名（可选，缺省为默认连接）
        db: 逻辑库编号（可选，0~15）
        confirm: 是否确认执行高危删除操作（仅对 DEL/UNLINK 生效）

    Returns:
        dict[str, Any]: 统一信封结果字典，包含 command, result, data_type, is_truncated 等元数据

    Raises:
        DestructiveCommandError: 命中破坏性指令时抛出
        ReadOnlyModeError: 全局未授权写操作时抛出
        ReadOnlyConnectionError: 目标连接为只读配置时抛出
        ValueError: 命令为空或分词语法错误时抛出
    """
    active_guard = guard or _default_guard
    profile = registry.get_profile(alias=connection)

    # 1. 语法分词、破坏性阻断与阶梯双重写门禁判定
    verdict = active_guard.verify_command(command, profile)

    # 2. 高危删除二次确认防御（未确认时返回结构化确认信封，遵循 Envelope Shape 规范）
    if verdict.requires_confirmation and not confirm:
        logger.info("拦截到高危删除命令 (%s)，等待显式二次确认", command)
        message = (
            f"该高危删除操作涉及 {len(verdict.keys)} 个键: {verdict.keys}。"
            "为防止非预期数据丢失，请在仔细核对后显式传入 confirm=True 确认执行。"
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

    # 3. 获取无状态路由客户端并执行命令
    client = registry.get_client(alias=connection, db=db)
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
        raise

    # 4. 结果安全序列化与信封模型包装
    serialized = SafeSerializer.serialize_result(raw_result, command=command)
    return serialized.to_dict()


def register_command_tools(
    server: Any,
    registry: ConnectionRegistry,
    guard: SecurityGuard | None = None,
) -> None:
    """向 FastMCP 服务端挂载核心命令网关工具。

    Args:
        server: FastMCP 服务端实例
        registry: 连接注册中心单例
        guard: 安全守卫单例
    """
    active_guard = guard or _default_guard

    @server.tool(name="redis_command")  # type: ignore[untyped-decorator]
    async def _tool_command(
        command: str,
        connection: str | None = None,
        db: int | None = None,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """执行单行原生 Redis 命令（核心命令网关）。

        支持单行原生 Redis 语法与标准引号分词（如 'GET key', 'SET key "hello world"', 'HGETALL user:1001'）。
        内置破坏性指令物理阻断（FLUSHALL/KEYS 等）、Fail-Close 阶梯写门禁与高危删除二次确认保护。
        大集合返回结果自动安全切片截断（上限 100 项），防止客户端内存溢出与上下文爆炸。

        Args:
            command: 原生 Redis 命令行字符串（如 'GET user:1001' 或 'SET greeting "hello world"'）
            connection: 目标连接别名（可选，缺省使用默认连接）
            db: 逻辑库编号（可选，0~15，集群模式下忽略并绑定 db=0）
            confirm: 是否确认执行高危删除操作（仅对 DEL/UNLINK 命令生效，未确认时返回待确认详情）

        Returns:
            dict[str, Any]: 统一信封结果字典，包含 command, result, data_type, is_truncated 等元数据
        """
        return await redis_command(
            registry=registry,
            command=command,
            guard=active_guard,
            connection=connection,
            db=db,
            confirm=confirm,
        )
