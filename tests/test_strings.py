"""
字符串读写、TTL 设置与二次确认删除门禁契约测试。

@author Ateng
@since 2026-10-04
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import redis.exceptions

from mcp_server_redis.core.connection import ConnectionProfile, ConnectionRegistry
from mcp_server_redis.core.guard import (
    ReadOnlyConnectionError,
    ReadOnlyModeError,
    SecurityGuard,
)
from mcp_server_redis.tools.strings import (
    redis_delete_keys,
    redis_expire_key,
    redis_get_string,
    redis_set_string,
    register_string_tools,
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
    registry.register(
        ConnectionProfile(
            alias="prod_ro",
            url="redis://prod.internal:6379/0",
            readonly=True,
            db=0,
        )
    )
    return registry


@pytest.fixture
def write_guard() -> SecurityGuard:
    """提供已开启写入权限的安全守卫。"""
    return SecurityGuard(allow_write=True)


@pytest.fixture
def readonly_guard() -> SecurityGuard:
    """提供只读模式的安全守卫。"""
    return SecurityGuard(allow_write=False)


# --- 1. redis_get_string 测试 ---


@pytest.mark.asyncio
async def test_redis_get_string_plain_text(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证读取普通非 JSON 纯文本字符串。"""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value="hello world")

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res = await redis_get_string(sample_registry, key="greeting", parse_json=True)

        assert res["key"] == "greeting"
        assert res["exists"] is True
        assert res["value"] == "hello world"
        assert res["json_data"] is None
        assert res["is_binary"] is False
        assert res["is_truncated"] is False
        assert res["total_length"] == 11


@pytest.mark.asyncio
async def test_redis_get_string_wrongtype_error(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证对非 String 类型键（如 Hash/List）执行读取时优雅返回类型不匹配信息。"""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(
        side_effect=redis.exceptions.ResponseError(
            "WRONGTYPE Operation against a key holding the wrong kind of value"
        )
    )

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res = await redis_get_string(sample_registry, key="my_hash")

        assert res["key"] == "my_hash"
        assert res["exists"] is True
        assert res["value"] is None
        assert "键类型不匹配" in res["error"]


@pytest.mark.asyncio
async def test_redis_get_string_json_text(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证读取合法 JSON 文本时，正确解析并在 json_data 中返回结构化数据。"""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=b'{"user": "alice", "age": 30, "active": true}')

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res = await redis_get_string(sample_registry, key="user:alice", parse_json=True)

        assert res["key"] == "user:alice"
        assert res["exists"] is True
        assert res["is_binary"] is False
        assert res["json_data"] == {"user": "alice", "age": 30, "active": True}
        assert '{"user": "alice"' in res["value"]
        assert res["is_truncated"] is False
        mock_client.get.assert_called_once_with("user:alice")


@pytest.mark.asyncio
async def test_redis_get_string_binary_data(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证读取非 UTF-8 二进制数据时，自动转为 Base64 编码并标记 is_binary 为 True。"""
    mock_client = AsyncMock()
    # 构造非法 UTF-8 字节串
    mock_client.get = AsyncMock(return_value=b"\x00\xff\xfe\xfd\x80")

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res = await redis_get_string(sample_registry, key="bin:data")

        assert res["key"] == "bin:data"
        assert res["exists"] is True
        assert res["is_binary"] is True
        assert res["json_data"] is None
        assert isinstance(res["value"], str)
        assert res["is_truncated"] is False


@pytest.mark.asyncio
async def test_redis_get_string_nonexistent_and_empty(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证读取不存在的键及空键名时，返回标准结构。"""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=None)

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        # 1. 不存在的键
        res_none = await redis_get_string(sample_registry, key="unknown:key")
        assert res_none["key"] == "unknown:key"
        assert res_none["exists"] is False
        assert res_none["value"] is None
        assert res_none["json_data"] is None

        # 2. 空键名
        res_empty = await redis_get_string(sample_registry, key="")
        assert res_empty["key"] == ""
        assert res_empty["exists"] is False
        assert res_empty["value"] is None


