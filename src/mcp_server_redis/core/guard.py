"""安全守卫：物理阻断破坏性指令、双重写门禁、高危删除二次确认与命令分类裁决器。

为 Redis 模型上下文协议服务提供工业级只读防护、命令分类与底层硬编码命令拦截防线。

@author Ateng
@since 2026-10-04
"""

import logging
import shlex
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Final

from mcp_server_redis.core.connection import ConnectionProfile

logger = logging.getLogger(__name__)

# 底层物理永久阻断的高危破坏性指令集合
DESTRUCTIVE_COMMANDS: Final[frozenset[str]] = frozenset(
    {"FLUSHALL", "FLUSHDB", "KEYS", "SHUTDOWN", "CONFIG", "DEBUG"}
)

# 涉及高危批量/单键删除需二次确认的指令集合
CONFIRMATION_COMMANDS: Final[frozenset[str]] = frozenset({"DEL", "UNLINK"})

# 容易引发工作进程挂起的阻塞式读取指令集合（需安全收敛超时）
BLOCKING_COMMANDS: Final[frozenset[str]] = frozenset(
    {"BLPOP", "BRPOP", "BRPOPLPUSH", "BLMOVE", "BZPOPMIN", "BZPOPMAX"}
)

# 80+ 常用只读与无副作用命令白名单集合（单动词）

READONLY_COMMANDS: Final[frozenset[str]] = frozenset(
    {
        # String
        "GET",
        "MGET",
        "GETRANGE",
        "SUBSTR",
        "STRLEN",
        "GETBIT",
        "BITCOUNT",
        "BITPOS",
        # Key / Generic Inspection
        "EXISTS",
        "TYPE",
        "TTL",
        "PTTL",
        "EXPIRETIME",
        "PEXPIRETIME",
        "DUMP",
        "RANDOMKEY",
        "SCAN",
        # Hash
        "HGET",
        "HMGET",
        "HGETALL",
        "HKEYS",
        "HVALS",
        "HLEN",
        "HEXISTS",
        "HSTRLEN",
        "HRANDFIELD",
        "HSCAN",
        # List
        "LINDEX",
        "LLEN",
        "LRANGE",
        "LPOS",
        # Set
        "SCARD",
        "SDIFF",
        "SINTER",
        "SINTERCARD",
        "SUNION",
        "SISMEMBER",
        "SMISMEMBER",
        "SMEMBERS",
        "SRANDMEMBER",
        "SSCAN",
        # Sorted Set (ZSet)
        "ZCARD",
        "ZCOUNT",
        "ZDIFF",
        "ZINTER",
        "ZINTERCARD",
        "ZUNION",
        "ZRANGE",
        "ZRANGEBYSCORE",
        "ZREVRANGEBYSCORE",
        "ZRANGEBYLEX",
        "ZREVRANGEBYLEX",
        "ZREVRANGE",
        "ZRANK",
        "ZREVRANK",
        "ZSCORE",
        "ZMSCORE",
        "ZLEXCOUNT",
        "ZRANDMEMBER",
        "ZSCAN",
        # Stream
        "XREAD",
        "XRANGE",
        "XREVRANGE",
        "XLEN",
        "XINFO",
        "XPENDING",
        # Geospatial
        "GEODIST",
        "GEOHASH",
        "GEOPOS",
        "GEORADIUS_RO",
        "GEORADIUSBYMEMBER_RO",
        "GEOSEARCH",
        # HyperLogLog
        "PFCOUNT",
        # Connection / Server / Diagnostics
        "PING",
        "ECHO",
        "INFO",
        "DBSIZE",
        "TIME",
        "ROLE",
        "LASTSAVE",
        "LOLWUT",
        "COMMAND",
        # RedisJSON Module
        "JSON.GET",
        "JSON.MGET",
        "JSON.TYPE",
        "JSON.STRLEN",
        "JSON.ARRLEN",
        "JSON.OBJKEYS",
        "JSON.OBJLEN",
        "JSON.RESP",
    }
)

# 需要子命令判定的父级命令集合
SUBCOMMAND_PARENT_COMMANDS: Final[frozenset[str]] = frozenset(
    {"CLIENT", "SLOWLOG", "CLUSTER", "COMMAND", "MEMORY", "OBJECT"}
)

