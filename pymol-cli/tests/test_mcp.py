# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import io
import json
import threading
from pathlib import Path
from typing import Any, Self

import pytest

from pymol_cli import mcp
from pymol_cli.mcp import MCP_PROTOCOL_VERSION, McpServer, build_tools, run_stdio
from pymol_cli.rpc.client import EngineClientError


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def count_atoms(self, selection: str) -> dict[str, Any]:
        self.calls.append(("count_atoms", (selection,)))
        return {"selection": selection, "count": 10, "revision": 1}

    def load_structure(self, path: str, object_name: str) -> dict[str, Any]:
        self.calls.append(("load_structure", (path, object_name)))
        return {"path": path, "object_name": object_name, "revision": 1}

    def list_objects(self) -> dict[str, Any]:
        self.calls.append(("list_objects", ()))
        return {"object_names": ["prot"], "revision": 1}

    def show_representation(
        self, representation: str, selection: str
    ) -> dict[str, Any]:
        self.calls.append(("show_representation", (representation, selection)))
        return {"revision": 1}

    def hide_representation(
        self, representation: str, selection: str
    ) -> dict[str, Any]:
        self.calls.append(("hide_representation", (representation, selection)))
        return {"revision": 1}

    def color_selection(self, color: str, selection: str) -> dict[str, Any]:
        self.calls.append(("color_selection", (color, selection)))
        return {"revision": 1}

    def zoom_selection(self, selection: str, buffer: float) -> dict[str, Any]:
        self.calls.append(("zoom_selection", (selection, buffer)))
        return {"revision": 1}

    def label_residues(self, selection: str) -> dict[str, Any]:
        self.calls.append(("label_residues", (selection,)))
        return {"revision": 1}

    def render_png(
        self, path: str, width: int, height: int, dpi: int, ray: bool
    ) -> dict[str, Any]:
        self.calls.append(("render_png", (path, width, height, dpi, ray)))
        return {"path": path, "revision": 1}

    def session_summary(self) -> dict[str, Any]:
        self.calls.append(("session_summary", ()))
        return {"objects": [], "revision": 1}

    def clear_session(self) -> dict[str, Any]:
        self.calls.append(("clear_session", ()))
        return {"revision": 2}

    def save_session(self, path: str) -> dict[str, Any]:
        self.calls.append(("save_session", (path,)))
        return {"path": path, "revision": 1}


class FailingClient(FakeClient):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    def count_atoms(self, selection: str) -> dict[str, Any]:
        raise self.error


def initialize(server: McpServer, *, request_id: int = 1) -> dict[str, Any]:
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0"},
            },
        }
    )
    assert response is not None
    assert "result" in response
    initialized = server.handle(
        {"jsonrpc": "2.0", "method": "notifications/initialized"}
    )
    assert initialized is None
    return response


def call_tool(
    server: McpServer,
    name: str,
    arguments: dict[str, Any],
    *,
    request_id: int = 2,
) -> dict[str, Any]:
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
    )
    assert response is not None
    return response


def test_mcp_tool_surface_excludes_unsafe_operations_and_bounds_render() -> None:
    tools = build_tools()

    assert {"unsafe_execute_pml", "unsafe_command", "session_restore"}.isdisjoint(tools)
    assert {
        "session_save",
        "atoms_count",
        "scene_label_residues",
        "render_png",
    } <= tools.keys()
    schema = tools["render_png"].input_schema
    properties = schema["properties"]
    assert schema["additionalProperties"] is False
    assert (properties["width"]["minimum"], properties["width"]["maximum"]) == (1, 8192)
    assert (properties["height"]["minimum"], properties["height"]["maximum"]) == (
        1,
        8192,
    )
    assert (properties["dpi"]["minimum"], properties["dpi"]["maximum"]) == (1, 2400)


def test_mcp_initialization_lifecycle_and_protocol_version() -> None:
    server = McpServer(lambda: FakeClient())

    before_initialize = server.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )
    assert before_initialize is not None
    assert before_initialize["error"]["code"] == -32002

    unsupported = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "initialize",
            "params": {
                "protocolVersion": "1900-01-01",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        }
    )
    assert unsupported is not None
    assert unsupported["error"]["code"] == -32602

    initialized = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        }
    )
    assert initialized is not None
    assert initialized["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert initialized["result"]["capabilities"] == {"tools": {}}

    before_notification = server.handle(
        {"jsonrpc": "2.0", "id": 4, "method": "tools/list"}
    )
    assert before_notification is not None
    assert before_notification["error"]["code"] == -32002

    assert (
        server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    )
    listed = server.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/list"})
    assert listed is not None
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert names == set(build_tools())

    duplicate = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        }
    )
    assert duplicate is not None
    assert duplicate["error"]["code"] == -32600


