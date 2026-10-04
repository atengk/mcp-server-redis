"""
实例与连接探活工具契约测试。

@author Ateng
@since 2026-10-04
"""

from unittest.mock import AsyncMock, patch

import pytest
import redis.exceptions

from mcp_server_redis.core.connection import (
    ConnectionProfile,
    ConnectionRegistry,
    InvalidDatabaseError,
)
from mcp_server_redis.tools.instances import (
    redis_list_connections,
    redis_ping,
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
async def test_redis_ping_success(sample_registry: ConnectionRegistry) -> None:
    """验证 redis_ping 成功时的响应结构与延迟度量。"""
    mock_client = AsyncMock()
    mock_client.ping = AsyncMock(return_value=True)

    with patch.object(sample_registry, "get_client", return_value=mock_client) as mock_get_client:
        res = await redis_ping(sample_registry, connection="local", db=0)

        mock_get_client.assert_called_once_with(alias="local", db=0)
        assert res["status"] == "ok"
        assert res["connection"] == "local"
        assert res["db"] == 0
        assert res["response"] == "PONG"
        assert isinstance(res["latency_ms"], float)
        assert res["latency_ms"] >= 0.0


@pytest.mark.asyncio
async def test_redis_ping_with_custom_db(sample_registry: ConnectionRegistry) -> None:
    """验证 redis_ping 传递自定义 db 时无状态路由到目标库。"""
    mock_client = AsyncMock()
    mock_client.ping = AsyncMock(return_value=True)

    with patch.object(sample_registry, "get_client", return_value=mock_client) as mock_get_client:
        res = await redis_ping(sample_registry, db=5)

        mock_get_client.assert_called_once_with(alias=None, db=5)
        assert res["status"] == "ok"
        assert res["connection"] == "local"  # 默认连接
        assert res["db"] == 5


@pytest.mark.asyncio
async def test_redis_ping_connection_failure(sample_registry: ConnectionRegistry) -> None:
    """验证目标 Redis 实例不可达时返回结构化错误信息而非崩溃。"""
    mock_client = AsyncMock()
    mock_client.ping = AsyncMock(
        side_effect=redis.exceptions.ConnectionError("Connection refused")
    )

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res = await redis_ping(sample_registry, connection="staging")

        assert res["status"] == "error"
        assert res["connection"] == "staging"
        assert res["db"] == 1
        assert "Connection refused" in res["error"]


@pytest.mark.asyncio
async def test_redis_ping_invalid_db_raises(sample_registry: ConnectionRegistry) -> None:
    """验证传入非法数据库编号时抛出 InvalidDatabaseError。"""
    with pytest.raises(InvalidDatabaseError):
        await redis_ping(sample_registry, db=99)


@pytest.mark.asyncio
async def test_register_instance_tools_with_server(sample_registry: ConnectionRegistry) -> None:
    """验证工具能够正确注册至 MCP 服务端。"""
    from mcp.server import MCPServer

    from mcp_server_redis.tools.instances import register_instance_tools

    server = MCPServer("test-redis-server")
    register_instance_tools(server, sample_registry)

    tools = await server.list_tools()
    tool_names = [t.name for t in tools]
    assert "redis_list_connections" in tool_names
    assert "redis_ping" in tool_names


@pytest.mark.asyncio
async def test_redis_ping_unknown_connection_returns_error(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证指定未知连接别名时优雅返回错误结构而非崩溃。"""
    res = await redis_ping(sample_registry, connection="non_existent_alias")
    assert res["status"] == "error"
    assert res["connection"] == "non_existent_alias"
    assert "未找到连接别名" in res["error"]

