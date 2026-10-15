"""
Doctor 自检诊断器与版本环境指纹单元测试。

@author Ateng
@since 2026-10-14
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import redis.exceptions

from mcp_server_redis.core.doctor import (
    DoctorCheckItem,
    DoctorReport,
    DoctorRunner,
    format_json_report,
    format_terminal_report,
    get_version_fingerprint,
)
from mcp_server_redis.core.env import ServerConfig


def test_get_version_fingerprint() -> None:
    """验证版本环境指纹输出格式完整性。"""
    fp = get_version_fingerprint("2.0.0")
    assert "mcp-server-redis 2.0.0" in fp
    assert "Python " in fp
    assert "mcp " in fp
    assert "redis " in fp
    assert "pydantic " in fp
    assert "pyyaml " in fp


def test_doctor_report_model() -> None:
    """验证 DoctorReport 统计汇总与 JSON 转换。"""
    report = DoctorReport(
        items=[
            DoctorCheckItem(
                category="Runtime",
                name="Python",
                status="ok",
                message="Python 3.11",
            ),
            DoctorCheckItem(
                category="Configuration",
                name="Config",
                status="warn",
                message="缺少配置描述",
            ),
        ],
        duration_ms=12.34,
    )
    assert report.is_healthy is True
    assert report.summary == {"ok": 1, "warn": 1, "fail": 0, "total": 2}

    d = report.to_dict()
    assert d["healthy"] is True
    assert len(d["checks"]) == 2

    # 添加 fail 项
    report.items.append(
        DoctorCheckItem(
            category="Connection",
            name="Redis",
            status="fail",
            message="连接拒绝",
        )
    )
    assert report.is_healthy is False
    assert report.summary["fail"] == 1


@pytest.mark.asyncio
async def test_doctor_runner_single_connection_success() -> None:
    """验证单个正常连接在只读模式下的完整诊断流程。"""
    mock_client = AsyncMock()
    mock_client.ping = AsyncMock(return_value="PONG")
    mock_client.info = AsyncMock(
        return_value={"redis_version": "7.2.4", "redis_mode": "standalone"}
    )

    config = ServerConfig(
        url="redis://localhost:6379/0",
        config=None,
        allow_write=False,
        log_level="INFO",
    )
    runner = DoctorRunner(server_config=config)

    with patch(
        "mcp_server_redis.core.connection.ConnectionRegistry.get_client", return_value=mock_client
    ):
        report = await runner.run_diagnostics()

    assert report.is_healthy is True
    # 验证各项检查
    cat_names = [it.category for it in report.items]
    assert "Runtime" in cat_names
    assert "Configuration" in cat_names
    assert "Connection" in cat_names
    assert "Security" in cat_names

    # 验证只读模式被识别
    sec_item = next(it for it in report.items if it.category == "Security" and "实例" in it.name)
    assert sec_item.status == "ok"
    assert "受保护的只读模式" in sec_item.message

    # 验证报告格式化不报错
    term_out = format_terminal_report(report)
    assert "全部健康" in term_out
    assert "✔" in term_out

    json_out = format_json_report(report)
    parsed_json = json.loads(json_out)
    assert parsed_json["healthy"] is True


@pytest.mark.asyncio
async def test_doctor_runner_write_probe_success() -> None:
    """验证开启写权限时，隔离写探针正确执行 set、get 与 delete。"""
    mock_client = AsyncMock()
    mock_client.ping = AsyncMock(return_value="PONG")
    mock_client.info = AsyncMock(
        return_value={"redis_version": "7.2.4", "redis_mode": "standalone"}
    )
    mock_client.set = AsyncMock(return_value=True)
    mock_client.get = AsyncMock(return_value=b"1")
    mock_client.delete = AsyncMock(return_value=1)

    config = ServerConfig(
        url="redis://localhost:6379/0",
        config=None,
        allow_write=True,
        log_level="INFO",
    )
    runner = DoctorRunner(server_config=config)

    with patch(
        "mcp_server_redis.core.connection.ConnectionRegistry.get_client", return_value=mock_client
    ):
        report = await runner.run_diagnostics()

    assert report.is_healthy is True
    sec_item = next(it for it in report.items if it.category == "Security" and "实例" in it.name)
    assert sec_item.status == "ok"
    assert "写权限校验通过" in sec_item.message

    # 验证确实调用了 set/get/delete 并且携带 5s TTL
    mock_client.set.assert_called_once()
    set_kwargs = mock_client.set.call_args.kwargs
    assert set_kwargs.get("ex") == 5
    mock_client.delete.assert_called_once()


@pytest.mark.asyncio
async def test_doctor_runner_write_probe_readonly_replica_failure() -> None:
    """验证开启写权限但目标 Redis 是只读从库时，写探针报 fail。"""
    mock_client = AsyncMock()
    mock_client.ping = AsyncMock(return_value="PONG")
    mock_client.info = AsyncMock(
        return_value={"redis_version": "7.2.4", "redis_mode": "standalone"}
    )
    mock_client.set = AsyncMock(
        side_effect=redis.exceptions.ReadOnlyError(
            "READONLY You can't write against a read only replica."
        )
    )

    config = ServerConfig(
        url="redis://localhost:6379/0",
        config=None,
        allow_write=True,
        log_level="INFO",
    )
    runner = DoctorRunner(server_config=config)

    with patch(
        "mcp_server_redis.core.connection.ConnectionRegistry.get_client", return_value=mock_client
    ):
        report = await runner.run_diagnostics()

    assert report.is_healthy is False
    sec_item = next(it for it in report.items if it.category == "Security" and "实例" in it.name)
    assert sec_item.status == "fail"
    assert "只读从库" in sec_item.message


@pytest.mark.asyncio
async def test_doctor_runner_authentication_failure() -> None:
    """验证 Redis 认证失败时诊断项被精准捕获。"""
    mock_client = AsyncMock()
    mock_client.ping = AsyncMock(
        side_effect=redis.exceptions.AuthenticationError("WRONGPASS invalid username-password pair")
    )

    config = ServerConfig(
        url="redis://:wrong@localhost:6379/0",
        config=None,
        allow_write=False,
        log_level="INFO",
    )
    runner = DoctorRunner(server_config=config)

    with patch(
        "mcp_server_redis.core.connection.ConnectionRegistry.get_client", return_value=mock_client
    ):
        report = await runner.run_diagnostics()

    assert report.is_healthy is False
    conn_item = next(it for it in report.items if it.category == "Connection")
    assert conn_item.status == "fail"
    assert "认证失败" in conn_item.message


@pytest.mark.asyncio
async def test_doctor_runner_config_file_missing(tmp_path: Path) -> None:
    """验证配置文件不存在时的诊断报错。"""
    missing_path = tmp_path / "non_existent.yaml"
    config = ServerConfig(
        url="redis://localhost:6379/0",
        config=str(missing_path),
        allow_write=False,
        log_level="INFO",
    )
    runner = DoctorRunner(server_config=config)
    report = await runner.run_diagnostics()

    assert report.is_healthy is False
    cfg_item = next(it for it in report.items if it.category == "Configuration")
    assert cfg_item.status == "fail"
    assert "不存在" in cfg_item.message


@pytest.mark.asyncio
async def test_doctor_runner_multi_instance_config(tmp_path: Path) -> None:
    """验证多实例配置文件全量遍历诊断。"""
    yaml_content = """
