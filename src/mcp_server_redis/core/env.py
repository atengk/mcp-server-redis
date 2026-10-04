"""
环境变量探测、本地 .env 加载与服务配置分级决议器。

负责系统/用户级环境变量与本地 .env 文件安全解析，
支持整串 MCP_REDIS_URL 与离散式连接参数（Host/Port/Password 等）自动组装，
提供自动 URL 特殊字符转义与多层级配置优先级裁决。

@author Ateng
@since 2026-10-04
"""

import logging
import os
import urllib.parse
from pathlib import Path
from typing import Final, NamedTuple

logger = logging.getLogger(__name__)

# 判定为真值的环境变量字符串集合
_TRUTHY_VALUES: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on", "t", "y"})
# 判定为假值的环境变量字符串集合
_FALSY_VALUES: Final[frozenset[str]] = frozenset({"0", "false", "no", "off", "f", "n"})

# 允许的有效日志级别集合
_VALID_LOG_LEVELS: Final[frozenset[str]] = frozenset({"DEBUG", "INFO", "WARNING", "ERROR"})
# 默认日志级别保底值
_DEFAULT_LOG_LEVEL: Final[str] = "INFO"

# 允许的有效传输协议集合
_VALID_TRANSPORTS: Final[frozenset[str]] = frozenset({"stdio", "sse"})
# 默认传输协议保底值
_DEFAULT_TRANSPORT: Final[str] = "stdio"
# 默认服务绑定主机保底值
_DEFAULT_SERVER_HOST: Final[str] = "0.0.0.0"
# 默认服务监听端口保底值
_DEFAULT_SERVER_PORT: Final[int] = 8000


def load_dotenv_if_exists(dotenv_path: Path | str | None = None) -> bool:
    """探测并轻量加载本地 .env 文件至进程环境变量，绝不覆盖已存在的系统/用户级环境变量。

    @param dotenv_path 指定 .env 文件路径（可选，缺省时探测当前工作目录下的 .env）
    @return 若成功发现并加载有效文件返回 True，否则返回 False
    """
    target = Path(dotenv_path) if dotenv_path else Path.cwd() / ".env"
    if not target.is_file():
        return False

    try:
        content = target.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("读取 .env 配置文件失败: %s", exc)
        return False

    loaded_count = 0
    for line in content.splitlines():
        line = line.strip()
        # 跳过空行与注释行
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue

        key, raw_val = line.split("=", 1)
        key = key.strip()
        val = raw_val.strip()

        # 剥除可能包裹的成对单/双引号
        if (val.startswith('"') and val.endswith('"')) or (
            val.startswith("'") and val.endswith("'")
        ):
            val = val[1:-1]

        # 核心安全守则：仅注入当前进程未定义的变量，系统与用户级环境变量具有绝对优先权
        if key not in os.environ:
            os.environ[key] = val
            loaded_count += 1

    logger.debug("从 '%s' 成功补充加载 %d 个环境变量", target, loaded_count)
    return True


def parse_bool_env(key: str, default: bool = False) -> bool:
    """安全解析布尔型环境变量。

    @param key 环境变量名
    @param default 变量缺失或非法时的默认值（默认 False）
    @return 解析后的布尔值
    """
    val = os.getenv(key)
    if val is None:
        return default
    normalized = val.strip().lower()
    if normalized in _TRUTHY_VALUES:
        return True
    if normalized in _FALSY_VALUES:
        return False
    return default


def resolve_redis_url_from_env() -> str | None:
    """从环境变量解析或自动组装单实例 Redis 连接 URL。

    优先级：
    1. 显式指定的整串 `MCP_REDIS_URL`；
    2. 由离散环境变量 `MCP_REDIS_HOST`、`MCP_REDIS_PORT`、`MCP_REDIS_PASSWORD`、
       `MCP_REDIS_DB`、`MCP_REDIS_USERNAME` 自动组合。对密码及用户名中的特殊字符（如 `@`, `:`, `/`）
       自动执行 URL Percent-Encoding 编码，避免连接解析崩溃。

    @return 组装后的完整 Redis 连接 URL，若未提供任何相关变量则返回 None
    """
    # 1. 优先读取完整连接串
    explicit_url = os.getenv("MCP_REDIS_URL")
    if explicit_url:
        return explicit_url.strip()

    # 2. 探查离散变量
    host = os.getenv("MCP_REDIS_HOST")
    port_str = os.getenv("MCP_REDIS_PORT")
    password = os.getenv("MCP_REDIS_PASSWORD")
    username = os.getenv("MCP_REDIS_USERNAME")
    db_str = os.getenv("MCP_REDIS_DB")

    # 若未定义任何离散变量，返回 None 触发后续保底机制
    if not any([host, port_str, password, username, db_str]):
        return None

    target_host = host.strip() if host else "localhost"
    try:
        target_port = int(port_str.strip()) if port_str else 6379
    except ValueError:
        logger.warning("MCP_REDIS_PORT 格式非法 ('%s')，降级为默认端口 6379", port_str)
        target_port = 6379

    try:
        target_db = int(db_str.strip()) if db_str else 0
    except ValueError:
        logger.warning("MCP_REDIS_DB 格式非法 ('%s')，降级为默认数据库 0", db_str)
        target_db = 0

    # 3. 安全编码用户凭据，防御 `@` 等字符截断 netloc
    auth_part = ""
    if password is not None:
        quoted_password = urllib.parse.quote(password, safe="")
        if username:
            quoted_user = urllib.parse.quote(username, safe="")
            auth_part = f"{quoted_user}:{quoted_password}@"
        else:
            auth_part = f":{quoted_password}@"
    elif username:
        quoted_user = urllib.parse.quote(username, safe="")
        auth_part = f"{quoted_user}@"

    return f"redis://{auth_part}{target_host}:{target_port}/{target_db}"


