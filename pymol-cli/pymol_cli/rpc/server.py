# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Loopback TCP server for framed JSON-RPC engine sessions."""

from __future__ import annotations

import logging
import math
import queue
import secrets
import select
import socket
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Protocol, Self

from pymol_cli.engine.cancellation import request_cancellation
from pymol_cli.engine.service import EngineService
from pymol_cli.rpc.framing import FrameDecodeError, FrameReader, encode_frame
from pymol_cli.rpc.protocol import (
    INTERNAL_ERROR,
    PARSE_ERROR,
    JsonRpcError,
    build_error,
)
from pymol_cli.rpc.session import RpcSession

DEFAULT_AUTHENTICATION_TIMEOUT = 5.0
DEFAULT_PARTIAL_FRAME_TIMEOUT = 5.0
DEFAULT_MAX_CLIENTS = 32
_CLIENT_JOIN_TIMEOUT = 1.0
_LOGGER = logging.getLogger(__name__)


class RpcHandler(Protocol):
    def handle(self, message: dict[str, object]) -> dict[str, Any]: ...


@dataclass
class RpcWorkItem:
    session: RpcHandler
    message: dict[str, object]
    ready: threading.Event
    response: dict[str, Any] | None = None
    cancelled: threading.Event = field(default_factory=threading.Event)


