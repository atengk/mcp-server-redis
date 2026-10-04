"""
自适应双模连接注册中心与连接模型。

负责单连接与多实例配置文件解析、连接池生命周期管控、凭据安全脱敏及无状态动态多库路由。

@author Ateng
@since 2026-10-04
"""

import json
import logging
import urllib.parse
from pathlib import Path
from typing import Any

import redis.asyncio as aioredis
import redis.exceptions
import yaml
from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)


class ConnectionConfigError(ValueError):
    """连接配置格式或参数错误。

    @author Ateng
    @since 2026-10-04
    """


class ConnectionNotFoundError(KeyError):
    """指定连接别名未找到。

    @author Ateng
    @since 2026-10-04
    """


class InvalidDatabaseError(ValueError):
    """无效的数据库编号 (DB 必须在 0~15 之间)。

    @author Ateng
    @since 2026-10-04
    """


def mask_redis_url(url: str) -> str:
    """对 Redis URL 中的密码凭据进行掩码脱敏。

    @param url 待脱敏的完整 Redis 连接 URL
    @return 密码已被掩码替换的安全 URL
    """
    if not url:
        return ""

    parsed = urllib.parse.urlsplit(url)
    if "@" not in parsed.netloc:
        return url

    userinfo, hostport = parsed.netloc.rsplit("@", 1)
    if ":" in userinfo:
        user, _ = userinfo.split(":", 1)
        masked_userinfo = f"{user}:***"
    else:
        masked_userinfo = "***"

    masked_netloc = f"{masked_userinfo}@{hostport}"
    return urllib.parse.urlunsplit(
        (parsed.scheme, masked_netloc, parsed.path, parsed.query, parsed.fragment)
    )


def _extract_db_from_url(url: str) -> int | None:
    """从 Redis URL 的路径中提取数据库编号。

    @param url Redis 连接 URL
    @return 提取出的数据库编号，若无有效路径则返回 None
    """
    parsed = urllib.parse.urlsplit(url)
    path = parsed.path.lstrip("/")
    if path.isdigit():
        return int(path)
    return None


class ConnectionProfile(BaseModel):
    """Redis 连接档案模型。

    @author Ateng
    @since 2026-10-04
    """

    alias: str
    url: str
    readonly: bool = True
    description: str = ""
    db: int = Field(default=0, ge=0, le=15)

    @model_validator(mode="before")
    @classmethod
    def populate_defaults_from_url(cls, data: Any) -> Any:
        """从 URL 自动推断缺省的数据库编号。"""
        if isinstance(data, dict):
            url = data.get("url", "")
            if "db" not in data and url:
                parsed_db = _extract_db_from_url(url)
                if parsed_db is not None:
                    data["db"] = parsed_db
        return data

    @property
    def masked_url(self) -> str:
        """获取脱敏后的安全连接 URL。"""
        return mask_redis_url(self.url)

    def __repr__(self) -> str:
        """安全模型字符串展示，避免在日志与控制台中泄漏明文凭据。"""
        return (
            f"ConnectionProfile(alias='{self.alias}', url='{self.masked_url}', "
            f"readonly={self.readonly}, db={self.db}, description='{self.description}')"
        )


class _RawConnectionEntry(BaseModel):
    """原始配置文件中单个连接项定义。

    @author Ateng
    @since 2026-10-04
    """

    url: str
    readonly: bool = True
    description: str = ""
    db: int | None = Field(default=None, ge=0, le=15)


class _RawConfigFile(BaseModel):
    """原始多实例连接配置文件结构。

    @author Ateng
    @since 2026-10-04
    """

    default: str
    connections: dict[str, _RawConnectionEntry] = Field(default_factory=dict)


