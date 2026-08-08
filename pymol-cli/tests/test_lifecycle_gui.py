# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, ClassVar

import pytest

from pymol_cli.lifecycle import serve
from pymol_cli.rpc.descriptor import EngineDescriptor, write_descriptor


class _Signal:
    def __init__(self) -> None:
        self.callbacks: list[Any] = []

    def connect(self, callback: Any) -> None:
        self.callbacks.append(callback)

    def disconnect(self, callback: Any) -> None:
        if callback in self.callbacks:
            self.callbacks.remove(callback)

    def emit(self) -> None:
        for callback in list(self.callbacks):
            callback()


class _Timer:
    def __init__(self, _parent: object | None = None) -> None:
        self.timeout = _Signal()
        self.started_with: int | None = None
        self.stopped = False
        self.deleted = False

    def start(self, interval: int) -> None:
        self.started_with = interval

    def stop(self) -> None:
        self.stopped = True

    def deleteLater(self) -> None:
        self.deleted = True


class _Application:
    def __init__(self, qt_thread: object) -> None:
        self.aboutToQuit = _Signal()
        self._thread = qt_thread

    def thread(self) -> object:
        return self._thread


class _QtCore:
    app: _Application | None = None
    current_qt_thread: object = object()
    timers: ClassVar[list[_Timer]] = []

    class QCoreApplication:
        @staticmethod
        def instance() -> _Application | None:
            return _QtCore.app

    class QThread:
        @staticmethod
        def currentThread() -> object:
            return _QtCore.current_qt_thread

    @staticmethod
    def QTimer(parent: object | None = None) -> _Timer:
        timer = _Timer(parent)
        _QtCore.timers.append(timer)
        return timer


class _Server:
    port = 1234

    def __init__(self) -> None:
        self.pending_calls = 0
        self.stopping = False
        self.stopped = False

    def run_pending(self, *, timeout: float) -> bool:
        assert timeout == 0
        self.pending_calls += 1
        return True

    def is_stopping(self) -> bool:
        return self.stopping

    def stop(self) -> None:
        self.stopped = True
        self.stopping = True


class _Cmd:
    def __init__(self) -> None:
        self.quit_threads: list[threading.Thread] = []
        self.cancel_calls = 0

    def quit(self) -> None:
        self.quit_threads.append(threading.current_thread())

    def cancel_render(self) -> None:
        self.cancel_calls += 1


def _active_qt() -> tuple[type[_QtCore], _Application]:
    _QtCore.current_qt_thread = object()
    _QtCore.app = _Application(_QtCore.current_qt_thread)
    _QtCore.timers = []
    return _QtCore, _QtCore.app


def _descriptor(instance_id: str) -> EngineDescriptor:
    return EngineDescriptor(
        protocol_versions=[1],
        instance_id=instance_id,
        pid=1,
        mode="current-process",
        host="127.0.0.1",
        port=1234,
        token="token",
        started_at="now",
    )


def test_gui_requires_active_qcore_application() -> None:
    _QtCore.app = None
    with pytest.raises(serve.ServeError, match="active QCoreApplication"):
        serve._require_qt_owner_thread(_QtCore)


def test_gui_requires_python_main_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    qt_core, _app = _active_qt()
    monkeypatch.setattr(serve.threading, "current_thread", lambda: object())
    with pytest.raises(serve.ServeError, match="main thread"):
        serve._require_qt_owner_thread(qt_core)


def test_qt_pump_processes_bounded_work_and_closes_owned_gui(
    tmp_path: Path,
) -> None:
    qt_core, app = _active_qt()
    server = _Server()
    cmd = _Cmd()
    descriptor_path = tmp_path / "engine.json"
    write_descriptor(descriptor_path, _descriptor("ours"))

    pump = serve._install_qt_owner_thread_pump(
        server,
        descriptor_path,
        instance_id="ours",
        cmd=cmd,
        cancel_render=cmd.cancel_render,
        qt_core=qt_core,
        app=app,
    )
    timer = _QtCore.timers[-1]
    timer.timeout.emit()
    assert server.pending_calls == serve.GUI_PUMP_MAX_ITEMS

    server.stopping = True
    timer.timeout.emit()

    assert server.stopped is True
    assert timer.stopped is True
    assert not descriptor_path.exists()
    assert cmd.quit_threads == [threading.main_thread()]
    assert cmd.cancel_calls == 1
    assert pump not in serve._GUI_PUMP_REFS