class RpcServer:
    """Size- and time-bounded local server for authenticated engine clients."""

    def __init__(
        self,
        engine: EngineService,
        *,
        token: str,
        host: str = "127.0.0.1",
        owner_thread_dispatch: bool = False,
        authentication_timeout: float = DEFAULT_AUTHENTICATION_TIMEOUT,
        partial_frame_timeout: float = DEFAULT_PARTIAL_FRAME_TIMEOUT,
        max_clients: int = DEFAULT_MAX_CLIENTS,
        shutdown_callback: Callable[[], None] | None = None,
        request_cancel_callback: Callable[[], None] | None = None,
        instance_id: str | None = None,
    ) -> None:
        self._engine = engine
        self._token = token
        self._host = host
        self._owner_thread_dispatch = owner_thread_dispatch
        self._authentication_timeout = _positive_timeout(
            authentication_timeout, "authentication_timeout"
        )
        self._partial_frame_timeout = _positive_timeout(
            partial_frame_timeout, "partial_frame_timeout"
        )
        if (
            not isinstance(max_clients, int)
            or isinstance(max_clients, bool)
            or max_clients < 1
        ):
            raise ValueError("max_clients must be a positive integer")
        self._max_clients = max_clients
        self._shutdown_callback = shutdown_callback
        self._request_cancel_callback = request_cancel_callback
        self.instance_id = instance_id or secrets.token_hex(16)
        self._initialization_info = engine.get_info()
        self._work_queue: queue.Queue[RpcWorkItem] = queue.Queue()
        self._socket: socket.socket | None = None
        self._accept_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._stopped_event = threading.Event()
        self._engine_lock = threading.Lock()
        self._active_work_lock = threading.Lock()
        self._active_work_item: RpcWorkItem | None = None
        self._clients: set[socket.socket] = set()
        self._client_threads: set[threading.Thread] = set()
        self._clients_lock = threading.Lock()
        self.port = 0

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.stop()

    def start(self) -> None:
        if self._socket is not None:
            return
        if self._stop_event.is_set():
            raise RuntimeError("stopped RPC server cannot be restarted")
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((self._host, 0))
            listener.listen(self._max_clients)
            listener.settimeout(0.1)
        except BaseException:
            listener.close()
            raise
        self.port = int(listener.getsockname()[1])
        self._socket = listener
        self._stopped_event.clear()
        self._accept_thread = threading.Thread(
            target=self._accept_loop,
            name="pymol-rpc-accept",
            daemon=True,
        )
        self._accept_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._reject_queued_work()
        listener = self._socket
        if listener is not None:
            with suppress(OSError):
                listener.close()
        with self._clients_lock:
            clients = list(self._clients)
            client_threads = list(self._client_threads)
        for client in clients:
            with suppress(OSError):
                client.shutdown(socket.SHUT_RDWR)
            with suppress(OSError):
                client.close()
        accept_thread = self._accept_thread
        current = threading.current_thread()
        if accept_thread is not None and accept_thread is not current:
            accept_thread.join(timeout=1.0)
        deadline = time.monotonic() + _CLIENT_JOIN_TIMEOUT
        for thread in client_threads:
            if thread is current:
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            thread.join(timeout=remaining)
        # Close/enqueue races are harmless to callers because _handle_message
        # also observes stop, but draining releases any event still being waited on.
        self._reject_queued_work()
        self._stopped_event.set()

    def wait_stopped(self, *, timeout: float) -> bool:
        return self._stopped_event.wait(timeout)

    def is_stopping(self) -> bool:
        return self._stop_event.is_set()

    def run_pending(self, *, timeout: float) -> bool:
        if self._stop_event.is_set():
            self._reject_queued_work()
            return False
        try:
            item = self._work_queue.get(timeout=timeout)
        except queue.Empty:
            return False
        with self._active_work_lock:
            self._active_work_item = item
        try:
            if item.cancelled.is_set():
                item.response = _internal_error(item.message, "request was cancelled")
            else:
                with self._engine_lock, request_cancellation(item.cancelled):
                    item.response = item.session.handle(item.message)
        except Exception:
            _LOGGER.exception("unexpected exception while dispatching owner-thread RPC")
            item.response = _internal_error(item.message)
        finally:
            with self._active_work_lock:
                if self._active_work_item is item:
                    self._active_work_item = None
            item.ready.set()
        return True

    def _accept_loop(self) -> None:
        try:
            while not self._stop_event.is_set():
                listener = self._socket
                if listener is None:
                    return
                try:
                    client, _address = listener.accept()
                except TimeoutError:
                    continue
                except OSError:
                    return
                client.settimeout(
                    min(
                        0.05,
                        self._authentication_timeout,
                        self._partial_frame_timeout,
                    )
                )
                with self._clients_lock:
                    if len(self._clients) >= self._max_clients:
                        accepted = False
                    else:
                        accepted = True
                        self._clients.add(client)
                if not accepted:
                    with suppress(OSError):
                        client.close()
                    continue
                thread = threading.Thread(
                    target=self._client_loop,
                    args=(client,),
                    name="pymol-rpc-client",
                    daemon=True,
                )
                with self._clients_lock:
                    self._client_threads.add(thread)
                thread.start()
        finally:
            if self._stop_event.is_set():
                self._stopped_event.set()

    def _client_loop(self, client: socket.socket) -> None:
        reader = FrameReader()
        session = RpcSession(
            self._engine,
            token=self._token,
            instance_id=self.instance_id,
            initialization_info=self._initialization_info,
        )
        connected_at = time.monotonic()
        partial_started_at: float | None = None
        try:
            while not self._stop_event.is_set():
                now = time.monotonic()
                if (
                    not session.initialized
                    and now - connected_at >= self._authentication_timeout
                ):
                    return
                if (
                    partial_started_at is not None
                    and now - partial_started_at >= self._partial_frame_timeout
                ):
                    return
                try:
                    chunk = client.recv(65536)
                except TimeoutError:
                    continue
                except OSError:
                    return
                if not chunk:
                    return
                had_pending = reader.has_pending_data
                try:
                    messages = reader.feed(chunk)
                except FrameDecodeError as exc:
                    self._send_error(client, str(exc))
                    return
                if reader.has_pending_data:
                    if partial_started_at is None or not had_pending:
                        partial_started_at = time.monotonic()
                else:
                    partial_started_at = None
                for message in messages:
                    response = self._handle_message(session, message, client=client)
                    try:
                        client.sendall(encode_frame(response))
                    except (OSError, ValueError):
                        return
                    if session.should_shutdown:
                        threading.Thread(
                            target=self._shutdown_server,
                            name="pymol-rpc-stop",
                            daemon=True,
                        ).start()
                    if session.should_close:
                        return
        finally:
            current = threading.current_thread()
            with self._clients_lock:
                self._clients.discard(client)
                self._client_threads.discard(current)
            with suppress(OSError):
                client.close()

    def _shutdown_server(self) -> None:
        if self._shutdown_callback is not None:
            try:
                self._shutdown_callback()
            except Exception:
                _LOGGER.exception("engine shutdown callback failed")
        self.stop()

    def _handle_message(
        self,
        session: RpcSession,
        message: dict[str, object],
        *,
        client: socket.socket | None = None,
    ) -> dict[str, Any]:
        if self._stop_event.is_set():
            return _internal_error(message, "engine server is stopping")
        if not self._owner_thread_dispatch:
            try:
                with self._engine_lock:
                    return session.handle(message)
            except Exception:
                _LOGGER.exception("unexpected exception while dispatching RPC")
                return _internal_error(message)
        # Initialization and authenticated shutdown mutate connection-local state
        # only. Keeping both off a busy owner queue lets a fresh stop client cancel
        # an active GUI renderer.
        method = message.get("method")
        if method == "engine.initialize" or (
            session.initialized and method == "engine.shutdown"
        ):
            return session.handle(message)
        item = RpcWorkItem(session=session, message=message, ready=threading.Event())
        self._work_queue.put(item)
        authentication_deadline = (
            time.monotonic() + self._authentication_timeout
            if not session.initialized
            else None
        )
        request_deadline = _render_request_deadline(message)
        while True:
            wait_timeout = 0.05
            if request_deadline is not None:
                remaining = request_deadline - time.monotonic()
                if remaining <= 0:
                    self._cancel_work_item(item)
                    return _internal_error(message, "render.png timed out")
                wait_timeout = min(wait_timeout, remaining)
            if item.ready.wait(wait_timeout):
                break
            if self._stop_event.is_set():
                self._cancel_work_item(item)
                return _internal_error(message, "engine server is stopping")
            if client is not None and _peer_disconnected(client):
                self._cancel_work_item(item)
                return _internal_error(message, "request client disconnected")
            if (
                authentication_deadline is not None
                and time.monotonic() >= authentication_deadline
            ):
                self._cancel_work_item(item)
                return _internal_error(message, "authentication timed out")
        return item.response or _internal_error(message)

    def _cancel_work_item(self, item: RpcWorkItem) -> None:
        item.cancelled.set()
        if item.message.get("method") != "render.png":
            return
        with self._active_work_lock:
            if self._active_work_item is not item:
                return
            callback = self._request_cancel_callback
            if callback is None:
                return
            try:
                callback()
            except Exception:
                _LOGGER.exception("render request cancellation callback failed")

    def _reject_queued_work(self) -> None:
        while True:
            try:
                item = self._work_queue.get_nowait()
            except queue.Empty:
                return
            item.response = _internal_error(item.message, "engine server is stopping")
            item.ready.set()

    @staticmethod
    def _send_error(client: socket.socket, message: str) -> None:
        error = JsonRpcError(PARSE_ERROR, message)
        with suppress(OSError, ValueError):
            client.sendall(encode_frame(build_error(error)))


def _render_request_deadline(message: dict[str, object]) -> float | None:
    if message.get("method") != "render.png":
        return None
    value = message.get("request_timeout")
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(float(value))
        or value <= 0
    ):
        return None
    return time.monotonic() + float(value)


def _peer_disconnected(client: socket.socket) -> bool:
    try:
        readable, _, _ = select.select([client], [], [], 0)
    except (OSError, ValueError):
        return True
    if not readable:
        return False
    try:
        return client.recv(1, socket.MSG_PEEK) == b""
    except (BlockingIOError, TimeoutError):
        return False
    except OSError:
        return True


def _internal_error(
    message: dict[str, object], text: str = "internal error"
) -> dict[str, Any]:
    request_id = message.get("id")
    if isinstance(request_id, bool) or not isinstance(
        request_id, (str, int, type(None))
    ):
        request_id = None
    return build_error(JsonRpcError(INTERNAL_ERROR, text, request_id))


def _positive_timeout(value: float, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a positive finite number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return parsed
