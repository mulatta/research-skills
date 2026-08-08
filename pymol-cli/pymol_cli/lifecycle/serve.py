# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Internal foreground PyMOL engine server."""

from __future__ import annotations

import argparse
import importlib
import os
import secrets
import sys
import threading
from collections.abc import Callable, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn, Protocol

from pymol_cli.engine.adapter import PyMOLAdapter
from pymol_cli.engine.current_process import CurrentProcessPyMOLAdapter
from pymol_cli.engine.embedded import EmbeddedPyMOLAdapter
from pymol_cli.engine.service import EngineService
from pymol_cli.lifecycle.paths import default_descriptor_path
from pymol_cli.lifecycle.process import get_process_identity
from pymol_cli.rpc.descriptor import (
    EngineDescriptor,
    _read_descriptor_unlocked,
    descriptor_mutation_lock,
    write_descriptor,
)
from pymol_cli.rpc.server import RpcServer


class ServeError(Exception):
    """User-facing serve error."""


GUI_PUMP_MAX_ITEMS = 1
_GUI_PUMP_REFS: list[_QtOwnerThreadPump] = []


class _OwnerDispatchServer(Protocol):
    port: int

    def run_pending(self, *, timeout: float) -> bool: ...

    def is_stopping(self) -> bool: ...

    def stop(self) -> None: ...


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pymol-engine serve")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--embedded", action="store_true")
    mode.add_argument("--current-process", action="store_true")
    parser.add_argument("--descriptor", type=Path, default=default_descriptor_path())
    parser.add_argument("--token")
    parser.add_argument("--instance-id", help=argparse.SUPPRESS)
    parser.add_argument("--supervisor-pid", type=int, help=argparse.SUPPRESS)
    return parser


def serve_embedded(
    *,
    descriptor_path: Path,
    token: str,
    instance_id: str | None = None,
    supervisor_pid: int | None = None,
) -> None:
    with EmbeddedPyMOLAdapter() as adapter:
        serve_adapter(
            adapter,
            descriptor_path=descriptor_path,
            token=token,
            mode="embedded",
            instance_id=instance_id,
            supervisor_pid=supervisor_pid,
        )


def serve_current_process(
    *,
    descriptor_path: Path,
    token: str,
    instance_id: str | None = None,
    supervisor_pid: int | None = None,
) -> None:
    serve_adapter(
        CurrentProcessPyMOLAdapter(),
        descriptor_path=descriptor_path,
        token=token,
        mode="current-process",
        instance_id=instance_id,
        supervisor_pid=supervisor_pid,
    )


def start_current_process_background(
    *,
    descriptor_path: Path,
    token: str,
    instance_id: str | None = None,
    supervisor_pid: int | None = None,
) -> None:
    """Start GUI engine with all ``pymol.cmd`` calls on Qt owner thread."""
    qt_core = _load_qt_core()
    app = _require_qt_owner_thread(qt_core)
    adapter = CurrentProcessPyMOLAdapter()
    owned_instance_id = instance_id or secrets.token_hex(16)
    server = RpcServer(
        EngineService(adapter),
        token=token,
        owner_thread_dispatch=True,
        shutdown_callback=adapter.cancel_render,
        request_cancel_callback=adapter.cancel_active_render,
        instance_id=owned_instance_id,
    )
    pump: _QtOwnerThreadPump | None = None
    server.start()
    try:
        # Publish endpoint only after timer and shutdown hook can service requests.
        pump = _install_qt_owner_thread_pump(
            server,
            descriptor_path,
            instance_id=owned_instance_id,
            cmd=adapter.cmd,
            cancel_render=adapter.cancel_render,
            qt_core=qt_core,
            app=app,
        )
        _write_ready_descriptor(
            descriptor_path,
            token=token,
            server=server,
            instance_id=owned_instance_id,
            supervisor_pid=supervisor_pid,
        )
    except BaseException:
        if pump is not None:
            pump.cleanup(close_gui=False)
        else:
            server.stop()
            remove_descriptor(descriptor_path, instance_id=owned_instance_id)
        raise


