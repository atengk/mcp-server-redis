"""
MCP 工具层包。

@author Ateng
@since 2026-10-04
"""

from mcp_server_redis.tools.admin import (
    redis_client_list,
    redis_dbsize,
    redis_get_slowlog,
    redis_info,
    register_admin_tools,
)
from mcp_server_redis.tools.hashes import (
    redis_hash_get,
    register_hash_tools,
)
from mcp_server_redis.tools.instances import (
    redis_list_connections,
    redis_ping,
    register_instance_tools,
)
from mcp_server_redis.tools.keys import (
    redis_key_inspect,
    redis_key_ttl,
    redis_scan_keys,
    register_key_tools,
)
from mcp_server_redis.tools.lists import (
    redis_list_range,
    register_list_tools,
)
from mcp_server_redis.tools.sets import (
    redis_set_members,
    register_set_tools,
)
from mcp_server_redis.tools.streams import (
    redis_stream_read,
    register_stream_tools,
)
from mcp_server_redis.tools.strings import (
    redis_delete_keys,
    redis_expire_key,
    redis_get_string,
    redis_set_string,
    register_string_tools,
)
from mcp_server_redis.tools.zsets import (
    redis_zset_range,
    register_zset_tools,
)

__all__ = [
    "redis_client_list",
    "redis_dbsize",
    "redis_delete_keys",
    "redis_expire_key",
    "redis_get_slowlog",
    "redis_get_string",
    "redis_hash_get",
    "redis_info",
    "redis_key_inspect",
    "redis_key_ttl",
    "redis_list_connections",
    "redis_list_range",
    "redis_ping",
    "redis_scan_keys",
    "redis_set_members",
    "redis_set_string",
    "redis_stream_read",
    "redis_zset_range",
    "register_admin_tools",
    "register_hash_tools",
    "register_instance_tools",
    "register_key_tools",
    "register_list_tools",
    "register_set_tools",
    "register_stream_tools",
    "register_string_tools",
    "register_zset_tools",
]