# 常用只读子命令白名单（父命令+子命令）
READONLY_SUBCOMMANDS: Final[frozenset[str]] = frozenset(
    {
        # Memory
        "MEMORY USAGE",
        "MEMORY STATS",
        # Object
        "OBJECT ENCODING",
        "OBJECT IDLETIME",
        "OBJECT REFCOUNT",
        "OBJECT FREQ",
        # Client
        "CLIENT LIST",
        "CLIENT INFO",
        "CLIENT GETNAME",
        "CLIENT ID",
        # Slowlog
        "SLOWLOG GET",
        "SLOWLOG LEN",
        # Command
        "COMMAND INFO",
        "COMMAND LIST",
        "COMMAND COUNT",
        "COMMAND DOCS",
        # Cluster
        "CLUSTER INFO",
        "CLUSTER NODES",
        "CLUSTER SLOTS",
        "CLUSTER SHARDS",
        "CLUSTER KEYSLOT",
    }
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


class CommandCategory(str, Enum):
    """Redis 命令安全分类。

    @author Ateng
    @since 2026-10-12
    """

    DESTRUCTIVE = "destructive"  # 破坏性指令（物理阻断）
    READ_ONLY = "read_only"  # 只读白名单指令（只读与写模式均放行）
    WRITE = "write"  # 变更指令与未知指令（受阶梯双重写门禁管控）
    CONFIRMATION_REQUIRED = "confirmation_required"  # 高危删除指令（受写门禁管控且需二次确认）


@dataclass(frozen=True)
class ClassificationResult:
    """命令分类裁决结果。

    包含命令动词、分类级别、待删除键名列表与原始解析分词。

    @author Ateng
    @since 2026-10-12
    """

    command_name: str
    category: CommandCategory
    keys: list[str] = field(default_factory=list)
    raw_tokens: list[str] = field(default_factory=list)
    clamped_message: str | None = None

    @property
    def is_destructive(self) -> bool:
        """是否为高危破坏性指令。"""
        return self.category == CommandCategory.DESTRUCTIVE

    @property
    def is_readonly(self) -> bool:
        """是否为只读指令。"""
        return self.category == CommandCategory.READ_ONLY

    @property
    def is_write(self) -> bool:
        """是否为变更或需写权限的指令。"""
        return self.category in (
            CommandCategory.WRITE,
            CommandCategory.CONFIRMATION_REQUIRED,
            CommandCategory.DESTRUCTIVE,
        )

    @property
    def requires_confirmation(self) -> bool:
        """是否需要二次确认。"""
        return self.category == CommandCategory.CONFIRMATION_REQUIRED


class CommandClassifier:
    """Redis 原生命令分类裁决器。

    依据破坏性指令黑名单、80+ 只读白名单及删除确认规则，对输入命令进行安全分词与分类裁决。

    @author Ateng
    @since 2026-10-12
    """

    @classmethod
    def parse_tokens(cls, command: str | Sequence[str]) -> list[str]:
        """将输入命令解析为规范的参数列表。

        支持单行命令行字符串（基于 POSIX 引号规范分词）或已分词的字符串序列。

        Args:
            command: 原生 Redis 命令行字符串或分词序列

        Returns:
            list[str]: 分词参数列表

        Raises:
            ValueError: 分词语法错误（如未闭合引号）时抛出
        """
        if isinstance(command, str):
            if not command.strip():
                return []
            try:
                return shlex.split(command.strip())
            except ValueError as err:
                raise ValueError(f"命令分词解析错误: {err}") from err

        return [str(token) for token in command]

    @classmethod
    def classify(cls, command: str | Sequence[str]) -> ClassificationResult:
        """对输入的 Redis 命令执行分类裁决。

        1. 语法分词与有效性校验；
        2. 破坏性黑名单检查（命中必定永久物理阻断）；
        3. 删除确认指令检查（DEL / UNLINK 提取待删除键名）；
        4. 只读白名单匹配（包含单动词与安全子命令）；
        5. 未知命令与普通写命令默认作为变更命令处理（Fail-Close）。

        Args:
            command: 原生 Redis 命令行字符串或分词列表

        Returns:
            ClassificationResult: 分类裁决结果

        Raises:
            DestructiveCommandError: 命中高危破坏性指令时抛出
            ValueError: 命令为空或语法错误时抛出
        """
        tokens = cls.parse_tokens(command)
        if not tokens:
            raise ValueError("命令不能为空。")

        cmd_name = tokens[0].upper()

        # 0. 阻塞命令超时安全收敛（防止 0 秒无限等待挂死 MCP 服务进程，最大限制 5 秒）
        clamped_msg: str | None = None
        if cmd_name in BLOCKING_COMMANDS and len(tokens) >= 2:
            try:
                timeout_val = float(tokens[-1])
                if timeout_val <= 0:
                    tokens = list(tokens)
                    tokens[-1] = "2"
                    clamped_msg = (
                        f"阻塞命令 '{cmd_name}' 超时设为 {timeout_val:g}（零超时无限等待），"
                        "为防止 MCP 服务进程挂起假死，已主动安全收敛改写为 2 秒。"
                    )
                elif timeout_val > 5.0:
                    tokens = list(tokens)
                    tokens[-1] = "5"
                    clamped_msg = (
                        f"阻塞命令 '{cmd_name}' 超时为 {timeout_val:g} 秒，超过最大安全阈值（5 秒），"
                        "已主动安全收敛改写为 5 秒。"
                    )
            except ValueError:
                pass

        # 1. 物理阻断破坏性指令黑名单（永久物理切断）
        if cmd_name in DESTRUCTIVE_COMMANDS:
            logger.warning("底层物理拦截破坏性指令调度尝试: %s", cmd_name)
            raise DestructiveCommandError(
                f"底层代码已永久物理拦截破坏性指令: '{cmd_name}'。该命令禁止在大模型会话中执行。"
            )

        # 2. 识别高危删除操作（DEL 与 UNLINK）并提取待删除键名列表
        if cmd_name in CONFIRMATION_COMMANDS:
            keys_to_delete = list(tokens[1:])
            return ClassificationResult(
                command_name=cmd_name,
                category=CommandCategory.CONFIRMATION_REQUIRED,
                keys=keys_to_delete,
                raw_tokens=tokens,
            )

        # 3. 检查带子命令的只读白名单（优先匹配特定子命令如 CLIENT LIST, MEMORY USAGE 等）
        if cmd_name in SUBCOMMAND_PARENT_COMMANDS and len(tokens) >= 2:
            subcommand = f"{cmd_name} {tokens[1].upper()}"
            if subcommand in READONLY_SUBCOMMANDS:
                return ClassificationResult(
                    command_name=subcommand,
                    category=CommandCategory.READ_ONLY,
                    raw_tokens=tokens,
                )

        # 4. 检查单动词只读命令白名单（如 GET, PING, COMMAND 等）
        if cmd_name in READONLY_COMMANDS:
            return ClassificationResult(
                command_name=cmd_name,
                category=CommandCategory.READ_ONLY,
                raw_tokens=tokens,
            )

        # 5. Fail-Close：所有未知命令、扩展模块命令及写命令默认归为 WRITE
        return ClassificationResult(
            command_name=cmd_name,
            category=CommandCategory.WRITE,
            raw_tokens=tokens,
            clamped_message=clamped_msg,
        )


class SecurityGuard:
    """生产级安全守卫。

    负责高危破坏性指令物理切断、命令分类裁决、双重写门禁与高危操作二次确认。

    @author Ateng
    @since 2026-10-04
    """

    def __init__(self, allow_write: bool = False) -> None:
        """初始化安全守卫。

        Args:
            allow_write: 全局是否允许写操作（由 --allow-write 启动参数控制）
        """
        self.allow_write: bool = allow_write

    def check_command(self, command: str | Sequence[str]) -> None:
        """检查并物理拦截高危破坏性指令。

        无论是否开启写授权，黑名单中的指令在底层代码中均被永久物理阻断。
        保持存量 RPC 工具向前兼容。

        Args:
            command: 待执行的 Redis 命令或首个操作动词

        Raises:
            DestructiveCommandError: 命中破坏性指令时抛出
        """
        if not command:
            return

        if isinstance(command, str) and not command.strip():
            return

        try:
            CommandClassifier.classify(command)
        except ValueError:
            # 兼容存量测试与调用中对无效空语法的非阻塞放行
            pass

    def check_write_permission(self, profile: ConnectionProfile) -> None:
        """执行双重写门禁裁决。

        必须同时满足：全局 allow_write 为 True 且目标连接 profile.readonly 为 False。
        任一条件不满足则绝对阻断写操作。

        Args:
            profile: 目标连接档案模型

        Raises:
            ReadOnlyModeError: 全局未授权写操作时抛出
            ReadOnlyConnectionError: 目标连接被标记为只读时抛出
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

        Args:
            confirm: 调用方是否已确认删除
            target_count: 预计受影响的键数量

        Raises:
            ConfirmationRequiredError: 未确认时抛出
        """
        if not confirm:
            logger.info("高危删除拦截: 涉及 %d 个键，等待调用方显式二次确认", target_count)
            raise ConfirmationRequiredError(
                f"该删除操作将影响 {target_count} 个键。为防止非预期数据清空，"
                "请在仔细核对后显式传入 confirm=True 以确认物理删除。"
            )

    def verify_command(
        self,
        command: str | Sequence[str],
        profile: ConnectionProfile,
    ) -> ClassificationResult:
        """对待执行的命令进行分词解析、分类裁决与权限门禁判定。

        1. 通过 CommandClassifier 判定命令类别与提取键；
        2. 若命中破坏性指令，物理切断并抛出 DestructiveCommandError；
        3. 若为变更指令（包括普通写、未知命令、DEL/UNLINK），校验双重写门禁；
        4. 若为只读指令，直接放行返回。

        Args:
            command: 原生 Redis 命令行字符串或分词参数列表
            profile: 目标连接档案模型

        Returns:
            ClassificationResult: 分类裁决结果

        Raises:
            DestructiveCommandError: 命中破坏性指令时抛出
            ReadOnlyModeError: 全局未授权写操作时抛出
            ReadOnlyConnectionError: 目标连接被标记为只读时抛出
            ValueError: 命令为空或语法解析错误时抛出
        """
        result = CommandClassifier.classify(command)

        # 变更操作及删除操作强制校验双重写门禁
        if result.is_write:
            self.check_write_permission(profile)

        return result
