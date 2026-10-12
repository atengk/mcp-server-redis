"""
实例信息检视工具。

提供连接列表查阅与连接配置脱敏展示能力。

@author Ateng
@since 2026-10-04
"""

import logging
from typing import Any

from mcp_server_redis.core.connection import ConnectionRegistry

logger = logging.getLogger(__name__)


async def redis_list_connections(registry: ConnectionRegistry) -> dict[str, Any]:
    """查看所有已配置的 Redis 连接别名、脱敏 URL 及默认连接标识。

    @param registry 连接注册中心实例
    @return 包含连接列表与默认连接信息的字典
    """
    profiles = registry.list_profiles()
    connections: list[dict[str, Any]] = []

    for profile in profiles:
        connections.append(
            {
                "alias": profile.alias,
                "url": profile.masked_url,
                "db": profile.db,
                "readonly": profile.readonly,
                "description": profile.description,
                "is_default": (profile.alias == registry.default_alias),
            }
        )

    return {
        "default": registry.default_alias,
        "total": len(connections),
        "connections": connections,
    }


def register_instance_tools(server: Any, registry: ConnectionRegistry) -> None:
    """将连接实例查阅工具挂载注册至 MCP 服务端。

    @param server MCP 服务端实例 (FastMCP / MCPServer)
    @param registry 连接注册中心单例
    """

    @server.tool(name="redis_list_connections")  # type: ignore[untyped-decorator]
    async def _tool_list_connections() -> dict[str, Any]:
        """查看当前所有可用的 Redis 连接别名、脱敏连接信息与默认连接。"""
        return await redis_list_connections(registry)
