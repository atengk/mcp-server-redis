"""结构化命令审计跟踪器。

为大模型访问 Redis 提供企业级可观测性与合规追溯，输出单行 JSONL 审计日志。
严格遵循 STDIO 管道物理隔离红线与零明文机密规范。

@author Ateng
@since 2026-10-14
"""

import json
import logging
import re
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 密码与敏感参数屏蔽正则
_AUTH_PATTERN = re.compile(r"^(\s*AUTH\s+)(.+)$", re.IGNORECASE)


def mask_command_for_audit(command: str) -> str:
    """对审计记录中的 Redis 命令进行敏感参数脱敏。

    例如：AUTH 密码脱敏为 AUTH ***。

    Args:
        command: 原生 Redis 命令行字符串

    Returns:
        str: 脱敏后的命令行字符串
    """
    if not command:
        return ""
    auth_match = _AUTH_PATTERN.match(command)
    if auth_match:
        prefix = auth_match.group(1)
        return f"{prefix}***"
    return command


class AuditLogger:
    """生产级结构化命令审计记录器。

    支持向 stderr、stdout 或指定日志文件持久化 JSONL 审计事件。
    在 stdio 协议传输模式下，强制拦截向 stdout 输出，物理阻断对 MCP 协议管道的污染。

    @author Ateng
    @since 2026-10-14
    """

    def __init__(
        self,
        target: str | None = None,
        is_stdio: bool = True,
    ) -> None:
        """初始化审计记录器。

        Args:
            target: 审计输出目标（如 "stderr", "stdout", 文件绝对/相对路径），None 为关闭
            is_stdio: 当前服务端是否以 stdio 协议管道模式运行
        """
        self.target: str | None = target.strip() if target else None
        self.is_stdio: bool = is_stdio
        self._lock = threading.Lock()
        self._file_handle: Any = None

        if not self.target:
            self._mode = "disabled"
            return

        normalized = self.target.lower()
        if normalized in ("stderr", "sys.stderr"):
            self._mode = "stderr"
        elif normalized in ("stdout", "sys.stdout"):
            if self.is_stdio:
                logger.warning(
                    "安全拦截：服务以 stdio 管道模式运行，审计日志禁止定向至 stdout（防协议通信污染），已强制安全重定向至 stderr。"
                )
                self._mode = "stderr"
            else:
                self._mode = "stdout"
        else:
            self._mode = "file"
            try:
                log_path = Path(self.target).resolve()
                log_path.parent.mkdir(parents=True, exist_ok=True)
                self._file_handle = open(log_path, mode="a", encoding="utf-8")  # noqa: SIM115
            except OSError as exc:
                logger.error(
                    "初始化审计日志文件失败 ('%s'): %s，审计记录已安全降级至 stderr",
                    self.target,
                    exc,
                )
                self._mode = "stderr"

    @property
    def is_enabled(self) -> bool:
        """审计记录是否处于启用状态。"""
        return self._mode != "disabled"

    def log(
        self,
        command: str,
        connection: str = "default",
        db: int = 0,
        duration_ms: float = 0.0,
        status: str = "success",
        keys: list[str] | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """记录单次命令执行的结构化审计日志。

        Args:
            command: 原生 Redis 命令行（会自动执行机密掩码）
            connection: 连接别名
            db: 逻辑库编号
            duration_ms: 执行耗时（毫秒）
            status: 执行结果状态 ('success', 'rejected', 'error', 'confirmation_required')
            keys: 涉及的 Redis 键名列表
            error_type: 异常类型名（可选）
            error_message: 错误描述信息（可选）
        """
        if not self.is_enabled:
            return

        try:
            record: dict[str, Any] = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "connection": connection or "default",
                "db": db,
                "command": mask_command_for_audit(command),
                "duration_ms": round(duration_ms, 2),
                "status": status,
                "keys": keys or [],
            }
            if error_type:
                record["error_type"] = error_type
            if error_message:
                record["error_message"] = str(error_message)

            line = json.dumps(record, ensure_ascii=False) + "\n"

            with self._lock:
                if self._mode == "stderr":
                    sys.stderr.write(line)
                    sys.stderr.flush()
                elif self._mode == "stdout":
                    sys.stdout.write(line)
                    sys.stdout.flush()
                elif self._mode == "file" and self._file_handle:
                    self._file_handle.write(line)
                    self._file_handle.flush()
        except Exception as exc:  # noqa: BLE001
            # 审计日志内部异常决不反噬破坏主业务命令执行
            logger.debug("输出审计日志异常: %s", exc)

    def close(self) -> None:
        """安全关闭已打开的审计日志文件句柄。"""
        with self._lock:
            if self._file_handle:
                try:
                    self._file_handle.close()
                except OSError:
                    pass
                self._file_handle = None
