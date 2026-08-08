# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Stateful MCP request dispatcher."""

from __future__ import annotations

import logging
import threading
from typing import Any

from pymol_cli.rpc.client import EngineClientError

from .model import ClientFactory, EngineClientLike, JsonObject, McpError, McpRequestId
from .protocol import (
    _REQUEST_FIELDS,
    MCP_PROTOCOL_VERSION,
    SERVER_INFO,
    SERVER_NOT_INITIALIZED,
    is_request_id,
    jsonrpc_error,
    tool_error_result,
    tool_result,
)
from .tools import build_tools

MAX_CONCURRENT_TOOL_CALLS = 32
_PENDING_REQUEST = object()
_CANCELLED_REQUEST = object()
_LOGGER = logging.getLogger("pymol_cli.mcp")


class McpServer:
    def __init__(self, client_factory: ClientFactory) -> None:
        self._client_factory = client_factory
        self._tools = build_tools()
        self._initialize_received = False
        self._ready = False
        self._active_request_lock = threading.Lock()
        self._active_requests: dict[McpRequestId, object] = {}
        self._request_context = threading.local()

    def handle(self, message: object) -> JsonObject | None:
        request_id = self._request_id_for_error(message)
        self._request_context.request_id = request_id
        is_notification = False
        method: str | None = None
        try:
            method, is_notification = self._validate_envelope(message)
            if not isinstance(message, dict):
                raise McpError(-32600, "request must be an object")
            result = self._dispatch(method, message.get("params"))
            if is_notification:
                return None
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except McpError as exc:
            if is_notification:
                return None
            return jsonrpc_error(request_id, exc.code, exc.message)
        except Exception:
            _LOGGER.exception("unexpected exception while handling MCP request")
            if is_notification:
                return None
            return jsonrpc_error(request_id, -32603, "internal error")
        finally:
            if method == "tools/call" and is_request_id(request_id):
                self._finish_request(request_id)
            try:
                del self._request_context.request_id
            except AttributeError:
                pass

    @staticmethod
    def _request_id_for_error(message: object) -> Any:
        if not isinstance(message, dict) or "id" not in message:
            return None
        value = message.get("id")
        if not is_request_id(value):
            return None
        return value

    @staticmethod
    def _validate_envelope(message: object) -> tuple[str, bool]:
        if not isinstance(message, dict):
            raise McpError(-32600, "request must be an object")
        if message.get("jsonrpc") != "2.0":
            raise McpError(-32600, 'jsonrpc must be "2.0"')
        unexpected = set(message) - _REQUEST_FIELDS
        if unexpected:
            names = ", ".join(sorted(str(name) for name in unexpected))
            raise McpError(-32600, f"unexpected request fields: {names}")
        method = message.get("method")
        if not isinstance(method, str) or not method:
            raise McpError(-32600, "method must be a non-empty string")
        is_notification = method.startswith("notifications/")
        if is_notification:
            if "id" in message:
                raise McpError(-32600, "notifications must not include id")
        elif "id" not in message:
            raise McpError(-32600, "requests must include id")
        elif not is_request_id(message.get("id")):
            raise McpError(-32600, "id must be a string or finite number")
        return method, is_notification

    def is_async_tool_request(self, message: object) -> bool:
        try:
            method, is_notification = self._validate_envelope(message)
        except McpError:
            return False
        return not is_notification and method == "tools/call" and self._ready

    def has_active_request(self, request_id: McpRequestId) -> bool:
        with self._active_request_lock:
            return request_id in self._active_requests

    def reserve_async_request(self, request_id: McpRequestId) -> str | None:
        with self._active_request_lock:
            if request_id in self._active_requests:
                return "duplicate active request id"
            if len(self._active_requests) >= MAX_CONCURRENT_TOOL_CALLS:
                return "too many active tool calls"
            self._active_requests[request_id] = _PENDING_REQUEST
            return None

    def _dispatch(self, method: str, params: Any) -> JsonObject | None:
        if method == "initialize":
            return self._initialize(params)
        if method == "notifications/initialized":
            self._mark_ready(params)
            return None
        if method == "ping":
            self._validate_optional_params(params, "ping")
            return {}
        if not self._ready:
            raise McpError(SERVER_NOT_INITIALIZED, "server is not initialized")
        if method == "notifications/cancelled":
            self._cancel_request(params)
            return None
        if method == "tools/list":
            self._validate_optional_params(params, method)
            return {"tools": [tool.to_mcp() for tool in self._tools.values()]}
        if method == "tools/call":
            return self._call_tool(params)
        raise McpError(-32601, f"method not found: {method}")

    def _initialize(self, params: Any) -> JsonObject:
        if self._initialize_received:
            raise McpError(-32600, "server is already initialized")
        if not isinstance(params, dict):
            raise McpError(-32602, "initialize params must be an object")
        protocol_version = params.get("protocolVersion")
        if protocol_version != MCP_PROTOCOL_VERSION:
            raise McpError(
                -32602,
                f"unsupported protocol version: {protocol_version!r}",
            )
        if not isinstance(params.get("capabilities"), dict):
            raise McpError(-32602, "initialize capabilities must be an object")
        client_info = params.get("clientInfo")
        if not isinstance(client_info, dict):
            raise McpError(-32602, "initialize clientInfo must be an object")
        for field in ("name", "version"):
            if not isinstance(client_info.get(field), str) or not client_info[field]:
                raise McpError(
                    -32602,
                    f"initialize clientInfo.{field} must be a non-empty string",
                )
        self._initialize_received = True
        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        }

    def _mark_ready(self, params: Any) -> None:
        self._validate_optional_params(params, "notifications/initialized")
        if not self._initialize_received or self._ready:
            raise McpError(-32600, "unexpected initialized notification")
        self._ready = True

    @staticmethod
    def _validate_optional_params(params: Any, method: str) -> None:
        if params is not None and not isinstance(params, dict):
            raise McpError(-32602, f"{method} params must be an object")

    def _cancel_request(self, params: Any) -> None:
        if not isinstance(params, dict):
            raise McpError(-32602, "notifications/cancelled params must be an object")
        unexpected = set(params) - {"requestId", "reason"}
        if unexpected:
            names = ", ".join(sorted(str(name) for name in unexpected))
            raise McpError(-32602, f"unexpected cancellation params: {names}")
        request_id = params.get("requestId")
        if not is_request_id(request_id):
            raise McpError(-32602, "cancellation requestId must be valid")
        reason = params.get("reason")
        if reason is not None and not isinstance(reason, str):
            raise McpError(-32602, "cancellation reason must be a string")
        client: object | None = None
        with self._active_request_lock:
            active = self._active_requests.get(request_id)
            if active is _PENDING_REQUEST:
                self._active_requests[request_id] = _CANCELLED_REQUEST
            elif active is not None and active is not _CANCELLED_REQUEST:
                self._active_requests[request_id] = _CANCELLED_REQUEST
                client = active
        if client is not None:
            self._close_client(client)

    def _attach_request_client(
        self, request_id: McpRequestId, client: EngineClientLike
    ) -> bool:
        with self._active_request_lock:
            active = self._active_requests.get(request_id)
            if active is _CANCELLED_REQUEST:
                return False
            if active is not None and active is not _PENDING_REQUEST:
                return False
            self._active_requests[request_id] = client
            return True

    def _request_was_cancelled(self, request_id: McpRequestId) -> bool:
        with self._active_request_lock:
            return self._active_requests.get(request_id) is _CANCELLED_REQUEST

    def _finish_request(self, request_id: McpRequestId) -> None:
        with self._active_request_lock:
            self._active_requests.pop(request_id, None)

    @staticmethod
    def _close_client(client: object) -> None:
        close = getattr(client, "close", None)
        if not callable(close):
            return
        try:
            close()
        except OSError:
            pass

    def _call_tool(self, params: Any) -> JsonObject:
        if not isinstance(params, dict):
            raise McpError(-32602, "tools/call params must be an object")
        name = params.get("name")
        if not isinstance(name, str):
            raise McpError(-32602, "tools/call requires string name")
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            raise McpError(-32602, "tools/call arguments must be an object")
        tool = self._tools.get(name)
        if tool is None:
            raise McpError(-32602, f"unknown tool: {name}")
        properties = tool.input_schema.get("properties")
        allowed = set(properties) if isinstance(properties, dict) else set()
        unexpected = set(arguments) - allowed
        if unexpected:
            names = ", ".join(sorted(str(key) for key in unexpected))
            raise McpError(-32602, f"unexpected tool arguments: {names}")
        request_id = getattr(self._request_context, "request_id", None)
        if not is_request_id(request_id):
            raise McpError(-32600, "tools/call requires a valid request id")
        try:
            client = self._client_factory()
            if not self._attach_request_client(request_id, client):
                self._close_client(client)
                return tool_error_result("request was cancelled")
            with client:
                result = tool.handler(client, arguments)
            if self._request_was_cancelled(request_id):
                return tool_error_result("request was cancelled")
            return tool_result(result)
        except McpError:
            raise
        except (EngineClientError, OSError) as exc:
            if self._request_was_cancelled(request_id):
                return tool_error_result("request was cancelled")
            return tool_error_result(str(exc) or "tool execution failed")
        except Exception:
            _LOGGER.exception("unexpected exception while executing MCP tool")
            return tool_error_result("tool execution failed")
