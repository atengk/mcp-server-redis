"""
FastMCP 服务主装配与 CLI 参数解析端到端集成测试。

@author Ateng
@since 2026-10-04
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.server.mcpserver.exceptions import UnexpectedToolError
from mcp.types import CallToolResult, GetPromptResult, TextContent

from mcp_server_redis.server import (
    SERVER_VERSION,
    build_argument_parser,
    create_app,
    main,
    parse_cli_arguments,
)


@pytest.mark.asyncio
async def test_create_app_mounts_all_4_tools() -> None:
    """验证 create_app 成功初始化并挂载收敛后的核心 4 个生产级 MCP 工具。"""
    app = create_app(url="redis://localhost:6379/0", allow_write=False)

    # 检视已注册工具列表
    tools = await app.list_tools()
    tool_names = {t.name for t in tools}

    expected_4_tools = {
        "redis_execute_command",
        "redis_list_connections",
        "redis_scan_keys",
        "redis_inspect_key",
    }

    assert tool_names == expected_4_tools
    assert len(tool_names) == 4


@pytest.mark.asyncio
async def test_create_app_mounts_resources_and_prompts() -> None:
    """验证 create_app 挂载核心只读快照资源与诊断引导 Prompts 模板。"""
    app = create_app(url="redis://localhost:6379/0", allow_write=False)

    # 1. 验证 Prompts 挂载与生成
    prompts = await app.list_prompts()
    prompt_names = {p.name for p in prompts}
    assert "redis_diagnose_memory" in prompt_names
    assert "redis_analyze_slowlog" in prompt_names
    assert "redis_troubleshoot_bigkeys" in prompt_names

    p_mem = await app.get_prompt("redis_diagnose_memory", arguments={"connection": "prod"})
    assert isinstance(p_mem, GetPromptResult)
    first_msg = p_mem.messages[0].content
    assert isinstance(first_msg, TextContent)
    assert "prod" in first_msg.text
    assert "INFO memory" in first_msg.text

    p_big = await app.get_prompt("redis_troubleshoot_bigkeys", arguments={"connection": "test"})
    assert isinstance(p_big, GetPromptResult)
    big_msg = p_big.messages[0].content
    assert isinstance(big_msg, TextContent)
    assert "test" in big_msg.text
    assert "UNLINK" in big_msg.text

    # 2. 验证 Resources 与 Resource Templates 挂载
    resources = await app.list_resources()
    resource_uris = {str(r.uri) for r in resources}
    assert "redis://info" in resource_uris
    assert "redis://slowlog" in resource_uris
    assert "redis://clients" in resource_uris

    templates = await app.list_resource_templates()
    template_uris = {t.uri_template for t in templates}
    assert "redis://{connection}/info" in template_uris
    assert "redis://{connection}/slowlog" in template_uris
    assert "redis://{connection}/clients" in template_uris


def test_create_app_sets_server_version() -> None:
    """验证 create_app 正确配置服务协议版本号为 2.1.0。"""
    app = create_app(url="redis://localhost:6379/0")
    assert app.version == SERVER_VERSION
    assert SERVER_VERSION == "2.1.0"


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

    # 2. 验证只读模式下调用写命令受安全门禁拦截
    with pytest.raises(UnexpectedToolError):
        await app.call_tool("redis_execute_command", {"command": "SET test_key val"})


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
    assert args.cluster is False
    assert args.audit_log is None
    assert args.server_name is None
    assert args.server_instructions is None
    assert args.doctor is False
    assert args.json is False


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
            "--cluster",
            "--audit-log",
            "stderr",
            "--server-name",
            "custom-redis-srv",
            "--server-instructions",
            "自定义业务系统提示",
            "--doctor",
            "--json",
        ]
    )

    assert config_dict["url"] == "redis://127.0.0.1:6380/2"
    assert config_dict["config"] is None
    assert config_dict["allow_write"] is True
    assert config_dict["log_level"] == "DEBUG"
    assert config_dict["transport"] == "sse"
    assert config_dict["host"] == "127.0.0.1"
    assert config_dict["port"] == 8888
    assert config_dict["cluster"] is True
    assert config_dict["audit_log"] == "stderr"
    assert config_dict["server_name"] == "custom-redis-srv"
    assert config_dict["server_instructions"] == "自定义业务系统提示"
    assert config_dict["doctor"] is True
    assert config_dict["json"] is True


def test_main_doctor_exit_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证 main() 执行 --doctor 时依据自检结果输出正确 POSIX 退出码。"""
    from mcp_server_redis.core.doctor import DoctorCheckItem, DoctorReport

    # 1. 模拟全部自检项通过 -> 退出码 0
    monkeypatch.setattr("sys.argv", ["mcp-server-redis", "--doctor"])
    mock_success_report = DoctorReport(items=[], duration_ms=5.0)
    with patch(
        "mcp_server_redis.core.doctor.DoctorRunner.run_diagnostics",
        return_value=mock_success_report,
    ):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0

    # 2. 模拟存在失败项 -> 退出码 1
    fail_item = DoctorCheckItem(
        category="Connection", name="Redis", status="fail", message="连接超时"
    )
    mock_fail_report = DoctorReport(items=[fail_item], duration_ms=5.0)
    with patch(
        "mcp_server_redis.core.doctor.DoctorRunner.run_diagnostics", return_value=mock_fail_report
    ):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1


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


