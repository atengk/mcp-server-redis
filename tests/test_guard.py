"""
安全守卫（高危指令物理阻断、双重写门禁、二次确认）契约测试。

@author Ateng
@since 2026-10-04
"""

import pytest

from mcp_server_redis.core.connection import ConnectionProfile
from mcp_server_redis.core.guard import (
    READONLY_COMMANDS,
    READONLY_SUBCOMMANDS,
    ClassificationResult,
    CommandCategory,
    CommandClassifier,
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


def test_command_classifier_destructive_commands_physically_blocked() -> None:
    """验证所有高危破坏性指令被 CommandClassifier 与 SecurityGuard 物理阻断。"""
    guard = SecurityGuard(allow_write=True)
    profile = ConnectionProfile(alias="local", url="redis://localhost:6379/0", readonly=False)

    destructive_commands = [
        "FLUSHALL",
        "flushall",
        "FLUSHDB",
        "flushdb",
        "KEYS *",
        "keys user:*",
        "KEYS",
        "SHUTDOWN",
        "shutdown NOSAVE",
        "CONFIG GET maxmemory",
        "config set dir /tmp",
        "DEBUG OBJECT mykey",
        "debug sleep 10",
    ]

    for cmd in destructive_commands:
        # 1. 验证分类器直接抛出 DestructiveCommandError 永久物理切断
        with pytest.raises(DestructiveCommandError, match="物理拦截破坏性指令"):
            CommandClassifier.classify(cmd)

        # 2. 验证 SecurityGuard.verify_command 必定物理拦截
        with pytest.raises(DestructiveCommandError, match="物理拦截破坏性指令"):
            guard.verify_command(cmd, profile)


def test_command_classifier_readonly_whitelist_comprehensiveness() -> None:
    """验证只读命令白名单收录 80+ 个常见只读命令，且只读模式与写授权模式下均被放行。"""
    # 验证白名单命令数量满足 80+ 要求
    assert len(READONLY_COMMANDS) >= 80
    assert len(READONLY_SUBCOMMANDS) >= 15

    guard_readonly = SecurityGuard(allow_write=False)
    guard_write = SecurityGuard(allow_write=True)
    readonly_profile = ConnectionProfile(alias="slave", url="redis://slave:6379/0", readonly=True)
    write_profile = ConnectionProfile(alias="master", url="redis://master:6379/0", readonly=False)

    sample_readonly_commands = [
        # String
        "GET user:1001",
        "MGET k1 k2 k3",
        "GETRANGE doc 0 10",
        "STRLEN session_id",
        "GETBIT bits 3",
        "BITCOUNT bits",
        "BITPOS bits 1",
        # Key / Generic
        "EXISTS user:1001",
        "TYPE mylist",
        "TTL token",
        "PTTL token",
        "EXPIRETIME token",
        "PEXPIRETIME token",
        "DUMP target_key",
        "RANDOMKEY",
        "SCAN 0 MATCH user:* COUNT 10",
        # Hash
        "HGET user:1001 name",
        "HMGET user:1001 name email age",
        "HGETALL user:1001",
        "HKEYS user:1001",
        "HVALS user:1001",
        "HLEN user:1001",
        "HEXISTS user:1001 name",
        "HSTRLEN user:1001 name",
        "HRANDFIELD user:1001 2",
        "HSCAN user:1001 0",
        # List
        "LINDEX queue 0",
        "LLEN queue",
        "LRANGE queue 0 -1",
        "LPOS queue item",
        # Set
        "SCARD tags",
        "SDIFF set1 set2",
        "SINTER set1 set2",
        "SINTERCARD 2 set1 set2",
        "SUNION set1 set2",
        "SISMEMBER tags python",
        "SMISMEMBER tags python redis",
        "SMEMBERS tags",
        "SRANDMEMBER tags 2",
        "SSCAN tags 0",
        # ZSet
        "ZCARD leaderboard",
        "ZCOUNT leaderboard 0 100",
        "ZDIFF 2 z1 z2",
        "ZINTER 2 z1 z2",
        "ZRANGE leaderboard 0 10 WITHSCORES",
        "ZRANGEBYSCORE leaderboard 0 100",
        "ZRANK leaderboard player1",
        "ZREVRANK leaderboard player1",
        "ZSCORE leaderboard player1",
        "ZMSCORE leaderboard p1 p2",
        "ZSCAN leaderboard 0",
        # Stream
        "XREAD COUNT 2 STREAMS mystream 0-0",
        "XRANGE mystream - + COUNT 10",
        "XREVRANGE mystream + - COUNT 10",
        "XLEN mystream",
        "XINFO STREAM mystream",
        "XPENDING mystream group1",
        # Geo / HyperLogLog
        "GEODIST points p1 p2 km",
        "GEOHASH points p1 p2",
        "GEOPOS points p1 p2",
        "GEOSEARCH points FROMLONLAT 120.0 30.0 BYRADIUS 10 km",
        "PFCOUNT hll",
        # Connection / Server / Diagnostics
        "PING",
        "ECHO 'hello world'",
        "INFO all",
        "DBSIZE",
        "TIME",
        "ROLE",
        "LASTSAVE",
        "LOLWUT 5 10",
        "COMMAND",
        # RedisJSON
        "JSON.GET doc:1001 $",
        "JSON.MGET doc:1 doc:2 $",
        "JSON.TYPE doc:1001 $",
        "JSON.STRLEN doc:1001 $.name",
        # 子命令 (Subcommands)
        "MEMORY USAGE large_key",
        "MEMORY STATS",
        "OBJECT ENCODING mykey",
        "OBJECT IDLETIME mykey",
        "CLIENT LIST",
        "CLIENT INFO",
        "SLOWLOG GET 10",
        "SLOWLOG LEN",
        "COMMAND INFO GET",
        "COMMAND COUNT",
        "CLUSTER INFO",
        "CLUSTER NODES",
    ]

    for cmd in sample_readonly_commands:
        # 分类结果断言
        res = CommandClassifier.classify(cmd)
        assert isinstance(res, ClassificationResult)
        assert res.category == CommandCategory.READ_ONLY, f"命令 '{cmd}' 未被判定为 READ_ONLY"
        assert res.is_readonly is True
        assert res.is_write is False

        # 在完全只读模式与只读连接下验证放行
        verdict_ro = guard_readonly.verify_command(cmd, readonly_profile)
        assert verdict_ro.category == CommandCategory.READ_ONLY

        # 在完全写授权模式下验证放行
        verdict_rw = guard_write.verify_command(cmd, write_profile)
        assert verdict_rw.category == CommandCategory.READ_ONLY


def test_command_classifier_common_write_commands() -> None:
    """验证常见写操作在只读模式下被拦截，在写授权模式下被放行。"""
    guard_readonly = SecurityGuard(allow_write=False)
    guard_write = SecurityGuard(allow_write=True)
    readonly_profile = ConnectionProfile(
        alias="staging", url="redis://staging:6379/0", readonly=True
    )
    write_profile = ConnectionProfile(
        alias="prod_master", url="redis://prod:6379/0", readonly=False
    )

    write_commands = [
        "SET key val",
        "HSET user:1001 name 'John Doe'",
        "LPUSH queue task1",
        "RPUSH queue task2",
        "SADD tags redis",
        "ZADD zset 100 player",
        "EXPIRE key 60",
        "PEXPIRE key 60000",
        "INCR counter",
        "DECR counter",
        "MSET k1 v1 k2 v2",
        "LPOP queue",
        "RPOP queue",
        "SREM tags redis",
        "ZREM zset player",
        "HDEL hash field",
    ]

    for cmd in write_commands:
        res = CommandClassifier.classify(cmd)
        assert res.category == CommandCategory.WRITE
        assert res.is_write is True
        assert res.is_readonly is False

        # 1. 全局 allow_write=False 时拦截
        with pytest.raises(ReadOnlyModeError, match="服务处于只读保护模式"):
            guard_readonly.verify_command(cmd, write_profile)

        # 2. 全局 allow_write=True 但连接 readonly=True 时拦截
        with pytest.raises(ReadOnlyConnectionError, match="已配置为只读保护"):
            guard_write.verify_command(cmd, readonly_profile)

        # 3. 双重授权满足时放行
        verdict = guard_write.verify_command(cmd, write_profile)
        assert verdict.category == CommandCategory.WRITE


def test_command_classifier_unknown_and_module_commands_fail_close() -> None:
    """验证未在白名单收录的未知命令与扩展模块命令执行 Fail-Close（默认作为写操作对待）。"""
    guard_readonly = SecurityGuard(allow_write=False)
    guard_write = SecurityGuard(allow_write=True)
    readonly_profile = ConnectionProfile(alias="slave", url="redis://slave:6379/0", readonly=True)
    write_profile = ConnectionProfile(alias="master", url="redis://master:6379/0", readonly=False)

    unknown_commands = [
        "UNKNOWN_SYSTEM_CMD arg1 arg2",
        "BF.ADD myfilter item1",
        "CF.INSERT ring item1",
        "TOPK.ADD topk item1",
        "CMS.INCRBY cms item 1",
        "GRAPH.QUERY mygraph 'MATCH (n) RETURN n'",
    ]

    for cmd in unknown_commands:
        res = CommandClassifier.classify(cmd)
        assert res.category == CommandCategory.WRITE
        assert res.is_write is True

        # 只读模式下必须安全拦截
        with pytest.raises(ReadOnlyModeError, match="服务处于只读保护模式"):
            guard_readonly.verify_command(cmd, write_profile)

        with pytest.raises(ReadOnlyConnectionError, match="已配置为只读保护"):
            guard_write.verify_command(cmd, readonly_profile)

        # 写授权模式下放行
        verdict = guard_write.verify_command(cmd, write_profile)
        assert verdict.category == CommandCategory.WRITE


def test_command_classifier_del_and_unlink_confirmation_and_key_extraction() -> None:
    """验证 DEL 与 UNLINK 命令能准确提取待删除键名列表并标识二次确认。"""
    guard_readonly = SecurityGuard(allow_write=False)
    guard_write = SecurityGuard(allow_write=True)
    readonly_profile = ConnectionProfile(alias="slave", url="redis://slave:6379/0", readonly=True)
    write_profile = ConnectionProfile(alias="master", url="redis://master:6379/0", readonly=False)

    del_cases = [
        ("DEL k1 k2 k3", ["k1", "k2", "k3"]),
        ("del single_key", ["single_key"]),
        ("UNLINK user:1 user:2", ["user:1", "user:2"]),
        ("unlink 'key with spaces' \"quoted_key\"", ["key with spaces", "quoted_key"]),
        ("DEL", []),
    ]

    for cmd, expected_keys in del_cases:
        res = CommandClassifier.classify(cmd)
        assert res.category == CommandCategory.CONFIRMATION_REQUIRED
        assert res.requires_confirmation is True
        assert res.is_write is True
        assert res.is_readonly is False
        assert res.keys == expected_keys

        # 权限门禁依然生效：只读拦截
        with pytest.raises(ReadOnlyModeError, match="服务处于只读保护模式"):
            guard_readonly.verify_command(cmd, write_profile)

        with pytest.raises(ReadOnlyConnectionError, match="已配置为只读保护"):
            guard_write.verify_command(cmd, readonly_profile)

        # 授权模式下返回待确认结果
        verdict = guard_write.verify_command(cmd, write_profile)
        assert verdict.category == CommandCategory.CONFIRMATION_REQUIRED
        assert verdict.requires_confirmation is True
        assert verdict.keys == expected_keys


def test_command_classifier_subcommands_security_isolation() -> None:
    """验证多词子命令的安全隔离性（如 CLIENT LIST 放行，而 CLIENT KILL 作为写操作拦截）。"""
    guard_readonly = SecurityGuard(allow_write=False)
    guard_write = SecurityGuard(allow_write=True)
    write_profile = ConnectionProfile(alias="master", url="redis://master:6379/0", readonly=False)

    # 1. 只读子命令
    res_list = CommandClassifier.classify("CLIENT LIST")
    assert res_list.category == CommandCategory.READ_ONLY
    assert guard_readonly.verify_command("CLIENT LIST", write_profile).is_readonly is True

    # 2. 变更/非只读子命令
    non_readonly_subcommands = [
        "CLIENT KILL 127.0.0.1:12345",
        "CLIENT SETNAME worker-1",
        "SLOWLOG RESET",
        "MEMORY PURGE",
        "CLUSTER MEET 127.0.0.1 7000",
    ]
    for cmd in non_readonly_subcommands:
        res = CommandClassifier.classify(cmd)
        assert res.category == CommandCategory.WRITE
        with pytest.raises(ReadOnlyModeError):
            guard_readonly.verify_command(cmd, write_profile)
        # 写授权模式放行
        verdict = guard_write.verify_command(cmd, write_profile)
        assert verdict.category == CommandCategory.WRITE


def test_command_classifier_edge_cases_and_input_types() -> None:
    """验证空指令、分词语法错误、列表传参等边界条件。"""
    guard = SecurityGuard(allow_write=True)
    profile = ConnectionProfile(alias="local", url="redis://localhost:6379/0", readonly=False)

    # 1. 空命令与纯空白抛出 ValueError
    with pytest.raises(ValueError, match="命令不能为空"):
        CommandClassifier.classify("")
    with pytest.raises(ValueError, match="命令不能为空"):
        CommandClassifier.classify("    ")
    with pytest.raises(ValueError, match="命令不能为空"):
        guard.verify_command("", profile)

    # 2. 引号未闭合分词语法错误抛出 ValueError
    with pytest.raises(ValueError, match="分词解析错误"):
        CommandClassifier.classify('SET "unclosed quote')

    # 3. 支持列表传参（list[str]）
    verdict = guard.verify_command(["GET", "user:1001"], profile)
    assert verdict.category == CommandCategory.READ_ONLY
    assert verdict.command_name == "GET"
    assert verdict.raw_tokens == ["GET", "user:1001"]
