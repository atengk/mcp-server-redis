"""
环境变量探测、本地 .env 文件解析与分级配置决议器单元测试。

@author Ateng
@since 2026-10-04
"""

import os
from pathlib import Path
from unittest.mock import patch

from mcp_server_redis.core.env import (
    ServerConfig,
    load_dotenv_if_exists,
    parse_bool_env,
    resolve_allow_write_from_env,
    resolve_cluster_flag_from_env,
    resolve_config_path_from_env,
    resolve_log_level_from_env,
    resolve_redis_url_from_env,
    resolve_server_configuration,
    resolve_server_host_from_env,
    resolve_server_port_from_env,
    resolve_transport_from_env,
)


def test_load_dotenv_basic(tmp_path: Path) -> None:
    """验证 .env 文件基本解析，支持注释、空行、单双引号去除。"""
    dotenv_file = tmp_path / ".env"
    dotenv_file.write_text(
        """
# 这是注释行
MCP_REDIS_HOST=192.168.1.100

MCP_REDIS_PORT="6380"
MCP_REDIS_PASSWORD='MySecretPass#123'
INVALID_LINE_WITHOUT_EQUALS
        """,
        encoding="utf-8",
    )

    with patch.dict(os.environ, {}, clear=True):
        loaded = load_dotenv_if_exists(dotenv_file)
        assert loaded is True
        assert os.environ.get("MCP_REDIS_HOST") == "192.168.1.100"
        assert os.environ.get("MCP_REDIS_PORT") == "6380"
        assert os.environ.get("MCP_REDIS_PASSWORD") == "MySecretPass#123"


def test_load_dotenv_preserves_existing_system_user_env(tmp_path: Path) -> None:
    """验证系统/用户级已有环境变量不会被 .env 文件覆盖（最高优先级守卫）。"""
    dotenv_file = tmp_path / ".env"
    dotenv_file.write_text("MCP_REDIS_HOST=dotenv_host\nNEW_KEY=dotenv_val\n", encoding="utf-8")

    # 预设系统级环境变量
    with patch.dict(os.environ, {"MCP_REDIS_HOST": "system_host"}, clear=True):
        load_dotenv_if_exists(dotenv_file)
        # 已有的保持系统级，不被覆盖
        assert os.environ["MCP_REDIS_HOST"] == "system_host"
        # 新增的成功补充
        assert os.environ["NEW_KEY"] == "dotenv_val"


def test_load_dotenv_nonexistent_file() -> None:
    """验证目标 .env 文件不存在时安全返回 False 且不崩溃。"""
    assert load_dotenv_if_exists("nonexistent_dotenv_file.env") is False


def test_parse_bool_env() -> None:
    """验证布尔型环境变量的安全归一化解析。"""
    with patch.dict(
        os.environ,
        {
            "VAR_TRUE1": "true",
            "VAR_TRUE2": "1",
            "VAR_TRUE3": "YES",
            "VAR_TRUE4": "on",
            "VAR_FALSE1": "false",
            "VAR_FALSE2": "0",
            "VAR_FALSE3": "no",
            "VAR_FALSE4": "off",
            "VAR_INVALID": "random_string",
        },
        clear=True,
    ):
        assert parse_bool_env("VAR_TRUE1") is True
        assert parse_bool_env("VAR_TRUE2") is True
        assert parse_bool_env("VAR_TRUE3") is True
        assert parse_bool_env("VAR_TRUE4") is True
        assert parse_bool_env("VAR_FALSE1") is False
        assert parse_bool_env("VAR_FALSE2") is False
        assert parse_bool_env("VAR_FALSE3") is False
        assert parse_bool_env("VAR_FALSE4") is False
        assert parse_bool_env("VAR_INVALID", default=False) is False
        assert parse_bool_env("VAR_NOT_EXIST", default=True) is True


def test_resolve_redis_url_explicit_priority() -> None:
    """验证显式 MCP_REDIS_URL 具有最高优先级，覆盖离散参数。"""
    with patch.dict(
        os.environ,
        {
            "MCP_REDIS_URL": "redis://:token@explicit.host:6379/1",
            "MCP_REDIS_HOST": "discrete.host",
            "MCP_REDIS_PORT": "6380",
        },
        clear=True,
    ):
        url = resolve_redis_url_from_env()
        assert url == "redis://:token@explicit.host:6379/1"