def _write_ready_descriptor(
    descriptor_path: Path,
    *,
    token: str,
    server: _OwnerDispatchServer,
    instance_id: str | None = None,
    supervisor_pid: int | None = None,
) -> EngineDescriptor:
    descriptor = _make_descriptor(
        token=token,
        server=server,
        mode="current-process",
        instance_id=instance_id,
        supervisor_pid=supervisor_pid,
    )
    write_descriptor(descriptor_path, descriptor)
    print(f"engine ready {descriptor.host}:{descriptor.port}", flush=True)
    return descriptor


def _make_descriptor(
    *,
    token: str,
    server: _OwnerDispatchServer,
    mode: str,
    instance_id: str | None = None,
    supervisor_pid: int | None = None,
) -> EngineDescriptor:
    return EngineDescriptor(
        protocol_versions=[1],
        instance_id=instance_id or secrets.token_hex(16),
        pid=os.getpid(),
        mode=mode,
        host="127.0.0.1",
        port=server.port,
        token=token,
        started_at=datetime.now(UTC).isoformat(),
        supervisor_pid=supervisor_pid,
        process_identity=get_process_identity(os.getpid()),
    )


def _load_qt_core() -> Any:
    try:
        qt_module: Any = importlib.import_module("pymol.Qt")
    except ImportError as exc:
        raise ServeError("GUI engine requires PyMOL Qt support") from exc
    return qt_module.QtCore


def _qt_available() -> bool:
    """Return whether usable Qt owner context exists, without enabling fallback."""
    try:
        qt_core = _load_qt_core()
        _require_qt_owner_thread(qt_core)
    except ServeError:
        return False
    return True


def _require_qt_owner_thread(qt_core: Any) -> Any:
    app = qt_core.QCoreApplication.instance()
    if app is None:
        raise ServeError("GUI engine requires an active QCoreApplication")
    if threading.current_thread() is not threading.main_thread():
        raise ServeError("GUI engine bootstrap must run on the main thread")
    if qt_core.QThread.currentThread() != app.thread():
        raise ServeError("GUI engine bootstrap must run on the Qt application thread")
    return app


class _QtOwnerThreadPump:
    def __init__(
        self,
        *,
        server: _OwnerDispatchServer,
        descriptor_path: Path,
        instance_id: str,
        cmd: Any,
        cancel_render: Callable[[], None] | None,
        timer: Any,
        app: Any,
    ) -> None:
        self.server = server
        self.descriptor_path = descriptor_path
        self.instance_id = instance_id
        self.cmd = cmd
        self.cancel_render = cancel_render
        self.timer = timer
        self.app = app
        self.cleaned = False
        self.processing = False

    def pump(self) -> None:
        # A nested processEvents call during rendering must unwind before PyMOL
        # shutdown; cmd.quit is reliable only from the next top-level timer tick.
        if self.processing:
            return
        if self.server.is_stopping():
            self.cleanup(close_gui=True)
            return
        self.processing = True
        try:
            for _ in range(GUI_PUMP_MAX_ITEMS):
                if not self.server.run_pending(timeout=0):
                    break
        finally:
            self.processing = False

    def about_to_quit(self) -> None:
        self.cleanup(close_gui=False)

    def cleanup(self, *, close_gui: bool) -> None:
        if self.cleaned:
            return
        self.cleaned = True
        with suppress(Exception):
            self.timer.stop()
        with suppress(Exception):
            self.timer.timeout.disconnect(self.pump)
        with suppress(Exception):
            self.app.aboutToQuit.disconnect(self.about_to_quit)
        if self.cancel_render is not None:
            with suppress(Exception):
                self.cancel_render()
        with suppress(Exception):
            self.server.stop()
        remove_descriptor(self.descriptor_path, instance_id=self.instance_id)
        with suppress(ValueError):
            _GUI_PUMP_REFS.remove(self)
        with suppress(Exception):
            self.timer.deleteLater()
        if close_gui:
            # pump() reaches cleanup only from a top-level owner-thread timer tick.
            with suppress(Exception):
                self.cmd.quit()