def resolve_config_path_from_env() -> str | None:
    """从环境变量获取多实例配置文件路径。

    仅支持规范标准名称 `MCP_REDIS_CONFIG`。

    @return 配置文件路径字符串，未指定时返回 None
    """
    val = os.getenv("MCP_REDIS_CONFIG")
    return val.strip() if val else None


def resolve_allow_write_from_env() -> bool:
    """从环境变量检查是否启用写操作权限。

    支持双通道语义判定：
    1. 正向显式授权：`MCP_REDIS_ALLOW_WRITE=true/1/yes/on`；
    2. 反向显式解除只读：`MCP_REDIS_READ_ONLY=false/0/no/off`。

    @return 是否授权写权限
    """
    if parse_bool_env("MCP_REDIS_ALLOW_WRITE", default=False):
        return True
    val = os.getenv("MCP_REDIS_READ_ONLY")
    return bool(val is not None and not parse_bool_env("MCP_REDIS_READ_ONLY", default=True))


def resolve_cluster_flag_from_env() -> bool:
    """从环境变量检查是否启用 Redis Cluster 分片集群连接模式。

    读取 `MCP_REDIS_CLUSTER` 环境变量（支持 true/1/yes/on）。

    @return 是否开启分片集群模式
    """
    return parse_bool_env("MCP_REDIS_CLUSTER", default=False)


def resolve_log_level_from_env() -> str:
    """从环境变量解析运行时日志级别。

    读取 `MCP_REDIS_LOG_LEVEL` 环境变量，支持 DEBUG、INFO、WARNING、ERROR。
    自动执行大小写不敏感归一化与前后空格剥离。
    若变量未设置或取值非法，安全保底返回默认级别 "INFO"。

    @return 归一化后的有效日志级别字符串（如 "DEBUG", "INFO", "WARNING", "ERROR"）
    """
    val = os.getenv("MCP_REDIS_LOG_LEVEL")
    if not val:
        return _DEFAULT_LOG_LEVEL

    normalized = val.strip().upper()
    if normalized in _VALID_LOG_LEVELS:
        return normalized

    logger.warning(
        "环境变量 MCP_REDIS_LOG_LEVEL 取值非法 ('%s')，安全降级为默认级别 '%s'",
        val,
        _DEFAULT_LOG_LEVEL,
    )
    return _DEFAULT_LOG_LEVEL


def normalize_transport(
    transport_str: str | None,
    default: str = _DEFAULT_TRANSPORT,
) -> str:
    """归一化传输协议名称，未知值告警并安全降级。

    @param transport_str 原始协议名称输入
    @param default 缺省保底协议（默认 "stdio"）
    @return 归一化后的有效协议字符串
    """
    if not transport_str:
        return default
    normalized = transport_str.strip().lower()
    if normalized in _VALID_TRANSPORTS:
        return normalized
    logger.warning(
        "传输协议取值非法 ('%s')，安全降级为默认协议 '%s'",
        transport_str,
        default,
    )
    return default


def resolve_transport_from_env() -> str:
    """从环境变量解析传输协议。

    读取 `MCP_REDIS_TRANSPORT` 环境变量，支持 stdio、sse（大小写不敏感）。
    若变量未设置或取值非法，安全保底返回默认值 "stdio"。

    @return 归一化后的传输协议字符串（"stdio" 或 "sse"）
    """
    return normalize_transport(os.getenv("MCP_REDIS_TRANSPORT"))


def resolve_server_host_from_env() -> str:
    """从环境变量解析服务绑定主机地址。

    读取 `MCP_REDIS_SERVER_HOST` 环境变量。
    若变量未设置，安全保底返回 "0.0.0.0"。

    @return 服务监听主机地址
    """
    val = os.getenv("MCP_REDIS_SERVER_HOST")
    return val.strip() if val else _DEFAULT_SERVER_HOST


