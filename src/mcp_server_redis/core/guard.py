"""
安全守卫：物理阻断破坏性指令、双重写门禁与高危删除二次确认。

为 Redis 模型上下文协议服务提供工业级只读防护与底层硬编码命令拦截防线。

@author Ateng
@since 2026-10-04
"""

import logging
from typing import Final

from mcp_server_redis.core.connection import ConnectionProfile

logger = logging.getLogger(__name__)

# 底层物理永久阻断的高危破坏性指令集合
DESTRUCTIVE_COMMANDS: Final[frozenset[str]] = frozenset(
    {"FLUSHALL", "FLUSHDB", "KEYS", "SHUTDOWN", "CONFIG", "DEBUG"}
)


class SecurityError(Exception):
    """安全守卫通用基础异常。

    @author Ateng
    @since 2026-10-04
    """


class DestructiveCommandError(SecurityError):
    """物理阻断高危破坏性指令异常。

    @author Ateng
    @since 2026-10-04
    """


class ReadOnlyModeError(SecurityError):
    """全局只读保护模式拦截异常。

    @author Ateng
    @since 2026-10-04
    """


class ReadOnlyConnectionError(SecurityError):
    """目标连接只读配置拦截异常。

    @author Ateng
    @since 2026-10-04
    """


class ConfirmationRequiredError(SecurityError):
    """未二次确认的高危删除操作拦截异常。

    @author Ateng
    @since 2026-10-04
    """


class SecurityGuard:
    """生产级安全守卫。

    负责高危破坏性指令物理切断、双重写门禁裁决与高危操作二次确认。

    @author Ateng
    @since 2026-10-04
    """

    def __init__(self, allow_write: bool = False) -> None:
        """初始化安全守卫。

        @param allow_write 全局是否允许写操作（由 --allow-write 启动参数控制）
        """
        self.allow_write: bool = allow_write

    def check_command(self, command: str) -> None:
        """检查并物理拦截高危破坏性指令。

        无论是否开启写授权，黑名单中的指令在底层代码中均被永久物理阻断。

        @param command 待执行的 Redis 命令或首个操作动词
        @throws DestructiveCommandError 命中破坏性指令时抛出
        """
        if not command or not command.strip():
            return

        cmd_name = command.strip().split()[0].upper()
        if cmd_name in DESTRUCTIVE_COMMANDS:
            logger.warning("底层物理拦截破坏性指令调度尝试: %s", cmd_name)
            raise DestructiveCommandError(
                f"底层代码已永久物理拦截破坏性指令: '{cmd_name}'。该命令禁止在大模型会话中执行。"
            )

    def check_write_permission(self, profile: ConnectionProfile) -> None:
        """执行双重写门禁裁决。

        必须同时满足：全局 allow_write 为 True 且目标连接 profile.readonly 为 False。
        任一条件不满足则绝对阻断写操作。

        @param profile 目标连接档案模型
        @throws ReadOnlyModeError 全局未授权写操作时抛出
        @throws ReadOnlyConnectionError 目标连接被标记为只读时抛出
        """
        if profile is None:
            raise ReadOnlyConnectionError("未提供有效的连接档案，禁止执行写操作。")

        if not self.allow_write:
            raise ReadOnlyModeError(
                "服务处于只读保护模式。写操作已被安全拦截，请在服务启动时传入 --allow-write 参数以启用写入。"
            )

        if profile.readonly:
            raise ReadOnlyConnectionError(
                f"目标连接 '{profile.alias}' 已配置为只读保护 (readonly: true)，严禁执行写入或删除操作。"
            )

    def check_confirmation(self, confirm: bool, target_count: int = 1) -> None:
        """检查高危删除操作的二次确认状态。

        @param confirm 调用方是否已确认删除
        @param target_count 预计受影响的键数量
        @throws ConfirmationRequiredError 未确认时抛出
        """
        if not confirm:
            logger.info("高危删除拦截: 涉及 %d 个键，等待调用方显式二次确认", target_count)
            raise ConfirmationRequiredError(
                f"该删除操作将影响 {target_count} 个键。为防止非预期数据清空，"
                "请在仔细核对后显式传入 confirm=True 以确认物理删除。"
            )
