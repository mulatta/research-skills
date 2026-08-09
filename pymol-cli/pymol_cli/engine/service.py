# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Transport-independent engine service."""

from __future__ import annotations

import math
import os
import stat
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from pymol_cli import __version__
from pymol_cli.engine.adapter import PyMOLAdapter
from pymol_cli.engine.cancellation import require_request_not_cancelled
from pymol_cli.engine.errors import EngineError, ErrorCategory
from pymol_cli.engine.models import (
    PROTOCOL_VERSION,
    AtomCount,
    CommandResult,
    EngineInfo,
    FileResult,
    LoadResult,
    MutationResult,
    ObjectList,
    SelectionResult,
    SessionSummary,
)
from pymol_cli.engine.validation import (
    require_text,
    validate_object_name,
    validate_selection_name,
    validate_session_path,
    validate_structure_path,
)

MAX_RENDER_WIDTH = 8192
MAX_RENDER_HEIGHT = 8192
MAX_RENDER_PIXELS = 64_000_000
MAX_RENDER_DPI = 2400
MAX_SCENE_SCALE = 10.0
MAX_CONTACT_CUTOFF = 20.0
MAX_DASH_WIDTH = 20.0
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

CAPABILITIES = (
    "engine.info",
    "session.summary",
    "session.clear",
    "objects.list",
    "structure.load",
    "atoms.count",
    "selection.create",
    "scene.show",
    "scene.hide",
    "scene.color",
    "scene.zoom",
    "scene.label_residues",
    "scene.ball_and_stick",
    "scene.polar_contacts",
    "scene.background",
    "render.png",
    "session.save",
    "session.restore",
    "unsafe.execute_pml",
)

_T = TypeVar("_T")


