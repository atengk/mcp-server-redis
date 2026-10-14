"""
FastMCP 服务主装配与 CLI 命令行协议入口。

负责加载连接注册中心、装配安全守卫、挂载核心 4 个 MCP 工具并管理服务生命周期。

@author Ateng
@since 2026-10-04
"""

import argparse
import asyncio
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Final

import redis.exceptions
from mcp.server import MCPServer
from starlette.responses import JSONResponse

# 兼容 FastMCP 历史类型名称
FastMCP = MCPServer

# 服务端版本号常量
SERVER_VERSION: Final[str] = "2.1.0"

from mcp_server_redis.core.audit import AuditLogger
from mcp_server_redis.core.connection import ConnectionRegistry
from mcp_server_redis.core.doctor import (
    DoctorRunner,
    format_json_report,
    format_terminal_report,
    get_version_fingerprint,
)
from mcp_server_redis.core.env import ServerConfig, resolve_server_configuration
from mcp_server_redis.core.guard import SecurityGuard
from mcp_server_redis.prompts import register_prompts
from mcp_server_redis.resources import register_resources
from mcp_server_redis.tools.command import register_command_tools
from mcp_server_redis.tools.connections import register_connection_tools
from mcp_server_redis.tools.keys import register_key_tools

logger = logging.getLogger("mcp_server_redis")


def setup_healthz_routes(server: FastMCP, registry: ConnectionRegistry) -> None:
    """为 FastMCP 挂载 /health 与 /healthz 云原生健康检查 HTTP 端点。

    结合底层 Redis PING 探活，正常返回 200，异常返回 503。

    Args:
        server: FastMCP 服务端实例
        registry: 连接注册中心单例
    """
    original_sse_app = server.sse_app

    def wrapped_sse_app(*args: Any, **kwargs: Any) -> Any:
        starlette_app = original_sse_app(*args, **kwargs)

        async def _health_endpoint(request: Any) -> Any:
            status_code = 200
            redis_status = "ok"
            error_message = None
            try:
                client = registry.get_client()
                await asyncio.wait_for(client.ping(), timeout=1.0)
            except (redis.exceptions.RedisError, OSError, TimeoutError) as exc:
                status_code = 503
                redis_status = "error"
                error_message = str(exc)

            content: dict[str, Any] = {
                "status": "healthy" if status_code == 200 else "unhealthy",
                "version": SERVER_VERSION,
                "redis": redis_status,
            }
            if error_message:
                content["error"] = error_message
            return JSONResponse(content, status_code=status_code)

        starlette_app.add_route("/health", _health_endpoint, methods=["GET"])
        starlette_app.add_route("/healthz", _health_endpoint, methods=["GET"])
        return starlette_app

    server.sse_app = wrapped_sse_app  # type: ignore[method-assign]


def build_argument_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。

    按照逻辑功能分组归类参数，并附加典型场景使用示例。

    @return 配置完成的 ArgumentParser 实例
    """
    epilog_text = """
使用示例 (Examples):
  # 1. 默认全局只读模式启动并监听于标准 stdio 管道 (Claude Desktop / Cursor 推荐):
  atengk-mcp-server-redis --url "redis://localhost:6379/0"

  # 2. 显式开启数据写权限并持久化结构化审计日志:
  atengk-mcp-server-redis --url "redis://:pwd@remote.host:6379/0" --allow-write --audit-log /var/log/redis_audit.jsonl

  # 3. 加载多环境连接配置文件并以 HTTP SSE 网关模式启动:
  atengk-mcp-server-redis --config ./connections.yaml --transport sse --host 0.0.0.0 --port 8000

  # 4. 执行生产环境连通性、配置与权限四维健康自检探针:
  atengk-mcp-server-redis --url "redis://localhost:6379/0" --doctor

  # 5. 导出 CI/CD 机器可读的结构化 JSON 诊断报告:
  atengk-mcp-server-redis --config ./connections.yaml --doctor --json

  # 6. 查看服务版本与底层运行时环境指纹:
  atengk-mcp-server-redis --version
