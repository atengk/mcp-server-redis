"""
Sorted Set (ZSet) 有序集合安全切片读取工具。

提供基于 ZRANGE 的有序集合排名/分值切片读取，强制限制返回上限，防止大 ZSet OOM。

@author Ateng
@since 2026-10-04
"""

import logging
from typing import Any, Final

import redis.exceptions

from mcp_server_redis.core.connection import ConnectionRegistry
from mcp_server_redis.core.serializer import SafeSerializer

logger = logging.getLogger(__name__)

# ZSet 单次切片最大跨度硬上限（个）
MAX_ZSET_LIMIT: Final[int] = 200


async def redis_zset_range(
    registry: ConnectionRegistry,
    key: str,
    start: int = 0,
    stop: int = 49,
    reverse: bool = False,
    connection: str | None = None,
    db: int | None = None,
) -> dict[str, Any]:
    """安全读取 Sorted Set (ZSet) 有序集合的切片成员及对应分值。

    支持正序与倒序排名切片，单次返回数量受硬上限 200 条强制约束。
    对成员应用自适应安全序列化（支持 JSON 智能探测与 Base64 二进制转码）。

    @param registry 连接注册中心实例
    @param key 目标有序集合键名
    @param start 起始排名偏移量（从 0 开始）
    @param stop 结束排名偏移量（闭区间）
    @param reverse 是否降序排列（由大到小，默认 False）
    @param connection 目标连接别名（可选，缺省为默认连接）
    @param db 目标数据库编号（可选，0~15）
    @return 包含成员及其分值字典列表、条数及截断状态的字典
    """
    if not key:
        return {
            "key": "",
            "exists": False,
            "items": [],
            "count": 0,
            "is_truncated": False,
        }

    client = registry.get_client(alias=connection, db=db)

    effective_start = start
    effective_stop = stop
    truncated = False

    # 1. 负数索引标准化与跨度硬上限拦截 (防 stop=-1 击穿防 OOM 保护)
    if start < 0 or stop < 0:
        try:
            zcard = await client.zcard(key)
        except redis.exceptions.ResponseError as exc:
            if "WRONGTYPE" in str(exc):
                logger.warning("对非 ZSet 类型键 '%s' 执行 ZCARD: %s", key, exc)
                return {
                    "key": key,
                    "exists": True,
                    "items": [],
                    "count": 0,
                    "is_truncated": False,
                    "error": f"键类型不匹配: {exc}",
                }
            raise

        if zcard == 0:
            return {
                "key": key,
                "exists": False,
                "items": [],
                "count": 0,
                "is_truncated": False,
            }

        norm_start = start if start >= 0 else max(0, zcard + start)
        norm_stop = stop if stop >= 0 else max(0, zcard + stop)
        requested_span = norm_stop - norm_start + 1

        if requested_span > MAX_ZSET_LIMIT:
            effective_start = norm_start
            effective_stop = norm_start + MAX_ZSET_LIMIT - 1
            truncated = True
        else:
            effective_start = norm_start
            effective_stop = norm_stop
    else:
        requested_span = stop - start + 1
        if requested_span > MAX_ZSET_LIMIT:
            effective_stop = start + MAX_ZSET_LIMIT - 1
            truncated = True

    # 2. 调用底层 ZRANGE 获取带分值的切片
    try:
        raw_items = await client.zrange(
            key,
            effective_start,
            effective_stop,
            desc=reverse,
            withscores=True,
        )
    except redis.exceptions.ResponseError as exc:
        if "WRONGTYPE" in str(exc):
            logger.warning("对非 ZSet 类型键 '%s' 执行 ZRANGE: %s", key, exc)
            return {
                "key": key,
                "exists": True,
                "items": [],
                "count": 0,
                "is_truncated": False,
                "error": f"键类型不匹配: {exc}",
            }
        raise

    formatted_items: list[dict[str, Any]] = []
    if isinstance(raw_items, list):
        for item in raw_items:
            member_raw: Any
            score_val: Any
            if isinstance(item, tuple) and len(item) == 2:
                member_raw, score_val = item
            else:
                member_raw, score_val = item, 0.0

            serialized = SafeSerializer.serialize_value(member_raw)
            formatted_items.append(
                {
                    "member": serialized.value,
                    "json_data": serialized.json_data,
                    "score": float(score_val),
                    "is_binary": serialized.is_binary,
                    "is_truncated": serialized.truncated,
                }
            )

    exists = bool(formatted_items) or bool(await client.exists(key))

    return {
        "key": key,
        "exists": exists,
        "items": formatted_items,
        "count": len(formatted_items),
        "start": effective_start,
        "stop": effective_stop,
        "reverse": reverse,
        "is_truncated": truncated,
    }


def register_zset_tools(server: Any, registry: ConnectionRegistry) -> None:
    """将 ZSet 相关工具挂载至 MCP 服务端。

    @param server MCP 服务端实例 (FastMCP / MCPServer)
    @param registry 连接注册中心单例
    """

    @server.tool(name="redis_zset_range")  # type: ignore[untyped-decorator]
    async def _tool_zset_range(
        key: str,
        start: int = 0,
        stop: int = 49,
        reverse: bool = False,
        connection: str | None = None,
        db: int | None = None,
    ) -> dict[str, Any]:
        """安全读取有序集合切片成员与分值，支持排名范围与倒序排序。"""
        return await redis_zset_range(
            registry,
            key=key,
            start=start,
            stop=stop,
            reverse=reverse,
            connection=connection,
            db=db,
        )