@pytest.mark.parametrize(
    "message",
    [
        {"jsonrpc": "1.0", "id": 1, "method": "ping"},
        {"jsonrpc": "2.0", "id": 1, "method": 1},
        {"jsonrpc": "2.0", "method": "ping"},
        {"jsonrpc": "2.0", "id": 1, "method": "ping", "result": {}},
        {"jsonrpc": "2.0", "id": 1, "method": "notifications/initialized"},
    ],
)
def test_mcp_rejects_malformed_request_envelopes(message: object) -> None:
    server = McpServer(lambda: FakeClient())

    response = server.handle(message)

    assert response is not None
    assert response["jsonrpc"] == "2.0"
    assert response["error"]["code"] == -32600


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("atoms_count", {}),
        ("objects_list", {"extra": True}),
        ("render_png", {"path": "out.png", "width": 0}),
        ("render_png", {"path": "out.png", "height": 8193}),
        ("render_png", {"path": "out.png", "dpi": 2401}),
        ("render_png", {"path": "out.png", "width": True}),
        ("scene_zoom", {"selection": "all", "buffer": float("nan")}),
        ("scene_zoom", {"selection": "all", "buffer": float("inf")}),
    ],
)
def test_mcp_tool_call_validates_runtime_arguments(
    name: str, arguments: dict[str, Any]
) -> None:
    server = McpServer(lambda: FakeClient())
    initialize(server)

    response = call_tool(server, name, arguments)

    assert response["error"]["code"] == -32602


def test_mcp_normalizes_all_tool_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    work = tmp_path / "work"
    home.mkdir()
    work.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(work)
    fake = FakeClient()
    server = McpServer(lambda: fake)
    initialize(server)

    call_tool(
        server,
        "structure_load",
        {"path": "inputs/unverified.structure", "object_name": "prot"},
        request_id=10,
    )
    call_tool(
        server,
        "render_png",
        {"path": "~/renders/view.png"},
        request_id=11,
    )
    call_tool(server, "session_save", {"path": "state.pse"}, request_id=12)

    assert fake.calls == [
        (
            "load_structure",
            (str((work / "inputs/unverified.structure").resolve()), "prot"),
        ),
        (
            "render_png",
            (str((home / "renders/view.png").resolve()), 800, 600, 100, False),
        ),
        ("save_session", (str((work / "state.pse").resolve()),)),
    ]


@pytest.mark.parametrize(
    ("error", "expected_text"),
    [
        (EngineClientError("engine unavailable"), "engine unavailable"),
        (RuntimeError("secret implementation detail"), "tool execution failed"),
    ],
)
def test_mcp_tool_execution_failures_use_is_error_result(
    error: Exception, expected_text: str
) -> None:
    server = McpServer(lambda: FailingClient(error))
    initialize(server)

    response = call_tool(server, "atoms_count", {"selection": "all"})

    assert "error" not in response
    assert response["result"]["isError"] is True
    assert expected_text in response["result"]["content"][0]["text"]


def test_mcp_catches_unexpected_request_exception_and_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = McpServer(lambda: FakeClient())
    original_dispatch = server._dispatch
    should_fail = True

    def flaky_dispatch(method: str, params: Any) -> dict[str, Any] | None:
        nonlocal should_fail
        if should_fail:
            should_fail = False
            raise RuntimeError("unexpected")
        return original_dispatch(method, params)

    monkeypatch.setattr(server, "_dispatch", flaky_dispatch)

    failed = server.handle({"jsonrpc": "2.0", "id": 1, "method": "ping"})
    succeeded = server.handle({"jsonrpc": "2.0", "id": 2, "method": "ping"})

    assert failed is not None
    assert failed["error"] == {"code": -32603, "message": "internal error"}
    assert succeeded == {"jsonrpc": "2.0", "id": 2, "result": {}}


