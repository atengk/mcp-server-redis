"""连接实例检视兼容模块。

本模块重定向至 tools.connections 模块以保障向后兼容。

@author Ateng
@since 2026-10-04
"""

from mcp_server_redis.tools.connections import (
    redis_list_connections,
    register_connection_tools,
    register_instance_tools,
)

__all__ = [
    "redis_list_connections",
    "register_connection_tools",
    "register_instance_tools",
]
