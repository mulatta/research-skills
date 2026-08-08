# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Request-scoped cancellation visible on the serialized engine owner thread."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from pymol_cli.engine.errors import EngineError, ErrorCategory

_CURRENT_REQUEST_CANCELLATION: ContextVar[threading.Event | None] = ContextVar(
    "pymol_request_cancellation",
    default=None,
)


@contextmanager
def request_cancellation(event: threading.Event) -> Iterator[None]:
    token = _CURRENT_REQUEST_CANCELLATION.set(event)
    try:
        yield
    finally:
        _CURRENT_REQUEST_CANCELLATION.reset(token)


def request_is_cancelled() -> bool:
    event = _CURRENT_REQUEST_CANCELLATION.get()
    return event is not None and event.is_set()


def require_request_not_cancelled(operation: str) -> None:
    if request_is_cancelled():
        raise EngineError(
            ErrorCategory.BACKEND_FAILURE,
            f"{operation} was cancelled",
            {"operation": operation},
        )
