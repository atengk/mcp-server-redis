"""MCP 只读快照资源模块。

挂载实例运行指标快照 (redis://{connection}/info) 与慢查询日志快照 (redis://{connection}/slowlog)。

@author Ateng
@since 2026-10-14
"""

import json
import logging
import re
from typing import Any

import redis.exceptions

from mcp_server_redis.core.connection import ConnectionRegistry

logger = logging.getLogger(__name__)

# IPv4 地址末段屏蔽正则
_IPV4_PATTERN = re.compile(r"(\b\d{1,3}\.\d{1,3}\.\d{1,3}\.)\d{1,3}\b")


def mask_ip_address(text: str) -> str:
    """对文本中的 IPv4 地址末段进行脱敏掩码（如 192.168.1.100 -> 192.168.1.***）。

    @param text 原始字符串
    @return 脱敏后的字符串
    """
    if not text:
        return ""
    return _IPV4_PATTERN.sub(r"\g<1>***", text)


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


async def _get_formatted_client_list(client: Any) -> str:
    """提取当前连接的客户端列表并对 IP 末段脱敏，序列化为标准 JSON 字符串。

    @param client Redis 客户端
    @return 格式化后的 JSON 字符串
    """
    try:
        clients = await client.client_list()
    except (redis.exceptions.RedisError, OSError) as exc:
        logger.warning("读取 Redis 客户端连接列表失败: %s", exc)
        return json.dumps({"error": str(exc)}, ensure_ascii=False)

    clean_clients: list[dict[str, Any]] = []
    for entry in clients:
        if isinstance(entry, dict):
            clean_item: dict[str, Any] = {}
            for k, v in entry.items():
                str_key = k.decode("utf-8", errors="replace") if isinstance(k, bytes) else str(k)
                str_val = v.decode("utf-8", errors="replace") if isinstance(v, bytes) else str(v)
                # 对包含 IP 地址的字段（尤其是 addr）进行脱敏掩码
                if str_key == "addr" or "." in str_val:
                    str_val = mask_ip_address(str_val)
                clean_item[str_key] = str_val
            clean_clients.append(clean_item)
        else:
            clean_clients.append({"raw": mask_ip_address(str(entry))})

    return json.dumps(clean_clients, indent=2, ensure_ascii=False)


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

    @server.resource(
        "redis://{connection}/clients",
        mime_type="application/json",
        description="指定连接别名的 Redis 活跃客户端连接列表快照（IP 末段已脱敏，JSON 格式）",
    )  # type: ignore[untyped-decorator]
    async def _resource_connection_clients(connection: str) -> str:
        client = registry.get_client(alias=connection)
        return await _get_formatted_client_list(client)

    @server.resource(
        "redis://clients",
        mime_type="application/json",
        description="默认 Redis 连接实例的活跃客户端连接列表快照（IP 末段已脱敏，JSON 格式）",
    )  # type: ignore[untyped-decorator]
    async def _resource_default_clients() -> str:
        client = registry.get_client(alias=None)
        return await _get_formatted_client_list(client)
