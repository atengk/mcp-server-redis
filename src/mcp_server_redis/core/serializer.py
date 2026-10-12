"""
数据安全序列化器。

负责自适应 UTF-8 文本解码、非文本二进制 Base64 转码、智能 JSON 结构探测、超长内容安全截断与大集合切片截断守卫。

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

# 默认集合元素/键值对单次切片截断阈值（项数）
DEFAULT_MAX_COLLECTION_ITEMS: Final[int] = 100


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


class SerializedCollection(BaseModel):
    """大集合切片序列化结果模型。

    包含切片后的集合数据、推导类型、是否截断以及原始数量统计。

    @author Ateng
    @since 2026-10-12
    """

    items: Any
    data_type: str
    is_truncated: bool = False
    total_count: int = 0
    has_binary: bool = False


class SerializedResult(BaseModel):
    """通用命令执行结果安全序列化模型。

    用于适配统一协议网关结果信封，包含原始命令、解包数据、类型、截断标记与元数据。

    @author Ateng
    @since 2026-10-12
    """

    command: str = ""
    result: Any = None
    data_type: str = "none"
    is_truncated: bool = False
    total_count: int | None = None
    is_binary: bool = False

    def to_dict(self) -> dict[str, Any]:
        """转换为网关信封结果字典。"""
        envelope = {
            "result": self.result,
            "data_type": self.data_type,
            "is_truncated": self.is_truncated,
            "total_count": self.total_count,
        }
        if self.command:
            envelope["command"] = self.command
        return envelope


def _decode_bytes_safely(raw: bytes) -> tuple[str, bool]:
    """安全解码字节串为文本，若非 UTF-8 编码则自动降级为 Base64 编码。

    @param raw 原始字节串
    @return (解码后文本内容, 是否为二进制Base64)
    """
    try:
        return raw.decode("utf-8"), False
    except UnicodeDecodeError:
        return base64.b64encode(raw).decode("ascii"), True


def _sanitize_nested_item(val: Any, max_length: int = DEFAULT_MAX_LENGTH) -> tuple[Any, bool, bool]:
    """递归安全清洗嵌套数据项。

    保证嵌套中的字节串解码为 UTF-8 或 Base64，长文本安全截断，嵌套字典与列表深度清洗。

    Args:
        val: 原始嵌套数据项
        max_length: 单个字符串最大允许字符长度

    Returns:
        tuple[Any, bool, bool]: (清洗后对象, 是否发生截断, 是否包含二进制)
    """
    if val is None:
        return None, False, False
    if isinstance(val, bool):
        return val, False, False
    if isinstance(val, (int, float)):
        return val, False, False

    if isinstance(val, bytes):
        text, is_bin = _decode_bytes_safely(val)
        if len(text) > max_length:
            return text[:max_length], True, is_bin
        return text, False, is_bin

    if isinstance(val, str):
        if len(val) > max_length:
            return val[:max_length], True, False
        return val, False, False

    if isinstance(val, (list, tuple)):
        items = []
        truncated = False
        binary = False
        for item in val:
            s_val, s_trunc, s_bin = _sanitize_nested_item(item, max_length=max_length)
            items.append(s_val)
            if s_trunc:
                truncated = True
            if s_bin:
                binary = True
        return items, truncated, binary

    if isinstance(val, (set, frozenset)):
        items = []
        truncated = False
        binary = False
        sorted_val = sorted(val, key=lambda x: str(x))
        for item in sorted_val:
            s_val, s_trunc, s_bin = _sanitize_nested_item(item, max_length=max_length)
            items.append(s_val)
            if s_trunc:
                truncated = True
            if s_bin:
                binary = True
        return items, truncated, binary

    if isinstance(val, (dict, Mapping)):
        res_dict = {}
        truncated = False
        binary = False
        for k, v in val.items():
            k_val, k_trunc, k_bin = _sanitize_nested_item(k, max_length=max_length)
            v_val, v_trunc, v_bin = _sanitize_nested_item(v, max_length=max_length)
            res_dict[str(k_val)] = v_val
            if k_trunc or v_trunc:
                truncated = True
            if k_bin or v_bin:
                binary = True
        return res_dict, truncated, binary

    val_str = str(val)
    if len(val_str) > max_length:
        return val_str[:max_length], True, False
    return val_str, False, False


class SafeSerializer:
    """自适应安全序列化器。

    防范解码崩溃、上下文 OOM、长文本溢出与大集合条数超载。

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

    @classmethod
    def serialize_collection(
        cls,
        collection: Iterable[Any] | Mapping[Any, Any],
        max_items: int = DEFAULT_MAX_COLLECTION_ITEMS,
        max_length: int = DEFAULT_MAX_LENGTH,
    ) -> SerializedCollection:
        """对集合结构（列表、集合、字典）执行元素条数安全切片截断与递归清洗。

        Args:
            collection: 待序列化的复杂集合对象
            max_items: 最大允许保留的项数（默认 100）
            max_length: 单个字符串最大允许字符长度（默认 4000）

        Returns:
            SerializedCollection: 集合切片序列化结果
        """
        if isinstance(collection, (dict, Mapping)):
            total_count = len(collection)
            data_type = "dict"
            is_collection_truncated = total_count > max_items
            sliced_entries = (
                list(collection.items())[:max_items]
                if is_collection_truncated
                else list(collection.items())
            )

            result_dict: dict[str, Any] = {}
            any_item_truncated = False
            has_binary = False
            for k, v in sliced_entries:
                k_clean, k_trunc, k_bin = _sanitize_nested_item(k, max_length=max_length)
                v_clean, v_trunc, v_bin = _sanitize_nested_item(v, max_length=max_length)
                if k_trunc or v_trunc:
                    any_item_truncated = True
                if k_bin or v_bin:
                    has_binary = True
                result_dict[str(k_clean)] = v_clean

            return SerializedCollection(
                items=result_dict,
                data_type=data_type,
                is_truncated=is_collection_truncated or any_item_truncated,
                total_count=total_count,
                has_binary=has_binary,
            )

        if isinstance(collection, (set, frozenset)):
            data_type = "set"
            items_seq = sorted(collection, key=lambda x: str(x))
        else:
            data_type = "list"
            items_seq = list(collection)

        total_count = len(items_seq)
        is_collection_truncated = total_count > max_items
        sliced_seq = items_seq[:max_items] if is_collection_truncated else items_seq

        result_list = []
        any_item_truncated = False
        has_binary = False
        for item in sliced_seq:
            clean_item, item_trunc, item_bin = _sanitize_nested_item(item, max_length=max_length)
            if item_trunc:
                any_item_truncated = True
            if item_bin:
                has_binary = True
            result_list.append(clean_item)

        return SerializedCollection(
            items=result_list,
            data_type=data_type,
            is_truncated=is_collection_truncated or any_item_truncated,
            total_count=total_count,
            has_binary=has_binary,
        )

    @classmethod
    def serialize_result(
        cls,
        raw: Any,
        command: str = "",
        max_items: int = DEFAULT_MAX_COLLECTION_ITEMS,
        max_length: int = DEFAULT_MAX_LENGTH,
    ) -> SerializedResult:
        """对 Redis 命令执行返回的任意原生结果执行自适应安全序列化与信封模型包装。

        Args:
            raw: Redis 命令执行返回的原生数据
            command: 关联执行的命令字符串（可选）
            max_items: 集合结构最大保留项数（默认 100）
            max_length: 单个字符串最大允许字符长度（默认 4000）

        Returns:
            SerializedResult: 统一命令结果实体模型
        """
        if raw is None:
            return SerializedResult(
                command=command,
                result=None,
                data_type="none",
                is_truncated=False,
                total_count=None,
            )

        if isinstance(raw, bool):
            return SerializedResult(
                command=command,
                result=raw,
                data_type="boolean",
                is_truncated=False,
                total_count=None,
            )

        if isinstance(raw, int):
            return SerializedResult(
                command=command,
                result=raw,
                data_type="integer",
                is_truncated=False,
                total_count=None,
            )

        if isinstance(raw, float):
            return SerializedResult(
                command=command,
                result=raw,
                data_type="float",
                is_truncated=False,
                total_count=None,
            )

        if isinstance(raw, (list, tuple, set, frozenset, dict, Mapping)):
            coll = cls.serialize_collection(raw, max_items=max_items, max_length=max_length)
            return SerializedResult(
                command=command,
                result=coll.items,
                data_type=coll.data_type,
                is_truncated=coll.is_truncated,
                total_count=coll.total_count if coll.total_count > max_items else None,
                is_binary=coll.has_binary,
            )

        if isinstance(raw, bytes):
            text, is_binary = _decode_bytes_safely(raw)
            is_trunc = len(text) > max_length
            final_text = text[:max_length] if is_trunc else text
            return SerializedResult(
                command=command,
                result=final_text,
                data_type="binary" if is_binary else "string",
                is_truncated=is_trunc,
                total_count=None,
                is_binary=is_binary,
            )

        val_str = raw if isinstance(raw, str) else str(raw)
        is_trunc = len(val_str) > max_length
        final_text = val_str[:max_length] if is_trunc else val_str
        return SerializedResult(
            command=command,
            result=final_text,
            data_type="string",
            is_truncated=is_trunc,
            total_count=None,
            is_binary=False,
        )
