"""
安全守卫（高危指令物理阻断、双重写门禁、二次确认）契约测试。

@author Ateng
@since 2026-10-04
"""

import pytest

from mcp_server_redis.core.connection import ConnectionProfile
from mcp_server_redis.core.guard import (
    ConfirmationRequiredError,
    DestructiveCommandError,
    ReadOnlyConnectionError,
    ReadOnlyModeError,
    SecurityGuard,
)


def test_destructive_commands_physically_blocked() -> None:
    """验证 FLUSHALL、FLUSHDB、KEYS、SHUTDOWN、CONFIG、DEBUG 等高危破坏性指令被硬编码物理阻断。"""
    guard = SecurityGuard(allow_write=True)

    destructive_cmds = [
        "FLUSHALL",
        "flushall",
        "FLUSHDB",
        "flushdb",
        "KEYS",
        "keys",
        "SHUTDOWN",
        "shutdown",
        "CONFIG",
        "config",
        "DEBUG",
        "debug",
    ]

    for cmd in destructive_cmds:
        with pytest.raises(DestructiveCommandError, match="物理拦截破坏性指令"):
            guard.check_command(cmd)


def test_safe_commands_allowed() -> None:
    """验证常规非破坏性指令均能正常放行。"""
    guard = SecurityGuard(allow_write=True)
    safe_cmds = ["PING", "GET", "SET", "SCAN", "HGET", "LRANGE", "SMEMBERS", "ZRANGE"]
    for cmd in safe_cmds:
        # 不应抛出异常
        guard.check_command(cmd)


def test_dual_write_gate_blocks_when_allow_write_false() -> None:
    """验证当全局 --allow-write 为 False 时，写操作被拦截。"""
    guard = SecurityGuard(allow_write=False)
    profile = ConnectionProfile(alias="local", url="redis://localhost:6379/0", readonly=False)

    with pytest.raises(ReadOnlyModeError, match="服务处于只读保护模式"):
        guard.check_write_permission(profile)


def test_dual_write_gate_blocks_when_connection_readonly_true() -> None:
    """验证当目标连接为 readonly: true 时，即使全局开启 --allow-write 也绝对拦截写操作。"""
    guard = SecurityGuard(allow_write=True)
    profile = ConnectionProfile(alias="staging", url="redis://staging:6379/0", readonly=True)

    with pytest.raises(ReadOnlyConnectionError, match="已配置为只读保护"):
        guard.check_write_permission(profile)


def test_dual_write_gate_permits_when_both_conditions_met() -> None:
    """验证仅当全局 --allow-write 为 True 且连接 readonly 为 False 时放行写操作。"""
    guard = SecurityGuard(allow_write=True)
    profile = ConnectionProfile(alias="local", url="redis://localhost:6379/0", readonly=False)

    # 正常放行，不抛出异常
    guard.check_write_permission(profile)


def test_confirmation_guard_blocks_unconfirmed() -> None:
    """验证未传 confirm=True 时二次确认门禁拦截并抛出受控提示异常。"""
    guard = SecurityGuard(allow_write=True)
    with pytest.raises(ConfirmationRequiredError, match="confirm=True"):
        guard.check_confirmation(confirm=False, target_count=5)


def test_confirmation_guard_permits_confirmed() -> None:
    """验证显式传入 confirm=True 时二次确认门禁放行。"""
    guard = SecurityGuard(allow_write=True)
    # 正常放行
    guard.check_confirmation(confirm=True, target_count=5)


def test_safe_commands_whitespace_or_empty_does_not_crash() -> None:
    """验证空字符串或纯空白指令安全返回而不抛出 IndexError。"""
    guard = SecurityGuard(allow_write=True)
    guard.check_command("")
    guard.check_command("   ")


def test_dual_write_gate_blocks_none_profile() -> None:
    """验证未传入连接档案时阻断写操作并抛出异常。"""
    guard = SecurityGuard(allow_write=True)
    with pytest.raises(ReadOnlyConnectionError, match="未提供有效的连接档案"):
        guard.check_write_permission(None)  # type: ignore[arg-type]
