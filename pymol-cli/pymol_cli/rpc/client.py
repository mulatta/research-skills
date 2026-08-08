# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Synchronous client for the local PyMOL engine JSON-RPC transport."""

from __future__ import annotations

import math
import socket
import threading
from pathlib import Path
from types import TracebackType
from typing import Any, Protocol, Self

from pymol_cli.rpc.descriptor import read_descriptor
from pymol_cli.rpc.framing import FrameDecodeError, FrameReader, encode_frame
from pymol_cli.rpc.protocol import JsonRpcId

DEFAULT_REQUEST_TIMEOUT = 5.0
DEFAULT_RENDER_TIMEOUT = 305.0
# Compatibility name used by existing CLI flags.
DEFAULT_TIMEOUT = DEFAULT_REQUEST_TIMEOUT


class _SocketLike(Protocol):
    def gettimeout(self) -> float | None: ...

    def settimeout(self, value: float | None) -> None: ...

    def sendall(self, data: bytes) -> None: ...

    def recv(self, size: int) -> bytes: ...

    def shutdown(self, how: int) -> None: ...

    def close(self) -> None: ...


class EngineClientError(Exception):
    """Raised when an engine request fails."""


class EngineClient:
    """Blocking Engine RPC client with serialized request/response calls."""

    def __init__(
        self,
        sock: _SocketLike,
        *,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
        render_timeout: float = DEFAULT_RENDER_TIMEOUT,
    ) -> None:
        self._sock = sock
        self._reader = FrameReader()
        self._next_id = 1
        self._request_timeout = _positive_timeout(request_timeout, "request_timeout")
        self._render_timeout = _positive_timeout(render_timeout, "render_timeout")
        # Framing has no response demultiplexer, so one connection must have one
        # in-flight request. This also protects request IDs and socket timeouts.
        self._call_lock = threading.Lock()
        self._closed = False
        self.instance_id: str | None = None

    @classmethod
    def connect(
        cls,
        host: str,
        port: int,
        *,
        token: str,
        timeout: float = DEFAULT_TIMEOUT,
        request_timeout: float | None = None,
        render_timeout: float = DEFAULT_RENDER_TIMEOUT,
        expected_instance_id: str | None = None,
    ) -> Self:
        connect_timeout = _positive_timeout(timeout, "timeout")
        normal_timeout = (
            connect_timeout
            if request_timeout is None
            else _positive_timeout(request_timeout, "request_timeout")
        )
        try:
            sock = socket.create_connection((host, port), timeout=connect_timeout)
        except TimeoutError as exc:
            raise EngineClientError("engine connection timed out") from exc
        except OSError as exc:
            raise EngineClientError(f"could not connect to engine: {exc}") from exc
        client = cls(
            sock,
            request_timeout=normal_timeout,
            render_timeout=render_timeout,
        )
        try:
            client.initialize(token=token)
            if (
                expected_instance_id is not None
                and client.instance_id != expected_instance_id
            ):
                raise EngineClientError("engine instance does not match descriptor")
        except Exception:
            client.close()
            raise
        return client

    @classmethod
    def connect_descriptor(
        cls,
        path: Path,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        request_timeout: float | None = None,
        render_timeout: float = DEFAULT_RENDER_TIMEOUT,
    ) -> Self:
        descriptor = read_descriptor(path)
        return cls.connect(
            descriptor.host,
            descriptor.port,
            token=descriptor.token,
            timeout=timeout,
            request_timeout=request_timeout,
            render_timeout=render_timeout,
            expected_instance_id=descriptor.instance_id,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._closed = True
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self._sock.close()
        except OSError:
            pass

    def initialize(self, *, token: str) -> dict[str, Any]:
        result = self._object_result(
            "engine.initialize",
            self.call(
                "engine.initialize",
                {
                    "protocol_versions": [1],
                    "token": token,
                    "client": {"name": "pymol-cli"},
                },
            ),
        )
        instance_id = result.get("instance_id")
        if not isinstance(instance_id, str) or not instance_id:
            raise EngineClientError("engine.initialize returned an invalid instance_id")
        self.instance_id = instance_id
        return result

    def info(self) -> dict[str, Any]:
        return self._object_result("engine.info", self.call("engine.info"))

    def session_summary(self) -> dict[str, Any]:
        return self._object_result("session.summary", self.call("session.summary"))

    def list_objects(self) -> dict[str, Any]:
        return self._object_result("objects.list", self.call("objects.list"))

    def load_structure(self, path: str, object_name: str) -> dict[str, Any]:
        return self._object_result(
            "structure.load",
            self.call("structure.load", {"path": path, "object_name": object_name}),
        )

    def count_atoms(self, selection: str) -> dict[str, Any]:
        return self._object_result(
            "atoms.count", self.call("atoms.count", {"selection": selection})
        )

    def show_representation(
        self, representation: str, selection: str
    ) -> dict[str, Any]:
        return self._object_result(
            "scene.show",
            self.call(
                "scene.show",
                {"representation": representation, "selection": selection},
            ),
        )

    def hide_representation(
        self, representation: str, selection: str
    ) -> dict[str, Any]:
        return self._object_result(
            "scene.hide",
            self.call(
                "scene.hide",
                {"representation": representation, "selection": selection},
            ),
        )

    def color_selection(self, color: str, selection: str) -> dict[str, Any]:
        return self._object_result(
            "scene.color",
            self.call("scene.color", {"color": color, "selection": selection}),
        )

    def zoom_selection(self, selection: str, buffer: float) -> dict[str, Any]:
        return self._object_result(
            "scene.zoom",
            self.call("scene.zoom", {"selection": selection, "buffer": buffer}),
        )

    def label_residues(self, selection: str) -> dict[str, Any]:
        return self._object_result(
            "scene.label_residues",
            self.call("scene.label_residues", {"selection": selection}),
        )

    def render_png(
        self, path: str, width: int, height: int, dpi: int, ray: bool
    ) -> dict[str, Any]:
        return self._object_result(
            "render.png",
            self.call(
                "render.png",
                {
                    "path": path,
                    "width": width,
                    "height": height,
                    "dpi": dpi,
                    "ray": ray,
                },
                timeout=self._render_timeout,
            ),
        )

    def save_session(self, path: str) -> dict[str, Any]:
        return self._object_result(
            "session.save", self.call("session.save", {"path": path})
        )

    def restore_session(self, path: str) -> dict[str, Any]:
        return self._object_result(
            "session.restore", self.call("session.restore", {"path": path})
        )

    def clear_session(self) -> dict[str, Any]:
        return self._object_result("session.clear", self.call("session.clear"))

    def unsafe_execute_pml(self, command: str) -> dict[str, Any]:
        return self._object_result(
            "unsafe.execute_pml",
            self.call("unsafe.execute_pml", {"command": command}),
        )

    def shutdown(self) -> dict[str, Any]:
        return self._object_result("engine.shutdown", self.call("engine.shutdown"))

    def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Any:
        operation_timeout = (
            self._request_timeout
            if timeout is None
            else _positive_timeout(timeout, "timeout")
        )
        with self._call_lock:
            if self._closed:
                raise EngineClientError("engine connection is closed")
            request_id = self._next_request_id()
            message: dict[str, Any] = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
            }
            if params is not None:
                message["params"] = params
            if method == "render.png":
                cancellation_margin = min(
                    1.0,
                    max(0.05, operation_timeout * 0.02),
                )
                if cancellation_margin >= operation_timeout:
                    cancellation_margin = operation_timeout * 0.5
                message["request_timeout"] = operation_timeout - cancellation_margin
            previous_timeout = self._sock.gettimeout()
            try:
                self._sock.settimeout(operation_timeout)
                self._sock.sendall(encode_frame(message))
                response = self._read_response(request_id)
            except TimeoutError as exc:
                # Timed-out bytes can arrive during a later call, so this framed
                # connection cannot be reused safely.
                self.close()
                raise EngineClientError(f"{method} timed out") from exc
            except OSError as exc:
                self.close()
                raise EngineClientError(f"engine connection failed: {exc}") from exc
            except EngineClientError:
                self.close()
                raise
            finally:
                if not self._closed:
                    try:
                        self._sock.settimeout(previous_timeout)
                    except OSError:
                        self.close()
            if "error" in response:
                error = response["error"]
                message_text = (
                    str(error.get("message", "engine request failed"))
                    if isinstance(error, dict)
                    else "engine request failed"
                )
                raise EngineClientError(message_text)
            return response.get("result")

    def _next_request_id(self) -> int:
        request_id = self._next_id
        self._next_id += 1
        return request_id

    def _read_response(self, request_id: JsonRpcId) -> dict[str, Any]:
        while True:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise EngineClientError("engine connection closed")
            try:
                messages = self._reader.feed(chunk)
            except FrameDecodeError as exc:
                raise EngineClientError(str(exc)) from exc
            for message in messages:
                if message.get("id") == request_id:
                    return message

    @staticmethod
    def _object_result(method: str, result: Any) -> dict[str, Any]:
        if not isinstance(result, dict):
            raise EngineClientError(f"{method} returned non-object result")
        return result


def _positive_timeout(value: float, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a positive finite number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return parsed