"""
    parser = argparse.ArgumentParser(
        prog="mcp-server-redis",
        description="生产级 Redis 模型上下文协议 (MCP) 服务端",
        epilog=epilog_text,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # 1. 基础连接配置
    conn_group = parser.add_argument_group("基础连接配置 (Connection Options)")
    conn_group.add_argument(
        "--url",
        type=str,
        default=None,
        help="单个 Redis 连接 URL（默认读取 MCP_REDIS_URL 或 MCP_REDIS_HOST/PORT 等环境变量）",
    )
    conn_group.add_argument(
        "--config",
        type=str,
        default=None,
        help="多实例连接配置文件路径（默认读取 MCP_REDIS_CONFIG 环境变量，支持 YAML / JSON）",
    )
    conn_group.add_argument(
        "--cluster",
        action="store_true",
        default=False,
        help="激活 Redis Cluster 分片集群连接模式（默认读取 MCP_REDIS_CLUSTER 环境变量或连接配置）",
    )

    # 2. 安全与权限控制
    sec_group = parser.add_argument_group("安全与权限控制 (Security & Permissions)")
    sec_group.add_argument(
        "--allow-write",
        action="store_true",
        default=False,
        help="显式开启写操作权限（默认全局强只读，支持通过 MCP_REDIS_ALLOW_WRITE=true 或 MCP_REDIS_READ_ONLY=false 开启）",
    )
    sec_group.add_argument(
        "--audit-log",
        type=str,
        default=None,
        help="命令审计日志输出目标（'stderr', 'stdout' 或文件路径；默认读取 MCP_REDIS_AUDIT_LOG 环境变量）",
    )

    # 3. 服务与网络传输
    trans_group = parser.add_argument_group("服务与网络传输 (Transport & Server)")
    trans_group.add_argument(
        "--transport",
        type=str.lower,
        choices=["stdio", "sse"],
        default=None,
        help="传输协议模式（stdio 或 sse，默认读取 MCP_REDIS_TRANSPORT 环境变量或默认 stdio）",
    )
    trans_group.add_argument(
        "--host",
        type=str,
        default=None,
        help="SSE 模式服务监听主机（默认读取 MCP_REDIS_SERVER_HOST 环境变量或默认 0.0.0.0）",
    )
    trans_group.add_argument(
        "--port",
        type=int,
        default=None,
        help="SSE 模式服务监听端口（默认读取 MCP_REDIS_SERVER_PORT 环境变量或默认 8000）",
    )
    trans_group.add_argument(
        "--log-level",
        type=str.upper,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=None,
        help="运行时日志级别（DEBUG、INFO、WARNING、ERROR，默认读取 MCP_REDIS_LOG_LEVEL 或默认 INFO）",
    )
    trans_group.add_argument(
        "--server-name",
        type=str,
        default=None,
        help="MCP 协议服务实例名称标识（默认读取 MCP_REDIS_SERVER_NAME 环境变量或默认 'mcp-server-redis'）",
    )
    trans_group.add_argument(
        "--server-instructions",
        type=str,
        default=None,
        help="向大模型注入的全局系统级业务指导指令（默认读取 MCP_REDIS_SERVER_INSTRUCTIONS 环境变量）",
    )

    # 4. 运维诊断与信息
    diag_group = parser.add_argument_group("运维诊断与信息 (Diagnostics & Info)")
    diag_group.add_argument(
        "--doctor",
        action="store_true",
        default=False,
        help="执行生产环境连通性、配置语义与写权限四维健康自检探针并退出",
    )
    diag_group.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="配合 --doctor 标志时以结构化 JSON 格式输出自检报告（便于 CI/CD 流水线解析）",
    )
    diag_group.add_argument(
        "-v",
        "--version",
        action="version",
        version=get_version_fingerprint(SERVER_VERSION),
        help="显示详细服务版本号与底层运行时环境指纹并退出",
    )

    return parser


def parse_cli_arguments(args: list[str] | None = None) -> dict[str, Any]:
    """解析命令行参数或传入参数列表。

    @param args 可选自定义参数列表，缺省时读取 sys.argv[1:]
    @return 包含各个参数项的配置字典
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
        "audit_log": parsed.audit_log,
        "server_name": parsed.server_name,
        "server_instructions": parsed.server_instructions,
        "doctor": parsed.doctor,
        "json": parsed.json,
    }


