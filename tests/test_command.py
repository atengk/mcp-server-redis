"""核心命令网关 (redis_command) 契约测试。

@author Ateng
@since 2026-10-12
"""

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.server import MCPServer
from mcp.types import CallToolResult
from redis.exceptions import ClusterCrossSlotError, ResponseError

from mcp_server_redis.core.connection import ConnectionProfile, ConnectionRegistry
from mcp_server_redis.core.guard import (
    DestructiveCommandError,
    ReadOnlyConnectionError,
    ReadOnlyModeError,
    SecurityGuard,
)
from mcp_server_redis.tools.command import (
    redis_command,
    redis_execute_command,
    register_command_tools,
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
    """提供默认只读保护的安全守卫。"""
    return SecurityGuard(allow_write=False)


@pytest.fixture
def mock_client(sample_registry: ConnectionRegistry) -> Generator[AsyncMock, None, None]:
    """提供注入到 registry.get_client 的通用 AsyncMock 客户端。"""
    client = AsyncMock()
    with patch.object(sample_registry, "get_client", return_value=client):
        yield client


@pytest.mark.asyncio
async def test_redis_command_readonly_get(
    sample_registry: ConnectionRegistry,
    readonly_guard: SecurityGuard,
    mock_client: AsyncMock,
) -> None:
    """验证只读命令在只读模式下正常分词、执行并返回标准信封。"""
    mock_client.execute_command = AsyncMock(return_value="John Doe")

    res = await redis_command(
        registry=sample_registry,
        command="GET user:1001",
        guard=readonly_guard,
    )

    mock_client.execute_command.assert_awaited_once_with("GET", "user:1001")
    assert res["command"] == "GET user:1001"
    assert res["result"] == "John Doe"
    assert res["data_type"] == "string"
    assert res["is_truncated"] is False
    assert res["total_count"] is None


@pytest.mark.asyncio
async def test_redis_command_with_spaces_in_quotes(
    sample_registry: ConnectionRegistry,
    write_guard: SecurityGuard,
    mock_client: AsyncMock,
) -> None:
    """验证包含空格的引号包裹参数被准确分词并传递给 Redis 驱动。"""
    mock_client.execute_command = AsyncMock(return_value="OK")

    res = await redis_command(
        registry=sample_registry,
        command="SET greeting 'hello world' EX 60",
        guard=write_guard,
    )

    mock_client.execute_command.assert_awaited_once_with(
        "SET", "greeting", "hello world", "EX", "60"
    )
    assert res["result"] == "OK"
    assert res["data_type"] == "string"


@pytest.mark.asyncio
async def test_redis_command_write_blocked_in_readonly_mode(
    sample_registry: ConnectionRegistry,
    readonly_guard: SecurityGuard,
    mock_client: AsyncMock,
) -> None:
    """验证全局未开启写权限时，写命令被安全拦截并抛出只读保护异常。"""
    with pytest.raises(ReadOnlyModeError, match="服务处于只读保护模式"):
        await redis_command(
            registry=sample_registry,
            command="SET user:1001 Alice",
            guard=readonly_guard,
        )

    mock_client.execute_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_redis_command_write_blocked_on_readonly_connection(
    sample_registry: ConnectionRegistry,
    write_guard: SecurityGuard,
    mock_client: AsyncMock,
) -> None:
    """验证即使全局开启写权限，只读配置连接上的写操作仍被绝对阻断。"""
    with pytest.raises(ReadOnlyConnectionError, match="已配置为只读保护"):
        await redis_command(
            registry=sample_registry,
            command="SET user:1001 Alice",
            guard=write_guard,
            connection="prod_ro",
        )

    mock_client.execute_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_redis_command_destructive_physically_blocked(
    sample_registry: ConnectionRegistry,
    write_guard: SecurityGuard,
    mock_client: AsyncMock,
) -> None:
    """验证高危破坏性指令被底层物理切断。"""
    destructive_commands = [
        "FLUSHALL",
        "FLUSHDB",
        "KEYS *",
        "SHUTDOWN",
        "CONFIG GET maxmemory",
        "DEBUG OBJECT mykey",
    ]

    for cmd in destructive_commands:
        with pytest.raises(DestructiveCommandError, match="物理拦截破坏性指令"):
            await redis_command(
                registry=sample_registry,
                command=cmd,
                guard=write_guard,
            )

    mock_client.execute_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_redis_command_del_confirmation_flow(
    sample_registry: ConnectionRegistry,
    write_guard: SecurityGuard,
    mock_client: AsyncMock,
) -> None:
    """验证 DEL 删除命令未确认时返回待确认信封，确认后下发物理删除。"""
    mock_client.execute_command = AsyncMock(return_value=2)

    # 1. confirm=False: 返回待确认结构
    unconfirmed_res = await redis_command(
        registry=sample_registry,
        command="DEL user:1001 user:1002",
        guard=write_guard,
        confirm=False,
    )

    assert unconfirmed_res["status"] == "confirmation_required"
    assert unconfirmed_res["command"] == "DEL user:1001 user:1002"
    assert unconfirmed_res["keys"] == ["user:1001", "user:1002"]
    assert unconfirmed_res["target_count"] == 2
    assert unconfirmed_res["data_type"] == "confirmation_required"
    assert unconfirmed_res["is_truncated"] is False
    assert "confirm=True" in unconfirmed_res["message"]
    mock_client.execute_command.assert_not_awaited()

    # 2. confirm=True: 真正下发物理删除
    confirmed_res = await redis_command(
        registry=sample_registry,
        command="DEL user:1001 user:1002",
        guard=write_guard,
        confirm=True,
    )

    mock_client.execute_command.assert_awaited_once_with("DEL", "user:1001", "user:1002")
    assert confirmed_res["result"] == 2
    assert confirmed_res["data_type"] == "integer"


@pytest.mark.asyncio
async def test_redis_command_unlink_confirmation_flow(
    sample_registry: ConnectionRegistry,
    write_guard: SecurityGuard,
    mock_client: AsyncMock,
) -> None:
    """验证 UNLINK 非阻塞删除命令未确认时拦截，确认后执行删除。"""
    mock_client.execute_command = AsyncMock(return_value=1)

    # 1. 未确认
    unconfirmed = await redis_command(
        registry=sample_registry,
        command="UNLINK temp_cache",
        guard=write_guard,
        confirm=False,
    )
    assert unconfirmed["status"] == "confirmation_required"
    assert unconfirmed["keys"] == ["temp_cache"]
    mock_client.execute_command.assert_not_awaited()

    # 2. 确认删除
    confirmed = await redis_command(
        registry=sample_registry,
        command="UNLINK temp_cache",
        guard=write_guard,
        confirm=True,
    )
    mock_client.execute_command.assert_awaited_once_with("UNLINK", "temp_cache")
    assert confirmed["result"] == 1
    assert confirmed["data_type"] == "integer"


@pytest.mark.asyncio
async def test_redis_command_large_collection_slicing(
    sample_registry: ConnectionRegistry,
    readonly_guard: SecurityGuard,
    mock_client: AsyncMock,
) -> None:
    """验证大型集合（List/Set/Hash）返回超过 100 项时自动切片截断并标记元数据。"""
    mock_client.execute_command = AsyncMock(return_value=[f"item_{i}" for i in range(250)])

    res = await redis_command(
        registry=sample_registry,
        command="LRANGE mylist 0 -1",
        guard=readonly_guard,
    )

    assert res["data_type"] == "list"
    assert res["is_truncated"] is True
    assert res["total_count"] == 250
    assert len(res["result"]) == 100
    assert res["result"][0] == "item_0"
    assert res["result"][99] == "item_99"


@pytest.mark.asyncio
async def test_redis_command_cluster_crossslot_error(
    sample_registry: ConnectionRegistry,
    readonly_guard: SecurityGuard,
    write_guard: SecurityGuard,
    mock_client: AsyncMock,
) -> None:
    """验证分片集群模式下触发 ResponseError(CROSSSLOT) 与 ClusterCrossSlotError 时的优雅降级。"""
    # 1. 测试 ResponseError 中的 CROSSSLOT
    mock_client.execute_command = AsyncMock(
        side_effect=ResponseError("CROSSSLOT Keys in request don't hash to the same slot")
    )

    res1 = await redis_command(
        registry=sample_registry,
        command="MGET {user1}:a {user2}:b",
        guard=readonly_guard,
    )

    assert res1["status"] == "error"
    assert res1["error_type"] == "CrossSlotError"
    assert res1["data_type"] == "error"
    assert res1["is_truncated"] is False
    assert "跨槽执行失败" in res1["message"]

    # 2. 测试 redis-py ClusterCrossSlotError 实例 (在写模式下执行 DEL 并通过确认)
    mock_client.execute_command = AsyncMock(
        side_effect=ClusterCrossSlotError("Keys in request don't hash to the same slot")
    )

    res2 = await redis_command(
        registry=sample_registry,
        command="DEL {a}:1 {b}:2",
        guard=write_guard,
        confirm=True,
    )
    assert res2["status"] == "error"
    assert res2["error_type"] == "CrossSlotError"
    assert res2["data_type"] == "error"


@pytest.mark.asyncio
async def test_redis_command_stateless_routing_and_db_switch(
    sample_registry: ConnectionRegistry,
    readonly_guard: SecurityGuard,
) -> None:
    """验证可选的 connection 与 db 参数以无状态方式路由至目标客户端。"""
    mock_client = AsyncMock()
    mock_client.execute_command = AsyncMock(return_value="val")

    with patch.object(sample_registry, "get_client", return_value=mock_client) as mock_get_client:
        res = await redis_command(
            registry=sample_registry,
            command="GET key",
            guard=readonly_guard,
            connection="local",
            db=5,
        )

        mock_get_client.assert_called_once_with(alias="local", db=5)
        assert res["result"] == "val"


@pytest.mark.asyncio
async def test_redis_command_empty_and_syntax_error(
    sample_registry: ConnectionRegistry,
    readonly_guard: SecurityGuard,
) -> None:
    """验证空指令与引号语法未闭合时抛出清晰的 ValueError。"""
    with pytest.raises(ValueError, match="命令不能为空"):
        await redis_command(
            registry=sample_registry,
            command="",
            guard=readonly_guard,
        )

    with pytest.raises(ValueError, match="分词解析错误"):
        await redis_command(
            registry=sample_registry,
            command='SET "unclosed quote',
            guard=readonly_guard,
        )


def test_register_command_tools_registers_redis_command(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证 register_command_tools 成功向 FastMCP 挂载 redis_command 工具。"""
    mock_server = MagicMock()
    register_command_tools(mock_server, sample_registry)

    mock_server.tool.assert_called_once_with(name="redis_execute_command")


@pytest.mark.asyncio
async def test_fastmcp_call_tool_redis_command_protocol_seams(
    sample_registry: ConnectionRegistry,
    write_guard: SecurityGuard,
) -> None:
    """验证通过 FastMCP call_tool 协议入口端到端调度只读、写命令与删除确认。"""
    app = MCPServer(name="test-server")
    register_command_tools(app, sample_registry, guard=write_guard)

    mock_client = AsyncMock()

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        # 1. 协议级只读调度 (PING)
        mock_client.execute_command = AsyncMock(return_value="PONG")
        res_ping = await app.call_tool("redis_execute_command", {"command": "PING"})
        assert isinstance(res_ping, CallToolResult)
        assert not res_ping.is_error
        assert res_ping.structured_content["result"] == "PONG"
        assert res_ping.structured_content["command"] == "PING"

        # 2. 协议级写命令调度 (SET)
        mock_client.execute_command = AsyncMock(return_value="OK")
        res_set = await app.call_tool(
            "redis_execute_command", {"command": 'SET message "welcome to mcp"'}
        )
        assert isinstance(res_set, CallToolResult)
        assert not res_set.is_error
        assert res_set.structured_content is not None
        assert res_set.structured_content["result"] == "OK"

        # 3. 协议级 DEL 未确认拦截
        res_del = await app.call_tool("redis_execute_command", {"command": "DEL k1 k2"})
        assert isinstance(res_del, CallToolResult)
        assert not res_del.is_error
        assert res_del.structured_content is not None
        assert res_del.structured_content["status"] == "confirmation_required"
        assert res_del.structured_content["keys"] == ["k1", "k2"]


@pytest.mark.asyncio
async def test_redis_execute_command_info_parsing(
    sample_registry: ConnectionRegistry,
) -> None:
    """验证 redis_execute_command 执行 INFO 命令时自动解析为结构化紧凑字典。"""
    raw_info = (
        b"# Server\r\n"
        b"redis_version:7.2.4\r\n"
        b"uptime_in_seconds:86400\r\n"
        b"# Memory\r\n"
        b"used_memory:2097152\r\n"
        b"used_memory_human:2.00M\r\n"
        b"mem_fragmentation_ratio:1.25\r\n"
    )
    mock_client = AsyncMock()
    mock_client.execute_command = AsyncMock(return_value=raw_info)

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        # 全局 INFO
        res_all = await redis_execute_command(sample_registry, command="INFO")
        assert res_all["data_type"] == "dict"
        assert isinstance(res_all["result"], dict)
        assert "server" in res_all["result"]
        assert "memory" in res_all["result"]
        assert res_all["result"]["server"]["redis_version"] == "7.2.4"
        assert res_all["result"]["server"]["uptime_in_seconds"] == 86400
        assert res_all["result"]["memory"]["used_memory"] == 2097152
        assert res_all["result"]["memory"]["mem_fragmentation_ratio"] == 1.25

        # 单分节 INFO memory
        res_mem = await redis_execute_command(sample_registry, command="INFO memory")
        assert res_mem["data_type"] == "dict"
        assert res_mem["result"]["used_memory"] == 2097152
        assert res_mem["result"]["used_memory_human"] == "2.00M"


@pytest.mark.asyncio
async def test_redis_execute_command_pipeline_success(
    sample_registry: ConnectionRegistry,
    write_guard: SecurityGuard,
) -> None:
    """验证 commands 列表管道批处理正常下发与聚合信封组装。"""
    mock_client = AsyncMock()
    mock_pipe = AsyncMock()
    mock_pipe.execute_command = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=["OK", b"value1", 1])
    mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
    mock_pipe.__aexit__ = AsyncMock(return_value=None)
    mock_client.pipeline = MagicMock(return_value=mock_pipe)

    commands = ['SET k1 "value1"', "GET k1", "EXISTS k1"]

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res = await redis_execute_command(
            registry=sample_registry,
            commands=commands,
            guard=write_guard,
        )

        assert res["command"] == "PIPELINE"
        assert res["total_commands"] == 3
        assert res["status"] == "success"
        assert len(res["results"]) == 3
        assert res["results"][0]["result"] == "OK"
        assert res["results"][1]["result"] == "value1"
        assert res["results"][2]["result"] == 1
        assert mock_pipe.execute_command.call_count == 3


@pytest.mark.asyncio
async def test_redis_execute_command_pipeline_fail_close_destructive(
    sample_registry: ConnectionRegistry,
    write_guard: SecurityGuard,
) -> None:
    """验证管道批处理前置 Fail-Close：包含高危破坏性指令时整批直接阻断。"""
    commands = ["GET k1", "FLUSHALL", "GET k2"]

    with pytest.raises(DestructiveCommandError, match="物理拦截破坏性指令"):
        await redis_execute_command(
            registry=sample_registry,
            commands=commands,
            guard=write_guard,
        )


@pytest.mark.asyncio
async def test_redis_execute_command_pipeline_fail_close_readonly(
    sample_registry: ConnectionRegistry,
    readonly_guard: SecurityGuard,
) -> None:
    """验证管道批处理前置 Fail-Close：只读模式下包含写命令整批拒绝。"""
    commands = ["GET k1", 'SET k2 "v2"']

    with pytest.raises(ReadOnlyModeError, match="服务处于只读保护模式"):
        await redis_execute_command(
            registry=sample_registry,
            commands=commands,
            guard=readonly_guard,
        )


@pytest.mark.asyncio
async def test_redis_execute_command_pipeline_confirmation_required(
    sample_registry: ConnectionRegistry,
    write_guard: SecurityGuard,
) -> None:
    """验证管道批处理合并提取未确认删除键并返回二次确认信封。"""
    commands = ["GET k1", "DEL k2 k3", "UNLINK k4"]

    res = await redis_execute_command(
        registry=sample_registry,
        commands=commands,
        guard=write_guard,
        confirm=False,
    )

    assert res["status"] == "confirmation_required"
    assert res["command"] == "PIPELINE"
    assert res["keys"] == ["k2", "k3", "k4"]
    assert res["target_count"] == 3
    assert "confirm=True" in res["message"]


@pytest.mark.asyncio
async def test_redis_execute_command_pipeline_with_confirm_true(
    sample_registry: ConnectionRegistry,
    write_guard: SecurityGuard,
) -> None:
    """验证在显式 confirm=True 时管道批处理放行高危删除操作。"""
    mock_client = AsyncMock()
    mock_pipe = AsyncMock()
    mock_pipe.execute_command = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=["PONG", 2])
    mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
    mock_pipe.__aexit__ = AsyncMock(return_value=None)
    mock_client.pipeline = MagicMock(return_value=mock_pipe)

    commands = ["PING", "DEL k1 k2"]

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res = await redis_execute_command(
            registry=sample_registry,
            commands=commands,
            guard=write_guard,
            confirm=True,
        )

        assert res["status"] == "success"
        assert res["total_commands"] == 2


@pytest.mark.asyncio
async def test_redis_execute_command_validation_errors(
    sample_registry: ConnectionRegistry,
    readonly_guard: SecurityGuard,
) -> None:
    """验证参数冲突、空批次、超限批次的参数校验抛错。"""
    # 1. command 和 commands 二选一冲突
    with pytest.raises(ValueError, match="不能同时传入"):
        await redis_execute_command(
            sample_registry,
            command="PING",
            commands=["PING"],
            guard=readonly_guard,
        )

    # 2. 空 commands 列表
    with pytest.raises(ValueError, match="批处理列表不能为空"):
        await redis_execute_command(
            sample_registry,
            commands=[],
            guard=readonly_guard,
        )

    # 3. 超过 20 条上限
    with pytest.raises(ValueError, match="最多支持 20 条命令"):
        await redis_execute_command(
            sample_registry,
            commands=["PING"] * 21,
            guard=readonly_guard,
        )


@pytest.mark.asyncio
async def test_redis_execute_command_blocking_timeout_clamping(
    sample_registry: ConnectionRegistry,
    write_guard: SecurityGuard,
) -> None:
    """验证执行阻塞指令时超时主动改写并携带 message 说明。"""
    mock_client = AsyncMock()
    mock_client.execute_command = AsyncMock(return_value=None)

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        # 1. 单命令网关：0 秒超时收敛为 2 秒
        res = await redis_execute_command(
            registry=sample_registry,
            command="BLPOP myqueue 0",
            guard=write_guard,
        )
        assert "message" in res
        assert "2 秒" in res["message"]
        mock_client.execute_command.assert_called_once_with("BLPOP", "myqueue", "2")

    # 2. 管道网关：聚合提示 message
    mock_pipe = AsyncMock()
    mock_pipe.execute_command = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[None, "PONG"])
    mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
    mock_pipe.__aexit__ = AsyncMock(return_value=None)
    mock_client.pipeline = MagicMock(return_value=mock_pipe)

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res_pipe = await redis_execute_command(
            registry=sample_registry,
            commands=["BLPOP myqueue 0", "PING"],
            guard=write_guard,
        )
        assert "message" in res_pipe
        assert "2 秒" in res_pipe["message"]
        mock_pipe.execute_command.assert_any_call("BLPOP", "myqueue", "2")


@pytest.mark.asyncio
async def test_redis_execute_command_pipeline_individual_error(
    sample_registry: ConnectionRegistry,
    write_guard: SecurityGuard,
) -> None:
    """验证管道内某条命令在 Redis 端报错时，信封标记 error 并保留错误明细。"""
    mock_client = AsyncMock()
    mock_pipe = AsyncMock()
    mock_pipe.execute_command = MagicMock()
    # 模拟第二条命令返回 ResponseError
    mock_pipe.execute = AsyncMock(
        return_value=["OK", ResponseError("WRONGTYPE Operation against a key")]
    )
    mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
    mock_pipe.__aexit__ = AsyncMock(return_value=None)
    mock_client.pipeline = MagicMock(return_value=mock_pipe)

    with patch.object(sample_registry, "get_client", return_value=mock_client):
        res = await redis_execute_command(
            registry=sample_registry,
            commands=["SET k1 v1", "HGETALL k1"],
            guard=write_guard,
        )

        assert res["status"] == "error"
        assert res["results"][0]["status"] == "success" if "status" in res["results"][0] else True
        assert res["results"][1]["status"] == "error"
        assert res["results"][1]["error_type"] == "ResponseError"
        assert "WRONGTYPE" in res["results"][1]["result"]
