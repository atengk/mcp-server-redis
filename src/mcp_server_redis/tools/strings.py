"""
字符串读写、TTL 设置与二次确认删除门禁工具。

提供安全读取（智能 JSON 探测与二进制转码）、受控写入、键生存时间管理及防误删二次确认门禁。

@author Ateng
@since 2026-10-04
"""

import logging
from typing import Any

import redis.exceptions

from mcp_server_redis.core.connection import ConnectionRegistry
from mcp_server_redis.core.guard import SecurityGuard
from mcp_server_redis.core.serializer import SafeSerializer

logger = logging.getLogger(__name__)

# 内部默认安全守卫单例（无状态）
_default_guard = SecurityGuard(allow_write=False)


def _make_empty_string_result(key: str) -> dict[str, Any]:
    """生成键不存在或空键时的标准返回值字典。

    @param key 目标键名
    @return 标准结构的空字符串结果字典
    """
    return {
        "key": key,
        "exists": False,
        "value": None,
        "json_data": None,
        "is_binary": False,
        "is_truncated": False,
        "total_length": 0,
    }


def _verify_write_permission(
    registry: ConnectionRegistry,
    connection: str | None,
    guard: SecurityGuard | None,
) -> None:
    """验证目标连接的双重写门禁权限。

    @param registry 连接注册中心实例
    @param connection 目标连接别名
    @param guard 安全守卫单例
    @throws ReadOnlyModeError 全局未开启写权限时抛出
    @throws ReadOnlyConnectionError 目标连接被标记为只读时抛出
    """
    active_guard = guard or _default_guard
    profile = registry.get_profile(alias=connection)
    active_guard.check_write_permission(profile)


async def redis_get_string(
    registry: ConnectionRegistry,
    key: str,
    parse_json: bool = True,
    connection: str | None = None,
    db: int | None = None,
    max_length: int | None = None,
) -> dict[str, Any]:
    """安全读取指定键的字符串值，支持智能 JSON 探测与 Base64 二进制转码。

    @param registry 连接注册中心实例
    @param key 待读取的目标键名
    @param parse_json 是否尝试将合法 JSON 文本反序列化为结构化对象（默认 True）
    @param connection 目标连接别名（可选，缺省为默认连接）
    @param db 目标数据库编号（可选，0~15）
    @param max_length 最大允许字符长度，超出截断（可选）
    @return 包含字符串值、JSON 结构、二进制标记及截断元数据的字典
    """
    if not key:
        return _make_empty_string_result("")

    client = registry.get_client(alias=connection, db=db)
    try:
        raw_val = await client.get(key)
    except redis.exceptions.ResponseError as exc:
        if "WRONGTYPE" in str(exc):
            logger.warning("对非 String 类型键 '%s' 执行读取: %s", key, exc)
            return {
                "key": key,
                "exists": True,
                "value": None,
                "json_data": None,
                "is_binary": False,
                "is_truncated": False,
                "total_length": 0,
                "error": f"键类型不匹配: {exc}",
            }
        raise

    if raw_val is None:
        return _make_empty_string_result(key)

    kwargs: dict[str, Any] = {"parse_json": parse_json}
    if max_length is not None:
        kwargs["max_length"] = max_length

    serialized = SafeSerializer.serialize_value(raw_val, **kwargs)
    return {
        "key": key,
        "exists": True,
        "value": serialized.value,
        "json_data": serialized.json_data,
        "is_binary": serialized.is_binary,
        "is_truncated": serialized.truncated,
        "total_length": serialized.total_length,
    }


