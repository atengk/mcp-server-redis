"""
数据安全序列化器。

负责自适应 UTF-8 文本解码、非文本二进制 Base64 转码、智能 JSON 结构探测与超长内容安全截断。

@author Ateng
@since 2026-10-04
"""

import base64
import json
import logging
from collections.abc import Iterable, Mapping
from typing import Any, Final

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# 默认长文本单次截断阈值（字符数）
DEFAULT_MAX_LENGTH: Final[int] = 4000


class SerializedValue(BaseModel):
    """数据安全序列化结果模型。

    封装原始解码值、二进制标记、截断元数据与可选结构化 JSON 对象。

    @author Ateng
    @since 2026-10-04
    """

    value: str | None = None
    is_binary: bool = False
    truncated: bool = False
    total_length: int = 0
    json_data: Any | None = None

    def unwrap(self) -> Any:
        """获取解包后的最终展示值，优先返回 JSON 对象，否则返回解码文本。"""
        return self.json_data if self.json_data is not None else self.value

    def to_item_dict(self) -> dict[str, Any]:
        """将当前结果转化为列表或集合元素字典结构。"""
        return {
            "value": self.value,
            "json_data": self.json_data,
            "is_binary": self.is_binary,
            "is_truncated": self.truncated,
        }


def _decode_bytes_safely(raw: bytes) -> tuple[str, bool]:
    """安全解码字节串为文本，若非 UTF-8 编码则自动降级为 Base64 编码。

    @param raw 原始字节串
    @return (解码后文本内容, 是否为二进制Base64)
    """
    try:
        return raw.decode("utf-8"), False
    except UnicodeDecodeError:
        return base64.b64encode(raw).decode("ascii"), True


class SafeSerializer:
    """自适应安全序列化器。

    防范解码崩溃、上下文 OOM 与长文本溢出。

    @author Ateng
    @since 2026-10-04
    """

    @classmethod
    def serialize_value(
        cls,
        raw: Any,
        parse_json: bool = True,
        max_length: int = DEFAULT_MAX_LENGTH,
    ) -> SerializedValue:
        """对单个 Redis 原生值执行安全序列化。

        @param raw Redis 驱动返回的原生数据（bytes、str、None 等）
        @param parse_json 是否对文本执行智能 JSON 结构化探测
        @param max_length 最大允许字符长度，超出部分将被安全截断
        @return 序列化结果实体模型
        """
        if raw is None:
            return SerializedValue(
                value=None,
                is_binary=False,
                truncated=False,
                total_length=0,
                json_data=None,
            )

        is_binary = False
        text_content: str = ""

        # 1. 尝试自适应文本解码或二进制 Base64 降级
        if isinstance(raw, bytes):
            text_content, is_binary = _decode_bytes_safely(raw)
        elif isinstance(raw, str):
            text_content = raw
        else:
            text_content = str(raw)

        total_length = len(text_content)
        json_data: Any | None = None

        # 2. 超长内容安全截断判定
        truncated = False
        final_value = text_content
        if total_length > max_length:
            truncated = True
            final_value = text_content[:max_length]

        # 3. 文本且未截断时，执行智能 JSON 探测 (防止超大 JSON 穿透打爆上下文)
        if not is_binary and not truncated and parse_json and text_content:
            stripped = text_content.strip()
            if (stripped.startswith("{") and stripped.endswith("}")) or (
                stripped.startswith("[") and stripped.endswith("]")
            ):
                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, (dict, list)):
                        json_data = parsed
                except (json.JSONDecodeError, ValueError):
                    json_data = None

        return SerializedValue(
            value=final_value,
            is_binary=is_binary,
            truncated=truncated,
            total_length=total_length,
            json_data=json_data,
        )

    @classmethod
    def serialize_list(
        cls,
        items: Iterable[Any],
        parse_json: bool = False,
        max_length: int = DEFAULT_MAX_LENGTH,
    ) -> list[SerializedValue]:
        """批量安全序列化列表或集合数据。

        @param items 可迭代元素集合
        @param parse_json 是否探测 JSON
        @param max_length 元素最大长度截断阈值
        @return 序列化模型列表，为空时返回空列表
        """
        if not items:
            return []

        return [
            cls.serialize_value(item, parse_json=parse_json, max_length=max_length)
            for item in items
        ]

    @classmethod
    def serialize_dict(
        cls,
        mapping: Mapping[Any, Any],
        parse_json: bool = False,
        max_length: int = DEFAULT_MAX_LENGTH,
    ) -> dict[str, SerializedValue]:
        """批量安全序列化字典或哈希映射。

        @param mapping 键值映射字典
        @param parse_json 是否探测 JSON
        @param max_length 值最大长度截断阈值
        @return 序列化后的字典映射，为空时返回空字典
        """
        if not mapping:
            return {}

        result: dict[str, SerializedValue] = {}
        for key, value in mapping.items():
            if isinstance(key, bytes):
                key_str, _ = _decode_bytes_safely(key)
            else:
                key_str = str(key)

            result[key_str] = cls.serialize_value(
                value, parse_json=parse_json, max_length=max_length
            )
        return result
