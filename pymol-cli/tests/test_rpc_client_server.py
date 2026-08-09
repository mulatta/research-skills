# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pymol_cli.engine.errors import EngineError, ErrorCategory
from pymol_cli.engine.service import EngineService
from pymol_cli.rpc.client import EngineClient, EngineClientError
from pymol_cli.rpc.server import RpcServer, RpcWorkItem
from pymol_cli.rpc.session import RpcSession


class FakeAdapter:
    def __init__(self) -> None:
        self.atom_count = 0
        self.objects: list[str] = []
        self.commands: list[str] = []
        self.lock = threading.Lock()

    def get_version(self) -> str:
        return "3.1.0"

    def get_object_names(self) -> list[str]:
        return list(self.objects)

    def count_atoms(self, selection: str) -> int:
        return self.atom_count if selection in {"all", "smoke"} else 0

    def load_structure(self, path: str, object_name: str) -> None:
        self.objects = [object_name]
        self.atom_count = 0

    def show_representation(self, representation: str, selection: str) -> None:
        return None

    def hide_representation(self, representation: str, selection: str) -> None:
        return None

    def color_selection(self, color: str, selection: str) -> None:
        return None

    def zoom_selection(self, selection: str, buffer: float) -> None:
        return None

    def label_residues(self, selection: str) -> None:
        return None

    def create_selection(self, name: str, expression: str) -> None:
        return None

    def show_ball_and_stick(
        self, selection: str, stick_radius: float, sphere_scale: float
    ) -> None:
        return None

    def show_polar_contacts(
        self,
        name: str,
        selection1: str,
        selection2: str,
        cutoff: float,
        color: str,
        dash_width: float,
    ) -> None:
        return None

    def set_background(self, color: str, opaque: bool) -> None:
        return None

    def render_png(
        self, path: str, width: int, height: int, dpi: int, ray: bool
    ) -> None:
        return None

    def save_session(self, path: str) -> None:
        return None

    def restore_session(self, path: str) -> None:
        return None

    def execute_pml(self, command: str) -> Any:
        with self.lock:
            self.commands.append(command)
            if command == "fragment ala, smoke":
                self.objects = ["smoke"]
                self.atom_count = 10
            if command == "explode":
                raise RuntimeError("malformed backend call")
            if command.startswith("sleep "):
                time.sleep(float(command.split()[1]))
        return None

    def clear(self) -> None:
        self.objects = []
        self.atom_count = 0


@pytest.fixture
def server() -> Iterator[RpcServer]:
    server = RpcServer(EngineService(FakeAdapter()), token="secret")
    server.start()
    try:
        yield server
    finally:
        server.stop()


def test_engine_client_connects_initializes_and_calls_methods(
    server: RpcServer,
) -> None:
    with EngineClient.connect("127.0.0.1", server.port, token="secret") as client:
        info = client.info()
        assert info["backend"] == "pymol-open-source"

        command = client.unsafe_execute_pml("fragment ala, smoke")
        assert command["revision"] == 1

        assert client.count_atoms("smoke") == {
            "selection": "smoke",
            "count": 10,
            "revision": 1,
        }
        assert client.session_summary()["object_names"] == ["smoke"]


def test_engine_client_rejects_wrong_token(server: RpcServer) -> None:
    with pytest.raises(EngineClientError, match="authentication failed"):
        EngineClient.connect("127.0.0.1", server.port, token="wrong")


def test_rpc_server_serializes_concurrent_clients(server: RpcServer) -> None:
    started = threading.Barrier(3)
    results: list[int] = []

    def call_engine(command: str) -> None:
        with EngineClient.connect("127.0.0.1", server.port, token="secret") as client:
            started.wait(timeout=2)
            results.append(client.unsafe_execute_pml(command)["revision"])

    first = threading.Thread(target=call_engine, args=("sleep 0.05",))
    second = threading.Thread(target=call_engine, args=("fragment ala, smoke",))
    first.start()
    second.start()
    started.wait(timeout=2)
    first.join(timeout=2)
    second.join(timeout=2)

    assert sorted(results) == [1, 2]
    assert not first.is_alive()
    assert not second.is_alive()


