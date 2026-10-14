"""
MCP 只读快照资源与数据脱敏单元测试。

@author Ateng
@since 2026-10-14
"""

import json
from unittest.mock import AsyncMock

import pytest
import redis.exceptions

from mcp_server_redis.resources import (
    _get_formatted_client_list,
    _get_formatted_slowlog,
    mask_ip_address,
)


def test_mask_ip_address() -> None:
    """验证 IPv4 地址末段脱敏掩码函数。"""
    assert mask_ip_address("") == ""
    assert mask_ip_address("127.0.0.1:6379") == "127.0.0.***:6379"
    assert mask_ip_address("192.168.1.150") == "192.168.1.***"
    assert (
        mask_ip_address("id=42 addr=10.20.30.40:5432 fd=7") == "id=42 addr=10.20.30.***:5432 fd=7"
    )


@pytest.mark.asyncio
async def test_get_formatted_client_list_success() -> None:
    """验证成功提取活跃客户端连接列表并对 IP 末段进行脱敏。"""
    mock_client = AsyncMock()
    mock_client.client_list = AsyncMock(
        return_value=[
            {
                "id": "1",
                "addr": "192.168.1.105:54321",
                "fd": "8",
                "name": "worker-1",
                "age": "120",
                "idle": "0",
                "flags": "N",
                "db": "0",
                "cmd": "client",
            },
            {
                b"id": b"2",
                b"addr": b"10.0.0.88:6379",
                b"name": b"replica-node",
            },
        ]
    )

    result_json = await _get_formatted_client_list(mock_client)
    clients = json.loads(result_json)
    assert len(clients) == 2

    # 验证普通字典键值及 IP 脱敏
    assert clients[0]["id"] == "1"
    assert clients[0]["addr"] == "192.168.1.***:54321"

    # 验证二进制 bytes 解码及 IP 脱敏
    assert clients[1]["id"] == "2"
    assert clients[1]["addr"] == "10.0.0.***:6379"


@pytest.mark.asyncio
async def test_get_formatted_client_list_error() -> None:
    """验证读取客户端连接列表抛出异常时的安全容错。"""
    mock_client = AsyncMock()
    mock_client.client_list = AsyncMock(
        side_effect=redis.exceptions.ConnectionError("Redis connection lost")
    )

    result_json = await _get_formatted_client_list(mock_client)
    res = json.loads(result_json)
    assert "error" in res
    assert "Redis connection lost" in res["error"]


@pytest.mark.asyncio
async def test_get_formatted_slowlog() -> None:
    """验证慢日志提取格式化与异常兜底。"""
    mock_client = AsyncMock()
    mock_client.slowlog_get = AsyncMock(
        return_value=[
            {
                "id": 1,
                "start_time": 1600000000,
                "duration": 12500,
                "command": [b"KEYS", b"*"],
            }
        ]
    )

    result_json = await _get_formatted_slowlog(mock_client)
    slowlogs = json.loads(result_json)
    assert len(slowlogs) == 1
    assert slowlogs[0]["id"] == 1
    assert slowlogs[0]["command"] == ["KEYS", "*"]