class EngineService:
    """Coordinate typed engine operations over one PyMOL adapter."""

    def __init__(self, adapter: PyMOLAdapter) -> None:
        self._adapter = adapter
        self._revision = 0

    @property
    def revision(self) -> int:
        return self._revision

    def get_info(self) -> EngineInfo:
        backend_version = self._call_backend("engine.info", self._adapter.get_version)
        return EngineInfo(
            protocol_version=PROTOCOL_VERSION,
            engine_version=__version__,
            backend="pymol-open-source",
            backend_version=backend_version,
            capabilities=CAPABILITIES,
        )

    def get_session_summary(self) -> SessionSummary:
        return SessionSummary(
            object_names=self._call_backend(
                "session.summary", self._adapter.get_object_names
            ),
            atom_count=self._call_backend(
                "session.summary", lambda: self._adapter.count_atoms("all")
            ),
            revision=self._revision,
        )

    def list_objects(self) -> ObjectList:
        return ObjectList(
            object_names=self._call_backend(
                "objects.list", self._adapter.get_object_names
            ),
            revision=self._revision,
        )

    def count_atoms(self, selection: str) -> AtomCount:
        normalized_selection = require_text(selection, "selection")
        count = self._call_backend(
            "atoms.count", lambda: self._adapter.count_atoms(normalized_selection)
        )
        return AtomCount(
            selection=normalized_selection,
            count=count,
            revision=self._revision,
        )

    def create_selection(self, name: str, expression: str) -> SelectionResult:
        normalized_name = validate_selection_name(name)
        normalized_expression = require_text(expression, "expression")
        self._call_backend(
            "selection.create",
            lambda: self._adapter.create_selection(
                normalized_name, normalized_expression
            ),
        )
        self._revision += 1
        atom_count = self._call_backend(
            "atoms.count", lambda: self._adapter.count_atoms(normalized_name)
        )
        return SelectionResult(
            name=normalized_name,
            atom_count=atom_count,
            revision=self._revision,
        )

    def load_structure(self, *, path: str, object_name: str) -> LoadResult:
        normalized_path = validate_structure_path(path)
        normalized_object = validate_object_name(object_name)
        self._call_backend(
            "structure.load",
            lambda: self._adapter.load_structure(normalized_path, normalized_object),
        )
        self._revision += 1
        atom_count = self._call_backend(
            "atoms.count", lambda: self._adapter.count_atoms(normalized_object)
        )
        return LoadResult(
            object_name=normalized_object,
            atom_count=atom_count,
            revision=self._revision,
        )

    def show_representation(
        self, representation: str, selection: str
    ) -> MutationResult:
        normalized_representation = require_text(representation, "representation")
        normalized_selection = require_text(selection, "selection")
        self._call_backend(
            "scene.show",
            lambda: self._adapter.show_representation(
                normalized_representation, normalized_selection
            ),
        )
        self._revision += 1
        return MutationResult(revision=self._revision)

    def hide_representation(
        self, representation: str, selection: str
    ) -> MutationResult:
        normalized_representation = require_text(representation, "representation")
        normalized_selection = require_text(selection, "selection")
        self._call_backend(
            "scene.hide",
            lambda: self._adapter.hide_representation(
                normalized_representation, normalized_selection
            ),
        )
        self._revision += 1
        return MutationResult(revision=self._revision)

    def color_selection(self, color: str, selection: str) -> MutationResult:
        normalized_color = require_text(color, "color")
        normalized_selection = require_text(selection, "selection")
        self._call_backend(
            "scene.color",
            lambda: self._adapter.color_selection(
                normalized_color, normalized_selection
            ),
        )
        self._revision += 1
        return MutationResult(revision=self._revision)

    def zoom_selection(self, selection: str, *, buffer: float) -> MutationResult:
        normalized_selection = require_text(selection, "selection")
        if isinstance(buffer, bool):
            self._invalid_number("buffer", buffer)
        try:
            normalized_buffer = float(buffer)
        except (TypeError, ValueError, OverflowError):
            self._invalid_number("buffer", buffer)
        if not math.isfinite(normalized_buffer) or normalized_buffer < 0:
            self._invalid_number("buffer", buffer)
        self._call_backend(
            "scene.zoom",
            lambda: self._adapter.zoom_selection(
                normalized_selection, normalized_buffer
            ),
        )
        self._revision += 1
        return MutationResult(revision=self._revision)

    def label_residues(self, selection: str) -> MutationResult:
        normalized_selection = require_text(selection, "selection")
        self._call_backend(
            "scene.label_residues",
            lambda: self._adapter.label_residues(normalized_selection),
        )
        self._revision += 1
        return MutationResult(revision=self._revision)

    def show_ball_and_stick(
        self,
        selection: str,
        *,
        stick_radius: float,
        sphere_scale: float,
    ) -> MutationResult:
        normalized_selection = require_text(selection, "selection")
        normalized_stick_radius = self._require_bounded_positive_float(
            stick_radius, "stick_radius", MAX_SCENE_SCALE
        )
        normalized_sphere_scale = self._require_bounded_positive_float(
            sphere_scale, "sphere_scale", MAX_SCENE_SCALE
        )
        self._call_backend(
            "scene.ball_and_stick",
            lambda: self._adapter.show_ball_and_stick(
                normalized_selection,
                normalized_stick_radius,
                normalized_sphere_scale,
            ),
        )
        self._revision += 1
        return MutationResult(revision=self._revision)

    def show_polar_contacts(
        self,
        name: str,
        selection1: str,
        selection2: str,
        *,
        cutoff: float,
        color: str,
        dash_width: float,
    ) -> MutationResult:
        normalized_name = validate_selection_name(name)
        normalized_selection1 = require_text(selection1, "selection1")
        normalized_selection2 = require_text(selection2, "selection2")
        normalized_cutoff = self._require_bounded_positive_float(
            cutoff, "cutoff", MAX_CONTACT_CUTOFF
        )
        normalized_color = require_text(color, "color")
        normalized_dash_width = self._require_bounded_positive_float(
            dash_width, "dash_width", MAX_DASH_WIDTH
        )
        self._call_backend(
            "scene.polar_contacts",
            lambda: self._adapter.show_polar_contacts(
                normalized_name,
                normalized_selection1,
                normalized_selection2,
                normalized_cutoff,
                normalized_color,
                normalized_dash_width,
            ),
        )
        self._revision += 1
        return MutationResult(revision=self._revision)

    def set_background(self, color: str, *, opaque: bool) -> MutationResult:
        normalized_color = require_text(color, "color")
        if not isinstance(opaque, bool):
            raise EngineError(
                ErrorCategory.INVALID_ARGUMENT,
                "opaque must be a boolean",
                {"argument": "opaque"},
            )
        self._call_backend(
            "scene.background",
            lambda: self._adapter.set_background(normalized_color, opaque),
        )
        self._revision += 1
        return MutationResult(revision=self._revision)

    def render_png(
        self, *, path: str, width: int, height: int, dpi: int, ray: bool
    ) -> FileResult:
        require_request_not_cancelled("render.png")
        normalized_path = require_text(path, "path")
        normalized_width = self._require_bounded_positive_int(
            width, "width", MAX_RENDER_WIDTH
        )
        normalized_height = self._require_bounded_positive_int(
            height, "height", MAX_RENDER_HEIGHT
        )
        normalized_dpi = self._require_bounded_positive_int(dpi, "dpi", MAX_RENDER_DPI)
        if normalized_width * normalized_height > MAX_RENDER_PIXELS:
            raise EngineError(
                ErrorCategory.INVALID_ARGUMENT,
                "render pixel count exceeds the safety limit",
                {"limit": MAX_RENDER_PIXELS},
            )
        if not isinstance(ray, bool):
            raise EngineError(
                ErrorCategory.INVALID_ARGUMENT,
                "ray must be boolean",
                {"argument": "ray"},
            )

        target = self._prepare_output_target(
            normalized_path, "render.png", allowed_suffixes=frozenset({".png"})
        )
        temporary = self._create_output_temp(target, suffix=".png")
        try:
            render_token = self._call_backend(
                "render.png",
                lambda: self._adapter.render_png(
                    str(temporary),
                    normalized_width,
                    normalized_height,
                    normalized_dpi,
                    ray,
                ),
            )
            require_request_not_cancelled("render.png")
            self._verify_png(temporary)
            require_request_not_cancelled("render.png")
            publisher = getattr(self._adapter, "publish_render", None)
            if callable(publisher):
                self._call_backend(
                    "render.png",
                    lambda: publisher(str(temporary), str(target), render_token),
                )
            else:
                try:
                    os.replace(temporary, target)
                except OSError as exc:
                    raise EngineError(
                        ErrorCategory.BACKEND_FAILURE,
                        "render.png could not publish its output",
                        {"operation": "render.png"},
                    ) from exc
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        return FileResult(path=normalized_path, revision=self._revision)

    def save_session(self, path: str) -> FileResult:
        normalized_path = validate_session_path(path, must_exist=False)
        target = self._prepare_output_target(normalized_path, "session.save")
        temporary = self._create_output_temp(target, suffix=target.suffix)
        try:
            self._call_backend(
                "session.save", lambda: self._adapter.save_session(str(temporary))
            )
            self._verify_nonempty_file(temporary, "session.save")
            try:
                os.replace(temporary, target)
            except OSError as exc:
                raise EngineError(
                    ErrorCategory.BACKEND_FAILURE,
                    "session.save could not publish its output",
                    {"operation": "session.save"},
                ) from exc
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        return FileResult(path=normalized_path, revision=self._revision)

    def restore_session(self, path: str) -> FileResult:
        normalized_path = validate_session_path(path, must_exist=True)
        self._call_backend(
            "session.restore", lambda: self._adapter.restore_session(normalized_path)
        )
        self._revision += 1
        return FileResult(path=normalized_path, revision=self._revision)

    def execute_pml(self, command: str) -> CommandResult:
        normalized_command = require_text(command, "command")
        result = self._call_backend(
            "unsafe.execute_pml",
            lambda: self._adapter.execute_pml(normalized_command),
        )
        self._revision += 1
        return CommandResult(
            command=normalized_command,
            result=result,
            revision=self._revision,
        )

    def clear_session(self) -> MutationResult:
        self._call_backend("session.clear", self._adapter.clear)
        self._revision += 1
        return MutationResult(revision=self._revision)

    @staticmethod
    def _call_backend(operation: str, call: Callable[[], _T]) -> _T:
        try:
            return call()
        except EngineError:
            raise
        except TimeoutError as exc:
            raise EngineError(
                ErrorCategory.OPERATION_TIMEOUT,
                f"{operation} timed out",
                {"operation": operation},
            ) from exc
        except Exception as exc:
            raise EngineError(
                ErrorCategory.BACKEND_FAILURE,
                f"{operation} failed in the PyMOL backend",
                {"operation": operation},
            ) from exc

    @staticmethod
    def _invalid_number(name: str, value: object) -> None:
        raise EngineError(
            ErrorCategory.INVALID_ARGUMENT,
            f"{name} must be a finite non-negative number",
            {"argument": name},
        )

    @staticmethod
    def _require_bounded_positive_float(
        value: object, name: str, limit: float
    ) -> float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            normalized = math.nan
        else:
            normalized = float(value)
        if not math.isfinite(normalized) or normalized <= 0:
            raise EngineError(
                ErrorCategory.INVALID_ARGUMENT,
                f"{name} must be a finite positive number",
                {"argument": name},
            )
        if normalized > limit:
            raise EngineError(
                ErrorCategory.INVALID_ARGUMENT,
                f"{name} exceeds the safety limit",
                {"argument": name, "limit": limit},
            )
        return normalized

    @staticmethod
    def _require_bounded_positive_int(value: object, name: str, limit: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise EngineError(
                ErrorCategory.INVALID_ARGUMENT,
                f"{name} must be a positive integer",
                {"argument": name},
            )
        if value > limit:
            raise EngineError(
                ErrorCategory.INVALID_ARGUMENT,
                f"{name} exceeds the safety limit",
                {"argument": name, "limit": limit},
            )
        return value

    @staticmethod
    def _prepare_output_target(
        path: str,
        operation: str,
        *,
        allowed_suffixes: frozenset[str] | None = None,
    ) -> Path:
        target = Path(path)
        if not target.is_absolute():
            raise EngineError(
                ErrorCategory.INVALID_ARGUMENT,
                "output path must be absolute",
                {"argument": "path"},
            )
        if (
            allowed_suffixes is not None
            and target.suffix.lower() not in allowed_suffixes
        ):
            raise EngineError(
                ErrorCategory.INVALID_ARGUMENT,
                f"{operation} output has an unsupported file extension",
                {"allowed_suffixes": sorted(allowed_suffixes)},
            )
        parent = target.parent
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except (OSError, ValueError) as exc:
            raise EngineError(
                ErrorCategory.BACKEND_FAILURE,
                f"{operation} could not prepare the output directory",
                {"operation": operation},
            ) from exc
        try:
            target_exists = target.exists()
            target_is_file = target.is_file()
        except OSError as exc:
            raise EngineError(
                ErrorCategory.BACKEND_FAILURE,
                f"{operation} could not inspect the output path",
                {"operation": operation},
            ) from exc
        if target_exists and not target_is_file:
            raise EngineError(
                ErrorCategory.INVALID_ARGUMENT,
                "output path must not be a directory or special file",
                {"argument": "path"},
            )
        return target

    @staticmethod
    def _create_output_temp(target: Path, *, suffix: str) -> Path:
        try:
            descriptor, name = tempfile.mkstemp(
                prefix=f".{target.name}.", suffix=suffix, dir=target.parent
            )
            os.close(descriptor)
        except OSError as exc:
            raise EngineError(
                ErrorCategory.BACKEND_FAILURE,
                "could not create a temporary output",
                {"operation": "file.write"},
            ) from exc
        return Path(name)

    @staticmethod
    def _verify_nonempty_file(path: Path, operation: str) -> None:
        try:
            file_stat = path.stat()
        except (OSError, ValueError) as exc:
            raise EngineError(
                ErrorCategory.BACKEND_FAILURE,
                f"{operation} did not produce a readable file",
                {"operation": operation},
            ) from exc
        if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size == 0:
            raise EngineError(
                ErrorCategory.BACKEND_FAILURE,
                f"{operation} did not produce a nonempty file",
                {"operation": operation},
            )

    @staticmethod
    def _verify_png(path: Path) -> None:
        try:
            file_stat = path.stat()
            with path.open("rb") as handle:
                signature = handle.read(len(_PNG_SIGNATURE))
        except (OSError, ValueError) as exc:
            raise EngineError(
                ErrorCategory.BACKEND_FAILURE,
                "render.png did not produce a readable PNG",
                {"operation": "render.png"},
            ) from exc
        if (
            not stat.S_ISREG(file_stat.st_mode)
            or file_stat.st_size <= len(_PNG_SIGNATURE)
            or signature != _PNG_SIGNATURE
        ):
            raise EngineError(
                ErrorCategory.BACKEND_FAILURE,
                "render.png did not produce a valid nonempty PNG",
                {"operation": "render.png"},
            )
