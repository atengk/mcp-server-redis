"""
连接模型与注册中心契约测试。

@author Ateng
@since 2026-10-04
"""

import pytest

from mcp_server_redis.core.connection import (
    ConnectionConfigError,
    ConnectionNotFoundError,
    ConnectionProfile,
    ConnectionRegistry,
    InvalidDatabaseError,
    mask_redis_url,
)


def test_mask_redis_url_with_password() -> None:
    """验证包含密码的 Redis URL 正确脱敏为掩码。"""
    url = "redis://:my_super_secret@localhost:6379/0"
    masked = mask_redis_url(url)
    assert masked == "redis://:***@localhost:6379/0"


def test_mask_redis_url_with_user_and_password() -> None:
    """验证包含用户名和密码的 Redis URL 正确脱敏。"""
    url = "rediss://admin:secret123@redis.example.com:6380/2"
    masked = mask_redis_url(url)
    assert masked == "rediss://admin:***@redis.example.com:6380/2"


def test_mask_redis_url_without_password() -> None:
    """验证无密码的 Redis URL 保持原样不被破坏。"""
    url = "redis://localhost:6379/0"
    masked = mask_redis_url(url)
    assert masked == "redis://localhost:6379/0"


def test_connection_profile_defaults_and_masked_url() -> None:
    """验证 ConnectionProfile 模型默认值及 masked_url 属性。"""
    profile = ConnectionProfile(
        alias="local",
        url="redis://:secret@127.0.0.1:6379/0",
    )
    assert profile.alias == "local"
    assert profile.url == "redis://:secret@127.0.0.1:6379/0"
    assert profile.readonly is True
    assert profile.db == 0
    assert profile.masked_url == "redis://:***@127.0.0.1:6379/0"


def test_connection_profile_parse_db_from_url() -> None:
    """验证当未显式指定 db 时从 URL 自动解析出默认 db。"""
    profile = ConnectionProfile(
        alias="dev-db5",
        url="redis://127.0.0.1:6379/5",
    )
    assert profile.db == 5


def test_registry_from_url_default() -> None:
    """验证从单个 URL 构建注册中心时的默认连接配置。"""
    registry = ConnectionRegistry.from_url(
        url="redis://127.0.0.1:6379/0",
        readonly=False,
        description="单机测试",
    )
    assert registry.default_alias == "default"
    default_profile = registry.get_profile()
    assert default_profile.alias == "default"
    assert default_profile.readonly is False
    assert default_profile.description == "单机测试"
    assert len(registry.list_profiles()) == 1


def test_registry_from_yaml_file(tmp_path: pytest.TempPathFactory) -> None:
    """验证从 YAML 配置文件正确解析多实例连接档案。"""
    yaml_content = """
default: local

connections:
  local:
    url: "redis://127.0.0.1:6379/0"
    readonly: false
    description: "本地连接"
  remote-readonly:
    url: "redis://:pwd@remote.host:6379/1"
    readonly: true
    description: "远端只读"
"""
    config_file = tmp_path / "connections.yaml"  # type: ignore[operator]
    config_file.write_text(yaml_content, encoding="utf-8")

    registry = ConnectionRegistry.from_file(config_file)
    assert registry.default_alias == "local"
    assert len(registry.list_profiles()) == 2

    local = registry.get_profile("local")
    assert local.readonly is False
    assert local.db == 0

    remote = registry.get_profile("remote-readonly")
    assert remote.readonly is True
    assert remote.db == 1
    assert remote.masked_url == "redis://:***@remote.host:6379/1"


def test_registry_from_json_file(tmp_path: pytest.TempPathFactory) -> None:
    """验证从 JSON 配置文件正确解析多实例连接档案。"""
    json_content = """{
  "default": "prod",
  "connections": {
    "prod": {
      "url": "redis://127.0.0.1:6379/2",
      "readonly": true
    }
  }
}"""
    config_file = tmp_path / "connections.json"  # type: ignore[operator]
    config_file.write_text(json_content, encoding="utf-8")

    registry = ConnectionRegistry.from_file(config_file)
    assert registry.default_alias == "prod"
    profile = registry.get_profile()
    assert profile.alias == "prod"
    assert profile.db == 2
    assert profile.readonly is True


