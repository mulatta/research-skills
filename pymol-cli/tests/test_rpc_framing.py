# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import pytest

from pymol_cli.rpc.framing import FrameDecodeError, FrameReader, encode_frame


def test_encode_frame_uses_content_length_header() -> None:
    assert encode_frame({"jsonrpc": "2.0", "id": 1, "result": {}}) == (
        b'Content-Length: 36\r\n\r\n{"jsonrpc":"2.0","id":1,"result":{}}'
    )


def test_frame_reader_handles_fragmented_input() -> None:
    reader = FrameReader()

    assert reader.feed(b"Content-Length: 36\r\n") == []
    assert reader.feed(b'\r\n{"jsonrpc":"2.0",') == []
    assert reader.feed(b'"id":1,"result":{}}') == [
        {"jsonrpc": "2.0", "id": 1, "result": {}}
    ]


def test_frame_reader_handles_coalesced_frames() -> None:
    first = encode_frame({"jsonrpc": "2.0", "id": 1, "result": {}})
    second = encode_frame({"jsonrpc": "2.0", "method": "engine.ready"})

    assert FrameReader().feed(first + second) == [
        {"jsonrpc": "2.0", "id": 1, "result": {}},
        {"jsonrpc": "2.0", "method": "engine.ready"},
    ]


def test_frame_reader_rejects_missing_content_length() -> None:
    reader = FrameReader()

    with pytest.raises(FrameDecodeError, match="Content-Length"):
        reader.feed(b"Other: 1\r\n\r\n{}")


def test_frame_reader_rejects_oversized_body() -> None:
    reader = FrameReader(max_body_bytes=5)

    with pytest.raises(FrameDecodeError, match="too large"):
        reader.feed(b"Content-Length: 6\r\n\r\n{}")


def test_frame_reader_rejects_oversized_header_before_separator() -> None:
    reader = FrameReader(max_header_bytes=32)

    with pytest.raises(FrameDecodeError, match="header is too large"):
        reader.feed(b"X" * 33)


def test_frame_reader_rejects_non_ascii_header() -> None:
    reader = FrameReader()

    with pytest.raises(FrameDecodeError, match="ASCII"):
        reader.feed(b"X-Name: \xff\r\nContent-Length: 2\r\n\r\n{}")
