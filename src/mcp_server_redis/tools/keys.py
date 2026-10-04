"""
键空间检索与单键多维诊断工具。

提供聚合键扫描器、单键综合元数据检视与轻量级 TTL 存活状态查询。

@author Ateng
@since 2026-10-04
"""

import logging
from typing import Any, Final

import redis.exceptions

from mcp_server_redis.core.connection import ConnectionRegistry

logger = logging.getLogger(__name__)

# 聚合键扫描默认返回数量与硬上限
DEFAULT_SCAN_LIMIT: Final[int] = 50
MAX_SCAN_LIMIT: Final[int] = 200

# 聚合扫描最大迭代轮次保底保护，防大键空间稀疏匹配死循环
MAX_SCAN_ITERATIONS: Final[int] = 100

# 支持过滤的有效 Redis 数据类型
VALID_KEY_TYPES: Final[set[str]] = {
    "string",
    "hash",
    "list",
    "set",
    "zset",
    "stream",
}


def _make_empty_inspect_result(key: str) -> dict[str, Any]:
    """生成键不存在或空键时的标准空诊断结果字典。

    @param key 目标键名
    @return 标准结构的不存在诊断字典
    """
    return {
        "key": key,
        "exists": False,
        "type": "none",
        "ttl": -2,
        "pttl": -2,
        "memory_usage": None,
        "encoding": None,
    }


async def redis_scan_keys(
    registry: ConnectionRegistry,
    pattern: str = "*",
    limit: int = DEFAULT_SCAN_LIMIT,
    type: str | None = None,
    connection: str | None = None,
    db: int | None = None,
) -> dict[str, Any]:
    """使用非阻塞式聚合扫描器检索匹配的键名列表。

    服务内部自动循环调度游标并累积匹配键，对外屏蔽游标轮询复杂度，
    单次强制限制最多返回 200 条，防范大规模数据撑爆上下文。

    @param registry 连接注册中心实例
    @param pattern 键名匹配模式通配符（支持 *、? 等，默认 '*'）
    @param limit 最大返回条数（默认 50，硬上限 200）
    @param type 目标键类型过滤（支持 string/hash/list/set/zset/stream，可选）
    @param connection 目标连接别名（可选，缺省为默认连接）
    @param db 目标数据库编号（可选，0~15）
    @return 包含匹配键列表、总数及截断状态的字典
    @throws ValueError 传入不支持的键类型时抛出
    """
    effective_limit = min(max(limit, 1), MAX_SCAN_LIMIT) if limit > 0 else DEFAULT_SCAN_LIMIT

    type_filter: str | None = None
    if type:
        type_filter = type.lower()
        if type_filter not in VALID_KEY_TYPES:
            valid_list = ", ".join(sorted(VALID_KEY_TYPES))
            raise ValueError(f"不支持的 Redis 数据类型: '{type}'，支持的类型: {valid_list}")

    client = registry.get_client(alias=connection, db=db)
    cursor: int = 0
    accumulated_keys: list[str] = []
    seen_keys: set[str] = set()
    iterations: int = 0

    while True:
        iterations += 1
        scan_kwargs: dict[str, Any] = {
            "cursor": cursor,
            "match": pattern,
            "count": effective_limit,
        }
        if type_filter:
            scan_kwargs["_type"] = type_filter

        cursor, batch = await client.scan(**scan_kwargs)

        for key_item in batch:
            if isinstance(key_item, bytes):
                key_str = key_item.decode("utf-8", errors="replace")
            else:
                key_str = str(key_item)

            if key_str not in seen_keys:
                seen_keys.add(key_str)
                accumulated_keys.append(key_str)

        # 满足以下任一条件时终止循环：
        # 1. 累积去重键数量达到或超过请求上限；
        # 2. 游标回到 0（已全库扫描完毕）；
        # 3. 达到最大迭代轮次保底限制（防死循环）。
        if (
            len(accumulated_keys) >= effective_limit
            or cursor == 0
            or iterations >= MAX_SCAN_ITERATIONS
        ):
            break

    truncated = len(accumulated_keys) > effective_limit or cursor != 0
    final_keys = accumulated_keys[:effective_limit]

    return {
        "keys": final_keys,
        "count": len(final_keys),
        "pattern": pattern,
        "type": type,
        "cursor": cursor,
        "is_truncated": truncated,
    }


