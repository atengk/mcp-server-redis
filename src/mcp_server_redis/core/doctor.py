"""生产级环境健康与连通性自检诊断器 (Doctor)。

为开发者与自动化流水线提供开箱即用的四维全景自检：
1. 运行时与依赖库版本检测；
2. 环境变量与多实例配置文件语法语义校验；
3. Redis 目标实例连通性、网络往返延迟 (RTT) 与架构模式探查；
4. 读写安全门禁与临时隔离写探针校验（5秒 TTL 双保险，即刻物理清理）。

@author Ateng
@since 2026-10-14
"""

import asyncio
import importlib.metadata
import json
import logging
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal

import redis.exceptions

from mcp_server_redis.core.connection import ConnectionRegistry
from mcp_server_redis.core.env import ServerConfig

logger = logging.getLogger(__name__)

# 服务端版本号常量
SERVER_VERSION: Final[str] = "2.1.0"

DoctorCheckStatus = Literal["ok", "warn", "fail"]


def get_version_fingerprint(server_version: str = SERVER_VERSION) -> str:
    """生成包含 Python 解释器、操作系统平台与核心底层依赖版本的增强型环境指纹。

    Args:
        server_version: 服务版本号

    Returns:
        str: 格式化的单行环境指纹摘要
    """
    pkg_versions: dict[str, str] = {}
    for pkg in ("mcp", "redis", "pydantic", "pyyaml"):
        try:
            pkg_versions[pkg] = importlib.metadata.version(pkg)
        except Exception:  # noqa: BLE001
            pkg_versions[pkg] = "unknown"

    py_ver = sys.version.split()[0]
    return (
        f"mcp-server-redis {server_version} "
        f"(Python {py_ver}, mcp {pkg_versions['mcp']}, redis {pkg_versions['redis']}, "
        f"pydantic {pkg_versions['pydantic']}, pyyaml {pkg_versions['pyyaml']} on {sys.platform})"
    )


@dataclass
class DoctorCheckItem:
    """单个自检检查项结果数据模型。"""

    category: str
    name: str
    status: DoctorCheckStatus
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class DoctorReport:
    """自检诊断聚合报告。"""

    items: list[DoctorCheckItem] = field(default_factory=list)
    duration_ms: float = 0.0

    @property
    def is_healthy(self) -> bool:
        """所有项均未发生阻断性错误时视为健康。"""
        return not any(item.status == "fail" for item in self.items)

    @property
    def summary(self) -> dict[str, int]:
        """统计各类状态项数量。"""
        return {
            "ok": sum(1 for i in self.items if i.status == "ok"),
            "warn": sum(1 for i in self.items if i.status == "warn"),
            "fail": sum(1 for i in self.items if i.status == "fail"),
            "total": len(self.items),
        }

    def to_dict(self) -> dict[str, Any]:
        """将报告转换为结构化字典对象。"""
        return {
            "healthy": self.is_healthy,
            "version": SERVER_VERSION,
            "summary": self.summary,
            "duration_ms": round(self.duration_ms, 2),
            "checks": [
                {
                    "category": item.category,
                    "name": item.name,
                    "status": item.status,
                    "message": item.message,
                    "details": item.details,
                }
                for item in self.items
            ],
        }


