"""
FastMCP 服务主装配与 CLI 命令行协议入口。

负责加载连接注册中心、装配安全守卫、挂载全部 18 个 MCP 工具并管理服务生命周期。

@author Ateng
@since 2026-10-04
"""

import argparse
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Final

from mcp.server import MCPServer

# 兼容 FastMCP 历史类型名称
FastMCP = MCPServer

# 服务端版本号常量
SERVER_VERSION: Final[str] = "1.0.2"

from mcp_server_redis.core.connection import ConnectionRegistry
from mcp_server_redis.core.env import ServerConfig, resolve_server_configuration
from mcp_server_redis.core.guard import SecurityGuard
from mcp_server_redis.tools.admin import register_admin_tools
from mcp_server_redis.tools.hashes import register_hash_tools
from mcp_server_redis.tools.instances import register_instance_tools
from mcp_server_redis.tools.keys import register_key_tools
from mcp_server_redis.tools.lists import register_list_tools
from mcp_server_redis.tools.sets import register_set_tools
from mcp_server_redis.tools.streams import register_stream_tools
from mcp_server_redis.tools.strings import register_string_tools
from mcp_server_redis.tools.zsets import register_zset_tools

logger = logging.getLogger("mcp_server_redis")


def build_argument_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。

    @return 配置完成的 ArgumentParser 实例
    """
    parser = argparse.ArgumentParser(
        prog="mcp-server-redis",
        description="生产级 Redis 模型上下文协议 (MCP) 服务端",
    )
    parser.add_argument(
        "--url",
        type=str,
        default=None,
        help="单个 Redis 连接 URL（默认读取 MCP_REDIS_URL 或 MCP_REDIS_HOST/PORT 等环境变量）",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="多实例连接配置文件路径（默认读取 MCP_REDIS_CONFIG 环境变量，支持 YAML / JSON）",
    )
    parser.add_argument(
        "--allow-write",
        action="store_true",
        default=False,
        help="显式开启写操作权限（默认全局强只读，支持通过 MCP_REDIS_ALLOW_WRITE=true 或 MCP_REDIS_READ_ONLY=false 开启）",
    )
    parser.add_argument(
        "--log-level",
        type=str.upper,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=None,
        help="运行时日志级别（DEBUG、INFO、WARNING、ERROR，默认读取 MCP_REDIS_LOG_LEVEL 或默认 INFO）",
    )
    parser.add_argument(
        "--transport",
        type=str.lower,
        choices=["stdio", "sse"],
        default=None,
        help="传输协议模式（stdio 或 sse，默认读取 MCP_REDIS_TRANSPORT 环境变量或默认 stdio）",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="SSE 模式服务监听主机（默认读取 MCP_REDIS_SERVER_HOST 环境变量或默认 0.0.0.0）",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="SSE 模式服务监听端口（默认读取 MCP_REDIS_SERVER_PORT 环境变量或默认 8000）",
    )
    parser.add_argument(
        "--cluster",
        action="store_true",
        default=False,
        help="激活 Redis Cluster 分片集群连接模式（默认读取 MCP_REDIS_CLUSTER 环境变量或连接配置）",
    )
    return parser


def parse_cli_arguments(args: list[str] | None = None) -> dict[str, Any]:
    """解析命令行参数或传入参数列表。

    @param args 可选自定义参数列表，缺省时读取 sys.argv[1:]
    @return 包含 url, config, allow_write, log_level, transport, host, port, cluster 键的配置字典
    """
    parser = build_argument_parser()
    parsed = parser.parse_args(args)
    return {
        "url": parsed.url,
        "config": parsed.config,
        "allow_write": parsed.allow_write,
        "log_level": parsed.log_level,
        "transport": parsed.transport,
        "host": parsed.host,
        "port": parsed.port,
        "cluster": parsed.cluster,
    }


def create_app(
    url: str | None = None,
    config: str | None = None,
    allow_write: bool = False,
    log_level: str | None = None,
    cluster: bool | None = None,
    server_config: ServerConfig | None = None,
) -> FastMCP:
    """工厂函数：根据配置初始化连接注册中心、安全守卫并装配全部 18 个 MCP 工具。

    支持多层级配置决议：CLI 显式参数 > 环境变量整串/离散参数 > 本地 .env > 系统保底默认。

    @param url 单实例 Redis 连接串（可选）
    @param config 多实例配置文件路径（可选）
    @param allow_write 是否开启写操作权限（默认 False）
    @param log_level 运行时日志级别（可选）
    @param cluster 是否开启 Redis Cluster 分片集群模式（可选）
    @param server_config 预决议完成的服务端配置对象（可选，若提供则优先采用，避免二次决议）
    @return 已经完成全部工具装配与生命周期绑定的 FastMCP 实例
    """
    # 0. 综合决议配置优先级（若已传入预决议对象直接复用，否则启动全量决议）
    effective_config = server_config or resolve_server_configuration(
        cli_url=url,
        cli_config=config,
        cli_allow_write=allow_write,
        cli_log_level=log_level,
        cli_cluster=cluster,
    )

    # 1. 初始化连接注册中心 (ConnectionRegistry)
    if effective_config.config:
        registry = ConnectionRegistry.from_file(effective_config.config)
    else:
        registry = ConnectionRegistry.from_url(
            url=effective_config.url,
            readonly=not effective_config.allow_write,
            is_cluster=effective_config.is_cluster,
        )

    # 2. 初始化安全守卫 (SecurityGuard)
    guard = SecurityGuard(allow_write=effective_config.allow_write)

    # 3. 构建生命周期管理器以管理资源优雅释放
    @asynccontextmanager
    async def app_lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
        logger.info("mcp-server-redis 服务正在启动...")
        try:
            yield {"registry": registry, "guard": guard}
        finally:
            logger.info("mcp-server-redis 服务正在停止，关闭所有 Redis 连接池...")
            await registry.aclose()

    app = FastMCP(
        name="mcp-server-redis",
        version=SERVER_VERSION,
        lifespan=app_lifespan,
    )

    # 4. 装配挂载全部 18 个 MCP 工具
    register_instance_tools(app, registry)
    register_key_tools(app, registry)
    register_string_tools(app, registry, guard=guard)
    register_hash_tools(app, registry)
    register_list_tools(app, registry)
    register_set_tools(app, registry)
    register_zset_tools(app, registry)
    register_stream_tools(app, registry)
    register_admin_tools(app, registry)

    return app


def main() -> None:
    """CLI 主启动入口。"""
    config_dict = parse_cli_arguments()
    server_config = resolve_server_configuration(
        cli_url=config_dict["url"],
        cli_config=config_dict["config"],
        cli_allow_write=config_dict["allow_write"],
        cli_log_level=config_dict["log_level"],
        cli_transport=config_dict["transport"],
        cli_host=config_dict["host"],
        cli_port=config_dict["port"],
        cli_cluster=config_dict["cluster"],
    )

    # 动态设置日志级别，输出流严格绑定 sys.stderr，杜绝污染 stdout 协议流
    numeric_level = getattr(logging, server_config.log_level, logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
        force=True,
    )
    logging.getLogger().setLevel(numeric_level)
    logger.setLevel(numeric_level)

    app = create_app(server_config=server_config)

    # 根据传输协议启动对应网关（双模传输网关）
    if server_config.transport == "sse":
        logger.info(
            "mcp-server-redis 正在以 SSE 传输网关模式启动于 http://%s:%d/sse ...",
            server_config.host,
            server_config.port,
        )
        app.run(transport="sse", host=server_config.host, port=server_config.port)
    else:
        logger.info("mcp-server-redis 正在以标准 stdio 协议管道模式运行...")
        app.run(transport="stdio")


if __name__ == "__main__":
    main()
