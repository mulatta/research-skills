# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""LSP-style Content-Length framing for JSON-RPC messages."""

from __future__ import annotations

import json
from typing import Any, NoReturn

HEADER_SEPARATOR = b"\r\n\r\n"
DEFAULT_MAX_HEADER_BYTES = 16 * 1024
DEFAULT_MAX_BODY_BYTES = 8 * 1024 * 1024


class FrameDecodeError(Exception):
    """Raised when an incoming frame cannot be decoded safely."""


def encode_frame(message: dict[str, Any]) -> bytes:
    try:
        body = json.dumps(message, allow_nan=False, separators=(",", ":")).encode(
            "utf-8"
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("JSON-RPC message is not JSON serializable") from exc
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    return header + body


class FrameReader:
    """Incrementally decode size-limited Content-Length JSON messages."""

    def __init__(
        self,
        *,
        max_header_bytes: int = DEFAULT_MAX_HEADER_BYTES,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    ) -> None:
        if max_header_bytes <= 0:
            raise ValueError("max_header_bytes must be positive")
        if max_body_bytes <= 0:
            raise ValueError("max_body_bytes must be positive")
        self._max_header_bytes = max_header_bytes
        self._max_body_bytes = max_body_bytes
        self._buffer = bytearray()

    @property
    def has_pending_data(self) -> bool:
        return bool(self._buffer)

    def feed(self, data: bytes) -> list[dict[str, Any]]:
        self._buffer.extend(data)
        messages: list[dict[str, Any]] = []
        while True:
            header_end = self._buffer.find(HEADER_SEPARATOR)
            if header_end < 0:
                if len(self._buffer) > self._max_header_bytes:
                    raise FrameDecodeError("message header is too large")
                return messages
            if header_end > self._max_header_bytes:
                raise FrameDecodeError("message header is too large")
            headers = bytes(self._buffer[:header_end])
            body_length = self._parse_content_length(headers)
            frame_end = header_end + len(HEADER_SEPARATOR) + body_length
            if len(self._buffer) < frame_end:
                return messages
            body_start = header_end + len(HEADER_SEPARATOR)
            body = bytes(self._buffer[body_start:frame_end])
            del self._buffer[:frame_end]
            messages.append(self._decode_body(body))

    def _parse_content_length(self, headers: bytes) -> int:
        try:
            header_text = headers.decode("ascii", errors="strict")
        except UnicodeDecodeError as exc:
            raise FrameDecodeError("message header must contain only ASCII") from exc
        found: int | None = None
        for line in header_text.split("\r\n"):
            if not line:
                continue
            name, separator, value = line.partition(":")
            if not separator:
                raise FrameDecodeError("invalid header line")
            if name.lower() != "content-length":
                continue
            if found is not None:
                raise FrameDecodeError("duplicate Content-Length header")
            try:
                found = int(value.strip())
            except ValueError as exc:
                raise FrameDecodeError("invalid Content-Length header") from exc
        if found is None:
            raise FrameDecodeError("missing Content-Length header")
        if found < 0:
            raise FrameDecodeError("negative Content-Length header")
        if found > self._max_body_bytes:
            raise FrameDecodeError("message body is too large")
        return found

    @staticmethod
    def _decode_body(body: bytes) -> dict[str, Any]:
        try:
            decoded = json.loads(
                body.decode("utf-8"), parse_constant=_reject_json_constant
            )
        except UnicodeDecodeError as exc:
            raise FrameDecodeError("message body is not valid UTF-8") from exc
        except (json.JSONDecodeError, ValueError) as exc:
            raise FrameDecodeError("message body is not valid JSON") from exc
        if not isinstance(decoded, dict):
            raise FrameDecodeError("JSON-RPC message must be an object")
        return decoded


def _reject_json_constant(value: str) -> NoReturn:
    raise ValueError(f"invalid JSON constant: {value}")