class ConnectionRegistry:
    """自适应双模连接注册中心。

    管理单实例或多环境 Redis 连接档案及连接池生命周期。

    @author Ateng
    @since 2026-10-04
    """

    def __init__(self, default_alias: str = "default") -> None:
        """初始化空的连接注册中心。

        @param default_alias 默认使用的连接别名
        """
        self._profiles: dict[str, ConnectionProfile] = {}
        self._clients: dict[tuple[str, int], aioredis.Redis] = {}
        self.default_alias: str = default_alias

    @property
    def profiles(self) -> dict[str, ConnectionProfile]:
        """获取当前所有已注册连接档案映射。"""
        return dict(self._profiles)

    def register(self, profile: ConnectionProfile, is_default: bool = False) -> None:
        """注册单个连接档案。

        @param profile 连接档案模型实例
        @param is_default 是否设定为默认连接
        """
        self._profiles[profile.alias] = profile
        logger.info(
            "已注册 Redis 连接档案: alias='%s', url='%s', db=%d, readonly=%s",
            profile.alias,
            profile.masked_url,
            profile.db,
            profile.readonly,
        )
        if is_default:
            self.default_alias = profile.alias

    def get_profile(self, alias: str | None = None) -> ConnectionProfile:
        """按别名获取连接档案，若未传参则返回默认连接档案。

        @param alias 连接别名（可选）
        @return 对应的连接档案模型
        @throws ConnectionNotFoundError 别名不存在时抛出
        """
        target_alias = alias if alias is not None else self.default_alias
        if target_alias not in self._profiles:
            raise ConnectionNotFoundError(f"未找到连接别名: '{target_alias}'")
        return self._profiles[target_alias]

    def list_profiles(self) -> list[ConnectionProfile]:
        """获取所有已注册的连接档案列表。

        @return 连接档案列表，空时返回空列表
        """
        return list(self._profiles.values())

    def is_readonly(self, alias: str | None = None) -> bool:
        """查询指定连接是否为只读。

        @param alias 连接别名（可选）
        @return 是否只读
        """
        profile = self.get_profile(alias)
        return profile.readonly

    def get_client(
        self,
        alias: str | None = None,
        db: int | None = None,
    ) -> aioredis.Redis:
        """按别名和数据库编号以无状态路由方式获取 Redis 异步客户端。

        严格以物理绑定数据库形式分发连接池，严禁在连接上执行全局有状态 SELECT。

        @param alias 连接别名（可选，缺省为默认连接）
        @param db 数据库编号（可选，0~15，缺省为连接档案配置的 db）
        @return 绑定至目标数据库的 Redis 客户端实例
        @throws ConnectionNotFoundError 别名不存在时抛出
        @throws InvalidDatabaseError 数据库编号不在 0~15 范围时抛出
        """
        profile = self.get_profile(alias)
        target_db = db if db is not None else profile.db

        if target_db < 0 or target_db > 15:
            raise InvalidDatabaseError(
                f"数据库编号必须在 0 到 15 之间，当前传入: {target_db}"
            )

        cache_key = (profile.alias, target_db)
        if cache_key in self._clients:
            return self._clients[cache_key]

        parsed = urllib.parse.urlsplit(profile.url)
        if parsed.scheme == "unix":
            query_params = urllib.parse.parse_qs(parsed.query)
            query_params["db"] = [str(target_db)]
            new_query = urllib.parse.urlencode(query_params, doseq=True)
            new_url = urllib.parse.urlunsplit(
                (parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment)
            )
        else:
            new_url = urllib.parse.urlunsplit(
                (parsed.scheme, parsed.netloc, f"/{target_db}", parsed.query, parsed.fragment)
            )

        client = aioredis.Redis.from_url(
            new_url,
            db=target_db,
            decode_responses=False,
        )
        self._clients[cache_key] = client
        return client

    async def aclose(self) -> None:
        """异步关闭所有已缓存的 Redis 客户端与底层连接池。"""
        for client in self._clients.values():
            try:
                await client.aclose()
            except (OSError, redis.exceptions.RedisError) as exc:
                logger.warning("关闭 Redis 客户端异常: %s", exc)
        self._clients.clear()

    @classmethod
    def from_url(
        cls,
        url: str,
        alias: str = "default",
        readonly: bool = True,
        description: str = "",
    ) -> "ConnectionRegistry":
        """从单个 Redis URL 构造极简连接注册中心。

        @param url Redis 连接 URL
        @param alias 连接别名，默认 'default'
        @param readonly 是否只读，默认 True
        @param description 连接描述
        @return 已装配好默认连接的注册中心实例
        """
        registry = cls(default_alias=alias)
        profile = ConnectionProfile(
            alias=alias,
            url=url,
            readonly=readonly,
            description=description,
        )
        registry.register(profile, is_default=True)
        return registry

    @classmethod
    def from_file(cls, file_path: str | Path) -> "ConnectionRegistry":
        """从 YAML 或 JSON 配置文件加载并构造多连接注册中心。

        @param file_path 配置文件路径
        @return 已加载配置的注册中心实例
        @throws ConnectionConfigError 配置文件不存在或格式错误时抛出
        """
        path = Path(file_path)
        if not path.exists():
            raise ConnectionConfigError(f"配置文件不存在: {path}")

        try:
            content = path.read_text(encoding="utf-8")
            suffix = path.suffix.lower()
            if suffix in (".yaml", ".yml"):
                raw_data = yaml.safe_load(content)
            elif suffix == ".json":
                raw_data = json.loads(content)
            else:
                raw_data = yaml.safe_load(content)
        except (yaml.YAMLError, json.JSONDecodeError, OSError, ValueError) as exc:
            raise ConnectionConfigError(f"配置文件解析失败: {exc}") from exc

        if not isinstance(raw_data, dict):
            raise ConnectionConfigError("配置文件内容必须为键值映射字典")

        try:
            config = _RawConfigFile.model_validate(raw_data)
        except (ValueError, TypeError) as exc:
            raise ConnectionConfigError(f"配置文件数据结构不合法: {exc}") from exc

        if config.default not in config.connections:
            raise ConnectionConfigError(
                f"默认连接 '{config.default}' 不在已配置的 connections 列表中"
            )

        registry = cls(default_alias=config.default)
        for alias, entry in config.connections.items():
            profile_kwargs: dict[str, Any] = {
                "alias": alias,
                "url": entry.url,
                "readonly": entry.readonly,
                "description": entry.description,
            }
            if entry.db is not None:
                profile_kwargs["db"] = entry.db

            profile = ConnectionProfile.model_validate(profile_kwargs)
            registry.register(profile, is_default=(alias == config.default))

        return registry
