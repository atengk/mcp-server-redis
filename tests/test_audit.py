"""
结构化命令审计跟踪器单元测试。

@author Ateng
@since 2026-10-14
"""

import json
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from mcp_server_redis.core.audit import AuditLogger, mask_command_for_audit


def test_mask_command_for_audit() -> None:
    """验证命令敏感信息掩码脱敏函数。"""
    assert mask_command_for_audit("") == ""
    assert mask_command_for_audit("GET user:1001") == "GET user:1001"
    assert mask_command_for_audit("AUTH my_secret_pwd") == "AUTH ***"
    assert mask_command_for_audit("auth   very_secret_pwd") == "auth   ***"
    assert mask_command_for_audit("HGETALL cache:data") == "HGETALL cache:data"


def test_audit_logger_disabled() -> None:
    """验证未指定 target 时处于关闭模式，不执行任何写入。"""
    logger = AuditLogger(target=None)
    assert not logger.is_enabled
    # 调用 log 不抛出异常
    logger.log(command="PING")


def test_audit_logger_stderr_output() -> None:
    """验证输出至 stderr 的 JSONL 格式正确。"""
    logger = AuditLogger(target="stderr", is_stdio=True)
    assert logger.is_enabled

    fake_stderr = StringIO()
    with patch("sys.stderr", fake_stderr):
        logger.log(
            command="AUTH password123",
            connection="prod",
            db=1,
            duration_ms=1.234,
            status="success",
            keys=["user:1001"],
        )

    output = fake_stderr.getvalue()
    assert output.endswith("\n")
    record = json.loads(output)
    assert record["connection"] == "prod"
    assert record["db"] == 1
    assert record["command"] == "AUTH ***"
    assert record["duration_ms"] == 1.23
    assert record["status"] == "success"
    assert record["keys"] == ["user:1001"]
    assert "timestamp" in record


def test_audit_logger_stdio_stdout_redirection() -> None:
    """验证在 stdio 传输模式下，若指定 target='stdout'，被强制重定向至 stderr（防协议污染）。"""
    fake_stderr = StringIO()
    fake_stdout = StringIO()

    with patch("sys.stderr", fake_stderr), patch("sys.stdout", fake_stdout):
        logger = AuditLogger(target="stdout", is_stdio=True)
        assert logger._mode == "stderr"
        logger.log(command="GET key")

    # stdout 绝对零写入
    assert fake_stdout.getvalue() == ""
    # stderr 捕获到审计行
    assert "GET key" in fake_stderr.getvalue()


def test_audit_logger_file_output(tmp_path: Path) -> None:
    """验证输出至指定日志文件，并能正常关闭。"""
    log_file = tmp_path / "audit" / "redis_audit.jsonl"
    logger = AuditLogger(target=str(log_file), is_stdio=False)
    assert logger.is_enabled
    assert logger._mode == "file"

    logger.log(
        command="DEL key1 key2",
        connection="default",
        db=0,
        duration_ms=0.5,
        status="confirmation_required",
        keys=["key1", "key2"],
    )
    logger.log(
        command="FLUSHALL",
        connection="default",
        db=0,
        duration_ms=0.1,
        status="rejected",
        error_type="DestructiveCommandError",
        error_message="破坏性指令已被物理阻断",
    )
    logger.close()

    assert log_file.is_file()
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2

    rec1 = json.loads(lines[0])
    assert rec1["status"] == "confirmation_required"
    assert rec1["keys"] == ["key1", "key2"]

    rec2 = json.loads(lines[1])
    assert rec2["status"] == "rejected"
    assert rec2["error_type"] == "DestructiveCommandError"
    assert "破坏性指令已被物理阻断" in rec2["error_message"]
