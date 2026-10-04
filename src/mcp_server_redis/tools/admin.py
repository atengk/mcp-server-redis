"""
运维性能诊断与慢查询监控工具。

提供 Redis 运行时指标概览（INFO）、当前库键总数（DBSIZE）、慢查询审计（SLOWLOG GET）与客户端连接列表（CLIENT LIST）。

@author Ateng
@since 2026-10-04
"""

import logging
from typing import Any, Final

from mcp_server_redis.core.connection import ConnectionRegistry

logger = logging.getLogger(__name__)

DEFAULT_SLOWLOG_COUNT: Final[int] = 10
MAX_SLOWLOG_COUNT: Final[int] = 50

DEFAULT_CLIENT_LIST_LIMIT: Final[int] = 20
MAX_CLIENT_LIST_LIMIT: Final[int] = 100


# 慢查询命令文本显示最大截断长度（字符）
MAX_SLOWLOG_COMMAND_LENGTH: Final[int] = 500


def _safe_int(val: Any, default: int = 0) -> int:
    """安全解析整数，若为 None、空串或非法格式则返回默认值。

    @param val 待解析值
    @param default 默认值（默认 0）
    @return 安全解析后的整数
    """
    if val is None or val == "":
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _get_profile_and_client(
    registry: ConnectionRegistry,
    connection: str | None,
    db: int | None,
) -> tuple[Any, Any]:
    """统一提取目标连接档案模型与客户端实例。"""
    profile = registry.get_profile(alias=connection)
    client = registry.get_client(alias=connection, db=db)
    return profile, client


async def redis_info(
    registry: ConnectionRegistry,
    section: str | None = None,
    connection: str | None = None,
    db: int | None = None,
) -> dict[str, Any]:
    """获取 Redis 实例的运行状态与系统性能指标。

    @param registry 连接注册中心实例
    @param section 指定探查的信息模块（如 server, clients, memory, stats, cpu 等，可选）
    @param connection 目标连接别名（可选，缺省为默认连接）
    @param db 目标数据库编号（可选，0~15）
    @return 包含系统指标字典与连接元数据的字典
    """
    profile, client = _get_profile_and_client(registry, connection, db)
    logger.debug("查询实例 INFO: alias=%s, section=%s", profile.alias, section)
    info_data = await client.info(section=section)

    return {
        "connection": profile.alias,
        "section": section,
        "info": info_data,
    }


async def redis_dbsize(
    registry: ConnectionRegistry,
    connection: str | None = None,
    db: int | None = None,
) -> dict[str, Any]:
    """查询指定数据库中的键总数统计。

    @param registry 连接注册中心实例
    @param connection 目标连接别名（可选，缺省为默认连接）
    @param db 目标数据库编号（可选，0~15）
    @return 包含键总量统计与数据库编号的字典
    """
    profile, client = _get_profile_and_client(registry, connection, db)
    effective_db = db if db is not None else profile.db
    count = await client.dbsize()

    return {
        "connection": profile.alias,
        "db": effective_db,
        "dbsize": count,
    }


async def redis_get_slowlog(
    registry: ConnectionRegistry,
    count: int = DEFAULT_SLOWLOG_COUNT,
    connection: str | None = None,
    db: int | None = None,
) -> dict[str, Any]:
    """检索并格式化输出目标实例的最新慢查询日志。

    格式化提取执行耗时（微秒及毫秒）、发生时间戳与命令详情（包含长命令安全截断）。

    @param registry 连接注册中心实例
    @param count 最多拉取的慢日志条数（默认 10，硬上限 50）
    @param connection 目标连接别名（可选，缺省为默认连接）
    @param db 目标数据库编号（可选，0~15）
    @return 包含格式化慢查询条目列表的字典
    """
    profile, client = _get_profile_and_client(registry, connection, db)
    effective_count = min(max(count, 1), MAX_SLOWLOG_COUNT) if count > 0 else DEFAULT_SLOWLOG_COUNT

    raw_slowlogs = await client.slowlog_get(effective_count)
    formatted_entries: list[dict[str, Any]] = []

    for item in raw_slowlogs:
        duration_us = _safe_int(item.get("duration", 0))
        cmd_raw = item.get("command", "")
        if isinstance(cmd_raw, (list, tuple)):
            cmd_str = " ".join(
                arg.decode("utf-8", errors="replace") if isinstance(arg, bytes) else str(arg)
                for arg in cmd_raw
            )
        elif isinstance(cmd_raw, bytes):
            cmd_str = cmd_raw.decode("utf-8", errors="replace")
        else:
            cmd_str = str(cmd_raw)

        if len(cmd_str) > MAX_SLOWLOG_COMMAND_LENGTH:
            cmd_str = cmd_str[:MAX_SLOWLOG_COMMAND_LENGTH] + "... [截断]"

        formatted_entries.append(
            {
                "id": _safe_int(item.get("id")),
                "start_time": _safe_int(item.get("start_time")),
                "duration_us": duration_us,
                "duration_ms": round(duration_us / 1000.0, 2),
                "command": cmd_str,
            }
        )

    return {
        "connection": profile.alias,
        "count": len(formatted_entries),
        "entries": formatted_entries,
    }


