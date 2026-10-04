"""
FastMCP 服务主装配与 CLI 参数解析端到端集成测试。

@author Ateng
@since 2026-10-04
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.server.mcpserver.exceptions import UnexpectedToolError
from mcp.types import CallToolResult

from mcp_server_redis.server import (
    SERVER_VERSION,
    build_argument_parser,
    create_app,
    main,
    parse_cli_arguments,
)


@pytest.mark.asyncio
async def test_create_app_mounts_all_18_tools() -> None:
    """验证 create_app 成功初始化并装配全部 18 个生产级 MCP 工具。"""
    app = create_app(url="redis://localhost:6379/0", allow_write=False)

    # 检视已注册工具列表
    tools = await app.list_tools()
    tool_names = {t.name for t in tools}

    expected_18_tools = {
        # 1. 实例探查与连接 (2)
        "redis_list_connections",
        "redis_ping",
        # 2. 键空间检索与诊断 (3)
        "redis_scan_keys",
        "redis_key_inspect",
        "redis_key_ttl",
        # 3. 字符串读写与删除门禁 (4)
        "redis_get_string",
        "redis_set_string",
        "redis_expire_key",
        "redis_delete_keys",
        # 4. 五大复杂集合与流 (5)
        "redis_hash_get",
        "redis_list_range",
        "redis_set_members",
        "redis_zset_range",
        "redis_stream_read",
        # 5. 运维性能诊断 (4)
        "redis_info",
        "redis_dbsize",
        "redis_get_slowlog",
        "redis_client_list",
    }

    assert expected_18_tools.issubset(tool_names)
    assert len(tool_names) == 18


def test_create_app_sets_server_version() -> None:
    """验证 create_app 正确配置服务协议版本号。"""
    app = create_app(url="redis://localhost:6379/0")
    assert app.version == SERVER_VERSION


@pytest.mark.asyncio
async def test_end_to_end_mcp_call_tool() -> None:
    """验证通过 FastMCP call_tool 协议接口进行端到端工具分发调用。"""
    app = create_app(url="redis://localhost:6379/0", allow_write=False)

    # 1. 验证正常只读工具调用 (redis_list_connections)
    res = await app.call_tool("redis_list_connections", {})
    assert isinstance(res, CallToolResult)
    assert not res.is_error
    assert res.structured_content is not None
    assert res.structured_content["total"] == 1
    assert res.structured_content["default"] == "default"

    # 2. 验证只读模式下调用写工具受安全门禁拦截
    with pytest.raises(UnexpectedToolError):
        await app.call_tool("redis_set_string", {"key": "test_key", "value": "val"})


def test_build_argument_parser_defaults() -> None:
    """验证命令行参数解析器默认参数设置。"""
    parser = build_argument_parser()
    args = parser.parse_args([])

    assert args.url is None
    assert args.config is None
    assert args.allow_write is False
    assert args.log_level is None
    assert args.transport is None
    assert args.host is None
    assert args.port is None


def test_parse_cli_arguments_custom_values() -> None:
    """验证解析自定义命令行参数。"""
    config_dict = parse_cli_arguments(
        [
            "--url",
            "redis://127.0.0.1:6380/2",
            "--allow-write",
            "--log-level",
            "debug",
            "--transport",
            "SSE",
            "--host",
            "127.0.0.1",
            "--port",
            "8888",
        ]
    )

    assert config_dict["url"] == "redis://127.0.0.1:6380/2"
    assert config_dict["config"] is None
    assert config_dict["allow_write"] is True
    assert config_dict["log_level"] == "DEBUG"
    assert config_dict["transport"] == "sse"
    assert config_dict["host"] == "127.0.0.1"
    assert config_dict["port"] == 8888


def test_parse_cli_arguments_with_config_file(tmp_path: Path) -> None:
    """验证传递 --config 配置文件参数解析。"""
    cfg_file = tmp_path / "redis.yaml"
    cfg_file.write_text("connections: []", encoding="utf-8")

    config_dict = parse_cli_arguments(["--config", str(cfg_file)])
    assert config_dict["config"] == str(cfg_file)
    assert config_dict["allow_write"] is False
    assert config_dict["log_level"] is None
    assert config_dict["transport"] is None
    assert config_dict["host"] is None
    assert config_dict["port"] is None


def test_parse_cli_arguments_log_level_choices() -> None:
    """验证 --log-level 支持大小写不敏感解析并限制合法选项。"""
    for choice in ["DEBUG", "info", "Warning", "ERROR"]:
        res = parse_cli_arguments(["--log-level", choice])
        assert res["log_level"] == choice.upper()

    with pytest.raises(SystemExit):
        parse_cli_arguments(["--log-level", "INVALID_LEVEL"])


def test_parse_cli_arguments_transport_choices() -> None:
    """验证 --transport 支持大小写不敏感解析并限制合法选项。"""
    for choice in ["stdio", "STDIO", "sse", "SSE"]:
        res = parse_cli_arguments(["--transport", choice])
        assert res["transport"] == choice.lower()

    with pytest.raises(SystemExit):
        parse_cli_arguments(["--transport", "websocket"])



@pytest.mark.asyncio
async def test_app_cleanup_closes_connection_pools() -> None:
    """验证服务生命周期正常退出时自动调用连接池 aclose() 进行资源清理。"""
    app = create_app(url="redis://localhost:6379/0")
    assert app.settings.lifespan is not None

    mock_aclose = AsyncMock()
    async with app.settings.lifespan(app) as ctx:
        registry = ctx["registry"]
        registry.aclose = mock_aclose

    mock_aclose.assert_awaited_once()


def test_main_entrypoint_stdio(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证 main() 入口默认以 stdio 模式启动服务。"""
    monkeypatch.setattr(
        "sys.argv",
        ["mcp-server-redis", "--log-level", "DEBUG", "--url", "redis://localhost:6379/1"],
    )
    with patch("mcp_server_redis.server.create_app") as mock_create_app:
        mock_app = MagicMock()
        mock_create_app.return_value = mock_app
        main()
        mock_create_app.assert_called_once()
        mock_app.run.assert_called_once_with(transport="stdio")


def test_main_entrypoint_sse_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证 main() 入口在显式指定 --transport sse 时启动 HTTP SSE 网关。"""
    monkeypatch.setattr(
        "sys.argv",
        [
            "mcp-server-redis",
            "--transport",
            "sse",
            "--host",
            "127.0.0.1",
            "--port",
            "8080",
        ],
    )
    with patch("mcp_server_redis.server.create_app") as mock_create_app:
        mock_app = MagicMock()
        mock_create_app.return_value = mock_app
        main()
        mock_create_app.assert_called_once()
        mock_app.run.assert_called_once_with(
            transport="sse",
            host="127.0.0.1",
            port=8080,
        )