def _install_qt_owner_thread_pump(
    server: _OwnerDispatchServer,
    descriptor_path: Path,
    *,
    instance_id: str,
    cmd: Any,
    cancel_render: Callable[[], None] | None = None,
    qt_core: Any | None = None,
    app: Any | None = None,
) -> _QtOwnerThreadPump:
    core = _load_qt_core() if qt_core is None else qt_core
    active_app = _require_qt_owner_thread(core) if app is None else app
    timer = core.QTimer(active_app)
    pump = _QtOwnerThreadPump(
        server=server,
        descriptor_path=descriptor_path,
        instance_id=instance_id,
        cmd=cmd,
        cancel_render=cancel_render,
        timer=timer,
        app=active_app,
    )
    _GUI_PUMP_REFS.append(pump)
    try:
        timer.timeout.connect(pump.pump)
        active_app.aboutToQuit.connect(pump.about_to_quit)
        timer.start(10)
    except BaseException:
        pump.cleanup(close_gui=False)
        raise
    return pump


def serve_adapter(
    adapter: PyMOLAdapter,
    *,
    descriptor_path: Path,
    token: str,
    mode: str,
    instance_id: str | None = None,
    supervisor_pid: int | None = None,
) -> None:
    owned_instance_id = instance_id or secrets.token_hex(16)
    cancel_render = getattr(adapter, "cancel_render", None)
    cancel_active_render = getattr(adapter, "cancel_active_render", None)
    server = RpcServer(
        EngineService(adapter),
        token=token,
        owner_thread_dispatch=True,
        shutdown_callback=cancel_render if callable(cancel_render) else None,
        request_cancel_callback=(
            cancel_active_render if callable(cancel_active_render) else None
        ),
        instance_id=owned_instance_id,
    )
    server.start()
    try:
        descriptor = _make_descriptor(
            token=token,
            server=server,
            mode=mode,
            instance_id=owned_instance_id,
            supervisor_pid=supervisor_pid,
        )
        write_descriptor(descriptor_path, descriptor)
        print(f"engine ready {descriptor.host}:{descriptor.port}", flush=True)
        while not server.is_stopping():
            server.run_pending(timeout=0.1)
    finally:
        server.stop()
        remove_descriptor(descriptor_path, instance_id=owned_instance_id)


def remove_descriptor(path: Path, *, instance_id: str) -> bool:
    """Remove descriptor only while mutation lock still names this instance."""
    with descriptor_mutation_lock(path):
        try:
            descriptor = _read_descriptor_unlocked(path)
        except FileNotFoundError:
            return True
        except (KeyError, OSError, TypeError, ValueError):
            return False
        if descriptor.instance_id != instance_id:
            return False
        try:
            path.unlink()
        except FileNotFoundError:
            return True
        return True


def die(message: str, code: int = 1) -> NoReturn:
    print(f"pymol-engine: {message}", file=sys.stderr)
    raise SystemExit(code)


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    ns = parser.parse_args(argv)
    token = ns.token or secrets.token_urlsafe(32)
    try:
        if ns.embedded:
            serve_embedded(
                descriptor_path=ns.descriptor,
                token=token,
                instance_id=ns.instance_id,
                supervisor_pid=ns.supervisor_pid,
            )
            return
        if ns.current_process:
            serve_current_process(
                descriptor_path=ns.descriptor,
                token=token,
                instance_id=ns.instance_id,
                supervisor_pid=ns.supervisor_pid,
            )
            return
        raise ServeError("no engine mode selected")
    except (OSError, ServeError, TypeError, ValueError) as exc:
        die(str(exc))


if __name__ == "__main__":
    main()
