# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Cross-platform advisory lock for engine startup serialization."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, BinaryIO


class EngineStartLocked(Exception):
    """Raised when another process is already starting this engine."""


def engine_start_lock_path(descriptor_path: Path) -> Path:
    return descriptor_path.with_name(f".{descriptor_path.name}.start.lock")


@contextmanager
def engine_start_lock(descriptor_path: Path) -> Iterator[None]:
    """Hold non-blocking OS lock while checking and starting one engine."""
    lock_path = engine_start_lock_path(descriptor_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    from pymol_cli.rpc.descriptor import open_private_lock_file

    handle = open_private_lock_file(lock_path)
    try:
        _acquire_file_lock(handle)
        try:
            yield
        finally:
            _release_file_lock(handle)
    finally:
        handle.close()


def _acquire_file_lock(handle: BinaryIO) -> None:
    try:
        if os.name == "nt":
            _acquire_windows_lock(handle)
        else:
            _acquire_posix_lock(handle)
    except (BlockingIOError, PermissionError) as exc:
        raise EngineStartLocked("another engine start is already in progress") from exc
    except OSError as exc:
        # Windows reports lock contention as EACCES/EDEADLK depending on runtime.
        if exc.errno in {11, 13, 35, 36}:
            raise EngineStartLocked(
                "another engine start is already in progress"
            ) from exc
        raise


def _release_file_lock(handle: BinaryIO) -> None:
    if os.name == "nt":
        msvcrt: Any = __import__("msvcrt")
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _acquire_windows_lock(handle: BinaryIO) -> None:
    msvcrt: Any = __import__("msvcrt")
    _prepare_windows_lock_byte(handle)
    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)


def _prepare_windows_lock_byte(handle: BinaryIO) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)


def _acquire_posix_lock(handle: BinaryIO) -> None:
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