@pytest.mark.asyncio
async def test_create_app_cluster_flag_propagation() -> None:
    """验证 create_app 在显式指定 cluster=True 时正确将集群标记传递给 ConnectionRegistry。"""
    app = create_app(url="redis://localhost:6379/0", cluster=True)
    assert app.settings.lifespan is not None

    async with app.settings.lifespan(app) as ctx:
        registry = ctx["registry"]
        profile = registry.get_profile()
        assert profile.is_cluster is True


@pytest.mark.asyncio
async def test_health_and_healthz_routes() -> None:
    """验证 SSE 模式下挂载的 /health 与 /healthz 端点结合 Redis PING 探活。"""
    import json

    app = create_app(url="redis://localhost:6379/0")
    sse = app.sse_app()

    from starlette.routing import Route

    endpoints = {r.path: r.endpoint for r in sse.routes if isinstance(r, Route)}
    assert "/health" in endpoints
    assert "/healthz" in endpoints

    # 1. 模拟 Redis PING 探活成功
    mock_client = AsyncMock()
    mock_client.ping = AsyncMock(return_value="PONG")
    with patch(
        "mcp_server_redis.core.connection.ConnectionRegistry.get_client",
        return_value=mock_client,
    ):
        res = await endpoints["/healthz"](None)
        assert res.status_code == 200
        body = json.loads(res.body)
        assert body["status"] == "healthy"
        assert body["redis"] == "ok"
        assert body["version"] == SERVER_VERSION

    # 2. 模拟 Redis PING 探活失败
    mock_failing_client = AsyncMock()
    mock_failing_client.ping = AsyncMock(side_effect=OSError("Connection refused"))
    with patch(
        "mcp_server_redis.core.connection.ConnectionRegistry.get_client",
        return_value=mock_failing_client,
    ):
        res_fail = await endpoints["/healthz"](None)
        assert res_fail.status_code == 503
        body_fail = json.loads(res_fail.body)
        assert body_fail["status"] == "unhealthy"
        assert body_fail["redis"] == "error"
        assert "Connection refused" in body_fail["error"]


def test_create_app_server_identity_and_instructions() -> None:
    """验证 create_app 正确将 server_name 与 server_instructions 设置到 FastMCP 实例中。"""
    # 1. 默认设置
    app_default = create_app(url="redis://localhost:6379/0")
    assert app_default.name == "mcp-server-redis"
    assert app_default.instructions is not None
    assert "生产环境" in app_default.instructions

    # 2. 自定义参数设置
    app_custom = create_app(
        url="redis://localhost:6379/0",
        server_name="order-center-redis",
        server_instructions="专门处理订单与库存业务",
    )
    assert app_custom.name == "order-center-redis"
    assert app_custom.instructions == "专门处理订单与库存业务"
