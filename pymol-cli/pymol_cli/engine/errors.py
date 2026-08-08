# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Stable engine error categories."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ErrorCategory(StrEnum):
    INVALID_ARGUMENT = "InvalidArgument"
    INVALID_SELECTION = "InvalidSelection"
    NOT_FOUND = "NotFound"
    CONFLICT = "Conflict"
    UNSUPPORTED_CAPABILITY = "UnsupportedCapability"
    BACKEND_FAILURE = "BackendFailure"
    OPERATION_TIMEOUT = "OperationTimeout"
    UNSAFE_OPERATION_REQUIRED = "UnsafeOperationRequired"


@dataclass
class EngineError(Exception):
    category: ErrorCategory
    message: str
    details: dict[str, Any] | None = None

    def __str__(self) -> str:
        return self.message
