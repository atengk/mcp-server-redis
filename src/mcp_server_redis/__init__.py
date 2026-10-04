"""
mcp-server-redis 核心包入口。

@author Ateng
@since 2026-10-04
"""

from mcp_server_redis.server import SERVER_VERSION, create_app, main

__version__ = SERVER_VERSION

__all__ = ["SERVER_VERSION", "__version__", "create_app", "main"]

