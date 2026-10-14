"""
键空间检索与单键多维诊断工具。

提供聚合键扫描器与单键综合元数据检视能力。

@author Ateng
@since 2026-10-04
"""

import asyncio
import logging
from typing import Any, Final

import redis.exceptions
from redis.asyncio.cluster import RedisCluster

from mcp_server_redis.core.connection import ConnectionNotFoundError, ConnectionRegistry

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


async def _fetch_keys_metadata(client: Any, keys: list[str]) -> list[dict[str, Any]]:
    """并发拉取键的基础数据类型与 TTL 元数据，避免串行网络开销。

    @param client Redis 客户端对象（单机或集群驱动）
    @param keys 待探查键名列表
    @return 结构化元数据字典列表
    """

    async def _fetch_single(k: str) -> dict[str, Any]:
        try:
            raw_type, ttl = await asyncio.gather(client.type(k), client.ttl(k))
            type_name = raw_type.decode("utf-8") if isinstance(raw_type, bytes) else str(raw_type)
            return {"key": k, "type": type_name, "ttl": ttl}
        except (redis.exceptions.RedisError, OSError, ValueError) as exc:
            logger.debug("获取键 '%s' 元数据降级: %s", k, exc)
            return {"key": k, "type": "unknown", "ttl": -2}

    return list(await asyncio.gather(*[_fetch_single(k) for k in keys]))


async def redis_scan_keys(
    registry: ConnectionRegistry,
    pattern: str = "*",
    limit: int = DEFAULT_SCAN_LIMIT,
    cursor: int = 0,
    type: str | None = None,
    connection: str | None = None,
    db: int | None = None,
    include_meta: bool = False,
) -> dict[str, Any]:
    """使用非阻塞式聚合扫描器检索匹配的键名列表。

    服务内部自动循环调度游标并累积匹配键，对外屏蔽游标轮询复杂度，
    支持传入上一页返回的 cursor 实现单机断点续翻（从 0 开始扫描）。
    单次强制限制最多返回 200 条，防范大规模数据撑爆上下文。
    若开启 include_meta=True，将并行拉取每个键的 type 与 ttl 元数据，终结 N+1 交互。

    @param registry 连接注册中心实例
    @param pattern 键名匹配模式通配符（支持 *、? 等，默认 '*'）
    @param limit 最大返回条数（默认 50，硬上限 200）
    @param cursor 起始扫描游标（默认 0，支持传入上一页返回的游标实现断点续翻）
    @param type 目标键类型过滤（支持 string/hash/list/set/zset/stream，可选）
    @param connection 目标连接别名（可选，缺省为默认连接）
    @param db 目标数据库编号（可选，0~15）
    @param include_meta 是否在单次往返中并发附加键类型与 TTL 元数据（默认 False）
    @return 包含匹配键列表、总数、截断状态及可选 entries 元数据字典
    @throws ValueError 传入不支持的键类型时抛出
    """
    effective_limit = min(max(limit, 1), MAX_SCAN_LIMIT) if limit > 0 else DEFAULT_SCAN_LIMIT

    type_filter: str | None = None
    if type:
        type_filter = type.lower()
        if type_filter not in VALID_KEY_TYPES:
            valid_list = ", ".join(sorted(VALID_KEY_TYPES))
            raise ValueError(f"不支持的 Redis 数据类型: '{type}'，支持的类型: {valid_list}")

    try:
        client = registry.get_client(alias=connection, db=db)
    except ConnectionNotFoundError:
        guide_msg = registry.format_not_found_message(connection or "")
        logger.warning("redis_scan_keys 指定了不存在的 Redis 连接别名 '%s'", connection)
        return {
            "status": "error",
            "error_type": "ConnectionNotFoundError",
            "message": guide_msg,
            "keys": [],
            "count": 0,
            "pattern": pattern,
            "cursor": 0,
            "is_truncated": False,
        }

    accumulated_keys: list[str] = []
    seen_keys: set[str] = set()

    # 1. 集群模式：分片集群无全局游标，利用 client.scan_iter 聚合各分片节点匹配键
    if isinstance(client, RedisCluster):
        cluster_scan_kwargs: dict[str, Any] = {
            "match": pattern,
            "count": effective_limit,
        }
        if type_filter:
            cluster_scan_kwargs["_type"] = type_filter

        async for key_item in client.scan_iter(**cluster_scan_kwargs):
            if isinstance(key_item, bytes):
                key_str = key_item.decode("utf-8", errors="replace")
            else:
                key_str = str(key_item)

            if key_str not in seen_keys:
                seen_keys.add(key_str)
                accumulated_keys.append(key_str)

            # 多探查 1 条以精准判断是否存在截断
            if len(accumulated_keys) > effective_limit:
                break

        truncated = len(accumulated_keys) > effective_limit
        final_keys = accumulated_keys[:effective_limit]

        result_payload: dict[str, Any] = {
            "keys": final_keys,
            "count": len(final_keys),
            "pattern": pattern,
            "type": type,
            "cursor": 0,
            "is_truncated": truncated,
        }
        if cursor > 0:
            result_payload["message"] = (
                "Redis Cluster 分片集群采用全局节点迭代，已聚合返回当前批次键；"
                "若需缩小范围建议细化 pattern 或调整 limit。"
            )
        if include_meta:
            result_payload["entries"] = (
                await _fetch_keys_metadata(client, final_keys) if final_keys else []
            )

        return result_payload

    # 2. 单机模式：通过游标循环非阻塞聚合扫描
    current_cursor: int = max(cursor, 0)
    iterations: int = 0

    while True:
        iterations += 1
        scan_kwargs: dict[str, Any] = {
            "cursor": current_cursor,
            "match": pattern,
            "count": effective_limit,
        }
        if type_filter:
            scan_kwargs["_type"] = type_filter

        current_cursor, batch = await client.scan(**scan_kwargs)

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
            or current_cursor == 0
            or iterations >= MAX_SCAN_ITERATIONS
        ):
            break

    truncated = len(accumulated_keys) > effective_limit or current_cursor != 0
    final_keys = accumulated_keys[:effective_limit]

    result_payload = {
        "keys": final_keys,
        "count": len(final_keys),
        "pattern": pattern,
        "type": type,
        "cursor": current_cursor,
        "is_truncated": truncated,
    }
    if include_meta:
        result_payload["entries"] = (
            await _fetch_keys_metadata(client, final_keys) if final_keys else []
        )

    return result_payload


