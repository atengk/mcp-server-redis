"""
Set 集合安全切片读取工具。

提供基于 SSCAN 游标的非阻塞集合采样，严禁全量 SMEMBERS，强制单次截断上限，防范大集合 OOM。

@author Ateng
@since 2026-10-04
"""

import logging
from typing import Any, Final

import redis.exceptions

from mcp_server_redis.core.connection import ConnectionRegistry
from mcp_server_redis.core.serializer import SafeSerializer

logger = logging.getLogger(__name__)

DEFAULT_SET_LIMIT: Final[int] = 50
MAX_SET_LIMIT: Final[int] = 200
MAX_SET_ITERATIONS: Final[int] = 50


async def redis_set_members(
    registry: ConnectionRegistry,
    key: str,
    limit: int = DEFAULT_SET_LIMIT,
    connection: str | None = None,
    db: int | None = None,
) -> dict[str, Any]:
    """安全采样读取 Set 集合成员。

    底层使用 SSCAN 游标循环迭代采样，屏蔽全量 SMEMBERS 导致的单线程阻塞与 OOM 风险。
    强制限制单次返回上限（默认 50，硬上限 200），对成员执行自适应安全序列化。

    @param registry 连接注册中心实例
    @param key 目标集合键名
    @param limit 最大采样返回条数（默认 50，硬上限 200）
    @param connection 目标连接别名（可选，缺省为默认连接）
    @param db 目标数据库编号（可选，0~15）
    @return 包含成员列表、总数及截断状态的字典
    """
    if not key:
        return {
            "key": "",
            "exists": False,
            "members": [],
            "count": 0,
            "is_truncated": False,
        }

    effective_limit = min(max(limit, 1), MAX_SET_LIMIT) if limit > 0 else DEFAULT_SET_LIMIT
    client = registry.get_client(alias=connection, db=db)

    cursor: int = 0
    accumulated_members: list[Any] = []
    seen: set[str] = set()
    iterations = 0
    has_more = False

    while True:
        iterations += 1
        try:
            cursor, batch = await client.sscan(key, cursor=cursor, count=effective_limit)
        except redis.exceptions.ResponseError as exc:
            if "WRONGTYPE" in str(exc):
                logger.warning("对非 Set 类型键 '%s' 执行 SSCAN: %s", key, exc)
                return {
                    "key": key,
                    "exists": True,
                    "members": [],
                    "count": 0,
                    "is_truncated": False,
                    "error": f"键类型不匹配: {exc}",
                }
            raise

        for item in batch:
            if len(accumulated_members) >= effective_limit:
                has_more = True
                break

            serialized = SafeSerializer.serialize_value(item)
            val = serialized.unwrap()
            val_str = str(val)
            if val_str not in seen:
                seen.add(val_str)
                accumulated_members.append(val)

        if len(accumulated_members) >= effective_limit:
            if cursor != 0:
                has_more = True
            break

        if cursor == 0 or iterations >= MAX_SET_ITERATIONS:
            break

    truncated = has_more or cursor != 0
    exists = bool(accumulated_members) or bool(await client.exists(key))

    return {
        "key": key,
        "exists": exists,
        "members": accumulated_members,
        "count": len(accumulated_members),
        "is_truncated": truncated,
    }


def register_set_tools(server: Any, registry: ConnectionRegistry) -> None:
    """将 Set 相关工具挂载至 MCP 服务端。

    @param server MCP 服务端实例 (FastMCP / MCPServer)
    @param registry 连接注册中心单例
    """

    @server.tool(name="redis_set_members")  # type: ignore[untyped-decorator]
    async def _tool_set_members(
        key: str,
        limit: int = DEFAULT_SET_LIMIT,
        connection: str | None = None,
        db: int | None = None,
    ) -> dict[str, Any]:
        """安全采样读取 Set 集合成员，使用 SSCAN 非阻塞遍历并限制数量。"""
        return await redis_set_members(
            registry,
            key=key,
            limit=limit,
            connection=connection,
            db=db,
        )
