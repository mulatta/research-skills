# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""JSON-RPC 2.0 envelope validation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

JsonRpcId = str | int | None

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


@dataclass(frozen=True)
class JsonRpcRequest:
    id: JsonRpcId
    method: str
    params: dict[str, Any]


@dataclass
class JsonRpcError(Exception):
    code: int
    message: str
    id: JsonRpcId = None
    data: dict[str, Any] | None = None

    def __str__(self) -> str:
        return self.message


def parse_request(message: dict[str, Any]) -> JsonRpcRequest:
    if message.get("jsonrpc") != "2.0":
        raise JsonRpcError(
            INVALID_REQUEST, "invalid JSON-RPC version", message.get("id")
        )
    method = message.get("method")
    if not isinstance(method, str) or not method:
        raise JsonRpcError(
            INVALID_REQUEST, "method must be a non-empty string", message.get("id")
        )
    request_id = message.get("id")
    if not _is_valid_id(request_id):
        raise JsonRpcError(INVALID_REQUEST, "id must be string, integer, or null", None)
    params_value = message.get("params", {})
    if params_value is None:
        params: dict[str, Any] = {}
    elif isinstance(params_value, dict):
        params = params_value
    else:
        raise JsonRpcError(INVALID_REQUEST, "params must be an object", request_id)
    return JsonRpcRequest(id=request_id, method=method, params=params)


def build_result(request_id: JsonRpcId, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def build_error(error: JsonRpcError) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": error.id,
        "error": {"code": error.code, "message": error.message},
    }
    if error.data is not None:
        payload["error"]["data"] = error.data
    return payload


def _is_valid_id(value: Any) -> bool:
    return value is None or isinstance(value, str) or _is_integer_id(value)


def _is_integer_id(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
