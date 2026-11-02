#!/usr/bin/env python
"""DeepSeek Search / Fetch as a minimal MCP stdio server.

Tools:
- deepseek_search: POST https://api.deepseek.com/v1/tools/search
- deepseek_fetch: POST https://api.deepseek.com/v1/tools/fetch

Authentication uses DEEPSEEK_API_KEY when set. Otherwise it reuses
model_providers.deepseek.experimental_bearer_token from ~/.codex/config.toml.
The token is never logged or returned.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tomllib
import traceback
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


SERVER_NAME = "deepseek_web"
SERVER_VERSION = "1.0.0"
PROTOCOL_VERSION = "2025-06-18"
API_BASE = "https://api.deepseek.com"
REQUEST_TIMEOUT_SECONDS = 120
LOG_PATH = Path(__file__).resolve().parents[1] / "_tmp" / "deepseek_web_mcp.log"

TOOLS = [
    {
        "name": "deepseek_search",
        "description": (
            "Search the public web with DeepSeek's search API. "
            "Prefers a small result set and includes page content by default."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                    "description": "Search query. Supports site:, lang:, after:, before:.",
                },
                "count": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 5,
                    "description": "Number of results to return.",
                },
                "need_content": {
                    "type": "boolean",
                    "default": True,
                    "description": "Include page content in each result.",
                },
                "ori_question": {
                    "type": "string",
                    "maxLength": 128,
                    "description": "Original user question for search intent.",
                },
                "localization": {
                    "type": "string",
                    "description": "IP address used to prefer localized results.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "deepseek_fetch",
        "description": "Fetch one public web page and return its Markdown text.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Public HTTP or HTTPS URL.",
                }
            },
            "required": ["url"],
        },
    },
]


def _load_api_key() -> str:
    env_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if env_key:
        return env_key

    config_path = Path.home() / ".codex" / "config.toml"
    try:
        with config_path.open("rb") as fh:
            config = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeError(f"无法读取 DeepSeek 配置：{config_path}") from exc

    provider = config.get("model_providers", {}).get("deepseek", {})
    token = str(provider.get("experimental_bearer_token", "")).strip()
    if not token:
        raise RuntimeError(
            "缺少 DEEPSEEK_API_KEY，且 config.toml 的 "
            "model_providers.deepseek.experimental_bearer_token 为空"
        )
    return token


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    token = _load_api_key()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()

    request = urllib.request.Request(
        API_BASE + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "codex-deepseek-web-mcp/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request, timeout=REQUEST_TIMEOUT_SECONDS
        ) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        message = body
        try:
            message = json.loads(body).get("error", {}).get("message", body)
        except (json.JSONDecodeError, AttributeError):
            pass
        raise RuntimeError(f"DeepSeek API HTTP {exc.code}: {message}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"DeepSeek API 连接失败：{exc.reason}") from exc

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError("DeepSeek API 返回了非 JSON 内容") from exc
    if not isinstance(data, dict):
        raise RuntimeError("DeepSeek API 返回格式不是 JSON object")
    return data


def deepseek_search(arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query", "")).strip()
    if not query:
        raise RuntimeError("query 不能为空")
    if len(query) > 128:
        raise RuntimeError("query 不能超过 128 个字符")

    try:
        count = int(arguments.get("count", 5))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("count 必须是整数") from exc
    if not 1 <= count <= 50:
        raise RuntimeError("count 必须在 1 到 50 之间")

    payload: dict[str, Any] = {
        "query": query,
        "count": count,
        "need_content": bool(arguments.get("need_content", True)),
    }
    for key in ("ori_question", "localization"):
        value = arguments.get(key)
        if value not in (None, ""):
            payload[key] = str(value)
    return _post("/v1/tools/search", payload)


def deepseek_fetch(arguments: dict[str, Any]) -> dict[str, Any]:
    url = str(arguments.get("url", "")).strip()
    if not re.match(r"^https?://[^/\s]+", url, flags=re.IGNORECASE):
        raise RuntimeError("url 必须是完整的 HTTP/HTTPS 地址")
    if len(url) > 8192:
        raise RuntimeError("url 不能超过 8192 个字符")
    return _post("/v1/tools/fetch", {"url": url})


def _tool_result(payload: Any, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, ensure_ascii=False),
            }
        ],
        "isError": is_error,
    }


def _debug(message: str) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] {message}\n")
    except OSError:
        pass


def _handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}
    _debug(f"request method={method}")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": SERVER_NAME,
                    "version": SERVER_VERSION,
                },
                "instructions": (
                    "Use deepseek_search for current public information. "
                    "Use deepseek_fetch only when an exact page is needed."
                ),
            },
        }
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": TOOLS},
        }
    if method == "resources/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"resources": []},
        }
    if method == "resources/templates/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"resourceTemplates": []},
        }
    if method == "prompts/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"prompts": []},
        }
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        arg_keys = sorted(arguments) if isinstance(arguments, dict) else type(arguments).__name__
        _debug(f"tool_call name={name} arg_keys={arg_keys} param_keys={sorted(params)}")
        try:
            if name == "deepseek_search":
                payload = deepseek_search(arguments)
            elif name == "deepseek_fetch":
                payload = deepseek_fetch(arguments)
            else:
                raise RuntimeError(f"未知工具：{name}")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": _tool_result(payload),
            }
        except Exception as exc:
            _debug(f"tool_error name={name}\n{traceback.format_exc()}")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": _tool_result(str(exc), is_error=True),
            }
    if method == "logging/setLevel":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}

    if request_id is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    _debug(f"server_start pid={os.getpid()}")
    for raw_line in sys.stdin.buffer:
        try:
            message = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {exc}"},
            }
        else:
            if not isinstance(message, dict):
                response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32600, "message": "Invalid Request"},
                }
            else:
                try:
                    response = _handle_request(message)
                except BaseException:
                    _debug("fatal_request_error\n" + traceback.format_exc())
                    response = {
                        "jsonrpc": "2.0",
                        "id": message.get("id"),
                        "error": {"code": -32603, "message": "Internal error"},
                    }
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
