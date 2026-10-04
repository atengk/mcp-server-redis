"""
运维性能诊断工具（redis_info, redis_dbsize, redis_get_slowlog, redis_client_list）契约测试。

@author Ateng
@since 2026-10-04
"""

from unittest.mock import AsyncMock, patch

import pytest

from mcp_server_redis.core.connection import ConnectionProfile, ConnectionRegistry
from mcp_server_redis.tools.admin import (
    redis_client_list,
    redis_dbsize,
    redis_get_slowlog,
    redis_info,
    register_admin_tools,
)


@pytest.fixture
def sample_registry() -> ConnectionRegistry:
    """提供测试用连接注册中心。"""
    registry = ConnectionRegistry(default_alias="local")
    registry.register(
        ConnectionProfile(
            alias="local",
            url="redis://localhost:6379/0",
            readonly=False,
            db=0,
        ),
        is_default=True,
    )
    return registry


# --- 1. redis_info 测试 ---


@pytest.mark.asyncio
async def test_redis_info_default_and_section(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证获取系统 INFO 指标，支持 section 过滤与别名路由。"""
    mock_client = AsyncMock()
    mock_client.info = AsyncMock(
        return_value={
            "redis_version": "7.2.4",
            "connected_clients": 5,
            "used_memory_human": "2.4M",
        }
    )

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        # 1. 默认无 section
        res = await redis_info(sample_registry)
        assert res["connection"] == "local"
        assert res["section"] is None
        assert res["info"]["redis_version"] == "7.2.4"
        mock_client.info.assert_called_once_with(section=None)

        # 2. 指定 section="memory"
        mock_client.info.reset_mock()
        res_mem = await redis_info(sample_registry, section="memory")
        assert res_mem["section"] == "memory"
        mock_client.info.assert_called_once_with(section="memory")


# --- 2. redis_dbsize 测试 ---


@pytest.mark.asyncio
async def test_redis_dbsize(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证查询当前库键总数统计。"""
    mock_client = AsyncMock()
    mock_client.dbsize = AsyncMock(return_value=1280)

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res = await redis_dbsize(sample_registry, db=1)

        assert res["connection"] == "local"
        assert res["db"] == 1
        assert res["dbsize"] == 1280
        mock_client.dbsize.assert_called_once()


# --- 3. redis_get_slowlog 测试 ---


@pytest.mark.asyncio
async def test_redis_get_slowlog_formatting_and_limit(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证格式化提取慢查询日志列表，包含 ID、耗时与命令参数。"""
    mock_client = AsyncMock()
    # redis-py slowlog_get 返回结构为字典列表
    mock_client.slowlog_get = AsyncMock(
        return_value=[
            {
                "id": 1,
                "start_time": 1712188800,
                "duration": 15000,  # 微秒
                "command": [b"KEYS", b"user:*"],
            },
            {
                "id": 2,
                "start_time": 1712188810,
                "duration": 8500,
                "command": "LRANGE huge_list 0 1000",
            },
        ]
    )

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res = await redis_get_slowlog(sample_registry, count=10)

        assert res["connection"] == "local"
        assert res["count"] == 2
        entries = res["entries"]
        assert len(entries) == 2
        assert entries[0]["id"] == 1
        assert entries[0]["duration_us"] == 15000
        assert entries[0]["duration_ms"] == 15.0
        assert "KEYS user:*" in entries[0]["command"]
        assert entries[1]["id"] == 2
        mock_client.slowlog_get.assert_called_once_with(10)


# --- 4. redis_client_list 测试 ---


@pytest.mark.asyncio
async def test_redis_client_list_formatting_and_truncation(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证检视连接客户端列表，过滤诊断核心字段并支持数量截断。"""
    mock_client = AsyncMock()
    # 模拟 30 个客户端连接
    clients_data = [
        {
            "id": f"{i}",
            "addr": f"127.0.0.1:{50000 + i}",
            "name": f"client_{i}",
            "age": 100 + i,
            "idle": i,
            "flags": "N",
            "db": 0,
            "cmd": "client",
        }
        for i in range(30)
    ]
    mock_client.client_list = AsyncMock(return_value=clients_data)

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        # 限制最多获取 10 条
        res = await redis_client_list(sample_registry, limit=10)

        assert res["connection"] == "local"
        assert res["total_clients"] == 30
        assert res["returned_clients"] == 10
        assert res["is_truncated"] is True
        assert len(res["clients"]) == 10
        assert res["clients"][0]["id"] == "0"
        assert res["clients"][0]["addr"] == "127.0.0.1:50000"


@pytest.mark.asyncio
async def test_redis_get_slowlog_oversized_command_truncation(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证慢查询长命令被安全截断并附带截断标记。"""
    mock_client = AsyncMock()
    oversized_cmd = "MGET " + " ".join([f"k_{i}" for i in range(200)])
    mock_client.slowlog_get = AsyncMock(
        return_value=[
            {
                "id": 100,
                "start_time": 1712188820,
                "duration": 50000,
                "command": oversized_cmd,
            }
        ]
    )

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res = await redis_get_slowlog(sample_registry, count=5)
        entries = res["entries"]
        assert len(entries) == 1
        assert "[截断]" in entries[0]["command"]


@pytest.mark.asyncio
async def test_redis_client_list_null_safety_and_missing_fields(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证客户端列表处理缺失字段或 None 值时的空安全防御。"""
    mock_client = AsyncMock()
    mock_client.client_list = AsyncMock(
        return_value=[
            {
                "id": None,
                "addr": None,
                "name": None,
                "age": None,
                "idle": "",
                "flags": None,
                "db": None,
                "cmd": None,
            }
        ]
    )

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res = await redis_client_list(sample_registry, limit=5)
        assert res["total_clients"] == 1
        c = res["clients"][0]
        assert c["id"] == ""
        assert c["age"] == 0
        assert c["idle"] == 0
        assert c["db"] == 0
        assert c["cmd"] == ""


# --- 5. 工具注册测试 ---


@pytest.mark.asyncio
async def test_register_admin_tools_with_server(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证运维诊断工具成功挂载至 MCP 服务端。"""
    from mcp.server import MCPServer

    server = MCPServer("test-server")
    register_admin_tools(server, sample_registry)

    tools = await server.list_tools()
    tool_names = [t.name for t in tools]
    assert "redis_info" in tool_names
    assert "redis_dbsize" in tool_names
    assert "redis_get_slowlog" in tool_names
    assert "redis_client_list" in tool_names
