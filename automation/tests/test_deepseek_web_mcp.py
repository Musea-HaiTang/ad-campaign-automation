from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import deepseek_web_mcp as mcp  # noqa: E402


def test_tools_list_contains_search_and_fetch():
    response = mcp._handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    )
    names = {tool["name"] for tool in response["result"]["tools"]}
    assert names == {"deepseek_search", "deepseek_fetch"}


def test_search_defaults_to_five_results_with_content(monkeypatch):
    captured = {}

    def fake_post(path, payload):
        captured["path"] = path
        captured["payload"] = payload
        return {"results": []}

    monkeypatch.setattr(mcp, "_post", fake_post)
    mcp.deepseek_search({"query": "腾讯云 GPU 云服务器"})
    assert captured["path"] == "/v1/tools/search"
    assert captured["payload"]["count"] == 5
    assert captured["payload"]["need_content"] is True


def test_fetch_rejects_non_http_url():
    with pytest.raises(RuntimeError, match="HTTP/HTTPS"):
        mcp.deepseek_fetch({"url": "example.com"})


def test_initialize_returns_server_info():
    response = mcp._handle_request(
        {"jsonrpc": "2.0", "id": 7, "method": "initialize", "params": {}}
    )
    assert response["result"]["serverInfo"]["name"] == "deepseek_web"
    assert "tools" in response["result"]["capabilities"]


@pytest.mark.parametrize(
    ("method", "key"),
    [
        ("resources/list", "resources"),
        ("resources/templates/list", "resourceTemplates"),
        ("prompts/list", "prompts"),
    ],
)
def test_standard_empty_lists_keep_transport_alive(method, key):
    response = mcp._handle_request(
        {"jsonrpc": "2.0", "id": 8, "method": method, "params": {}}
    )
    assert response["result"][key] == []


def test_missing_query_returns_tool_error():
    response = mcp._handle_request(
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {"name": "deepseek_search", "arguments": {}},
        }
    )
    result = response["result"]
    assert result["isError"] is True
    assert json.loads(result["content"][0]["text"]) == "query 不能为空"


def test_tools_call_forwards_search_arguments(monkeypatch):
    captured = {}

    def fake_post(path, payload):
        captured["path"] = path
        captured["payload"] = payload
        return {"results": []}

    monkeypatch.setattr(mcp, "_post", fake_post)
    response = mcp._handle_request(
        {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {
                "name": "deepseek_search",
                "arguments": {
                    "query": "腾讯云 GPU",
                    "count": 1,
                    "need_content": False,
                },
            },
        }
    )

    assert response["result"]["isError"] is False
    assert captured["payload"]["query"] == "腾讯云 GPU"
    assert captured["payload"]["count"] == 1
