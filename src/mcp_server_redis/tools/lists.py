"""
List 列表安全切片读取工具。

提供基于 LRANGE 的列表分页读取，强制限制切片跨度上限（stop - start <= 100），杜绝全量拉取 OOM。

@author Ateng
@since 2026-10-04
"""

import logging
from typing import Any, Final

import redis.exceptions

from mcp_server_redis.core.connection import ConnectionRegistry
from mcp_server_redis.core.serializer import SafeSerializer

logger = logging.getLogger(__name__)

# 列表单次切片最大跨度硬上限（个）
MAX_LIST_SPAN: Final[int] = 100


async def redis_list_range(
    registry: ConnectionRegistry,
    key: str,
    start: int = 0,
    stop: int = 49,
    connection: str | None = None,
    db: int | None = None,
) -> dict[str, Any]:
    """安全分页读取 List 列表切片元素。

    强制对请求跨度进行安全收敛（单次最多 100 个元素），支持负数索引标准化转换。
    每个列表元素均经过自适应序列化（支持 JSON 智能解析与 Base64 二进制转码）。

    @param registry 连接注册中心实例
    @param key 目标列表键名
    @param start 起始偏移量（从 0 开始，支持负数索引）
    @param stop 结束偏移量（闭区间，支持负数索引）
    @param connection 目标连接别名（可选，缺省为默认连接）
    @param db 目标数据库编号（可选，0~15）
    @return 包含切片元素列表、实际条数及截断状态的字典
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

    # 1. 负数索引或超量跨度标准化防御
    effective_start = start
    effective_stop = stop
    truncated = False
    message = "操作成功"

    # 若包含负数索引，先探查列表总长度以精确计算跨度
    if start < 0 or stop < 0:
        try:
            llen = await client.llen(key)
        except redis.exceptions.ResponseError as exc:
            if "WRONGTYPE" in str(exc):
                logger.warning("对非 List 类型键 '%s' 执行 LLEN: %s", key, exc)
                return {
                    "key": key,
                    "exists": True,
                    "items": [],
                    "count": 0,
                    "is_truncated": False,
                    "error": f"键类型不匹配: {exc}",
                }
            raise

        if llen == 0:
            return {
                "key": key,
                "exists": False,
                "items": [],
                "count": 0,
                "is_truncated": False,
            }

        norm_start = start if start >= 0 else max(0, llen + start)
        norm_stop = stop if stop >= 0 else max(0, llen + stop)
        requested_span = norm_stop - norm_start + 1

        if requested_span > MAX_LIST_SPAN:
            effective_start = norm_start
            effective_stop = norm_start + MAX_LIST_SPAN - 1
            truncated = True
            message = (
                f"请求跨度 ({requested_span}) 超出上限 ({MAX_LIST_SPAN})，已自动收敛截断。"
            )
        else:
            effective_start = norm_start
            effective_stop = norm_stop
    else:
        requested_span = stop - start + 1
        if requested_span > MAX_LIST_SPAN:
            effective_stop = start + MAX_LIST_SPAN - 1
            truncated = True
            message = (
                f"请求跨度 ({requested_span}) 超出上限 ({MAX_LIST_SPAN})，已自动收敛截断。"
            )

    # 2. 调用底层 LRANGE 获取切片
    try:
        raw_items = await client.lrange(key, effective_start, effective_stop)
    except redis.exceptions.ResponseError as exc:
        if "WRONGTYPE" in str(exc):
            logger.warning("对非 List 类型键 '%s' 执行 LRANGE: %s", key, exc)
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
    for item in raw_items:
        serialized = SafeSerializer.serialize_value(item)
        formatted_items.append(serialized.to_item_dict())

    exists = bool(formatted_items) or bool(await client.exists(key))

    return {
        "key": key,
        "exists": exists,
        "items": formatted_items,
        "count": len(formatted_items),
        "start": effective_start,
        "stop": effective_stop,
        "is_truncated": truncated,
        "message": message,
    }


def register_list_tools(server: Any, registry: ConnectionRegistry) -> None:
    """将 List 相关工具挂载至 MCP 服务端。

    @param server MCP 服务端实例 (FastMCP / MCPServer)
    @param registry 连接注册中心单例
    """

    @server.tool(name="redis_list_range")  # type: ignore[untyped-decorator]
    async def _tool_list_range(
        key: str,
        start: int = 0,
        stop: int = 49,
        connection: str | None = None,
        db: int | None = None,
    ) -> dict[str, Any]:
        """安全切片读取 List 列表元素，自动限制跨度不超过 100 条。"""
        return await redis_list_range(
            registry,
            key=key,
            start=start,
            stop=stop,
            connection=connection,
            db=db,
        )