def resolve_server_port_from_env() -> int:
    """从环境变量解析服务监听端口。

    读取 `MCP_REDIS_SERVER_PORT` 环境变量。
    若变量未设置或格式非法，安全保底返回 8000。

    @return 服务监听端口整数值
    """
    val = os.getenv("MCP_REDIS_SERVER_PORT")
    if not val:
        return _DEFAULT_SERVER_PORT

    try:
        return int(val.strip())
    except ValueError:
        logger.warning(
            "环境变量 MCP_REDIS_SERVER_PORT 格式非法 ('%s')，降级为默认端口 %d",
            val,
            _DEFAULT_SERVER_PORT,
        )
        return _DEFAULT_SERVER_PORT


class ServerConfig(NamedTuple):
    """服务端运行时生效配置对象。

    继承自命名元组 (NamedTuple)，具备元组解构与属性访问双重兼容性。

    @author Ateng
    @since 2026-10-04
    @property url 生效的 Redis 连接 URL
    @property config 生效的多实例配置文件路径（或 None）
    @property allow_write 是否开启写权限
    @property log_level 生效的日志级别（如 "INFO", "DEBUG" 等）
    @property transport 生效的传输协议（"stdio" 或 "sse"）
    @property host SSE 监听地址（默认 "0.0.0.0"）
    @property port SSE 监听端口（默认 8000）
    @property is_cluster 是否开启 Redis Cluster 集群模式（默认 False）
    """

    url: str
    config: str | None
    allow_write: bool
    log_level: str
    transport: str = _DEFAULT_TRANSPORT
    host: str = _DEFAULT_SERVER_HOST
    port: int = _DEFAULT_SERVER_PORT
    is_cluster: bool = False


def resolve_server_configuration(
    cli_url: str | None = None,
    cli_config: str | None = None,
    cli_allow_write: bool = False,
    cli_log_level: str | None = None,
    cli_transport: str | None = None,
    cli_host: str | None = None,
    cli_port: int | None = None,
    cli_cluster: bool | None = None,
) -> ServerConfig:
    """统一决议服务端最终启动配置参数。

    遵循工业级配置分级优先级：
    CLI 显式参数 > 环境变量配置 > 默认保底值。

    @param cli_url CLI 命令行传入的 --url（可选）
    @param cli_config CLI 命令行传入的 --config（可选）
    @param cli_allow_write CLI 命令行传入的 --allow-write 开关
    @param cli_log_level CLI 命令行传入的 --log-level（可选）
    @param cli_transport CLI 命令行传入的 --transport（可选）
    @param cli_host CLI 命令行传入的 --host（可选）
    @param cli_port CLI 命令行传入的 --port（可选）
    @param cli_cluster CLI 命令行传入的 --cluster 开关（可选）
    @return ServerConfig 命名元组 (url, config, allow_write, log_level, transport, host, port, is_cluster)
    """
    # 1. 尝试探测并安全载入 .env 文件
    load_dotenv_if_exists()

    # 2. 决议配置文件路径（CLI > 环境变量）
    effective_config = cli_config or resolve_config_path_from_env()

    # 3. 决议连接 URL（CLI > 环境变量整串 > 离散变量组装 > 默认本地）
    effective_url = cli_url or resolve_redis_url_from_env() or "redis://localhost:6379/0"

    # 4. 决议写权限授权状态（任一途径声明开启即为 True）
    effective_allow_write = cli_allow_write or resolve_allow_write_from_env()

    # 5. 决议生效日志级别（CLI > 环境变量 > 默认保底 INFO）
    if cli_log_level is not None:
        normalized_log = cli_log_level.strip().upper()
        if normalized_log in _VALID_LOG_LEVELS:
            effective_log_level = normalized_log
        else:
            logger.warning(
                "CLI 指定的 --log-level 取值非法 ('%s')，安全降级为默认级别 '%s'",
                cli_log_level,
                _DEFAULT_LOG_LEVEL,
            )
            effective_log_level = _DEFAULT_LOG_LEVEL
    else:
        effective_log_level = resolve_log_level_from_env()

    # 6. 决议生效传输协议（CLI > 环境变量 > 默认保底 stdio）
    if cli_transport is not None:
        effective_transport = normalize_transport(cli_transport)
    else:
        effective_transport = resolve_transport_from_env()

    # 7. 决议生效服务绑定主机（CLI > 环境变量 > 默认保底 0.0.0.0）
    if cli_host is not None and cli_host.strip():
        effective_host = cli_host.strip()
    else:
        effective_host = resolve_server_host_from_env()

    # 8. 决议生效服务监听端口（CLI > 环境变量 > 默认保底 8000）
    if cli_port is not None:
        effective_port = cli_port
    else:
        effective_port = resolve_server_port_from_env()

    # 9. 决议生效集群模式（CLI > 环境变量）
    if cli_cluster is not None:
        effective_cluster = cli_cluster
    else:
        effective_cluster = resolve_cluster_flag_from_env()

    return ServerConfig(
        url=effective_url,
        config=effective_config,
        allow_write=effective_allow_write,
        log_level=effective_log_level,
        transport=effective_transport,
        host=effective_host,
        port=effective_port,
        is_cluster=effective_cluster,
    )
