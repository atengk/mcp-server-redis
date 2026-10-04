"""
实例信息检视与健康探活工具。

提供连接列表查阅与网络往返延迟度量能力。

@author Ateng
@since 2026-10-04
"""

import logging
import time
from typing import Any

import redis.exceptions

from mcp_server_redis.core.connection import (
    ConnectionNotFoundError,
    ConnectionRegistry,
    InvalidDatabaseError,
)

logger = logging.getLogger(__name__)


async def redis_list_connections(registry: ConnectionRegistry) -> dict[str, Any]:
    """查看所有已配置的 Redis 连接别名、脱敏 URL 及默认连接标识。

    @param registry 连接注册中心实例
    @return 包含连接列表与默认连接信息的字典
    """
    profiles = registry.list_profiles()
    connections: list[dict[str, Any]] = []

    for profile in profiles:
        connections.append(
            {
                "alias": profile.alias,
                "url": profile.masked_url,
                "db": profile.db,
                "readonly": profile.readonly,
                "description": profile.description,
                "is_default": (profile.alias == registry.default_alias),
            }
        )

    return {
        "default": registry.default_alias,
        "total": len(connections),
        "connections": connections,
    }


async def redis_ping(
    registry: ConnectionRegistry,
    connection: str | None = None,
    db: int | None = None,
) -> dict[str, Any]:
    """验证目标 Redis 实例与指定逻辑库的网络连通性并度量往返延迟。

    @param registry 连接注册中心实例
    @param connection 目标连接别名（可选，缺省为默认连接）
    @param db 目标数据库编号（可选，0~15，缺省为连接自身配置的 db）
    @return 探活结果与响应耗时字典
    @throws InvalidDatabaseError 当数据库编号超出 0~15 范围时抛出
    """
    # 1. 显式校验可选 db 范围（若提供）
    if db is not None and (db < 0 or db > 15):
        raise InvalidDatabaseError(
            f"数据库编号必须在 0 到 15 之间，当前传入: {db}"
        )

    target_alias = connection if connection is not None else registry.default_alias
    target_db = db if db is not None else 0

    # 2. 获取无状态路由客户端并执行网络探活
    try:
        profile = registry.get_profile(connection)
        target_db = db if db is not None else profile.db
        client = registry.get_client(alias=connection, db=db)
        start_time = time.perf_counter()
        response = await client.ping()
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

        return {
            "status": "ok",
            "connection": profile.alias,
            "db": target_db,
            "latency_ms": latency_ms,
            "response": "PONG" if response is True else str(response),
        }
    except (redis.exceptions.RedisError, ConnectionNotFoundError) as exc:
        logger.warning(
            "Redis 探活失败 (connection: %s): %s",
            target_alias,
            exc,
        )
        return {
            "status": "error",
            "connection": target_alias,
            "db": target_db,
            "error": str(exc),
        }


def register_instance_tools(server: Any, registry: ConnectionRegistry) -> None:
    """将实例相关工具挂载注册至 MCP 服务端。

    @param server MCP 服务端实例 (FastMCP / MCPServer)
    @param registry 连接注册中心单例
    """

    @server.tool(name="redis_list_connections")  # type: ignore[untyped-decorator]
    async def _tool_list_connections() -> dict[str, Any]:
        """查看当前所有可用的 Redis 连接别名、脱敏连接信息与默认连接。"""
        return await redis_list_connections(registry)

    @server.tool(name="redis_ping")  # type: ignore[untyped-decorator]
    async def _tool_ping(
        connection: str | None = None,
        db: int | None = None,
    ) -> dict[str, Any]:
        """快速验证目标 Redis 实例与逻辑库的连通性与网络往返延迟。"""
        return await redis_ping(registry, connection=connection, db=db)
