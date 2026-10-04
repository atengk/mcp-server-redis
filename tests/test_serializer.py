"""
安全序列化器（UTF-8 解码、Base64 转码、JSON 探测、长度截断）契约测试。

@author Ateng
@since 2026-10-04
"""

import base64
import gzip

from mcp_server_redis.core.serializer import SafeSerializer


def test_serialize_none() -> None:
    """验证传入 None 时返回空值模型。"""
    res = SafeSerializer.serialize_value(None)
    assert res.value is None
    assert res.is_binary is False
    assert res.truncated is False
    assert res.total_length == 0
    assert res.json_data is None


def test_serialize_utf8_string() -> None:
    """验证标准 UTF-8 文本正常解码并保留原始值。"""
    res = SafeSerializer.serialize_value("hello world")
    assert res.value == "hello world"
    assert res.is_binary is False
    assert res.truncated is False
    assert res.total_length == 11
    assert res.json_data is None


def test_serialize_utf8_bytes() -> None:
    """验证 UTF-8 字节串自动解码为文本。"""
    raw_bytes = "你好，Redis".encode()
    res = SafeSerializer.serialize_value(raw_bytes)
    assert res.value == "你好，Redis"
    assert res.is_binary is False
    assert res.truncated is False
    assert res.total_length == len("你好，Redis")


def test_serialize_json_string_and_bytes() -> None:
    """验证合法 JSON 文本及字节串自动解析为结构化字典。"""
    json_str = '{"user_id": 1001, "name": "Ateng", "active": true}'
    res = SafeSerializer.serialize_value(json_str, parse_json=True)
    assert res.value == json_str
    assert res.is_binary is False
    assert res.json_data == {"user_id": 1001, "name": "Ateng", "active": True}

    # 测试 JSON 列表
    json_list_bytes = b'["apple", "banana", "cherry"]'
    res_list = SafeSerializer.serialize_value(json_list_bytes, parse_json=True)
    assert res_list.json_data == ["apple", "banana", "cherry"]


def test_serialize_invalid_json_keeps_string() -> None:
    """验证非法 JSON 不报错并保留 json_data 为 None。"""
    raw_text = "not a valid {json"
    res = SafeSerializer.serialize_value(raw_text, parse_json=True)
    assert res.value == raw_text
    assert res.json_data is None


def test_serialize_binary_bytes_auto_base64() -> None:
    """验证非 UTF-8 二进制字节串自动转码为 Base64 并打标 is_binary: true。"""
    # 构造非 UTF-8 二进制数据（如 gzip 压缩数据）
    compressed_bytes = gzip.compress(b"some large binary payload")
    res = SafeSerializer.serialize_value(compressed_bytes)

    assert res.is_binary is True
    assert res.json_data is None
    assert isinstance(res.value, str)
    assert res.total_length == len(res.value)
    # 验证能逆向 Base64 解码并与原始字节一致
    decoded = base64.b64decode(res.value)
    assert decoded == compressed_bytes


def test_serialize_long_text_truncation() -> None:
    """验证超长字符串被安全截断并附带截断元数据。"""
    long_text = "A" * 5000
    res = SafeSerializer.serialize_value(long_text, max_length=100)

    assert res.truncated is True
    assert res.total_length == 5000
    assert res.value == "A" * 100
    assert len(res.value) == 100


def test_serialize_long_binary_truncation() -> None:
    """验证超长二进制 Base64 被安全截断。"""
    raw_binary = bytes([i % 256 for i in range(5000)])
    res = SafeSerializer.serialize_value(raw_binary, max_length=200)

    assert res.is_binary is True
    assert res.truncated is True
    assert res.total_length > 200
    assert len(res.value) == 200  # type: ignore[arg-type]


def test_serialize_list_and_dict() -> None:
    """验证批量列表与字典结构的安全序列化。"""
    items = [b"item1", b'{"key": "val"}', None]
    serialized_items = SafeSerializer.serialize_list(items, parse_json=True)
    assert len(serialized_items) == 3
    assert serialized_items[0].value == "item1"
    assert serialized_items[1].json_data == {"key": "val"}
    assert serialized_items[2].value is None

    mapping = {b"field1": b"value1", "field2": b'{"a": 1}'}
    serialized_dict = SafeSerializer.serialize_dict(mapping, parse_json=True)
    assert "field1" in serialized_dict
    assert serialized_dict["field1"].value == "value1"
    assert serialized_dict["field2"].json_data == {"a": 1}


def test_serialize_large_json_truncated_does_not_penetrate_json_data() -> None:
    """验证超长 JSON 被截断时不反序列化庞大 json_data，防止撑爆大模型上下文。"""
    import json

    big_dict = {"data": "X" * 1000}
    big_json = json.dumps(big_dict)
    res = SafeSerializer.serialize_value(big_json, parse_json=True, max_length=50)

    assert res.truncated is True
    assert len(res.value) == 50  # type: ignore[arg-type]
    assert res.json_data is None  # 超长截断时安全置空，杜绝上下文穿透

