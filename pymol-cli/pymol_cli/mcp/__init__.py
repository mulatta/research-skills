# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Minimal MCP stdio adapter for the local PyMOL engine."""

from __future__ import annotations

from .cli import build_parser, die, main, positive_finite_float
from .model import (
    ClientFactory,
    EngineClientLike,
    JsonObject,
    McpError,
    McpRequestId,
    Tool,
)
from .protocol import (
    MCP_PROTOCOL_VERSION,
    SERVER_INFO,
    SERVER_NOT_INITIALIZED,
    is_request_id,
    jsonrpc_error,
    reject_nonstandard_json_constant,
    tool_error_result,
    tool_result,
)
from .server import MAX_CONCURRENT_TOOL_CALLS, McpServer
from .stdio import run_stdio, write_jsonl
from .tools import (
    MIN_RENDER_DIMENSION,
    MIN_RENDER_DPI,
    boolean_arg,
    build_tools,
    integer_arg,
    normalize_path,
    number_arg,
    object_schema,
    optional_bool,
    optional_float,
    optional_int,
    require_string,
    string_arg,
)

__all__ = [
    "MAX_CONCURRENT_TOOL_CALLS",
    "MCP_PROTOCOL_VERSION",
    "MIN_RENDER_DIMENSION",
    "MIN_RENDER_DPI",
    "SERVER_INFO",
    "SERVER_NOT_INITIALIZED",
    "ClientFactory",
    "EngineClientLike",
    "JsonObject",
    "McpError",
    "McpRequestId",
    "McpServer",
    "Tool",
    "boolean_arg",
    "build_parser",
    "build_tools",
    "die",
    "integer_arg",
    "is_request_id",
    "jsonrpc_error",
    "main",
    "normalize_path",
    "number_arg",
    "object_schema",
    "optional_bool",
    "optional_float",
    "optional_int",
    "positive_finite_float",
    "reject_nonstandard_json_constant",
    "require_string",
    "run_stdio",
    "string_arg",
    "tool_error_result",
    "tool_result",
    "write_jsonl",
]
