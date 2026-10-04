"""
FastMCP 服务主装配与 CLI 命令行协议入口。

负责加载连接注册中心、装配安全守卫、挂载全部 18 个 MCP 工具并管理服务生命周期。

@author Ateng
@since 2026-10-04
"""

import argparse
import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Final

from mcp.server import MCPServer

# 兼容 FastMCP 历史类型名称
FastMCP = MCPServer

# 服务端版本号常量
SERVER_VERSION: Final[str] = "0.1.0"

from mcp_server_redis.core.connection import ConnectionRegistry
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
        help="单个 Redis 连接 URL（如 redis://localhost:6379/0，默认读取 REDIS_URL 环境变量）",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="多实例连接配置文件路径（支持 YAML / JSON）",
    )
    parser.add_argument(
        "--allow-write",
        action="store_true",
        default=False,
        help="显式开启写操作权限（默认全局强只读保护）",
    )
    return parser


def parse_cli_arguments(args: list[str] | None = None) -> dict[str, Any]:
    """解析命令行参数或传入参数列表。

    @param args 可选自定义参数列表，缺省时读取 sys.argv[1:]
    @return 包含 url, config, allow_write 键的配置字典
    """
    parser = build_argument_parser()
    parsed = parser.parse_args(args)
    return {
        "url": parsed.url,
        "config": parsed.config,
        "allow_write": parsed.allow_write,
    }


def create_app(
    url: str | None = None,
    config: str | None = None,
    allow_write: bool = False,
) -> FastMCP:
    """工厂函数：根据配置初始化连接注册中心、安全守卫并装配全部 18 个 MCP 工具。

    @param url 单实例 Redis 连接串（可选）
    @param config 多实例配置文件路径（可选）
    @param allow_write 是否开启写操作权限（默认 False）
    @return 已经完成全部工具装配与生命周期绑定的 FastMCP 实例
    """
    # 1. 初始化连接注册中心 (ConnectionRegistry)
    if config:
        registry = ConnectionRegistry.from_file(config)
    else:
        target_url: str = (
            url if url else (os.getenv("REDIS_URL") or "redis://localhost:6379/0")
        )
        registry = ConnectionRegistry.from_url(url=target_url, readonly=not allow_write)

    # 2. 初始化安全守卫 (SecurityGuard)
    guard = SecurityGuard(allow_write=allow_write)

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
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    config_dict = parse_cli_arguments()
    app = create_app(
        url=config_dict["url"],
        config=config_dict["config"],
        allow_write=config_dict["allow_write"],
    )
    app.run()


if __name__ == "__main__":
    main()