def test_registry_missing_file_raises_error() -> None:
    """验证指定不存在的文件时抛出 ConnectionConfigError。"""
    with pytest.raises(ConnectionConfigError, match="配置文件不存在"):
        ConnectionRegistry.from_file("non_existent_file.yaml")


def test_registry_invalid_yaml_raises_error(tmp_path: pytest.TempPathFactory) -> None:
    """验证默认别名不在连接列表中时抛出 ConnectionConfigError。"""
    yaml_content = """
default: nonexistent
connections:
  local:
    url: "redis://localhost:6379/0"
"""
    config_file = tmp_path / "invalid.yaml"  # type: ignore[operator]
    config_file.write_text(yaml_content, encoding="utf-8")

    with pytest.raises(ConnectionConfigError, match="默认连接"):
        ConnectionRegistry.from_file(config_file)


def test_registry_unknown_alias_raises_not_found() -> None:
    """验证查询未知别名时抛出 ConnectionNotFoundError。"""
    registry = ConnectionRegistry.from_url("redis://localhost:6379/0")
    with pytest.raises(ConnectionNotFoundError, match="未找到连接别名"):
        registry.get_profile("unknown")


@pytest.mark.asyncio
async def test_registry_get_client_defaults() -> None:
    """验证获取客户端时缺省使用默认连接别名与该连接档案默认 DB。"""
    registry = ConnectionRegistry.from_url("redis://localhost:6379/2")
    client = registry.get_client()
    assert client is not None
    # 验证底层连接参数绑定的 db 为 2
    assert client.connection_pool.connection_kwargs.get("db") == 2
    await registry.aclose()


@pytest.mark.asyncio
async def test_registry_get_client_stateless_routing_custom_db() -> None:
    """验证无状态多库路由：动态传入不同 db 得到绑定各 db 的客户端。"""
    registry = ConnectionRegistry.from_url("redis://localhost:6379/0")
    client_db0 = registry.get_client(db=0)
    client_db5 = registry.get_client(db=5)

    assert client_db0.connection_pool.connection_kwargs.get("db") == 0
    assert client_db5.connection_pool.connection_kwargs.get("db") == 5
    assert client_db0 is not client_db5
    await registry.aclose()


def test_registry_get_client_invalid_db_raises_error() -> None:
    """验证传入非法数据库编号（小于 0 或大于 15）时抛出 InvalidDatabaseError。"""
    registry = ConnectionRegistry.from_url("redis://localhost:6379/0")
    with pytest.raises(InvalidDatabaseError, match="数据库编号必须在 0 到 15 之间"):
        registry.get_client(db=-1)

    with pytest.raises(InvalidDatabaseError, match="数据库编号必须在 0 到 15 之间"):
        registry.get_client(db=16)


@pytest.mark.asyncio
async def test_registry_client_caching_and_aclose() -> None:
    """验证相同别名和 DB 复用已缓存的客户端，并在 aclose 时释放。"""
    registry = ConnectionRegistry.from_url("redis://localhost:6379/0")
    client1 = registry.get_client(db=3)
    client2 = registry.get_client(db=3)
    assert client1 is client2

    await registry.aclose()
    # 再次获取时重新创建
    client3 = registry.get_client(db=3)
    assert client3 is not client1
    await registry.aclose()


def test_connection_profile_safe_repr_masks_password() -> None:
    """验证 ConnectionProfile 的 repr 格式绝不泄漏明文密码。"""
    profile = ConnectionProfile(
        alias="prod",
        url="redis://:super_secret_password@127.0.0.1:6379/0",
    )
    repr_str = repr(profile)
    assert "super_secret_password" not in repr_str
    assert ":***@" in repr_str


@pytest.mark.asyncio
async def test_registry_get_client_stateless_routing_unix_socket() -> None:
    """验证 Unix Domain Socket 路径切库时路径不被破坏并正确注入 db。"""
    registry = ConnectionRegistry.from_url("unix:///var/run/redis.sock?db=0")
    client = registry.get_client(db=7)
    assert client.connection_pool.connection_kwargs.get("db") == 7
    assert client.connection_pool.connection_kwargs.get("path") == "/var/run/redis.sock"
    await registry.aclose()