def test_resolve_redis_url_ignores_unprefixed_legacy_env() -> None:
    """验证非规范的裸 REDIS_* 变量被严格隔离忽略，遵循单一标准。"""
    with patch.dict(
        os.environ,
        {
            "REDIS_URL": "redis://unprefixed.host:6379/0",
            "REDIS_HOST": "unprefixed.host",
        },
        clear=True,
    ):
        assert resolve_redis_url_from_env() is None


def test_resolve_redis_url_from_discrete_variables_with_special_chars() -> None:
    """验证由离散参数组装 URL，且对密码及用户名中的特殊字符（如 @, :, /）进行自动 URL 编码防御。"""
    with patch.dict(
        os.environ,
        {
            "MCP_REDIS_HOST": "103.236.97.210",
            "MCP_REDIS_PORT": "63730",
            "MCP_REDIS_PASSWORD": "Admin@123:special/pwd",
            "MCP_REDIS_USERNAME": "test_user@org",
            "MCP_REDIS_DB": "2",
        },
        clear=True,
    ):
        url = resolve_redis_url_from_env()
        # 密码与用户名中的 @ 必须被转义为 %40，确保解析时不会发生 netloc 分裂
        assert url is not None
        assert "Admin%40123%3Aspecial%2Fpwd" in url
        assert "test_user%40org" in url
        assert url.startswith(
            "redis://test_user%40org:Admin%40123%3Aspecial%2Fpwd@103.236.97.210:63730/2"
        )


def test_resolve_redis_url_discrete_defaults() -> None:
    """验证仅提供部分离散参数时自动补全默认 Host 和 Port。"""
    with patch.dict(
        os.environ,
        {"MCP_REDIS_PASSWORD": "simplepassword"},
        clear=True,
    ):
        url = resolve_redis_url_from_env()
        assert url == "redis://:simplepassword@localhost:6379/0"


def test_resolve_redis_url_none_when_empty() -> None:
    """验证未提供任何相关变量时返回 None。"""
    with patch.dict(os.environ, {}, clear=True):
        assert resolve_redis_url_from_env() is None


def test_resolve_config_path_and_allow_write_from_env() -> None:
    """验证配置文件路径与双通道写权限判定（正向开启与反向解除只读）。"""
    # 1. 正向开启 MCP_REDIS_ALLOW_WRITE
    with patch.dict(
        os.environ,
        {"MCP_REDIS_CONFIG": "/etc/redis/connections.yaml", "MCP_REDIS_ALLOW_WRITE": "true"},
        clear=True,
    ):
        assert resolve_config_path_from_env() == "/etc/redis/connections.yaml"
        assert resolve_allow_write_from_env() is True

    # 2. 反向显式解除只读 MCP_REDIS_READ_ONLY=false/0
    with patch.dict(
        os.environ,
        {"MCP_REDIS_READ_ONLY": "false"},
        clear=True,
    ):
        assert resolve_allow_write_from_env() is True

    with patch.dict(
        os.environ,
        {"MCP_REDIS_READ_ONLY": "0"},
        clear=True,
    ):
        assert resolve_allow_write_from_env() is True

    # 3. 默认情况下保持只读 (False)
    with patch.dict(os.environ, {}, clear=True):
        assert resolve_config_path_from_env() is None
        assert resolve_allow_write_from_env() is False

    # 4. 显式设为只读 MCP_REDIS_READ_ONLY=true
    with patch.dict(
        os.environ,
        {"MCP_REDIS_READ_ONLY": "true", "MCP_REDIS_ALLOW_WRITE": "false"},
        clear=True,
    ):
        assert resolve_allow_write_from_env() is False


def test_resolve_server_configuration_cli_overrides_env() -> None:
    """验证 CLI 参数绝对优先于环境变量。"""
    with patch.dict(
        os.environ,
        {
            "MCP_REDIS_URL": "redis://env.host:6379/0",
            "MCP_REDIS_CONFIG": "/path/to/env.yaml",
            "MCP_REDIS_ALLOW_WRITE": "false",
            "MCP_REDIS_LOG_LEVEL": "ERROR",
        },
        clear=True,
    ):
        res = resolve_server_configuration(
            cli_url="redis://cli.host:6379/2",
            cli_config="/path/to/cli.yaml",
            cli_allow_write=True,
            cli_log_level="DEBUG",
        )
        assert res.url == "redis://cli.host:6379/2"
        assert res.config == "/path/to/cli.yaml"
        assert res.allow_write is True
        assert res.log_level == "DEBUG"