async def redis_inspect_key(
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

    try:
        client = registry.get_client(alias=connection, db=db)
    except ConnectionNotFoundError:
        guide_msg = registry.format_not_found_message(connection or "")
        logger.warning("redis_inspect_key 指定了不存在的 Redis 连接别名 '%s'", connection)
        return {
            "status": "error",
            "error_type": "ConnectionNotFoundError",
            "message": guide_msg,
            "key": key,
            "exists": False,
        }

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


# 库内向后兼容别名
redis_key_inspect = redis_inspect_key


def register_key_tools(server: Any, registry: ConnectionRegistry) -> None:
    """将键检索与诊断相关工具挂载注册至 MCP 服务端。

    @param server MCP 服务端实例 (FastMCP / MCPServer)
    @param registry 连接注册中心单例
    """
    conn_hint = registry.format_connection_hint_for_llm()

    async def _tool_scan_keys(
        pattern: str = "*",
        limit: int = DEFAULT_SCAN_LIMIT,
        cursor: int = 0,
        type: str | None = None,
        connection: str | None = None,
        db: int | None = None,
        include_meta: bool = False,
    ) -> dict[str, Any]:
        return await redis_scan_keys(
            registry,
            pattern=pattern,
            limit=limit,
            cursor=cursor,
            type=type,
            connection=connection,
            db=db,
            include_meta=include_meta,
        )

    _tool_scan_keys.__doc__ = f"""使用非阻塞式聚合扫描器检索匹配的键名列表，自动处理底层游标分页。

支持传入上一页返回的 cursor 实现单机断点续翻（从 0 开始扫描）。
可选择传入 include_meta=True 一次性并发拉取各键的类型与 TTL 元数据，避免 N+1 往返。

Args:
    pattern: 键名匹配模式通配符（默认 '*'）
    limit: 最大返回条数（默认 50，硬上限 200）
    cursor: 起始扫描游标（默认 0 从头扫描，可传入上一页返回的 cursor 实现单机断点续翻）
    type: 目标键类型过滤（支持 string/hash/list/set/zset/stream，可选）
    connection: {conn_hint}
    db: 目标数据库编号（可选，0~15）
    include_meta: 是否在单次调用中并发附加 type 与 ttl 元数据（默认 False）
"""
    server.tool(name="redis_scan_keys")(_tool_scan_keys)

    async def _tool_inspect_key(
        key: str,
        connection: str | None = None,
        db: int | None = None,
    ) -> dict[str, Any]:
        return await redis_inspect_key(registry, key=key, connection=connection, db=db)

    _tool_inspect_key.__doc__ = f"""单键多维诊断工具：聚合获取类型、TTL、内存占用与编码结构。

Args:
    key: 待诊断的目标键名
    connection: {conn_hint}
    db: 目标数据库编号（可选，0~15）
"""
    server.tool(name="redis_inspect_key")(_tool_inspect_key)
