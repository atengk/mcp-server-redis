"""
键空间聚合扫描与单键诊断工具契约测试。

@author Ateng
@since 2026-10-04
"""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest

from mcp_server_redis.core.connection import ConnectionProfile, ConnectionRegistry
from mcp_server_redis.tools.keys import (
    redis_key_inspect,
    redis_key_ttl,
    redis_scan_keys,
    register_key_tools,
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


@pytest.mark.asyncio
async def test_redis_scan_keys_accumulates_until_limit(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证 redis_scan_keys 内部循环迭代游标直至达到请求条数或扫描完成。"""
    mock_client = AsyncMock()
    # 第一轮返回 cursor=10 及 2 个键，第二轮返回 cursor=0 及 2 个键
    mock_client.scan = AsyncMock(
        side_effect=[
            (10, [b"user:1", b"user:2"]),
            (0, [b"user:3", b"user:4"]),
        ]
    )

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res = await redis_scan_keys(sample_registry, pattern="user:*", limit=10)

        assert res["pattern"] == "user:*"
        assert res["count"] == 4
        assert res["keys"] == ["user:1", "user:2", "user:3", "user:4"]
        assert res["cursor"] == 0
        assert res["is_truncated"] is False
        assert mock_client.scan.call_count == 2


@pytest.mark.asyncio
async def test_redis_scan_keys_hard_limit_200(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证 redis_scan_keys 单次请求数量硬上限为 200 条。"""
    mock_client = AsyncMock()
    # 模拟每次返回 150 个键
    batch1 = [f"k:{i}".encode() for i in range(150)]
    batch2 = [f"k:{i}".encode() for i in range(150, 300)]
    mock_client.scan = AsyncMock(side_effect=[(50, batch1), (0, batch2)])

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        # 传入超出上限的 500
        res = await redis_scan_keys(sample_registry, pattern="*", limit=500)

        # 验证单次严格截断在 200 条
        assert res["count"] == 200
        assert len(res["keys"]) == 200
        assert res["is_truncated"] is True


@pytest.mark.asyncio
async def test_redis_scan_keys_type_filtering(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证 redis_scan_keys 正确将类型过滤参数传递给底层驱动。"""
    mock_client = AsyncMock()
    mock_client.scan = AsyncMock(return_value=(0, [b"list:1"]))

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res = await redis_scan_keys(sample_registry, pattern="list:*", type="list")

        assert res["type"] == "list"
        assert res["keys"] == ["list:1"]
        # 验证底层 scan 调用时包含 _type="list"
        mock_client.scan.assert_called_once_with(
            cursor=0,
            match="list:*",
            count=50,
            _type="list",
        )


@pytest.mark.asyncio
async def test_redis_scan_keys_empty_db(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证空数据库扫描时立即优雅返回空列表且 cursor 为 0。"""
    mock_client = AsyncMock()
    mock_client.scan = AsyncMock(return_value=(0, []))

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res = await redis_scan_keys(sample_registry, pattern="*")

        assert res["count"] == 0
        assert res["keys"] == []
        assert res["cursor"] == 0
        assert res["is_truncated"] is False
        mock_client.scan.assert_called_once_with(cursor=0, match="*", count=50)


@pytest.mark.asyncio
async def test_redis_scan_keys_deduplicates_across_iterations(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证多轮 SCAN 迭代中出现的重复键被保序去重，不占用有效 limit 额度。"""
    mock_client = AsyncMock()
    # 模拟两轮扫描，第一轮包含 key1, key2；第二轮包含重复的 key2 和新的 key3
    mock_client.scan = AsyncMock(
        side_effect=[
            (10, [b"k:1", b"k:2"]),
            (0, [b"k:2", b"k:3"]),
        ]
    )

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res = await redis_scan_keys(sample_registry, pattern="k:*", limit=10)

        assert res["count"] == 3
        assert res["keys"] == ["k:1", "k:2", "k:3"]
        assert res["cursor"] == 0
        assert res["is_truncated"] is False


@pytest.mark.asyncio
async def test_redis_scan_keys_invalid_type_raises_error(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证传入不支持的 Redis 数据类型过滤时抛出语义明确的 ValueError。"""
    with pytest.raises(ValueError, match="不支持的 Redis 数据类型: 'invalid_type'"):
        await redis_scan_keys(sample_registry, pattern="*", type="invalid_type")


@pytest.mark.asyncio
async def test_redis_scan_keys_max_iterations_protection(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证在大键空间且匹配稀疏时，循环达到最大轮次保底保护自动终止。"""
    mock_client = AsyncMock()
    # 始终返回 cursor=1 且匹配列表为空
    mock_client.scan = AsyncMock(return_value=(1, []))

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res = await redis_scan_keys(sample_registry, pattern="rare:*", limit=10)

        assert res["count"] == 0
        assert res["keys"] == []
        assert res["cursor"] == 1
        assert res["is_truncated"] is True
        # 验证不会陷入死循环，调用次数受最大迭代保护约束
        assert mock_client.scan.call_count == 100


@pytest.mark.asyncio
async def test_redis_key_inspect_existing_key(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证对存在的键进行多维诊断分析。"""
    mock_client = AsyncMock()
    mock_client.exists = AsyncMock(return_value=1)
    mock_client.type = AsyncMock(return_value="string")
    mock_client.ttl = AsyncMock(return_value=300)
    mock_client.pttl = AsyncMock(return_value=300000)
    mock_client.memory_usage = AsyncMock(return_value=1024)
    mock_client.object = AsyncMock(return_value="embstr")

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res = await redis_key_inspect(sample_registry, key="user:profile")

        assert res["key"] == "user:profile"
        assert res["exists"] is True
        assert res["type"] == "string"
        assert res["ttl"] == 300
        assert res["pttl"] == 300000
        assert res["memory_usage"] == 1024
        assert res["encoding"] == "embstr"


@pytest.mark.asyncio
async def test_redis_key_inspect_nonexistent_key(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证对不存在的键诊断时优雅返回默认空结构。"""
    mock_client = AsyncMock()
    mock_client.exists = AsyncMock(return_value=0)

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res = await redis_key_inspect(sample_registry, key="unknown:key")

        assert res["key"] == "unknown:key"
        assert res["exists"] is False
        assert res["type"] == "none"
        assert res["ttl"] == -2
        assert res["pttl"] == -2
        assert res["memory_usage"] is None
        assert res["encoding"] is None


@pytest.mark.asyncio
async def test_redis_key_ttl_scenarios(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证独立极轻量 TTL 工具对不同过期状态的解析。"""
    mock_client = AsyncMock()

    # 1. 具有过期时间
    mock_client.ttl = AsyncMock(return_value=60)
    mock_client.pttl = AsyncMock(return_value=60000)
    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res_exp = await redis_key_ttl(sample_registry, key="session:1")
        assert res_exp["ttl"] == 60
        assert res_exp["pttl"] == 60000
        assert res_exp["status"] == "has_expiry"
        assert res_exp["has_expiry"] is True
        assert res_exp["exists"] is True

    # 2. 永久无过期
    mock_client.ttl = AsyncMock(return_value=-1)
    mock_client.pttl = AsyncMock(return_value=-1)
    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res_persist = await redis_key_ttl(sample_registry, key="config:app")
        assert res_persist["ttl"] == -1
        assert res_persist["status"] == "no_expiry"
        assert res_persist["has_expiry"] is False
        assert res_persist["exists"] is True

    # 3. 键不存在
    mock_client.ttl = AsyncMock(return_value=-2)
    mock_client.pttl = AsyncMock(return_value=-2)
    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res_none = await redis_key_ttl(sample_registry, key="not_exist")
        assert res_none["ttl"] == -2
        assert res_none["status"] == "not_found"
        assert res_none["has_expiry"] is False
        assert res_none["exists"] is False


@pytest.mark.asyncio
async def test_register_key_tools_with_server(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证键操作相关工具成功挂载至 MCP 服务端。"""
    from mcp.server import MCPServer

    server = MCPServer("test-server")
    register_key_tools(server, sample_registry)

    tools = await server.list_tools()
    tool_names = [t.name for t in tools]
    assert "redis_scan_keys" in tool_names
    assert "redis_key_inspect" in tool_names
    assert "redis_key_ttl" in tool_names


@pytest.mark.asyncio
async def test_redis_scan_keys_cluster_iter(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证当底层客户端为 RedisCluster 时，自动调用 scan_iter 聚合分片节点匹配键。"""
    from redis.asyncio.cluster import RedisCluster

    mock_cluster = AsyncMock(spec=RedisCluster)

    async def _async_scan_iter(
        match: str | None = None, count: int | None = None, _type: str | None = None
    ) -> AsyncIterator[str | bytes]:
        yield b"cluster:node1:key1"
        yield "cluster:node2:key2"
        yield b"cluster:node1:key1"  # 模拟重复键，测试去重逻辑

    mock_cluster.scan_iter = _async_scan_iter

    with patch.object(sample_registry, "get_client", return_value=mock_cluster):
        res = await redis_scan_keys(sample_registry, pattern="cluster:*", limit=10)

        assert res["pattern"] == "cluster:*"
        assert res["count"] == 2
        assert res["keys"] == ["cluster:node1:key1", "cluster:node2:key2"]
        assert res["cursor"] == 0
        assert res["is_truncated"] is False


@pytest.mark.asyncio
async def test_redis_scan_keys_cluster_truncated(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证 RedisCluster 模式下若匹配键数超过 limit，正确截断并标记 is_truncated=True。"""
    from redis.asyncio.cluster import RedisCluster

    mock_cluster = AsyncMock(spec=RedisCluster)

    async def _async_scan_iter(
        match: str | None = None, count: int | None = None, _type: str | None = None
    ) -> AsyncIterator[str]:
        for i in range(10):
            yield f"item:{i}"

    mock_cluster.scan_iter = _async_scan_iter

    with patch.object(sample_registry, "get_client", return_value=mock_cluster):
        res = await redis_scan_keys(sample_registry, pattern="item:*", limit=3)

        assert res["count"] == 3
        assert res["keys"] == ["item:0", "item:1", "item:2"]
        assert res["cursor"] == 0
        assert res["is_truncated"] is True