def test_resolve_server_configuration_fallback_defaults() -> None:
    """验证无任何传参与环境变量时落入系统安全默认配置。"""
    with patch.dict(os.environ, {}, clear=True):
        res = resolve_server_configuration()
        assert res.url == "redis://localhost:6379/0"
        assert res.config is None
        assert res.allow_write is False
        assert res.log_level == "INFO"


def test_resolve_server_configuration_log_level_priority() -> None:
    """验证配置决议器对日志级别的优先级判定（CLI > 环境变量 > 默认 INFO）。"""
    # 1. CLI 优先于环境变量
    with patch.dict(os.environ, {"MCP_REDIS_LOG_LEVEL": "WARNING"}, clear=True):
        res = resolve_server_configuration(cli_log_level="DEBUG")
        assert isinstance(res, ServerConfig)
        assert res.log_level == "DEBUG"

    # 2. 未传 CLI 时采用环境变量
    with patch.dict(os.environ, {"MCP_REDIS_LOG_LEVEL": "error"}, clear=True):
        res = resolve_server_configuration()
        assert res.log_level == "ERROR"

    # 3. 均未指定时回退至 INFO
    with patch.dict(os.environ, {}, clear=True):
        res = resolve_server_configuration()
        assert res.log_level == "INFO"

    # 4. CLI 传入非法级别时回退至 INFO
    with patch.dict(os.environ, {}, clear=True):
        res = resolve_server_configuration(cli_log_level="INVALID")
        assert res.log_level == "INFO"


def test_resolve_server_configuration_transport_priority() -> None:
    """验证配置决议器对传输模式、主机与端口的优先级判定（CLI > 环境变量 > 默认保底）。"""
    # 1. 默认缺省保底值
    with patch.dict(os.environ, {}, clear=True):
        res = resolve_server_configuration()
        assert res.transport == "stdio"
        assert res.host == "0.0.0.0"
        assert res.port == 8000

    # 2. 环境变量决议
    with patch.dict(
        os.environ,
        {
            "MCP_REDIS_TRANSPORT": "sse",
            "MCP_REDIS_SERVER_HOST": "10.0.0.1",
            "MCP_REDIS_SERVER_PORT": "9090",
        },
        clear=True,
    ):
        res = resolve_server_configuration()
        assert res.transport == "sse"
        assert res.host == "10.0.0.1"
        assert res.port == 9090

    # 3. CLI 参数绝对优先于环境变量
    with patch.dict(
        os.environ,
        {
            "MCP_REDIS_TRANSPORT": "stdio",
            "MCP_REDIS_SERVER_HOST": "10.0.0.1",
            "MCP_REDIS_SERVER_PORT": "9090",
        },
        clear=True,
    ):
        res = resolve_server_configuration(
            cli_transport="sse",
            cli_host="127.0.0.1",
            cli_port=8080,
        )
        assert res.transport == "sse"
        assert res.host == "127.0.0.1"
        assert res.port == 8080

    # 4. CLI 传入非法 transport 时回退至 stdio
    with patch.dict(os.environ, {}, clear=True):
        res = resolve_server_configuration(cli_transport="websocket")
        assert res.transport == "stdio"


def test_resolve_log_level_from_env_defaults() -> None:
    """验证未设置 MCP_REDIS_LOG_LEVEL 时保底默认返回 INFO。"""
    with patch.dict(os.environ, {}, clear=True):
        assert resolve_log_level_from_env() == "INFO"


def test_resolve_log_level_from_env_valid_cases() -> None:
    """验证合法日志级别正常解析，支持大小写不敏感与前后空白去除。"""
    test_cases = [
        ("DEBUG", "DEBUG"),
        ("debug", "DEBUG"),
        ("  info  ", "INFO"),
        ("WARNING", "WARNING"),
        ("Warning", "WARNING"),
        ("error", "ERROR"),
        ("ERROR", "ERROR"),
    ]
    for env_val, expected in test_cases:
        with patch.dict(os.environ, {"MCP_REDIS_LOG_LEVEL": env_val}, clear=True):
            assert resolve_log_level_from_env() == expected


