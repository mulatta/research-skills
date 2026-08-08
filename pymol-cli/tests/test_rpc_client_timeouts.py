# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import socket
import threading
from typing import Any

import pytest

from pymol_cli.rpc.client import (
    DEFAULT_RENDER_TIMEOUT,
    EngineClient,
    EngineClientError,
)
from pymol_cli.rpc.framing import FrameReader


class RecordingSocket:
    def __init__(self) -> None:
        self.timeout: float | None = None
        self.timeouts: list[float | None] = []
        self.sent: list[bytes] = []
        self.shutdowns: list[int] = []
        self.closed = False

    def gettimeout(self) -> float | None:
        return self.timeout

    def settimeout(self, timeout: float | None) -> None:
        self.timeout = timeout
        self.timeouts.append(timeout)

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def recv(self, size: int) -> bytes:
        raise AssertionError("response reader should be replaced")

    def shutdown(self, how: int) -> None:
        self.shutdowns.append(how)

    def close(self) -> None:
        self.closed = True


def test_engine_client_uses_normal_and_render_specific_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sock = RecordingSocket()
    client = EngineClient(
        sock,
        request_timeout=2.5,
        render_timeout=DEFAULT_RENDER_TIMEOUT,
    )
    monkeypatch.setattr(
        client,
        "_read_response",
        lambda request_id: {"jsonrpc": "2.0", "id": request_id, "result": {}},
    )

    client.info()
    client.render_png("view.png", 320, 240, 100, True)

    assert sock.timeouts == [2.5, None, DEFAULT_RENDER_TIMEOUT, None]
    assert DEFAULT_RENDER_TIMEOUT == 305.0
    render_request = FrameReader().feed(sock.sent[1])[0]
    assert render_request["request_timeout"] == pytest.approx(304.0)


class TimingOutSocket(RecordingSocket):
    def recv(self, size: int) -> bytes:
        raise TimeoutError("slow engine")


def test_engine_client_wraps_request_socket_timeout() -> None:
    sock = TimingOutSocket()
    client = EngineClient(sock, request_timeout=0.1)

    with pytest.raises(EngineClientError, match="timed out") as exc_info:
        client.info()

    assert isinstance(exc_info.value.__cause__, TimeoutError)
    assert sock.shutdowns == [socket.SHUT_RDWR]
    assert sock.closed


def test_engine_client_wraps_connect_socket_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def time_out(*args: Any, **kwargs: Any) -> socket.socket:
        raise TimeoutError("connect timeout")

    monkeypatch.setattr(socket, "create_connection", time_out)

    with pytest.raises(EngineClientError, match="connection timed out"):
        EngineClient.connect("127.0.0.1", 49152, token="secret", timeout=0.1)


def test_engine_client_close_interrupts_blocked_response_reader() -> None:
    client_socket, peer_socket = socket.socketpair()
    client = EngineClient(client_socket, request_timeout=30)
    started = threading.Event()
    errors: list[EngineClientError | OSError] = []

    def read_response() -> None:
        started.set()
        try:
            client._read_response(1)
        except (EngineClientError, OSError) as exc:
            errors.append(exc)

    reader = threading.Thread(target=read_response)
    reader.start()
    try:
        assert started.wait(timeout=1)
        client.close()
        reader.join(timeout=0.2)
        interrupted = not reader.is_alive()
    finally:
        peer_socket.close()
        reader.join(timeout=1)

    assert interrupted
    assert len(errors) == 1
