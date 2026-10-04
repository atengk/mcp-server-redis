"""
五大复杂集合（Hash、List、Set、ZSet、Stream）安全切片读取工具契约测试。

@author Ateng
@since 2026-10-04
"""

from unittest.mock import AsyncMock, patch

import pytest
import redis.exceptions

from mcp_server_redis.core.connection import ConnectionProfile, ConnectionRegistry
from mcp_server_redis.tools.hashes import redis_hash_get, register_hash_tools
from mcp_server_redis.tools.lists import redis_list_range, register_list_tools
from mcp_server_redis.tools.sets import redis_set_members, register_set_tools
from mcp_server_redis.tools.streams import redis_stream_read, register_stream_tools
from mcp_server_redis.tools.zsets import redis_zset_range, register_zset_tools


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


# --- 1. redis_hash_get 测试 ---


@pytest.mark.asyncio
async def test_redis_hash_get_specified_fields(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证读取 Hash 指定字段列表，支持文本与 JSON 自适应解析。"""
    mock_client = AsyncMock()
    mock_client.hmget = AsyncMock(
        return_value=[
            b'{"theme": "dark", "lang": "zh"}',
            b"alice",
            None,
        ]
    )

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res = await redis_hash_get(
            sample_registry,
            key="user:1001",
            fields=["prefs", "name", "nonexistent"],
        )

        assert res["key"] == "user:1001"
        assert res["exists"] is True
        assert res["count"] == 2  # 过滤 None
        assert res["fields"]["name"] == "alice"
        assert res["fields"]["prefs"]["theme"] == "dark"
        assert "nonexistent" not in res["fields"]
        assert res["is_truncated"] is False
        mock_client.hmget.assert_called_once_with("user:1001", ["prefs", "name", "nonexistent"])


@pytest.mark.asyncio
async def test_redis_hash_get_scan_all_fields_with_truncation(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证未传 fields 时通过 HSCAN 安全采样，并在大 Hash 时强制截断。"""
    mock_client = AsyncMock()
    # 模拟两轮 HSCAN 采样
    batch1 = {f"f{i}".encode(): f"v{i}".encode() for i in range(40)}
    batch2 = {f"f{i}".encode(): f"v{i}".encode() for i in range(40, 80)}
    mock_client.hscan = AsyncMock(
        side_effect=[
            (10, batch1),
            (0, batch2),
        ]
    )

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        # 限制只取 50 个字段
        res = await redis_hash_get(sample_registry, key="big:hash", limit=50)

        assert res["key"] == "big:hash"
        assert res["count"] == 50
        assert len(res["fields"]) == 50
        assert res["is_truncated"] is True


@pytest.mark.asyncio
async def test_redis_hash_get_wrongtype_defense(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证对非 Hash 类型键读取时优雅返回类型不匹配信息。"""
    mock_client = AsyncMock()
    mock_client.hscan = AsyncMock(
        side_effect=redis.exceptions.ResponseError("WRONGTYPE Operation against a key")
    )

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res = await redis_hash_get(sample_registry, key="str:key")
        assert res["exists"] is True
        assert "键类型不匹配" in res["error"]
        assert res["fields"] == {}


# --- 2. redis_list_range 测试 ---


@pytest.mark.asyncio
async def test_redis_list_range_standard(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证分页读取列表元素并正确进行 SafeSerializer 转码。"""
    mock_client = AsyncMock()
    mock_client.lrange = AsyncMock(
        return_value=[
            b"item1",
            b'{"id": 102}',
            b"\x00\xff\xfe",  # 二进制
        ]
    )

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res = await redis_list_range(sample_registry, key="my:list", start=0, stop=2)

        assert res["key"] == "my:list"
        assert res["exists"] is True
        assert res["count"] == 3
        assert res["items"][0]["value"] == "item1"
        assert res["items"][1]["json_data"] == {"id": 102}
        assert res["items"][2]["is_binary"] is True
        assert res["is_truncated"] is False
        mock_client.lrange.assert_called_once_with("my:list", 0, 2)


@pytest.mark.asyncio
async def test_redis_list_range_span_guard_truncation(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证当跨度 stop - start 超过 100 时，自动强制收敛截断并返回保护标记。"""
    mock_client = AsyncMock()
    mock_client.lrange = AsyncMock(return_value=[b"item"] * 100)

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        # 尝试拉取 500 个元素
        res = await redis_list_range(sample_registry, key="huge:list", start=0, stop=499)

        assert res["count"] == 100
        assert res["is_truncated"] is True
        assert "超出上限" in res["message"]
        # 验证底层实际只拉取了 100 个元素 (0 到 99)
        mock_client.lrange.assert_called_once_with("huge:list", 0, 99)


@pytest.mark.asyncio
async def test_redis_list_range_negative_index_handling(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证对包含负数索引（如 start=0, stop=-1）的列表切片进行安全标准化防御。"""
    mock_client = AsyncMock()
    # 模拟大列表长度为 1000
    mock_client.llen = AsyncMock(return_value=1000)
    mock_client.lrange = AsyncMock(return_value=[b"item"] * 100)

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        # 尝试使用 0 到 -1 拉取全量大列表
        res = await redis_list_range(sample_registry, key="huge:list", start=0, stop=-1)

        assert res["count"] == 100
        assert res["is_truncated"] is True
        mock_client.lrange.assert_called_once_with("huge:list", 0, 99)


# --- 3. redis_set_members 测试 ---


@pytest.mark.asyncio
async def test_redis_set_members_scan_and_truncation(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证使用 SSCAN 聚合采样集合成员，并在超过上限时自动截断。"""
    mock_client = AsyncMock()
    batch1 = [f"tag:{i}".encode() for i in range(30)]
    batch2 = [f"tag:{i}".encode() for i in range(30, 70)]
    mock_client.sscan = AsyncMock(side_effect=[(5, batch1), (0, batch2)])

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res = await redis_set_members(sample_registry, key="user:tags", limit=50)

        assert res["key"] == "user:tags"
        assert res["count"] == 50
        assert len(res["members"]) == 50
        assert res["is_truncated"] is True


@pytest.mark.asyncio
async def test_redis_set_members_empty_and_nonexistent(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证空集合或不存在键时优雅返回。"""
    mock_client = AsyncMock()
    mock_client.sscan = AsyncMock(return_value=(0, []))

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res = await redis_set_members(sample_registry, key="empty:set")

        assert res["key"] == "empty:set"
        assert res["count"] == 0
        assert res["members"] == []
        assert res["is_truncated"] is False


# --- 4. redis_zset_range 测试 ---


@pytest.mark.asyncio
async def test_redis_zset_range_with_scores(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证获取有序集合成员及分值，支持排名切片与倒序。"""
    mock_client = AsyncMock()
    # redis-py 返回结构为 [(member, score), ...]
    mock_client.zrange = AsyncMock(
        return_value=[
            (b"player1", 100.0),
            (b"player2", 95.5),
            (b'{"player": 3}', 88.0),
        ]
    )

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res = await redis_zset_range(
            sample_registry,
            key="leaderboard",
            start=0,
            stop=10,
            reverse=True,
        )

        assert res["key"] == "leaderboard"
        assert res["exists"] is True
        assert res["count"] == 3
        assert res["items"][0]["member"] == "player1"
        assert res["items"][0]["score"] == 100.0
        assert res["items"][2]["json_data"] == {"player": 3}
        assert res["items"][2]["score"] == 88.0
        assert res["is_truncated"] is False
        mock_client.zrange.assert_called_once_with(
            "leaderboard",
            0,
            10,
            desc=True,
            withscores=True,
        )


@pytest.mark.asyncio
async def test_redis_zset_range_hard_limit(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证 ZSet 请求跨度被强制限制在硬上限 200 条之内。"""
    mock_client = AsyncMock()
    mock_client.zrange = AsyncMock(return_value=[(f"m{i}".encode(), float(i)) for i in range(200)])

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res = await redis_zset_range(sample_registry, key="big:zset", start=0, stop=500)

        assert res["count"] == 200
        assert res["is_truncated"] is True
        mock_client.zrange.assert_called_once_with(
            "big:zset",
            0,
            199,
            desc=False,
            withscores=True,
        )


# --- 5. redis_stream_read 测试 ---


@pytest.mark.asyncio
async def test_redis_stream_read_xrevrange(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证使用 XREVRANGE 逆序采样读取 Stream 最新消息条目。"""
    mock_client = AsyncMock()
    # xrevrange 返回 [(b'1712188800000-0', {b'event': b'login', b'meta': b'{"ip": "1.1.1.1"}'})]
    mock_client.xrevrange = AsyncMock(
        return_value=[
            (
                b"1712188800000-0",
                {
                    b"event": b"login",
                    b"meta": b'{"ip": "1.1.1.1"}',
                },
            )
        ]
    )

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res = await redis_stream_read(sample_registry, key="events:stream", count=10)

        assert res["key"] == "events:stream"
        assert res["exists"] is True
        assert res["count"] == 1
        entry = res["entries"][0]
        assert entry["id"] == "1712188800000-0"
        assert entry["fields"]["event"] == "login"
        assert entry["fields"]["meta"] == {"ip": "1.1.1.1"}
        mock_client.xrevrange.assert_called_once_with(
            "events:stream",
            max="+",
            min="-",
            count=10,
        )


@pytest.mark.asyncio
async def test_redis_zset_range_negative_index_stop_minus_one_truncation(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证传入 start=0, stop=-1 时，正确归一化负数索引并受硬上限 200 约束防范 OOM。"""
    mock_client = AsyncMock()
    # 模拟大 ZSet 总基数 1000
    mock_client.zcard = AsyncMock(return_value=1000)
    mock_client.zrange = AsyncMock(return_value=[(f"m{i}".encode(), float(i)) for i in range(200)])

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res = await redis_zset_range(sample_registry, key="huge:zset", start=0, stop=-1)

        assert res["count"] == 200
        assert res["is_truncated"] is True
        # 验证底层跨度被收敛到 0 到 199
        mock_client.zrange.assert_called_once_with(
            "huge:zset",
            0,
            199,
            desc=False,
            withscores=True,
        )


@pytest.mark.asyncio
async def test_redis_single_element_collections(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证五大集合对单元素结构的读取与自适应序列化。"""
    mock_client = AsyncMock()

    # 1. Hash 单字段
    mock_client.hmget = AsyncMock(return_value=[b"single_val"])
    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res_h = await redis_hash_get(sample_registry, key="h:single", fields="f1")
        assert res_h["count"] == 1
        assert res_h["fields"]["f1"] == "single_val"

    # 2. List 单元素
    mock_client.lrange = AsyncMock(return_value=[b"item0"])
    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res_l = await redis_list_range(sample_registry, key="l:single", start=0, stop=0)
        assert res_l["count"] == 1
        assert res_l["items"][0]["value"] == "item0"

    # 3. Set 单成员
    mock_client.sscan = AsyncMock(return_value=(0, [b"member0"]))
    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res_s = await redis_set_members(sample_registry, key="s:single")
        assert res_s["count"] == 1
        assert res_s["members"] == ["member0"]

    # 4. ZSet 单条目
    mock_client.zrange = AsyncMock(return_value=[(b"m0", 1.0)])
    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res_z = await redis_zset_range(sample_registry, key="z:single", start=0, stop=0)
        assert res_z["count"] == 1
        assert res_z["items"][0]["member"] == "m0"


@pytest.mark.asyncio
async def test_redis_stream_read_truncation(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证当 Stream 消息条数达到请求上限 count 时标记 is_truncated 为 True。"""
    mock_client = AsyncMock()
    mock_client.xrevrange = AsyncMock(
        return_value=[(f"{i}-0".encode(), {b"msg": f"data_{i}".encode()}) for i in range(20)]
    )

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res = await redis_stream_read(sample_registry, key="stream:overflow", count=20)

        assert res["count"] == 20
        assert res["is_truncated"] is True


@pytest.mark.asyncio
async def test_redis_stream_read_empty(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证读取空 Stream 或不存在键。"""
    mock_client = AsyncMock()
    mock_client.xrevrange = AsyncMock(return_value=[])

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res = await redis_stream_read(sample_registry, key="empty:stream")

        assert res["key"] == "empty:stream"
        assert res["count"] == 0
        assert res["entries"] == []


# --- 6. 工具注册测试 ---


@pytest.mark.asyncio
async def test_register_collection_tools_with_server(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证五大集合工具成功挂载至 MCP 服务端。"""
    from mcp.server import MCPServer

    server = MCPServer("test-server")
    register_hash_tools(server, sample_registry)
    register_list_tools(server, sample_registry)
    register_set_tools(server, sample_registry)
    register_zset_tools(server, sample_registry)
    register_stream_tools(server, sample_registry)

    tools = await server.list_tools()
    tool_names = [t.name for t in tools]
    assert "redis_hash_get" in tool_names
    assert "redis_list_range" in tool_names
    assert "redis_set_members" in tool_names
    assert "redis_zset_range" in tool_names
    assert "redis_stream_read" in tool_names