async def redis_key_inspect(
    registry: ConnectionRegistry,
    key: str,
    connection: str | None = None,
    db: int | None = None,
) -> dict[str, Any]:
    """单键多维诊断工具：聚合获取类型、存活时间、内存占用与编码方式。

    @param registry 连接注册中心实例
    @param key 待诊断的目标键名
    @param connection 目标连接别名（可选）
    @param db 目标数据库编号（可选）
    @return 包含键元数据的综合诊断字典
    """
    if not key:
        return _make_empty_inspect_result("")

    client = registry.get_client(alias=connection, db=db)
    exists = await client.exists(key)

    if not exists:
        return _make_empty_inspect_result(key)

    # 1. 查询基本类型与存活时间
    raw_type = await client.type(key)
    type_name = raw_type.decode("utf-8") if isinstance(raw_type, bytes) else str(raw_type)
    ttl = await client.ttl(key)
    pttl = await client.pttl(key)

    # 2. 尝试探查内存占用与底层编码（低版本或受限环境安全降级）
    memory_usage: int | None = None
    try:
        memory_usage = await client.memory_usage(key)
    except (redis.exceptions.RedisError, AttributeError) as exc:
        logger.debug("获取键 '%s' 的内存使用量降级: %s", key, exc)
        memory_usage = None

    encoding: str | None = None
    try:
        raw_encoding = await client.object("encoding", key)
        if raw_encoding is not None:
            encoding = (
                raw_encoding.decode("utf-8")
                if isinstance(raw_encoding, bytes)
                else str(raw_encoding)
            )
    except (redis.exceptions.RedisError, AttributeError) as exc:
        logger.debug("获取键 '%s' 的底层编码降级: %s", key, exc)
        encoding = None

    return {
        "key": key,
        "exists": True,
        "type": type_name,
        "ttl": ttl,
        "pttl": pttl,
        "memory_usage": memory_usage,
        "encoding": encoding,
    }


async def redis_key_ttl(
    registry: ConnectionRegistry,
    key: str,
    connection: str | None = None,
    db: int | None = None,
) -> dict[str, Any]:
    """极轻量独立存活时间查询工具，避免计算内存等高开销。

    @param registry 连接注册中心实例
    @param key 待查询的目标键名
    @param connection 目标连接别名（可选）
    @param db 目标数据库编号（可选）
    @return 存活时间秒数、毫秒数与过期状态字典
    """
    if not key:
        return {
            "key": "",
            "ttl": -2,
            "pttl": -2,
            "status": "not_found",
            "has_expiry": False,
            "exists": False,
        }

    client = registry.get_client(alias=connection, db=db)
    ttl = await client.ttl(key)
    pttl = await client.pttl(key)

    if ttl == -2:
        status = "not_found"
        has_expiry = False
        exists = False
    elif ttl == -1:
        status = "no_expiry"
        has_expiry = False
        exists = True
    else:
        status = "has_expiry"
        has_expiry = True
        exists = True

    return {
        "key": key,
        "ttl": ttl,
        "pttl": pttl,
        "status": status,
        "has_expiry": has_expiry,
        "exists": exists,
    }


def register_key_tools(server: Any, registry: ConnectionRegistry) -> None:
    """将键检索与诊断相关工具挂载注册至 MCP 服务端。

    @param server MCP 服务端实例 (FastMCP / MCPServer)
    @param registry 连接注册中心单例
    """

    @server.tool(name="redis_scan_keys")  # type: ignore[untyped-decorator]
    async def _tool_scan_keys(
        pattern: str = "*",
        limit: int = DEFAULT_SCAN_LIMIT,
        type: str | None = None,
        connection: str | None = None,
        db: int | None = None,
    ) -> dict[str, Any]:
        """使用非阻塞式聚合扫描器检索匹配的键名列表，自动处理底层游标分页。"""
        return await redis_scan_keys(
            registry,
            pattern=pattern,
            limit=limit,
            type=type,
            connection=connection,
            db=db,
        )

    @server.tool(name="redis_key_inspect")  # type: ignore[untyped-decorator]
    async def _tool_key_inspect(
        key: str,
        connection: str | None = None,
        db: int | None = None,
    ) -> dict[str, Any]:
        """单键多维诊断工具：聚合获取类型、TTL、内存占用与编码结构。"""
        return await redis_key_inspect(registry, key=key, connection=connection, db=db)

    @server.tool(name="redis_key_ttl")  # type: ignore[untyped-decorator]
    async def _tool_key_ttl(
        key: str,
        connection: str | None = None,
        db: int | None = None,
    ) -> dict[str, Any]:
        """低延迟快速检测键的存活剩余时间与过期状态，免除内存计算开销。"""
        return await redis_key_ttl(registry, key=key, connection=connection, db=db)