default: local
connections:
  local:
    url: "redis://localhost:6379/0"
    readonly: false
  remote-ro:
    url: "redis://remote:6379/1"
    readonly: true
"""
    cfg_file = tmp_path / "connections.yaml"
    cfg_file.write_text(yaml_content, encoding="utf-8")

    mock_client = AsyncMock()
    mock_client.ping = AsyncMock(return_value="PONG")
    mock_client.info = AsyncMock(
        return_value={"redis_version": "7.2.4", "redis_mode": "standalone"}
    )
    mock_client.set = AsyncMock(return_value=True)
    mock_client.get = AsyncMock(return_value=b"1")
    mock_client.delete = AsyncMock(return_value=1)

    config = ServerConfig(
        url="redis://localhost:6379/0",
        config=str(cfg_file),
        allow_write=True,
        log_level="INFO",
    )
    runner = DoctorRunner(server_config=config)

    with patch(
        "mcp_server_redis.core.connection.ConnectionRegistry.get_client", return_value=mock_client
    ):
        report = await runner.run_diagnostics()

    assert report.is_healthy is True
    # 检查连接项是否包含两个实例
    conn_items = [it for it in report.items if it.category == "Connection"]
    assert len(conn_items) == 2
    assert any("local" in it.name for it in conn_items)
    assert any("remote-ro" in it.name for it in conn_items)

    # 检查安全与权限项：传输安全 + local 写探针通过 + remote-ro 只读
    sec_items = [it for it in report.items if it.category == "Security"]
    assert len(sec_items) == 3
    local_sec = next(it for it in sec_items if "local" in it.name)
    assert "写权限校验通过" in local_sec.message
    remote_sec = next(it for it in sec_items if "remote-ro" in it.name)
    assert "受保护的只读模式" in remote_sec.message
    trans_sec = next(it for it in sec_items if "传输协议" in it.name)
    assert trans_sec.status == "ok"


def test_doctor_transport_security_stdio() -> None:
    """验证 Stdio 传输模式下的传输安全自检项判定为 OK。"""
    config = ServerConfig(
        url="redis://localhost:6379/0",
        config=None,
        allow_write=False,
        log_level="INFO",
        transport="stdio",
    )
    runner = DoctorRunner(server_config=config)
    report = DoctorReport()
    runner._check_transport_security(report)

    sec_item = next(it for it in report.items if it.category == "Security")
    assert sec_item.status == "ok"
    assert "Stdio" in sec_item.message


def test_doctor_transport_security_http_wildcard_no_auth() -> None:
    """验证 HTTP 网关绑定 0.0.0.0 且未配置 auth-token 时输出警告。"""
    config = ServerConfig(
        url="redis://localhost:6379/0",
        config=None,
        allow_write=False,
        log_level="INFO",
        transport="sse",
        host="0.0.0.0",
        auth_token=None,
    )
    runner = DoctorRunner(server_config=config)
    report = DoctorReport()
    runner._check_transport_security(report)

    sec_item = next(it for it in report.items if it.category == "Security")
    assert sec_item.status == "warn"
    assert "未配置 --auth-token" in sec_item.message


def test_doctor_transport_security_http_token_strength() -> None:
    """验证配置了短 Token 输出弱口令警告，满足 16 位安全基线输出 OK。"""
    # 1. 弱 Token (8 位) -> warn
    config_weak = ServerConfig(
        url="redis://localhost:6379/0",
        config=None,
        allow_write=False,
        log_level="INFO",
        transport="streamable-http",
        host="0.0.0.0",
        auth_token="weak1234",
    )
    runner_weak = DoctorRunner(server_config=config_weak)
    report_weak = DoctorReport()
    runner_weak._check_transport_security(report_weak)

    weak_item = next(it for it in report_weak.items if it.category == "Security")
    assert weak_item.status == "warn"
    assert "低于推荐的 16 字符安全基线" in weak_item.message

    # 2. 强 Token (32 位) -> ok
    config_strong = ServerConfig(
        url="redis://localhost:6379/0",
        config=None,
        allow_write=False,
        log_level="INFO",
        transport="streamable-http",
        host="0.0.0.0",
        auth_token="secure_token_with_high_entropy_32",
    )
    runner_strong = DoctorRunner(server_config=config_strong)
    report_strong = DoctorReport()
    runner_strong._check_transport_security(report_strong)

    strong_item = next(it for it in report_strong.items if it.category == "Security")
    assert strong_item.status == "ok"
    assert "满足复杂度基线" in strong_item.message