def create_app(
    url: str | None = None,
    config: str | None = None,
    allow_write: bool = False,
    log_level: str | None = None,
    cluster: bool | None = None,
    audit_log: str | None = None,
    server_name: str | None = None,
    server_instructions: str | None = None,
    server_config: ServerConfig | None = None,
) -> FastMCP:
    """工厂函数：根据配置初始化连接注册中心、安全守卫并装配核心 4 个 MCP 工具。

    支持多层级配置决议：CLI 显式参数 > 环境变量整串/离散参数 > 本地 .env > 系统保底默认。

    @param url 单实例 Redis 连接串（可选）
    @param config 多实例配置文件路径（可选）
    @param allow_write 是否开启写操作权限（默认 False）
    @param log_level 运行时日志级别（可选）
    @param cluster 是否开启 Redis Cluster 分片集群模式（可选）
    @param audit_log 命令审计日志输出目标（可选）
    @param server_name MCP 服务实例名称标识（可选）
    @param server_instructions 向大模型注入的全局系统级指导指令（可选）
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
        cli_audit_log=audit_log,
        cli_server_name=server_name,
        cli_server_instructions=server_instructions,
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

    # 2. 初始化安全守卫 (SecurityGuard) 与审计跟踪器 (AuditLogger)
    guard = SecurityGuard(allow_write=effective_config.allow_write)
    is_stdio = effective_config.transport == "stdio"
    audit_logger = AuditLogger(target=effective_config.audit_log, is_stdio=is_stdio)

    # 3. 构建生命周期管理器以管理资源优雅释放
    @asynccontextmanager
    async def app_lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
        logger.info("mcp-server-redis 服务正在启动...")
        try:
            yield {
                "registry": registry,
                "guard": guard,
                "audit_logger": audit_logger,
            }
        finally:
            logger.info("mcp-server-redis 服务正在停止，关闭所有 Redis 连接池与审计跟踪器...")
            audit_logger.close()
            await registry.aclose()

    app = FastMCP(
        name=effective_config.server_name,
        instructions=effective_config.server_instructions,
        version=SERVER_VERSION,
        lifespan=app_lifespan,
    )

    # 4. 装配挂载核心 4 个规范动宾 MCP 工具
    register_command_tools(
        app,
        registry,
        guard=guard,
        audit_logger=audit_logger,
        max_unbounded_read_items=effective_config.max_unbounded_read_items,
    )
    register_connection_tools(app, registry)
    register_key_tools(app, registry)

    # 5. 装配挂载 MCP 只读快照资源 (Resources) 与诊断引导提示词 (Prompts)
    register_resources(app, registry)
    register_prompts(app)

    # 6. 装配挂载云原生 HTTP 探活端点 (/health 与 /healthz)
    setup_healthz_routes(app, registry)

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
        cli_audit_log=config_dict["audit_log"],
        cli_server_name=config_dict.get("server_name"),
        cli_server_instructions=config_dict.get("server_instructions"),
    )

    # 若指定了 --doctor 标志，运行生产环境健康自检探针并按检测结果退出
    if config_dict.get("doctor"):
        runner = DoctorRunner(server_config=server_config)
        report = asyncio.run(runner.run_diagnostics())
        if config_dict.get("json"):
            sys.stdout.write(format_json_report(report) + "\n")
        else:
            sys.stdout.write(format_terminal_report(report) + "\n")
        sys.exit(0 if report.is_healthy else 1)

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
