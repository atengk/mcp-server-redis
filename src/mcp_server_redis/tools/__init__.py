"""
MCP 工具层包。

提供 v2.0 混合命令网关核心 4 工具：
- redis_command: 原生 Redis 命令执行网关
- redis_list_connections: 连接实例清单与配置检视
- redis_scan_keys: 聚合键扫描器
- redis_key_inspect: 单键多维元数据诊断

@author Ateng
@since 2026-10-04
"""

from mcp_server_redis.tools.command import (
    redis_command,
    register_command_tools,
)
from mcp_server_redis.tools.instances import (
    redis_list_connections,
    register_instance_tools,
)
from mcp_server_redis.tools.keys import (
    redis_key_inspect,
    redis_scan_keys,
    register_key_tools,
)

__all__ = [
    "redis_command",
    "redis_key_inspect",
    "redis_list_connections",
    "redis_scan_keys",
    "register_command_tools",
    "register_instance_tools",
    "register_key_tools",
]