def test_qt_pump_rejects_reentrant_rpc_dispatch(tmp_path: Path) -> None:
    qt_core, app = _active_qt()
    server = _Server()
    cmd = _Cmd()
    descriptor_path = tmp_path / "engine.json"
    write_descriptor(descriptor_path, _descriptor("ours"))
    pump = serve._install_qt_owner_thread_pump(
        server,
        descriptor_path,
        instance_id="ours",
        cmd=cmd,
        qt_core=qt_core,
        app=app,
    )
    timer = _QtCore.timers[-1]

    pump.processing = True
    server.stopping = True
    timer.timeout.emit()
    assert server.pending_calls == 0
    assert not pump.cleaned
    pump.processing = False
    timer.timeout.emit()
    assert pump.cleaned
    assert cmd.quit_threads == [threading.main_thread()]


def test_about_to_quit_cleans_server_without_recursive_cmd_quit(
    tmp_path: Path,
) -> None:
    qt_core, app = _active_qt()
    server = _Server()
    cmd = _Cmd()
    descriptor_path = tmp_path / "engine.json"
    write_descriptor(descriptor_path, _descriptor("ours"))

    serve._install_qt_owner_thread_pump(
        server,
        descriptor_path,
        instance_id="ours",
        cmd=cmd,
        cancel_render=cmd.cancel_render,
        qt_core=qt_core,
        app=app,
    )
    app.aboutToQuit.emit()

    assert server.stopped is True
    assert cmd.quit_threads == []
    assert cmd.cancel_calls == 1
    assert not descriptor_path.exists()


def test_descriptor_cleanup_only_removes_owned_instance(tmp_path: Path) -> None:
    descriptor_path = tmp_path / "engine.json"
    write_descriptor(descriptor_path, _descriptor("replacement"))

    assert serve.remove_descriptor(descriptor_path, instance_id="old") is False
    assert descriptor_path.exists()
    assert serve.remove_descriptor(descriptor_path, instance_id="replacement") is True
    assert not descriptor_path.exists()


def test_gui_installs_owner_pump_before_descriptor_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    qt_core, app = _active_qt()
    events: list[str] = []

    class Adapter:
        cmd = _Cmd()

        def cancel_render(self) -> None:
            self.cmd.cancel_render()

        def cancel_active_render(self) -> None:
            self.cmd.cancel_render()

    class Server(_Server):
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            super().__init__()

        def start(self) -> None:
            events.append("server")

    class Pump:
        def cleanup(self, *, close_gui: bool) -> None:
            assert close_gui is False

    monkeypatch.setattr(serve, "_load_qt_core", lambda: qt_core)
    monkeypatch.setattr(serve, "_require_qt_owner_thread", lambda _core: app)
    monkeypatch.setattr(serve, "CurrentProcessPyMOLAdapter", Adapter)
    monkeypatch.setattr(serve, "RpcServer", Server)

    def install_pump(*_args: object, **_kwargs: object) -> Pump:
        events.append("pump")
        return Pump()

    monkeypatch.setattr(serve, "_install_qt_owner_thread_pump", install_pump)
    monkeypatch.setattr(
        serve,
        "_write_ready_descriptor",
        lambda *_args, **_kwargs: events.append("descriptor"),
    )

    serve.start_current_process_background(
        descriptor_path=tmp_path / "engine.json",
        token="token",
        instance_id="ours",
    )

    assert events == ["server", "pump", "descriptor"]


def test_descriptor_replacement_waits_for_instance_owned_removal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    descriptor_path = tmp_path / "engine.json"
    write_descriptor(descriptor_path, _descriptor("old"))
    real_read = serve._read_descriptor_unlocked
    read_started = threading.Event()
    allow_read_return = threading.Event()
    writer_done = threading.Event()
    removal_results: list[bool] = []

    def paused_read(path: Path) -> EngineDescriptor:
        descriptor = real_read(path)
        if threading.current_thread().name == "descriptor-remover":
            read_started.set()
            assert allow_read_return.wait(timeout=1)
        return descriptor

    monkeypatch.setattr(serve, "_read_descriptor_unlocked", paused_read)
    remover = threading.Thread(
        target=lambda: removal_results.append(
            serve.remove_descriptor(descriptor_path, instance_id="old")
        ),
        name="descriptor-remover",
    )
    remover.start()
    assert read_started.wait(timeout=1)

    def publish_replacement() -> None:
        write_descriptor(descriptor_path, _descriptor("replacement"))
        writer_done.set()

    writer = threading.Thread(target=publish_replacement)
    writer.start()
    assert not writer_done.wait(timeout=0.1)
    allow_read_return.set()
    remover.join(timeout=1)
    writer.join(timeout=1)

    assert removal_results == [True]
    assert writer_done.is_set()
    assert real_read(descriptor_path).instance_id == "replacement"
