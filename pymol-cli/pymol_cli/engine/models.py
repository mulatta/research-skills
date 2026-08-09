# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Typed engine request and result models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PROTOCOL_VERSION = 1


@dataclass(frozen=True)
class EngineInfo:
    protocol_version: int
    engine_version: str
    backend: str
    backend_version: str
    capabilities: tuple[str, ...]


@dataclass(frozen=True)
class CommandResult:
    command: str
    result: Any
    revision: int


@dataclass(frozen=True)
class AtomCount:
    selection: str
    count: int
    revision: int


@dataclass(frozen=True)
class SelectionResult:
    name: str
    atom_count: int
    revision: int


@dataclass(frozen=True)
class SessionSummary:
    object_names: list[str]
    atom_count: int
    revision: int


@dataclass(frozen=True)
class ObjectList:
    object_names: list[str]
    revision: int


@dataclass(frozen=True)
class LoadResult:
    object_name: str
    atom_count: int
    revision: int


@dataclass(frozen=True)
class FileResult:
    path: str
    revision: int


@dataclass(frozen=True)
class MutationResult:
    revision: int
