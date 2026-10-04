"""
Hash 哈希表安全切片读取工具。

提供指定字段读取与基于 HSCAN 游标的安全分页采样，强制限制单次拉取数量，防范大表 OOM。

@author Ateng
@since 2026-10-04
"""

import logging
from typing import Any, Final

import redis.exceptions

from mcp_server_redis.core.connection import ConnectionRegistry
from mcp_server_redis.core.serializer import SafeSerializer

logger = logging.getLogger(__name__)

DEFAULT_HASH_LIMIT: Final[int] = 50
MAX_HASH_LIMIT: Final[int] = 200
MAX_HASH_ITERATIONS: Final[int] = 50


async def redis_hash_get(
    registry: ConnectionRegistry,
    key: str,
    fields: list[str] | str | None = None,
    limit: int = DEFAULT_HASH_LIMIT,
    connection: str | None = None,
    db: int | None = None,
) -> dict[str, Any]:
    """安全读取 Hash 哈希表字段与对应值。

    支持通过 fields 参数查询指定字段，或在未指定时通过 HSCAN 进行游标聚合采样。
    强制施加单次硬上限（默认 50，硬上限 200），对字段值应用安全自适应序列化。

    @param registry 连接注册中心实例
    @param key 目标哈希键名
    @param fields 指定读取的字段名或列表（可选）
    @param limit 最大返回字段条数（默认 50，硬上限 200）
    @param connection 目标连接别名（可选，缺省为默认连接）
    @param db 目标数据库编号（可选，0~15）
    @return 包含字段字典、条数及截断状态的字典
    """
    if not key:
        return {
            "key": "",
            "exists": False,
            "fields": {},
            "count": 0,
            "is_truncated": False,
        }

    effective_limit = min(max(limit, 1), MAX_HASH_LIMIT) if limit > 0 else DEFAULT_HASH_LIMIT
    client = registry.get_client(alias=connection, db=db)

    # 1. 场景 A: 指定具体字段列表 (HMGET)
    if fields is not None:
        target_fields = [fields] if isinstance(fields, str) else list(fields)
        target_fields = [f for f in target_fields if f]
        truncated = len(target_fields) > effective_limit
        selected_fields = target_fields[:effective_limit]

        try:
            raw_values = await client.hmget(key, selected_fields)
        except redis.exceptions.ResponseError as exc:
            if "WRONGTYPE" in str(exc):
                logger.warning("对非 Hash 类型键 '%s' 执行 HMGET: %s", key, exc)
                return {
                    "key": key,
                    "exists": True,
                    "fields": {},
                    "count": 0,
                    "is_truncated": False,
                    "error": f"键类型不匹配: {exc}",
                }
            raise

        result_fields: dict[str, Any] = {}
        for f, v in zip(selected_fields, raw_values, strict=False):
            if v is not None:
                serialized = SafeSerializer.serialize_value(v)
                result_fields[f] = serialized.unwrap()

        exists = bool(result_fields) or bool(await client.exists(key))
        return {
            "key": key,
            "exists": exists,
            "fields": result_fields,
            "count": len(result_fields),
            "is_truncated": truncated,
        }

    # 2. 场景 B: 未指定字段，使用非阻塞 HSCAN 游标聚合采样
    cursor: int = 0
    accumulated_fields: dict[str, Any] = {}
    iterations = 0
    has_more = False

    while True:
        iterations += 1
        try:
            cursor, batch = await client.hscan(key, cursor=cursor, count=effective_limit)
        except redis.exceptions.ResponseError as exc:
            if "WRONGTYPE" in str(exc):
                logger.warning("对非 Hash 类型键 '%s' 执行 HSCAN: %s", key, exc)
                return {
                    "key": key,
                    "exists": True,
                    "fields": {},
                    "count": 0,
                    "is_truncated": False,
                    "error": f"键类型不匹配: {exc}",
                }
            raise

        items_iter: Any
        if isinstance(batch, dict):
            items_iter = batch.items()
        elif isinstance(batch, list):
            items_iter = zip(batch[0::2], batch[1::2], strict=False)
        else:
            items_iter = []

        for raw_k, raw_v in items_iter:
            if len(accumulated_fields) >= effective_limit:
                has_more = True
                break

            field_name = (
                raw_k.decode("utf-8", errors="replace") if isinstance(raw_k, bytes) else str(raw_k)
            )
            serialized = SafeSerializer.serialize_value(raw_v)
            accumulated_fields[field_name] = serialized.unwrap()

        if len(accumulated_fields) >= effective_limit:
            if cursor != 0:
                has_more = True
            break

        if cursor == 0 or iterations >= MAX_HASH_ITERATIONS:
            break

    truncated = has_more or cursor != 0
    exists = bool(accumulated_fields) or bool(await client.exists(key))

    return {
        "key": key,
        "exists": exists,
        "fields": accumulated_fields,
        "count": len(accumulated_fields),
        "is_truncated": truncated,
    }


def register_hash_tools(server: Any, registry: ConnectionRegistry) -> None:
    """将 Hash 相关工具挂载至 MCP 服务端。

    @param server MCP 服务端实例 (FastMCP / MCPServer)
    @param registry 连接注册中心单例
    """

    @server.tool(name="redis_hash_get")  # type: ignore[untyped-decorator]
    async def _tool_hash_get(
        key: str,
        fields: list[str] | str | None = None,
        limit: int = DEFAULT_HASH_LIMIT,
        connection: str | None = None,
        db: int | None = None,
    ) -> dict[str, Any]:
        """安全读取 Hash 哈希表字段，支持指定字段查询与全表 HSCAN 分页采样。"""
        return await redis_hash_get(
            registry,
            key=key,
            fields=fields,
            limit=limit,
            connection=connection,
            db=db,
        )
