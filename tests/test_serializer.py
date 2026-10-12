"""
安全序列化器（UTF-8 解码、Base64 转码、JSON 探测、长度截断）契约测试。

@author Ateng
@since 2026-10-04
"""

import base64
import gzip

from mcp_server_redis.core.serializer import (
    DEFAULT_MAX_COLLECTION_ITEMS,
    SafeSerializer,
    SerializedCollection,
    SerializedResult,
)


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


def test_serialize_large_list_slicing() -> None:
    """验证列表元素超过阈值（默认 100 项）时被安全切片截断并标记元数据。"""
    assert DEFAULT_MAX_COLLECTION_ITEMS == 100
    large_list = [f"item_{i}" for i in range(250)]

    # 1. serialize_collection 切片测试
    res_coll = SafeSerializer.serialize_collection(large_list)
    assert isinstance(res_coll, SerializedCollection)
    assert res_coll.data_type == "list"
    assert res_coll.is_truncated is True
    assert res_coll.total_count == 250
    assert len(res_coll.items) == 100
    assert res_coll.items[0] == "item_0"
    assert res_coll.items[99] == "item_99"

    # 2. serialize_result 统一网关结果模型测试（支持可选 command 传入）
    res_result = SafeSerializer.serialize_result(large_list, command="LRANGE mylist 0 -1")
    assert isinstance(res_result, SerializedResult)
    assert res_result.command == "LRANGE mylist 0 -1"
    assert res_result.data_type == "list"
    assert res_result.is_truncated is True
    assert res_result.total_count == 250
    assert len(res_result.result) == 100
    assert res_result.to_dict()["command"] == "LRANGE mylist 0 -1"


def test_serialize_small_list_no_slicing() -> None:
    """验证元素数量在阈值范围内的列表完整保留且不标记截断。"""
    small_list = [f"item_{i}" for i in range(50)]

    res_coll = SafeSerializer.serialize_collection(small_list)
    assert res_coll.is_truncated is False
    assert res_coll.total_count == 50
    assert len(res_coll.items) == 50

    res_result = SafeSerializer.serialize_result(small_list)
    assert res_result.is_truncated is False
    assert res_result.total_count is None
    assert len(res_result.result) == 50


def test_serialize_large_set_slicing() -> None:
    """验证大型集合（set）超过阈值时被安全切片截断并确定性排序输出。"""
    large_set = {f"set_item_{i:03d}" for i in range(200)}

    res_coll = SafeSerializer.serialize_collection(large_set)
    assert res_coll.data_type == "set"
    assert res_coll.is_truncated is True
    assert res_coll.total_count == 200
    assert len(res_coll.items) == 100
    # 确定性排序验证
    assert res_coll.items[0] == "set_item_000"
    assert res_coll.items[99] == "set_item_099"

    res_result = SafeSerializer.serialize_result(large_set)
    assert res_result.data_type == "set"
    assert res_result.is_truncated is True
    assert res_result.total_count == 200
    assert len(res_result.result) == 100


def test_serialize_large_dict_slicing() -> None:
    """验证字典（dict）键值对超过阈值时被安全截断为前 100 项。"""
    large_dict = {f"field_{i:03d}": f"val_{i:03d}" for i in range(180)}

    res_coll = SafeSerializer.serialize_collection(large_dict)
    assert res_coll.data_type == "dict"
    assert res_coll.is_truncated is True
    assert res_coll.total_count == 180
    assert len(res_coll.items) == 100
    assert "field_000" in res_coll.items
    assert "field_099" in res_coll.items
    assert "field_100" not in res_coll.items

    res_result = SafeSerializer.serialize_result(large_dict)
    assert res_result.data_type == "dict"
    assert res_result.is_truncated is True
    assert res_result.total_count == 180
    assert len(res_result.result) == 100


def test_serialize_small_dict_no_slicing() -> None:
    """验证键值对在阈值内的字典不触发切片截断。"""
    small_dict = {f"k_{i}": f"v_{i}" for i in range(10)}

    res_coll = SafeSerializer.serialize_collection(small_dict)
    assert res_coll.is_truncated is False
    assert res_coll.total_count == 10
    assert len(res_coll.items) == 10

    res_result = SafeSerializer.serialize_result(small_dict)
    assert res_result.is_truncated is False
    assert res_result.total_count is None
    assert len(res_result.result) == 10


def test_serialize_collection_nested_binary_and_long_text() -> None:
    """验证嵌套结构中的二进制内容自动转 Base64 且超长文本安全截断。"""
    raw_binary = gzip.compress(b"nested compressed payload")
    long_str = "Z" * 5000

    nested_payload = [
        b"valid utf8 string",
        raw_binary,
        long_str,
        {"inner_bin": gzip.compress(b"inner payload"), "inner_long": "Y" * 6000},
    ]

    res_coll = SafeSerializer.serialize_collection(nested_payload, max_length=100)
    assert len(res_coll.items) == 4
    # 验证嵌套长文本截断与二进制标记正确向上传播
    assert res_coll.is_truncated is True
    assert res_coll.has_binary is True

    # 1. 验证 UTF-8 字节串转为文本
    assert res_coll.items[0] == "valid utf8 string"
    # 2. 验证非 UTF-8 二进制字节串自动转 Base64
    assert isinstance(res_coll.items[1], str)
    assert base64.b64decode(res_coll.items[1]) == raw_binary
    # 3. 验证长字符串截断为 max_length (100)
    assert res_coll.items[2] == "Z" * 100
    # 4. 验证嵌套字典内部也递归安全处理
    inner_dict = res_coll.items[3]
    assert isinstance(inner_dict, dict)
    assert base64.b64decode(inner_dict["inner_bin"]) == gzip.compress(b"inner payload")
    assert inner_dict["inner_long"] == "Y" * 100

    # 5. 验证统一信封模型正确继承集合内的截断与二进制状态
    res_result = SafeSerializer.serialize_result(nested_payload, max_length=100)
    assert res_result.is_truncated is True
    assert res_result.is_binary is True


def test_serialize_result_scalar_types() -> None:
    """验证通用 serialize_result 对标量基础类型（None/bool/int/float/str/bytes）的类型推导与信封格式。"""
    # None
    r_none = SafeSerializer.serialize_result(None)
    assert r_none.data_type == "none"
    assert r_none.result is None
    assert r_none.is_truncated is False

    # Boolean
    r_bool = SafeSerializer.serialize_result(True)
    assert r_bool.data_type == "boolean"
    assert r_bool.result is True

    # Integer
    r_int = SafeSerializer.serialize_result(42)
    assert r_int.data_type == "integer"
    assert r_int.result == 42

    # Float
    r_float = SafeSerializer.serialize_result(3.14159)
    assert r_float.data_type == "float"
    assert r_float.result == 3.14159

    # Standard UTF-8 bytes
    r_bytes = SafeSerializer.serialize_result(b"redis string")
    assert r_bytes.data_type == "string"
    assert r_bytes.result == "redis string"

    # Binary bytes
    bin_data = gzip.compress(b"binary data")
    r_bin = SafeSerializer.serialize_result(bin_data)
    assert r_bin.data_type == "binary"
    assert r_bin.is_binary is True
    assert base64.b64decode(r_bin.result) == bin_data

    # Long text truncation
    r_long = SafeSerializer.serialize_result("A" * 5000, max_length=50)
    assert r_long.data_type == "string"
    assert r_long.is_truncated is True
    assert len(r_long.result) == 50
