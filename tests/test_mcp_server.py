"""The MCP tools, driven in-process through the SDK client. Skipped without `mcp` 2.x."""
import asyncio
import io
import os
import sys

import pytest

pytest.importorskip("mcp")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mcp import Client  # noqa: E402

from wan3 import client as wan_client  # noqa: E402
from wan3.mcp_server import server  # noqa: E402


class Body(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def call(tool, args):
    async def go():
        async with Client(server) as session:
            return await session.call_tool(tool, args)
    return asyncio.run(go())


def test_tool_list():
    async def go():
        async with Client(server) as session:
            return sorted(t.name for t in (await session.list_tools()).tools)
    assert asyncio.run(go()) == ["check_video", "create_video", "edit_video", "fetch_video"]


def test_create_video_returns_request_id_and_price(monkeypatch):
    monkeypatch.setenv("WAN_API_KEY", "k")
    monkeypatch.setattr(wan_client.urllib.request, "urlopen", lambda req, timeout=None: Body(b'{"request_id": "r-1"}'))
    result = call("create_video", {"prompt": "fog", "seconds": 10, "tier": "1080p"})
    assert not result.is_error
    assert result.structured_content["result"] == {"request_id": "r-1", "price_usd_before_reference_video": 1.5}


def test_bad_arguments_come_back_as_readable_tool_errors(monkeypatch):
    monkeypatch.setenv("WAN_API_KEY", "k")
    result = call("create_video", {"prompt": "fog", "tier": "768p"})
    assert result.is_error
    assert "resolution must be one of" in result.content[0].text
