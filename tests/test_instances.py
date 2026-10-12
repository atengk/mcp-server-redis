"""
实例连接检视工具契约测试。

@author Ateng
@since 2026-10-04
"""

import pytest
from mcp.server import MCPServer

from mcp_server_redis.core.connection import (
    ConnectionProfile,
    ConnectionRegistry,
)
from mcp_server_redis.tools.instances import (
    redis_list_connections,
    register_instance_tools,
)


@pytest.fixture
def sample_registry() -> ConnectionRegistry:
    """提供包含多个连接档案的注册中心夹具。"""
    registry = ConnectionRegistry(default_alias="local")
    registry.register(
        ConnectionProfile(
            alias="local",
            url="redis://:secret1@127.0.0.1:6379/0",
            readonly=False,
            description="本地测试库",
            db=0,
        ),
        is_default=True,
    )
    registry.register(
        ConnectionProfile(
            alias="staging",
            url="redis://:secret2@staging.host:6379/1",
            readonly=True,
            description="预发只读库",
            db=1,
        )
    )
    return registry


@pytest.mark.asyncio
async def test_redis_list_connections(sample_registry: ConnectionRegistry) -> None:
    """验证 redis_list_connections 返回完整且脱敏的连接列表契约。"""
    result = await redis_list_connections(sample_registry)

    assert result["default"] == "local"
    assert result["total"] == 2
    connections = result["connections"]
    assert len(connections) == 2

    local = next(c for c in connections if c["alias"] == "local")
    assert local["url"] == "redis://:***@127.0.0.1:6379/0"
    assert local["readonly"] is False
    assert local["is_default"] is True
    assert local["db"] == 0

    staging = next(c for c in connections if c["alias"] == "staging")
    assert staging["url"] == "redis://:***@staging.host:6379/1"
    assert staging["readonly"] is True
    assert staging["is_default"] is False
    assert staging["db"] == 1


@pytest.mark.asyncio
async def test_register_instance_tools_with_server(sample_registry: ConnectionRegistry) -> None:
    """验证工具能够正确注册至 MCP 服务端，且仅注册 redis_list_connections。"""
    server = MCPServer("test-redis-server")
    register_instance_tools(server, sample_registry)

    tools = await server.list_tools()
    tool_names = [t.name for t in tools]
    assert tool_names == ["redis_list_connections"]