def test_engine_shutdown_runs_render_cancellation_callback() -> None:
    cancelled = threading.Event()
    server = RpcServer(
        EngineService(FakeAdapter()),
        token="secret",
        shutdown_callback=cancelled.set,
    )
    server.start()
    try:
        with EngineClient.connect("127.0.0.1", server.port, token="secret") as client:
            assert client.shutdown() == {"ok": True}

        assert cancelled.wait(timeout=1)
        assert server.wait_stopped(timeout=1)
    finally:
        server.stop()


def test_render_client_timeout_cancels_active_owner_work(tmp_path: Path) -> None:
    class BlockingRenderAdapter(FakeAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.render_started = threading.Event()
            self.render_cancelled = threading.Event()

        def render_png(
            self, path: str, width: int, height: int, dpi: int, ray: bool
        ) -> None:
            self.render_started.set()
            if not self.render_cancelled.wait(timeout=1):
                raise RuntimeError("render continued after its client disconnected")
            raise EngineError(
                ErrorCategory.BACKEND_FAILURE,
                "render was cancelled",
                {"operation": "render.png"},
            )

        def cancel_active_render(self) -> None:
            self.render_cancelled.set()

    adapter = BlockingRenderAdapter()
    server = RpcServer(
        EngineService(adapter),
        token="secret",
        owner_thread_dispatch=True,
        request_cancel_callback=adapter.cancel_active_render,
    )
    server.start()
    output = tmp_path / "cancelled.png"
    errors: list[EngineClientError] = []
    client = EngineClient.connect(
        "127.0.0.1",
        server.port,
        token="secret",
        timeout=1,
        render_timeout=0.05,
    )

    def render() -> None:
        try:
            client.render_png(str(output), 100, 100, 72, False)
        except EngineClientError as exc:
            errors.append(exc)

    caller = threading.Thread(target=render)
    try:
        caller.start()
        deadline = time.monotonic() + 1
        while server._work_queue.empty() and time.monotonic() < deadline:
            time.sleep(0.005)
        assert server.run_pending(timeout=1)
        caller.join(timeout=1)

        assert not caller.is_alive()
        assert adapter.render_started.is_set()
        assert adapter.render_cancelled.is_set()
        assert len(errors) == 1
        assert str(errors[0]) == "render.png timed out"
        assert not output.exists()
    finally:
        client.close()
        server.stop()


def test_backend_failure_leaves_server_and_client_usable(server: RpcServer) -> None:
    with EngineClient.connect("127.0.0.1", server.port, token="secret") as client:
        with pytest.raises(EngineClientError, match="failed in the PyMOL backend"):
            client.unsafe_execute_pml("explode")

        assert client.info()["backend"] == "pymol-open-source"


def test_engine_client_serializes_concurrent_calls_on_one_connection(
    server: RpcServer,
) -> None:
    with EngineClient.connect("127.0.0.1", server.port, token="secret") as client:
        started = threading.Barrier(3)
        results: list[int] = []
        errors: list[BaseException] = []

        def call_engine(command: str) -> None:
            try:
                started.wait(timeout=2)
                results.append(client.unsafe_execute_pml(command)["revision"])
            except (EngineClientError, threading.BrokenBarrierError) as exc:
                errors.append(exc)

        first = threading.Thread(target=call_engine, args=("sleep 0.05",))
        second = threading.Thread(target=call_engine, args=("fragment ala, smoke",))
        first.start()
        second.start()
        started.wait(timeout=2)
        first.join(timeout=2)
        second.join(timeout=2)

    assert errors == []
    assert sorted(results) == [1, 2]
    assert not first.is_alive()
    assert not second.is_alive()


def test_run_pending_releases_waiter_when_session_raises() -> None:
    class BrokenSession:
        def handle(self, message: dict[str, object]) -> dict[str, object]:
            raise RuntimeError("dispatch exploded")

    server = RpcServer(
        EngineService(FakeAdapter()), token="secret", owner_thread_dispatch=True
    )
    item = RpcWorkItem(
        session=BrokenSession(),
        message={"jsonrpc": "2.0", "id": 41, "method": "engine.info"},
        ready=threading.Event(),
    )
    server._work_queue.put(item)

    assert server.run_pending(timeout=0.1)
    assert item.ready.is_set()
    assert item.response is not None
    assert item.response["id"] == 41
    error = item.response["error"]
    assert isinstance(error, dict)
    assert error["code"] == -32603


def test_stop_drains_owner_dispatch_queue_and_rejects_new_work() -> None:
    server = RpcServer(
        EngineService(FakeAdapter()), token="secret", owner_thread_dispatch=True
    )
    session = RpcSession(EngineService(FakeAdapter()), token="secret")
    message: dict[str, object] = {
        "jsonrpc": "2.0",
        "id": 42,
        "method": "engine.info",
    }
    responses: list[dict[str, object]] = []
    waiter = threading.Thread(
        target=lambda: responses.append(server._handle_message(session, message))
    )
    waiter.start()
    deadline = time.monotonic() + 1
    while server._work_queue.empty() and time.monotonic() < deadline:
        time.sleep(0.005)

    server.stop()
    waiter.join(timeout=1)

    assert not waiter.is_alive()
    response_error = responses[0]["error"]
    assert isinstance(response_error, dict)
    assert response_error["code"] == -32603
    rejected = server._handle_message(session, {**message, "id": 43})
    assert rejected["id"] == 43
    rejected_error = rejected["error"]
    assert isinstance(rejected_error, dict)
    assert rejected_error["code"] == -32603


def test_initialize_bypasses_busy_owner_queue() -> None:
    engine = EngineService(FakeAdapter())
    session = RpcSession(engine, token="secret")
    server = RpcServer(engine, token="secret", owner_thread_dispatch=True)
    request = {
        "jsonrpc": "2.0",
        "id": 50,
        "method": "engine.initialize",
        "params": {"protocol_versions": [1], "token": "secret"},
    }

    response = server._handle_message(session, request)

    assert response["id"] == 50
    assert "result" in response
    assert session.initialized
    assert server._work_queue.empty()


def test_authenticated_shutdown_bypasses_busy_owner_queue() -> None:
    engine = EngineService(FakeAdapter())
    session = RpcSession(engine, token="secret")
    session.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "engine.initialize",
            "params": {"protocol_versions": [1], "token": "secret"},
        }
    )
    server = RpcServer(engine, token="secret", owner_thread_dispatch=True)

    response = server._handle_message(
        session,
        {"jsonrpc": "2.0", "id": 2, "method": "engine.shutdown"},
    )

    assert response == {"jsonrpc": "2.0", "id": 2, "result": {"ok": True}}
    assert session.should_shutdown
    assert server._work_queue.empty()