async def redis_set_string(
    registry: ConnectionRegistry,
    key: str,
    value: str,
    ex: int | None = None,
    nx: bool = False,
    connection: str | None = None,
    db: int | None = None,
    guard: SecurityGuard | None = None,
) -> dict[str, Any]:
    """写入或更新字符串值，支持设置秒级过期时间与 NX 互斥参数，受双重写门禁保护。

    @param registry 连接注册中心实例
    @param key 目标键名
    @param value 待写入的字符串内容
    @param ex 可选秒级生存时间（必须大于 0）
    @param nx 是否启用仅在键不存在时写入互斥锁模式（默认 False）
    @param connection 目标连接别名（可选，缺省为默认连接）
    @param db 目标数据库编号（可选，0~15）
    @param guard 安全守卫实例（可选，缺省为默认单例）
    @return 包含执行结果、键名与动作状态的字典
    @throws ValueError 参数不合法时抛出
    @throws ReadOnlyModeError 全局未开启写权限时抛出
    @throws ReadOnlyConnectionError 目标连接配置为只读时抛出
    """
    if not key:
        raise ValueError("键名不能为空")
    if ex is not None and ex <= 0:
        raise ValueError("ex 必须大于 0")

    # 1. 执行双重写门禁鉴权
    _verify_write_permission(registry, connection, guard)

    # 2. 执行底层写入
    client = registry.get_client(alias=connection, db=db)
    set_kwargs: dict[str, Any] = {}
    if ex is not None:
        set_kwargs["ex"] = ex
    if nx:
        set_kwargs["nx"] = True

    raw_res = await client.set(key, value, **set_kwargs)
    success = bool(raw_res)

    return {
        "key": key,
        "success": success,
        "action": "set" if success else "none",
        "ex": ex,
        "nx": nx,
    }


async def redis_expire_key(
    registry: ConnectionRegistry,
    key: str,
    seconds: int,
    connection: str | None = None,
    db: int | None = None,
    guard: SecurityGuard | None = None,
) -> dict[str, Any]:
    """为指定键设置生存秒数（TTL），受双重写门禁保护。

    @param registry 连接注册中心实例
    @param key 目标键名
    @param seconds 生存时间秒数（必须大于 0，禁止传 0 以防旁路删除）
    @param connection 目标连接别名（可选，缺省为默认连接）
    @param db 目标数据库编号（可选，0~15）
    @param guard 安全守卫实例（可选，缺省为默认单例）
    @return 包含执行状态与秒数的字典
    @throws ValueError 参数不合法时抛出
    @throws ReadOnlyModeError 全局未开启写权限时抛出
    @throws ReadOnlyConnectionError 目标连接配置为只读时抛出
    """
    if not key:
        raise ValueError("键名不能为空")
    if seconds <= 0:
        raise ValueError("seconds 必须大于 0，禁止通过 EXPIRE 0 旁路删除键")

    # 1. 执行双重写门禁鉴权
    _verify_write_permission(registry, connection, guard)

    # 2. 执行底层 EXPIRE 指令
    client = registry.get_client(alias=connection, db=db)
    raw_res = await client.expire(key, seconds)
    success = bool(raw_res)

    return {
        "key": key,
        "seconds": seconds,
        "success": success,
    }