class DoctorRunner:
    """生产级环境与网络自检运行器。"""

    def __init__(self, server_config: ServerConfig) -> None:
        """初始化自检运行器。

        Args:
            server_config: 决议完成的服务端配置
        """
        self.server_config = server_config

    async def run_diagnostics(self) -> DoctorReport:
        """执行完整的四维全景自检巡检。

        Returns:
            DoctorReport: 自检汇总诊断报告
        """
        start_time = time.perf_counter()
        report = DoctorReport()

        # 1. 维度一：运行时与核心依赖检测
        self._check_runtime_and_dependencies(report)

        # 2. 维度二：配置文件与环境变量校验
        registry = self._check_configuration(report)

        # 3. 维度三 & 维度四：Redis 实例网络连通性与读写门禁探测
        if registry is not None:
            try:
                await self._check_connections_and_permissions(registry, report)
            finally:
                await registry.aclose()

        report.duration_ms = (time.perf_counter() - start_time) * 1000
        return report

    def _check_runtime_and_dependencies(self, report: DoctorReport) -> None:
        """检测 Python 解释器与核心依赖包。"""
        # Python 版本要求 >= 3.10
        py_ver_str = sys.version.split()[0]
        if sys.version_info >= (3, 10):  # noqa: UP036
            report.items.append(
                DoctorCheckItem(
                    category="Runtime",
                    name="Python 运行时版本",
                    status="ok",
                    message=f"Python {py_ver_str} (满足 >= 3.10 要求)",
                    details={"version": py_ver_str, "executable": sys.executable},
                )
            )
        else:
            report.items.append(
                DoctorCheckItem(
                    category="Runtime",
                    name="Python 运行时版本",
                    status="fail",
                    message=f"当前 Python 版本为 {py_ver_str}，低于最低支持版本 3.10",
                    details={"version": py_ver_str, "executable": sys.executable},
                )
            )

        # 核心依赖项探查
        dep_statuses: dict[str, str] = {}
        all_deps_ok = True
        for dep in ("mcp", "redis", "pydantic", "pyyaml"):
            try:
                v = importlib.metadata.version(dep)
                dep_statuses[dep] = v
            except Exception as exc:  # noqa: BLE001
                dep_statuses[dep] = f"缺失 ({exc})"
                all_deps_ok = False

        if all_deps_ok:
            report.items.append(
                DoctorCheckItem(
                    category="Runtime",
                    name="核心依赖库",
                    status="ok",
                    message=f"全部已就绪: mcp {dep_statuses['mcp']}, redis {dep_statuses['redis']}, pydantic {dep_statuses['pydantic']}, pyyaml {dep_statuses['pyyaml']}",
                    details=dep_statuses,
                )
            )
        else:
            report.items.append(
                DoctorCheckItem(
                    category="Runtime",
                    name="核心依赖库",
                    status="fail",
                    message="检测到核心依赖缺失，请运行 'uv sync' 或重新安装依赖",
                    details=dep_statuses,
                )
            )

    def _check_configuration(self, report: DoctorReport) -> ConnectionRegistry | None:
        """检测配置文件合法性与连接档案解析。"""
        # 探查本地 .env
        dotenv_path = Path.cwd() / ".env"
        if dotenv_path.is_file():
            report.items.append(
                DoctorCheckItem(
                    category="Configuration",
                    name="本地 .env 配置",
                    status="ok",
                    message=f"已发现并加载工作区配置文件: {dotenv_path}",
                    details={"path": str(dotenv_path)},
                )
            )

        # 校验多实例配置文件
        if self.server_config.config:
            cfg_path = Path(self.server_config.config).resolve()
            if not cfg_path.is_file():
                report.items.append(
                    DoctorCheckItem(
                        category="Configuration",
                        name="多实例配置文件",
                        status="fail",
                        message=f"指定的配置文件不存在: {cfg_path}",
                        details={"path": str(cfg_path)},
                    )
                )
                return None
            try:
                registry = ConnectionRegistry.from_file(cfg_path)
                profiles = registry.list_profiles()
                report.items.append(
                    DoctorCheckItem(
                        category="Configuration",
                        name="多实例配置文件",
                        status="ok",
                        message=f"成功加载并解析多实例配置 (共 {len(profiles)} 个连接档案)",
                        details={
                            "path": str(cfg_path),
                            "default_connection": registry.default_alias,
                            "connections": [p.alias for p in profiles],
                        },
                    )
                )
                return registry
            except Exception as exc:  # noqa: BLE001
                report.items.append(
                    DoctorCheckItem(
                        category="Configuration",
                        name="多实例配置文件",
                        status="fail",
                        message=f"解析配置文件失败: {exc}",
                        details={"path": str(cfg_path), "error": str(exc)},
                    )
                )
                return None

        # 单连接 URL 解析验证
        try:
            registry = ConnectionRegistry.from_url(
                url=self.server_config.url,
                readonly=not self.server_config.allow_write,
                is_cluster=self.server_config.is_cluster,
            )
            profile = registry.get_profile()
            report.items.append(
                DoctorCheckItem(
                    category="Configuration",
                    name="单连接参数解析",
                    status="ok",
                    message=f"连接 URL 语法有效: {profile.masked_url} (Cluster: {profile.is_cluster})",
                    details={
                        "masked_url": profile.masked_url,
                        "cluster": profile.is_cluster,
                        "db": profile.db,
                    },
                )
            )
            return registry
        except Exception as exc:  # noqa: BLE001
            report.items.append(
                DoctorCheckItem(
                    category="Configuration",
                    name="单连接参数解析",
                    status="fail",
                    message=f"解析单连接 URL 失败: {exc}",
                    details={"error": str(exc)},
                )
            )
            return None

    async def _check_connections_and_permissions(
        self,
        registry: ConnectionRegistry,
        report: DoctorReport,
    ) -> None:
        """并发探检各连接实例的网络连通性、RTT 延迟与写权限探针。"""
        profiles = registry.list_profiles()
        for profile in profiles:
            alias = profile.alias
            timeout = profile.socket_connect_timeout or 5.0

            try:
                client = registry.get_client(alias=alias)
            except Exception as exc:  # noqa: BLE001
                report.items.append(
                    DoctorCheckItem(
                        category="Connection",
                        name=f"连接实例 [{alias}] 初始化",
                        status="fail",
                        message=f"创建客户端实例失败: {exc}",
                        details={"alias": alias, "error": str(exc)},
                    )
                )
                continue

            # 1. 网络与 PING 探测
            ping_start = time.perf_counter()
            try:
                pong = await asyncio.wait_for(client.ping(), timeout=timeout)
                ping_rtt = (time.perf_counter() - ping_start) * 1000
                if pong not in (True, "PONG", b"PONG"):
                    report.items.append(
                        DoctorCheckItem(
                            category="Connection",
                            name=f"Redis 实例 [{alias}] 探活",
                            status="warn",
                            message=f"PING 返回了非预期响应: {pong!r}",
                            details={"alias": alias, "response": str(pong)},
                        )
                    )
                else:
                    # 获取服务器架构与版本信息
                    server_info_msg = ""
                    try:
                        info_dict = await client.info("server")
                        ver = info_dict.get("redis_version", "unknown")
                        mode = info_dict.get("redis_mode", "standalone")
                        server_info_msg = f", Redis {ver}, {mode}"
                    except Exception:  # noqa: BLE001
                        logger.debug(
                            "获取 Redis 实例 [%s] 的 server info 失败，降级展示基础 PING", alias
                        )

                    report.items.append(
                        DoctorCheckItem(
                            category="Connection",
                            name=f"Redis 实例 [{alias}] 连通性",
                            status="ok",
                            message=f"PING 成功 (RTT: {ping_rtt:.1f}ms{server_info_msg})",
                            details={
                                "alias": alias,
                                "rtt_ms": round(ping_rtt, 2),
                                "url": profile.masked_url,
                            },
                        )
                    )
            except redis.exceptions.AuthenticationError as exc:
                report.items.append(
                    DoctorCheckItem(
                        category="Connection",
                        name=f"Redis 实例 [{alias}] 连通性",
                        status="fail",
                        message=f"认证失败 (密码错误或 ACL 未授权): {exc}",
                        details={"alias": alias, "error": str(exc)},
                    )
                )
                continue
            except (redis.exceptions.TimeoutError, asyncio.TimeoutError) as exc:
                report.items.append(
                    DoctorCheckItem(
                        category="Connection",
                        name=f"Redis 实例 [{alias}] 连通性",
                        status="fail",
                        message=f"连接超时 (超过 {timeout}s): 目标主机不可达或网络中断",
                        details={"alias": alias, "timeout": timeout, "error": str(exc)},
                    )
                )
                continue
            except Exception as exc:  # noqa: BLE001
                report.items.append(
                    DoctorCheckItem(
                        category="Connection",
                        name=f"Redis 实例 [{alias}] 连通性",
                        status="fail",
                        message=f"连接异常: {exc}",
                        details={"alias": alias, "error": str(exc)},
                    )
                )
                continue

            # 2. 读写安全门禁与隔离写探针校验
            is_writable = self.server_config.allow_write and not profile.readonly
            if not is_writable:
                reason = (
                    "全局 --allow-write 未开启"
                    if not self.server_config.allow_write
                    else "连接配置显式声明 readonly=true"
                )
                report.items.append(
                    DoctorCheckItem(
                        category="Security",
                        name=f"实例 [{alias}] 权限门禁",
                        status="ok",
                        message=f"连接处于受保护的只读模式 ({reason})",
                        details={"alias": alias, "readonly": True},
                    )
                )
            else:
                # 开启了写权限：使用隔离探针安全测试真实写与删能力
                probe_key = f"__mcp_doctor_probe_{uuid.uuid4().hex}__"
                probe_val = "1"
                try:
                    await client.set(probe_key, probe_val, ex=5)
                    read_back = await client.get(probe_key)
                    await client.delete(probe_key)

                    read_str = (
                        read_back.decode("utf-8")
                        if isinstance(read_back, bytes)
                        else str(read_back)
                    )
                    if read_str == probe_val:
                        report.items.append(
                            DoctorCheckItem(
                                category="Security",
                                name=f"实例 [{alias}] 写权限探针",
                                status="ok",
                                message="写权限校验通过 (已安全验证写入、回读与物理清理，5s TTL 双保险)",
                                details={"alias": alias, "writable": True},
                            )
                        )
                    else:
                        report.items.append(
                            DoctorCheckItem(
                                category="Security",
                                name=f"实例 [{alias}] 写权限探针",
                                status="warn",
                                message="写探针数据回读不一致",
                                details={"alias": alias, "expected": probe_val, "got": read_str},
                            )
                        )
                except redis.exceptions.ReadOnlyError as exc:
                    report.items.append(
                        DoctorCheckItem(
                            category="Security",
                            name=f"实例 [{alias}] 写权限探针",
                            status="fail",
                            message=f"写操作被 Redis 拒绝 (目标为只读从库 Replica): {exc}",
                            details={"alias": alias, "error": str(exc)},
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    report.items.append(
                        DoctorCheckItem(
                            category="Security",
                            name=f"实例 [{alias}] 写权限探针",
                            status="fail",
                            message=f"写探针测试异常: {exc}",
                            details={"alias": alias, "error": str(exc)},
                        )
                    )


def format_terminal_report(report: DoctorReport) -> str:
    """将自检报告格式化为美观直观的终端卡片文本。

    Args:
        report: 自检报告对象

    Returns:
        str: 终端排版字符串
    """
    lines: list[str] = [
        "=" * 64,
        "          mcp-server-redis 生产健康自检报告 (Doctor Report)",
        "=" * 64,
    ]

    category_names = {
        "Runtime": "运行时与依赖环境",
        "Configuration": "配置与参数解析",
        "Connection": "Redis 连接与网络往返",
        "Security": "安全门禁与写权限探针",
    }

    # 按类别组织项目
    categorized: dict[str, list[DoctorCheckItem]] = {}
    for item in report.items:
        categorized.setdefault(item.category, []).append(item)

    for cat_key in ("Runtime", "Configuration", "Connection", "Security"):
        items = categorized.get(cat_key, [])
        if not items:
            continue
        display_name = category_names.get(cat_key, cat_key)
        lines.append(f"\n【{display_name}】")
        for it in items:
            if it.status == "ok":
                symbol = "✔"
            elif it.status == "warn":
                symbol = "⚠"
            else:
                symbol = "✘"
            lines.append(f"  {symbol} [{it.name}] {it.message}")

    lines.append("\n" + "=" * 64)
    summary = report.summary
    status_text = "全部健康 (Healthy)" if report.is_healthy else "存在故障 (Failures Detected)"
    lines.append(
        f"自检结论: {status_text} (通过: {summary['ok']}, 告警: {summary['warn']}, 失败: {summary['fail']}, 耗时: {report.duration_ms:.1f}ms)"
    )
    lines.append("=" * 64)
    return "\n".join(lines)


def format_json_report(report: DoctorReport) -> str:
    """将自检报告格式化为标准 JSON 字符串。

    Args:
        report: 自检报告对象

    Returns:
        str: 格式化的 JSON 字符串
    """
    return json.dumps(report.to_dict(), indent=2, ensure_ascii=False)