def test_rpc_server_closes_idle_unauthenticated_client_and_releases_slot() -> None:
    server = RpcServer(
        EngineService(FakeAdapter()),
        token="secret",
        authentication_timeout=0.05,
        partial_frame_timeout=1.0,
        max_clients=1,
    )
    server.start()
    idle = socket.create_connection(("127.0.0.1", server.port), timeout=1)
    idle.settimeout(1)
    try:
        assert idle.recv(1) == b""
        with EngineClient.connect(
            "127.0.0.1", server.port, token="secret", timeout=1
        ) as client:
            assert client.info()["backend"] == "pymol-open-source"
    finally:
        idle.close()
        server.stop()


def test_rpc_server_closes_stalled_partial_frame() -> None:
    server = RpcServer(
        EngineService(FakeAdapter()),
        token="secret",
        authentication_timeout=1.0,
        partial_frame_timeout=0.05,
    )
    server.start()
    client = socket.create_connection(("127.0.0.1", server.port), timeout=1)
    client.settimeout(1)
    try:
        client.sendall(b"Content-Length: 100\r\n\r\n{")
        assert client.recv(1) == b""
    finally:
        client.close()
        server.stop()


def test_fresh_shutdown_client_bypasses_busy_owner_dispatch() -> None:
    cancelled = threading.Event()
    server = RpcServer(
        EngineService(FakeAdapter()),
        token="secret",
        owner_thread_dispatch=True,
        shutdown_callback=cancelled.set,
        instance_id="engine-instance",
    )
    server.start()
    try:
        with EngineClient.connect(
            "127.0.0.1",
            server.port,
            token="secret",
            timeout=1,
            expected_instance_id="engine-instance",
        ) as client:
            assert client.instance_id == "engine-instance"
            assert client.shutdown() == {"ok": True}

        assert cancelled.wait(timeout=1)
        assert server.wait_stopped(timeout=1)
    finally:
        server.stop()