async def redis_delete_keys(
    registry: ConnectionRegistry,
    keys: list[str] | str,
    confirm: bool = False,
    connection: str | None = None,
    db: int | None = None,
    guard: SecurityGuard | None = None,
) -> dict[str, Any]:
    """删除一个或多个键，受双重写门禁与防误删二次确认门禁保护。

    当 confirm=False 时拒绝执行物理删除，仅返回存在状态探测与待确认说明；
    当 confirm=True 且通过写授权时方执行物理删除并返回实际删除数量。

    @param registry 连接注册中心实例
    @param keys 目标键名或键名列表
    @param confirm 二次确认标记（必须显式设为 True 方可执行物理删除）
    @param connection 目标连接别名（可选，缺省为默认连接）
    @param db 目标数据库编号（可选，0~15）
    @param guard 安全守卫实例（可选，缺省为默认单例）
    @return 删除结果或二次确认拦截提示字典
    @throws ReadOnlyModeError 全局未开启写权限时抛出
    @throws ReadOnlyConnectionError 目标连接配置为只读时抛出
    """
    target_keys = [keys] if isinstance(keys, str) else list(keys)
    target_keys = [k for k in target_keys if k]
    if not target_keys:
        return {
            "status": "empty_keys",
            "confirmed": confirm,
            "deleted_count": 0,
            "existing_count": 0,
            "existing_keys": [],
            "keys": [],
            "message": "未指定有效的待删除键",
        }

    # 1. 验证双重写门禁（删除操作属于写操作）
    _verify_write_permission(registry, connection, guard)

    client = registry.get_client(alias=connection, db=db)

    # 2. 二次确认门禁拦截判断（使用 pipeline 单次往返批量探查，消除 N+1）
    if not confirm:
        pipe = client.pipeline(transaction=False)
        for k in target_keys:
            pipe.exists(k)
        exists_results = await pipe.execute()
        existing_keys = [
            k for k, ex in zip(target_keys, exists_results, strict=False) if bool(ex)
        ]

        msg = (
            f"高危删除拦截：涉及 {len(target_keys)} 个目标键（已探明存在 {len(existing_keys)} 个）。"
            "为防止数据误删，请显式传入 confirm=True 确认执行物理删除。"
        )
        logger.info(
            "删除操作已拦截等待二次确认: connection=%s, keys=%s",
            connection or "default",
            target_keys,
        )
        return {
            "status": "confirmation_required",
            "confirmed": False,
            "message": msg,
            "keys": target_keys,
            "existing_count": len(existing_keys),
            "existing_keys": existing_keys,
            "deleted_count": 0,
        }

    # 3. 经过确认，执行物理删除
    deleted_count = await client.delete(*target_keys)
    logger.info(
        "物理删除键成功: connection=%s, db=%s, keys=%s, deleted_count=%d",
        connection or "default",
        db,
        target_keys,
        deleted_count,
    )

    return {
        "status": "success",
        "confirmed": True,
        "deleted_count": deleted_count,
        "keys": target_keys,
        "message": f"成功删除 {deleted_count} 个键",
    }


def register_string_tools(
    server: Any,
    registry: ConnectionRegistry,
    guard: SecurityGuard | None = None,
) -> None:
    """将字符串读写、TTL 设置与二次确认删除工具挂载至 MCP 服务端。

    @param server MCP 服务端实例 (FastMCP / MCPServer)
    @param registry 连接注册中心单例
    @param guard 安全守卫单例
    """

    @server.tool(name="redis_get_string")  # type: ignore[untyped-decorator]
    async def _tool_get_string(
        key: str,
        parse_json: bool = True,
        connection: str | None = None,
        db: int | None = None,
        max_length: int | None = None,
    ) -> dict[str, Any]:
        """安全读取字符串键值，自动解析 JSON 结构并支持二进制 Base64 转码与安全截断。"""
        return await redis_get_string(
            registry,
            key=key,
            parse_json=parse_json,
            connection=connection,
            db=db,
            max_length=max_length,
        )

    @server.tool(name="redis_set_string")  # type: ignore[untyped-decorator]
    async def _tool_set_string(
        key: str,
        value: str,
        ex: int | None = None,
        nx: bool = False,
        connection: str | None = None,
        db: int | None = None,
    ) -> dict[str, Any]:
        """写入或更新字符串值，支持可选过期秒数与 NX 互斥写入，受双重写门禁保护。"""
        return await redis_set_string(
            registry,
            key=key,
            value=value,
            ex=ex,
            nx=nx,
            connection=connection,
            db=db,
            guard=guard,
        )

    @server.tool(name="redis_expire_key")  # type: ignore[untyped-decorator]
    async def _tool_expire_key(
        key: str,
        seconds: int,
        connection: str | None = None,
        db: int | None = None,
    ) -> dict[str, Any]:
        """为指定键设置生存秒数（TTL），受双重写门禁保护。"""
        return await redis_expire_key(
            registry,
            key=key,
            seconds=seconds,
            connection=connection,
            db=db,
            guard=guard,
        )

    @server.tool(name="redis_delete_keys")  # type: ignore[untyped-decorator]
    async def _tool_delete_keys(
        keys: list[str] | str,
        confirm: bool = False,
        connection: str | None = None,
        db: int | None = None,
    ) -> dict[str, Any]:
        """删除一个或多个键，强制受二次确认门禁（需显式 confirm=True）与双重写门禁保护。"""
        return await redis_delete_keys(
            registry,
            keys=keys,
            confirm=confirm,
            connection=connection,
            db=db,
            guard=guard,
        )