def test_mcp_stdio_survives_malformed_messages_then_serves_valid_sequence() -> None:
    fake = FakeClient()
    requests: list[bytes] = [
        b"not JSON",
        b"[]",
        json.dumps({"jsonrpc": "1.0", "id": 1, "method": "ping"}).encode(),
        b'{"jsonrpc":"2.0","id":2,"method":"ping","params":{"x":NaN}}',
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "stdio-test", "version": "1"},
                },
            }
        ).encode(),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode(),
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "objects_list",
                    "arguments": {"extra": True},
                },
            }
        ).encode(),
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "atoms_count",
                    "arguments": {"selection": "all"},
                },
            }
        ).encode(),
    ]
    stdin = io.BytesIO(b"\n".join(requests) + b"\n")
    stdout = io.BytesIO()

    run_stdio(McpServer(lambda: fake), stdin, stdout)

    messages = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert [message.get("id") for message in messages[:5]] == [None, None, 1, None, 3]
    assert [message["error"]["code"] for message in messages[:4]] == [
        -32700,
        -32600,
        -32600,
        -32700,
    ]
    assert messages[4]["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION
    tool_responses = {message["id"]: message for message in messages[5:]}
    assert set(tool_responses) == {4, 5}
    assert tool_responses[4]["error"]["code"] == -32602
    assert json.loads(tool_responses[5]["result"]["content"][0]["text"])["count"] == 10
    assert fake.calls == [("count_atoms", ("all",))]


def test_mcp_cancel_notification_closes_active_render_client(tmp_path: Path) -> None:
    class BlockingClient(FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self.render_started = threading.Event()
            self.closed = threading.Event()

        def close(self) -> None:
            self.closed.set()

        def render_png(
            self, path: str, width: int, height: int, dpi: int, ray: bool
        ) -> dict[str, Any]:
            self.render_started.set()
            if not self.closed.wait(timeout=0.5):
                raise RuntimeError("MCP cancellation was not consumed during render")
            raise EngineClientError("engine connection closed")

    client = BlockingClient()
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "cancel-test", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "render_png",
                "arguments": {"path": str(tmp_path / "cancelled.png")},
            },
        },
        {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {"requestId": 2, "reason": "user cancelled"},
        },
    ]
    payload = b"\n".join(json.dumps(request).encode() for request in requests) + b"\n"

    class CoordinatedInput(io.BytesIO):
        def __init__(self, value: bytes) -> None:
            super().__init__(value)
            self.read_count = 0

        def readline(self, size: int | None = -1) -> bytes:
            self.read_count += 1
            if self.read_count == 4:
                assert client.render_started.wait(timeout=0.5)
            return super().readline(size)

    stdin = CoordinatedInput(payload)
    stdout = io.BytesIO()

    run_stdio(McpServer(lambda: client), stdin, stdout)

    responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
    render_response = next(
        response for response in responses if response.get("id") == 2
    )
    assert client.render_started.is_set()
    assert client.closed.is_set()
    assert render_response["result"]["isError"] is True
    assert render_response["result"]["content"][0]["text"] == "request was cancelled"


def test_mcp_reader_consumes_cancel_while_second_tool_waits(tmp_path: Path) -> None:
    engine_lock = threading.Lock()
    render_started = threading.Event()
    count_finished = threading.Event()
    published = threading.Event()
    clients: list[SerializedClient] = []

    class SerializedClient(FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self.cancelled = threading.Event()

        def close(self) -> None:
            self.cancelled.set()

        def render_png(
            self, path: str, width: int, height: int, dpi: int, ray: bool
        ) -> dict[str, Any]:
            with engine_lock:
                render_started.set()
                if self.cancelled.wait(timeout=0.25):
                    raise EngineClientError("engine connection closed")
                published.set()
                return {"path": path, "revision": 1}

        def count_atoms(self, selection: str) -> dict[str, Any]:
            with engine_lock:
                count_finished.set()
                return {"selection": selection, "count": 10, "revision": 1}

    def client_factory() -> SerializedClient:
        client = SerializedClient()
        clients.append(client)
        return client

    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "multi-cancel-test", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "render_png",
                "arguments": {"path": str(tmp_path / "cancelled.png")},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "atoms_count",
                "arguments": {"selection": "all"},
            },
        },
        {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {"requestId": 2},
        },
    ]
    payload = b"\n".join(json.dumps(request).encode() for request in requests) + b"\n"

    class CoordinatedInput(io.BytesIO):
        def __init__(self, value: bytes) -> None:
            super().__init__(value)
            self.read_count = 0

        def readline(self, size: int | None = -1) -> bytes:
            self.read_count += 1
            if self.read_count == 4:
                assert render_started.wait(timeout=0.5)
            return super().readline(size)

    stdout = io.BytesIO()
    run_stdio(McpServer(client_factory), CoordinatedInput(payload), stdout)

    responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
    by_id = {response.get("id"): response for response in responses}
    assert by_id[2]["result"]["isError"] is True
    assert by_id[2]["result"]["content"][0]["text"] == "request was cancelled"
    assert json.loads(by_id[3]["result"]["content"][0]["text"])["count"] == 10
    assert render_started.is_set()
    assert count_finished.is_set()
    assert not published.is_set()


def test_mcp_async_reservations_enforce_bounds_and_unique_ids() -> None:
    server = McpServer(lambda: FakeClient())
    initialize(server)

    for request_id in range(100, 100 + mcp.MAX_CONCURRENT_TOOL_CALLS):
        assert server.reserve_async_request(request_id) is None
    assert server.reserve_async_request(100) == "duplicate active request id"
    assert server.reserve_async_request(999) == "too many active tool calls"

    stdout = io.BytesIO()
    run_stdio(
        server,
        io.BytesIO(b'{"jsonrpc":"2.0","id":100,"method":"ping"}\n'),
        stdout,
    )
    assert json.loads(stdout.getvalue())["error"] == {
        "code": -32600,
        "message": "duplicate active request id",
    }
    assert server.has_active_request(100)