def test_resolve_log_level_from_env_invalid_fallback() -> None:
    """验证非法或未知日志级别安全降级为默认 INFO。"""
    invalid_cases = [
        "CRITICAL",
        "TRACE",
        "UNKNOWN",
        "123",
        "",
        "   ",
    ]
    for invalid_val in invalid_cases:
        with patch.dict(os.environ, {"MCP_REDIS_LOG_LEVEL": invalid_val}, clear=True):
            assert resolve_log_level_from_env() == "INFO"


def test_resolve_transport_from_env() -> None:
    """验证从环境变量解析传输模式，支持大小写不敏感与安全回退 stdio。"""
    # 1. 默认缺省
    with patch.dict(os.environ, {}, clear=True):
        assert resolve_transport_from_env() == "stdio"

    # 2. 合法值测试
    test_cases = [
        ("stdio", "stdio"),
        ("STDIO", "stdio"),
        ("  stdio  ", "stdio"),
        ("sse", "sse"),
        ("SSE", "sse"),
        ("  sse  ", "sse"),
    ]
    for raw_val, expected in test_cases:
        with patch.dict(os.environ, {"MCP_REDIS_TRANSPORT": raw_val}, clear=True):
            assert resolve_transport_from_env() == expected

    # 3. 非法值降级
    with patch.dict(os.environ, {"MCP_REDIS_TRANSPORT": "grpc"}, clear=True):
        assert resolve_transport_from_env() == "stdio"


def test_resolve_server_host_from_env() -> None:
    """验证从环境变量解析服务绑定主机，缺省保底 0.0.0.0。"""
    with patch.dict(os.environ, {}, clear=True):
        assert resolve_server_host_from_env() == "0.0.0.0"

    with patch.dict(os.environ, {"MCP_REDIS_SERVER_HOST": "127.0.0.1"}, clear=True):
        assert resolve_server_host_from_env() == "127.0.0.1"


def test_resolve_server_port_from_env() -> None:
    """验证从环境变量解析服务监听端口，非法时保底 8000。"""
    with patch.dict(os.environ, {}, clear=True):
        assert resolve_server_port_from_env() == 8000

    with patch.dict(os.environ, {"MCP_REDIS_SERVER_PORT": "9090"}, clear=True):
        assert resolve_server_port_from_env() == 9090

    with patch.dict(os.environ, {"MCP_REDIS_SERVER_PORT": "not_a_number"}, clear=True):
        assert resolve_server_port_from_env() == 8000


def test_resolve_cluster_flag_from_env() -> None:
    """验证从环境变量解析集群模式开关，支持真假值归一化与缺省 False。"""
    with patch.dict(os.environ, {}, clear=True):
        assert resolve_cluster_flag_from_env() is False

    for truthy in ["true", "1", "yes", "on", "True", "TRUE"]:
        with patch.dict(os.environ, {"MCP_REDIS_CLUSTER": truthy}, clear=True):
            assert resolve_cluster_flag_from_env() is True

    for falsy in ["false", "0", "no", "off", "invalid"]:
        with patch.dict(os.environ, {"MCP_REDIS_CLUSTER": falsy}, clear=True):
            assert resolve_cluster_flag_from_env() is False


def test_resolve_server_configuration_cluster_precedence() -> None:
    """验证 resolve_server_configuration 中集群模式配置优先级（CLI > 环境变量 > 默认 False）。"""
    # 1. 默认保底 False
    with patch.dict(os.environ, {}, clear=True):
        cfg = resolve_server_configuration()
        assert cfg.is_cluster is False

    # 2. 环境变量生效
    with patch.dict(os.environ, {"MCP_REDIS_CLUSTER": "true"}, clear=True):
        cfg = resolve_server_configuration()
        assert cfg.is_cluster is True

    # 3. CLI 显式覆盖环境变量
    with patch.dict(os.environ, {"MCP_REDIS_CLUSTER": "true"}, clear=True):
        cfg = resolve_server_configuration(cli_cluster=False)
        assert cfg.is_cluster is False

    with patch.dict(os.environ, {"MCP_REDIS_CLUSTER": "false"}, clear=True):
        cfg = resolve_server_configuration(cli_cluster=True)
        assert cfg.is_cluster is True
