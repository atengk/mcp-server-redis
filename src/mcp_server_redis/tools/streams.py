"""
Stream 消息流逆序切片读取工具。

提供基于 XREVRANGE 的最新消息条目逆序采样，强制限制采样数量，防止海量事件流撑爆上下文。

@author Ateng
@since 2026-10-04
"""

import logging
from typing import Any, Final

import redis.exceptions

from mcp_server_redis.core.connection import ConnectionRegistry
from mcp_server_redis.core.serializer import SafeSerializer

logger = logging.getLogger(__name__)

DEFAULT_STREAM_COUNT: Final[int] = 20
MAX_STREAM_COUNT: Final[int] = 100


async def redis_stream_read(
    registry: ConnectionRegistry,
    key: str,
    count: int = DEFAULT_STREAM_COUNT,
    start: str = "+",
    end: str = "-",
    connection: str | None = None,
    db: int | None = None,
) -> dict[str, Any]:
    """使用 XREVRANGE 逆序采样读取 Stream 消息流最新条目。

    适用于事件积压排查与诊断，单次强制限制返回上限（默认 20，硬上限 100 条）。
    自动对消息字段进行自适应安全解码与 JSON 结构化解析。

    @param registry 连接注册中心实例
    @param key 目标 Stream 键名
    @param count 最大采样读取条数（默认 20，硬上限 100）
    @param start 起始消息 ID（默认 '+' 表示最新的一条）
    @param end 结束消息 ID（默认 '-' 表示最早的一条）
    @param connection 目标连接别名（可选，缺省为默认连接）
    @param db 目标数据库编号（可选，0~15）
    @return 包含消息条目列表、条数及截断状态的字典
    """
    if not key:
        return {
            "key": "",
            "exists": False,
            "entries": [],
            "count": 0,
            "is_truncated": False,
        }

    effective_count = min(max(count, 1), MAX_STREAM_COUNT) if count > 0 else DEFAULT_STREAM_COUNT
    client = registry.get_client(alias=connection, db=db)

    try:
        raw_entries = await client.xrevrange(
            key,
            max=start,
            min=end,
            count=effective_count,
        )
    except redis.exceptions.ResponseError as exc:
        if "WRONGTYPE" in str(exc):
            logger.warning("对非 Stream 类型键 '%s' 执行 XREVRANGE: %s", key, exc)
            return {
                "key": key,
                "exists": True,
                "entries": [],
                "count": 0,
                "is_truncated": False,
                "error": f"键类型不匹配: {exc}",
            }
        raise

    if not raw_entries:
        return {
            "key": key,
            "exists": False,
            "entries": [],
            "count": 0,
            "is_truncated": False,
        }

    formatted_entries: list[dict[str, Any]] = []
    for entry in raw_entries:
        if not entry:
            continue
        msg_id_raw, raw_fields = entry
        if not raw_fields or not isinstance(raw_fields, dict):
            continue

        msg_id_str = (
            msg_id_raw.decode("utf-8", errors="replace")
            if isinstance(msg_id_raw, bytes)
            else str(msg_id_raw)
        )
        fields_dict: dict[str, Any] = {}
        for f_raw, v_raw in raw_fields.items():
            f_str = (
                f_raw.decode("utf-8", errors="replace") if isinstance(f_raw, bytes) else str(f_raw)
            )
            serialized = SafeSerializer.serialize_value(v_raw)
            fields_dict[f_str] = serialized.unwrap()

        formatted_entries.append(
            {
                "id": msg_id_str,
                "fields": fields_dict,
            }
        )

    exists = bool(formatted_entries) or bool(await client.exists(key))

    return {
        "key": key,
        "exists": exists,
        "entries": formatted_entries,
        "count": len(formatted_entries),
        "is_truncated": len(formatted_entries) >= effective_count,
    }


def register_stream_tools(server: Any, registry: ConnectionRegistry) -> None:
    """将 Stream 相关工具挂载至 MCP 服务端。

    @param server MCP 服务端实例 (FastMCP / MCPServer)
    @param registry 连接注册中心单例
    """

    @server.tool(name="redis_stream_read")  # type: ignore[untyped-decorator]
    async def _tool_stream_read(
        key: str,
        count: int = DEFAULT_STREAM_COUNT,
        start: str = "+",
        end: str = "-",
        connection: str | None = None,
        db: int | None = None,
    ) -> dict[str, Any]:
        """逆序采样读取 Stream 消息流最新条目，自动解析消息 ID 与键值结构。"""
        return await redis_stream_read(
            registry,
            key=key,
            count=count,
            start=start,
            end=end,
            connection=connection,
            db=db,
        )