async def redis_client_list(
    registry: ConnectionRegistry,
    limit: int = DEFAULT_CLIENT_LIST_LIMIT,
    connection: str | None = None,
    db: int | None = None,
) -> dict[str, Any]:
    """检视当前已连接客户端会话列表，用于诊断连接堆积、慢客户端或阻塞会话。

    @param registry 连接注册中心实例
    @param limit 最大返回客户端条目（默认 20，硬上限 100）
    @param connection 目标连接别名（可选，缺省为默认连接）
    @param db 目标数据库编号（可选，0~15）
    @return 包含客户端诊断属性列表与总数的字典
    """
    profile, client = _get_profile_and_client(registry, connection, db)
    effective_limit = (
        min(max(limit, 1), MAX_CLIENT_LIST_LIMIT) if limit > 0 else DEFAULT_CLIENT_LIST_LIMIT
    )

    raw_clients = await client.client_list()
    total_clients = len(raw_clients)
    selected_clients = raw_clients[:effective_limit]

    formatted_clients: list[dict[str, Any]] = []
    for c in selected_clients:
        formatted_clients.append(
            {
                "id": str(c.get("id") or ""),
                "addr": str(c.get("addr") or ""),
                "name": str(c.get("name") or ""),
                "age": _safe_int(c.get("age")),
                "idle": _safe_int(c.get("idle")),
                "flags": str(c.get("flags") or ""),
                "db": _safe_int(c.get("db")),
                "cmd": str(c.get("cmd") or ""),
            }
        )

    return {
        "connection": profile.alias,
        "total_clients": total_clients,
        "returned_clients": len(formatted_clients),
        "clients": formatted_clients,
        "is_truncated": total_clients > effective_limit,
    }


def register_admin_tools(server: Any, registry: ConnectionRegistry) -> None:
    """将运维性能诊断相关工具挂载至 MCP 服务端。

    @param server MCP 服务端实例 (FastMCP / MCPServer)
    @param registry 连接注册中心单例
    """

    @server.tool(name="redis_info")  # type: ignore[untyped-decorator]
    async def _tool_info(
        section: str | None = None,
        connection: str | None = None,
        db: int | None = None,
    ) -> dict[str, Any]:
        """获取 Redis 运行时系统性能指标与组件状态（INFO）。"""
        return await redis_info(registry, section=section, connection=connection, db=db)

    @server.tool(name="redis_dbsize")  # type: ignore[untyped-decorator]
    async def _tool_dbsize(
        connection: str | None = None,
        db: int | None = None,
    ) -> dict[str, Any]:
        """查询指定数据库中的键总数统计（DBSIZE）。"""
        return await redis_dbsize(registry, connection=connection, db=db)

    @server.tool(name="redis_get_slowlog")  # type: ignore[untyped-decorator]
    async def _tool_get_slowlog(
        count: int = DEFAULT_SLOWLOG_COUNT,
        connection: str | None = None,
        db: int | None = None,
    ) -> dict[str, Any]:
        """检索并格式化输出目标实例的最新慢查询日志（SLOWLOG GET）。"""
        return await redis_get_slowlog(registry, count=count, connection=connection, db=db)

    @server.tool(name="redis_client_list")  # type: ignore[untyped-decorator]
    async def _tool_client_list(
        limit: int = DEFAULT_CLIENT_LIST_LIMIT,
        connection: str | None = None,
        db: int | None = None,
    ) -> dict[str, Any]:
        """检视当前已连接客户端列表及阻塞状态（CLIENT LIST）。"""
        return await redis_client_list(registry, limit=limit, connection=connection, db=db)
