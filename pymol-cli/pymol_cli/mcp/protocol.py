# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""MCP and JSON-RPC wire protocol helpers."""

from __future__ import annotations

import json
import math
from typing import Any, NoReturn, TypeGuard

from .model import JsonObject, McpRequestId

MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "pymol-mcp", "version": "0.1.0"}
SERVER_NOT_INITIALIZED = -32002
_REQUEST_FIELDS = frozenset({"jsonrpc", "id", "method", "params"})


def is_request_id(value: Any) -> TypeGuard[McpRequestId]:
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        return False
    return not isinstance(value, float) or math.isfinite(value)


def tool_result(result: JsonObject) -> JsonObject:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    result,
                    allow_nan=False,
                    indent=2,
                    sort_keys=True,
                ),
            }
        ]
    }


def tool_error_result(message: str) -> JsonObject:
    return {
        "content": [{"type": "text", "text": message}],
        "isError": True,
    }


def jsonrpc_error(request_id: Any, code: int, message: str) -> JsonObject:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def reject_nonstandard_json_constant(value: str) -> NoReturn:
    raise ValueError(f"invalid JSON constant: {value}")
