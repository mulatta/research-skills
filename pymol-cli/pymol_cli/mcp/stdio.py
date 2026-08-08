# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Concurrent MCP JSONL stdio transport."""

from __future__ import annotations

import json
import logging
import queue
import threading
from typing import BinaryIO, NoReturn

from .model import JsonObject
from .protocol import is_request_id, jsonrpc_error
from .server import McpServer

_LOGGER = logging.getLogger("pymol_cli.mcp")


def reject_nonstandard_json_constant(value: str) -> NoReturn:
    raise ValueError(f"invalid JSON constant: {value}")


def run_stdio(server: McpServer, stdin: BinaryIO, stdout: BinaryIO) -> None:
    output_lock = threading.Lock()
    tool_queue: queue.Queue[object] = queue.Queue()
    stop_worker = object()

    def emit(message: JsonObject) -> None:
        with output_lock:
            write_jsonl(stdout, message)

    def handle_message(decoded: object) -> None:
        try:
            response = server.handle(decoded)
        except Exception:
            _LOGGER.exception("unexpected exception at MCP stdio boundary")
            request_id = McpServer._request_id_for_error(decoded)
            response = jsonrpc_error(request_id, -32603, "internal error")
        if response is not None:
            emit(response)

    def tool_worker() -> None:
        while True:
            decoded = tool_queue.get()
            try:
                if decoded is stop_worker:
                    return
                handle_message(decoded)
            finally:
                tool_queue.task_done()

    worker = threading.Thread(target=tool_worker, name="pymol-mcp-tool")
    worker.start()
    try:
        while line := stdin.readline():
            if not line.strip():
                continue
            try:
                decoded = json.loads(
                    line.decode("utf-8"),
                    parse_constant=reject_nonstandard_json_constant,
                )
            except (UnicodeDecodeError, ValueError) as exc:
                emit(jsonrpc_error(None, -32700, str(exc)))
                continue
            request_id = McpServer._request_id_for_error(decoded)
            if is_request_id(request_id) and server.has_active_request(request_id):
                emit(jsonrpc_error(request_id, -32600, "duplicate active request id"))
                continue
            if server.is_async_tool_request(decoded):
                if not is_request_id(request_id):
                    handle_message(decoded)
                    continue
                reservation_error = server.reserve_async_request(request_id)
                if reservation_error is not None:
                    error_code = (
                        -32600 if reservation_error.startswith("duplicate") else -32000
                    )
                    emit(jsonrpc_error(request_id, error_code, reservation_error))
                    continue
                tool_queue.put(decoded)
                continue
            handle_message(decoded)
    finally:
        tool_queue.put(stop_worker)
        worker.join()


def write_jsonl(stdout: BinaryIO, message: JsonObject) -> None:
    stdout.write(
        json.dumps(message, allow_nan=False, separators=(",", ":")).encode("utf-8")
    )
    stdout.write(b"\n")
    stdout.flush()