def test_render_timeout_between_dispatch_and_backend_start_cannot_publish(
    tmp_path: Path,
) -> None:
    class WritingRenderAdapter(FakeAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.cancel_requested = threading.Event()
            self.render_started = threading.Event()

        def render_png(
            self, path: str, width: int, height: int, dpi: int, ray: bool
        ) -> None:
            self.render_started.set()
            Path(path).write_bytes(b"\x89PNG\r\n\x1a\nimage")

        def cancel_active_render(self) -> None:
            self.cancel_requested.set()

    class BlockingEngine(EngineService):
        def __init__(self, adapter: WritingRenderAdapter) -> None:
            super().__init__(adapter)
            self.dispatch_started = threading.Event()
            self.release_backend = threading.Event()

        def render_png(
            self, *, path: str, width: int, height: int, dpi: int, ray: bool
        ) -> Any:
            self.dispatch_started.set()
            assert self.release_backend.wait(timeout=1)
            return super().render_png(
                path=path,
                width=width,
                height=height,
                dpi=dpi,
                ray=ray,
            )

    adapter = WritingRenderAdapter()
    engine = BlockingEngine(adapter)
    server = RpcServer(
        engine,
        token="secret",
        owner_thread_dispatch=True,
        request_cancel_callback=adapter.cancel_active_render,
    )
    server.start()
    output = tmp_path / "late.png"
    client = EngineClient.connect(
        "127.0.0.1",
        server.port,
        token="secret",
        timeout=1,
        render_timeout=0.1,
    )
    errors: list[EngineClientError] = []
    caller = threading.Thread(
        target=lambda: _capture_render_error(client, output, errors)
    )
    pump = threading.Thread(target=lambda: server.run_pending(timeout=1))
    try:
        caller.start()
        deadline = time.monotonic() + 1
        while server._work_queue.empty() and time.monotonic() < deadline:
            time.sleep(0.005)
        pump.start()
        assert engine.dispatch_started.wait(timeout=1)
        assert adapter.cancel_requested.wait(timeout=1)
        caller.join(timeout=1)
        engine.release_backend.set()
        pump.join(timeout=1)

        assert not caller.is_alive()
        assert not pump.is_alive()
        assert len(errors) == 1
        assert str(errors[0]) == "render.png timed out"
        assert not adapter.render_started.is_set()
        assert not output.exists()
    finally:
        engine.release_backend.set()
        client.close()
        server.stop()


def _capture_render_error(
    client: EngineClient,
    output: Path,
    errors: list[EngineClientError],
) -> None:
    try:
        client.render_png(str(output), 100, 100, 72, False)
    except EngineClientError as exc:
        errors.append(exc)