@pytest.mark.asyncio
async def test_redis_get_string_truncation(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证长文本被安全截断并正确标记 is_truncated。"""
    mock_client = AsyncMock()
    # 返回超长文本
    mock_client.get = AsyncMock(return_value="A" * 5000)

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res = await redis_get_string(
            sample_registry,
            key="long:text",
            max_length=100,
        )

        assert res["exists"] is True
        assert res["is_truncated"] is True
        assert res["total_length"] == 5000
        assert len(res["value"]) < 5000


# --- 2. redis_set_string 测试 ---


@pytest.mark.asyncio
async def test_redis_set_string_write_gate_blocked(
    sample_registry: ConnectionRegistry,
    readonly_guard: SecurityGuard,
    write_guard: SecurityGuard,
) -> None:
    """验证在未授权写入或针对只读连接时，设置字符串被安全阻断。"""
    # 1. 全局未开启 --allow-write
    with pytest.raises(ReadOnlyModeError, match="只读保护模式"):
        await redis_set_string(
            sample_registry,
            key="test:k",
            value="v",
            connection="local",
            guard=readonly_guard,
        )

    # 2. 目标连接为 readonly: true，即使开启 --allow-write 也阻断
    with pytest.raises(ReadOnlyConnectionError, match="只读保护"):
        await redis_set_string(
            sample_registry,
            key="test:k",
            value="v",
            connection="prod_ro",
            guard=write_guard,
        )


@pytest.mark.asyncio
async def test_redis_set_string_success_with_options(
    sample_registry: ConnectionRegistry,
    write_guard: SecurityGuard,
) -> None:
    """验证授权模式下成功设置字符串并支持 ex 和 nx 选项。"""
    mock_client = AsyncMock()
    mock_client.set = AsyncMock(return_value=True)

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        # 1. 标准设置带 ex 与 nx
        res = await redis_set_string(
            sample_registry,
            key="cache:lock",
            value="token123",
            ex=60,
            nx=True,
            guard=write_guard,
        )

        assert res["key"] == "cache:lock"
        assert res["success"] is True
        assert res["action"] == "set"
        assert res["ex"] == 60
        assert res["nx"] is True
        mock_client.set.assert_called_once_with("cache:lock", "token123", ex=60, nx=True)

        # 2. nx 冲突导致写入未生效
        mock_client.set = AsyncMock(return_value=None)
        res_nx_fail = await redis_set_string(
            sample_registry,
            key="cache:lock",
            value="token456",
            nx=True,
            guard=write_guard,
        )
        assert res_nx_fail["success"] is False
        assert res_nx_fail["action"] == "none"


@pytest.mark.asyncio
async def test_redis_set_string_invalid_params(
    sample_registry: ConnectionRegistry,
    write_guard: SecurityGuard,
) -> None:
    """验证传入非法参数时抛出 ValueError。"""
    with pytest.raises(ValueError, match="键名不能为空"):
        await redis_set_string(sample_registry, key="", value="val", guard=write_guard)

    with pytest.raises(ValueError, match="ex 必须大于 0"):
        await redis_set_string(
            sample_registry, key="k", value="v", ex=0, guard=write_guard
        )


# --- 3. redis_expire_key 测试 ---


@pytest.mark.asyncio
async def test_redis_expire_key_scenarios(
    sample_registry: ConnectionRegistry,
    write_guard: SecurityGuard,
    readonly_guard: SecurityGuard,
) -> None:
    """验证设置键过期时间的不同场景及权限门禁。"""
    # 1. 只读阻断
    with pytest.raises(ReadOnlyModeError):
        await redis_expire_key(
            sample_registry,
            key="temp:key",
            seconds=120,
            guard=readonly_guard,
        )

    # 2. 成功设置
    mock_client = AsyncMock()
    mock_client.expire = AsyncMock(return_value=1)
    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res = await redis_expire_key(
            sample_registry,
            key="temp:key",
            seconds=120,
            guard=write_guard,
        )
        assert res["key"] == "temp:key"
        assert res["seconds"] == 120
        assert res["success"] is True
        mock_client.expire.assert_called_once_with("temp:key", 120)

    # 3. 键不存在导致设置失败
    mock_client.expire = AsyncMock(return_value=0)
    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res_fail = await redis_expire_key(
            sample_registry,
            key="nonexistent",
            seconds=30,
            guard=write_guard,
        )
        assert res_fail["success"] is False

    # 4. seconds <= 0 拦截，防御绕过确认门禁的旁路删除
    with pytest.raises(ValueError, match="seconds 必须大于 0"):
        await redis_expire_key(
            sample_registry,
            key="k",
            seconds=0,
            guard=write_guard,
        )

    with pytest.raises(ValueError, match="seconds 必须大于 0"):
        await redis_expire_key(
            sample_registry,
            key="k",
            seconds=-5,
            guard=write_guard,
        )


# --- 4. redis_delete_keys 二次确认门禁测试 ---


@pytest.mark.asyncio
async def test_redis_delete_keys_confirm_false_rejects_deletion(
    sample_registry: ConnectionRegistry,
    write_guard: SecurityGuard,
) -> None:
    """验证 confirm=False 时拒绝执行物理删除，仅返回存在状态探测与确认提示。"""
    mock_client = AsyncMock()
    mock_pipe = AsyncMock()
    mock_pipe.exists = MagicMock()
    # pipeline 执行结果：第一个键存在 (1)，第二个不存在 (0)
    mock_pipe.execute = AsyncMock(return_value=[1, 0])
    mock_client.pipeline = MagicMock(return_value=mock_pipe)
    mock_client.delete = AsyncMock()

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res = await redis_delete_keys(
            sample_registry,
            keys=["key:1", "key:2"],
            confirm=False,
            guard=write_guard,
        )

        assert res["status"] == "confirmation_required"
        assert res["confirmed"] is False
        assert res["deleted_count"] == 0
        assert res["existing_count"] == 1
        assert res["existing_keys"] == ["key:1"]
        assert "confirm=True" in res["message"]
        # 验证绝未调用物理删除
        mock_client.delete.assert_not_called()


@pytest.mark.asyncio
async def test_redis_delete_keys_confirm_true_executes_deletion(
    sample_registry: ConnectionRegistry,
    write_guard: SecurityGuard,
) -> None:
    """验证 confirm=True 且具备写权限时，执行物理删除并返回实际删除数。"""
    mock_client = AsyncMock()
    mock_client.delete = AsyncMock(return_value=2)

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res = await redis_delete_keys(
            sample_registry,
            keys=["key:1", "key:2"],
            confirm=True,
            guard=write_guard,
        )

        assert res["status"] == "success"
        assert res["confirmed"] is True
        assert res["deleted_count"] == 2
        assert res["keys"] == ["key:1", "key:2"]
        mock_client.delete.assert_called_once_with("key:1", "key:2")


@pytest.mark.asyncio
async def test_redis_delete_keys_single_key_and_nonexistent(
    sample_registry: ConnectionRegistry,
    write_guard: SecurityGuard,
) -> None:
    """验证支持单键字符串入参，且删除不存在键时返回 deleted_count 为 0。"""
    mock_client = AsyncMock()
    mock_client.delete = AsyncMock(return_value=0)

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        # 1. 单键字符串传参且不存在
        res = await redis_delete_keys(
            sample_registry,
            keys="single:nonexistent",
            confirm=True,
            guard=write_guard,
        )

        assert res["status"] == "success"
        assert res["confirmed"] is True
        assert res["deleted_count"] == 0
        assert res["keys"] == ["single:nonexistent"]
        mock_client.delete.assert_called_once_with("single:nonexistent")


@pytest.mark.asyncio
async def test_redis_delete_keys_requires_write_permission(
    sample_registry: ConnectionRegistry,
    readonly_guard: SecurityGuard,
) -> None:
    """验证即使传入 confirm=True，只读保护依然阻断删除操作。"""
    with pytest.raises(ReadOnlyModeError, match="只读保护模式"):
        await redis_delete_keys(
            sample_registry,
            keys=["key:1"],
            confirm=True,
            guard=readonly_guard,
        )


@pytest.mark.asyncio
async def test_register_string_tools_with_server(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证字符串与删除工具成功挂载至 MCP 服务端。"""
    from mcp.server import MCPServer

    server = MCPServer("test-server")
    register_string_tools(server, sample_registry)

    tools = await server.list_tools()
    tool_names = [t.name for t in tools]
    assert "redis_get_string" in tool_names
    assert "redis_set_string" in tool_names
    assert "redis_expire_key" in tool_names
    assert "redis_delete_keys" in tool_names
