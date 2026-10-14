"""MCP 只读快照资源模块。

挂载实例运行指标快照 (redis://{connection}/info) 与慢查询日志快照 (redis://{connection}/slowlog)。

@author Ateng
@since 2026-10-14
"""

import json
import logging
from typing import Any

import redis.exceptions

from mcp_server_redis.core.connection import ConnectionRegistry

logger = logging.getLogger(__name__)


async def _get_formatted_slowlog(client: Any) -> str:
    """提取慢查询日志并安全序列化为标准 JSON 字符串。

    @param client Redis 客户端
    @return 格式化后的 JSON 字符串
    """
    try:
        slowlogs = await client.slowlog_get(10)
    except (redis.exceptions.RedisError, OSError) as exc:
        logger.warning("读取 Redis 慢日志失败: %s", exc)
        return json.dumps({"error": str(exc)}, ensure_ascii=False)

    clean_entries: list[Any] = []
    for entry in slowlogs:
        if isinstance(entry, dict):
            clean_item: dict[str, Any] = {}
            for k, v in entry.items():
                if isinstance(v, bytes):
                    clean_item[k] = v.decode("utf-8", errors="replace")
                elif isinstance(v, list):
                    clean_item[k] = [
                        sub.decode("utf-8", errors="replace")
                        if isinstance(sub, bytes)
                        else str(sub)
                        for sub in v
                    ]
                else:
                    clean_item[k] = v
            clean_entries.append(clean_item)
        else:
            clean_entries.append(str(entry))

    return json.dumps(clean_entries, indent=2, ensure_ascii=False)


def register_resources(server: Any, registry: ConnectionRegistry) -> None:
    """向 FastMCP 服务端挂载核心只读快照资源。

    @param server FastMCP 服务端实例
    @param registry 连接注册中心单例
    """

    @server.resource(
        "redis://{connection}/info",
        mime_type="application/json",
        description="指定连接别名的 Redis 实例综合健康与关键运行指标快照（JSON 格式）",
    )  # type: ignore[untyped-decorator]
    async def _resource_connection_info(connection: str) -> str:
        client = registry.get_client(alias=connection)
        info_data = await client.info()
        return json.dumps(info_data, indent=2, ensure_ascii=False)

    @server.resource(
        "redis://info",
        mime_type="application/json",
        description="默认 Redis 连接实例的综合健康与关键运行指标快照（JSON 格式）",
    )  # type: ignore[untyped-decorator]
    async def _resource_default_info() -> str:
        client = registry.get_client(alias=None)
        info_data = await client.info()
        return json.dumps(info_data, indent=2, ensure_ascii=False)

    @server.resource(
        "redis://{connection}/slowlog",
        mime_type="application/json",
        description="指定连接别名的 Redis 最近 10 条慢查询日志快照（JSON 格式）",
    )  # type: ignore[untyped-decorator]
    async def _resource_connection_slowlog(connection: str) -> str:
        client = registry.get_client(alias=connection)
        return await _get_formatted_slowlog(client)

    @server.resource(
        "redis://slowlog",
        mime_type="application/json",
        description="默认 Redis 连接实例的最近 10 条慢查询日志快照（JSON 格式）",
    )  # type: ignore[untyped-decorator]
    async def _resource_default_slowlog() -> str:
        client = registry.get_client(alias=None)
        return await _get_formatted_slowlog(client)
