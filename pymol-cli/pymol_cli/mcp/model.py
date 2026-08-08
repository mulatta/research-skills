# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""MCP shared types and models."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Protocol, Self

JsonObject = dict[str, Any]
McpRequestId = str | float
_PENDING_REQUEST = object()
_CANCELLED_REQUEST = object()


class McpError(Exception):
    """JSON-RPC error for MCP requests."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class EngineClientLike(Protocol):
    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def count_atoms(self, selection: str) -> JsonObject: ...

    def load_structure(self, path: str, object_name: str) -> JsonObject: ...

    def list_objects(self) -> JsonObject: ...

    def show_representation(
        self, representation: str, selection: str
    ) -> JsonObject: ...

    def hide_representation(
        self, representation: str, selection: str
    ) -> JsonObject: ...

    def color_selection(self, color: str, selection: str) -> JsonObject: ...

    def zoom_selection(self, selection: str, buffer: float) -> JsonObject: ...

    def label_residues(self, selection: str) -> JsonObject: ...

    def render_png(
        self, path: str, width: int, height: int, dpi: int, ray: bool
    ) -> JsonObject: ...

    def session_summary(self) -> JsonObject: ...

    def clear_session(self) -> JsonObject: ...

    def save_session(self, path: str) -> JsonObject: ...


ClientFactory = Callable[[], EngineClientLike]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: JsonObject
    handler: Callable[[EngineClientLike, JsonObject], JsonObject]

    def to_mcp(self) -> JsonObject:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }
