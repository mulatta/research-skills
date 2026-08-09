# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Embedded PyMOL adapter for engine-core integration tests."""

from __future__ import annotations

import importlib
from types import TracebackType
from typing import Any, Self

from pymol_cli.engine.current_process import CurrentProcessPyMOLAdapter
from pymol_cli.engine.errors import EngineError, ErrorCategory
from pymol_cli.engine.validation import (
    require_exact_runtime_object_name,
    structure_format_for_path,
)


class EmbeddedPyMOLAdapter:
    """Own a `pymol2.PyMOL()` instance and expose minimal engine operations."""

    def __init__(self) -> None:
        self._pymol: Any | None = None
        self._renderer: CurrentProcessPyMOLAdapter | None = None

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.stop()

    @property
    def cmd(self) -> Any:
        if self._pymol is None:
            raise EngineError(
                ErrorCategory.CONFLICT,
                "embedded PyMOL adapter has not been started",
            )
        return self._pymol.cmd

    def start(self) -> None:
        if self._pymol is not None:
            return
        try:
            pymol2: Any = importlib.import_module("pymol2")
        except ImportError as exc:
            raise EngineError(
                ErrorCategory.UNSUPPORTED_CAPABILITY,
                "pymol2 module is not available in this runtime",
            ) from exc
        pymol = pymol2.PyMOL()
        try:
            pymol.start()
        except Exception as exc:  # pragma: no cover - depends on local PyMOL runtime
            raise EngineError(
                ErrorCategory.BACKEND_FAILURE,
                "embedded PyMOL failed to start",
            ) from exc
        self._pymol = pymol
        self._renderer = CurrentProcessPyMOLAdapter(
            cmd=pymol.cmd,
            headless_render_worker=True,
        )

    def stop(self) -> None:
        if self._pymol is None:
            return
        pymol = self._pymol
        renderer = self._renderer
        self._pymol = None
        self._renderer = None
        if renderer is not None:
            renderer.cancel_render()
        pymol.stop()

    def get_version(self) -> str:
        version = self.cmd.get_version()
        if isinstance(version, (tuple, list)) and version:
            return str(version[0])
        return str(version)

    def get_object_names(self) -> list[str]:
        names = self.cmd.get_names("objects")
        return [str(name) for name in names]

    def count_atoms(self, selection: str) -> int:
        return int(self.cmd.count_atoms(selection))

    def load_structure(self, path: str, object_name: str) -> None:
        require_exact_runtime_object_name(self.cmd, object_name)
        self.cmd.load(
            path,
            object_name,
            format=structure_format_for_path(path),
        )

    def show_representation(self, representation: str, selection: str) -> None:
        self.cmd.show(representation, selection)

    def hide_representation(self, representation: str, selection: str) -> None:
        self.cmd.hide(representation, selection)

    def color_selection(self, color: str, selection: str) -> None:
        self.cmd.color(color, selection)

    def zoom_selection(self, selection: str, buffer: float) -> None:
        self.cmd.zoom(selection, buffer=buffer)

    def label_residues(self, selection: str) -> None:
        self.cmd.label(
            f"({selection}) and name CA",
            '"%s%s/%s" % (resn, resi, chain)',
        )
        self.cmd.set("label_color", "black")
        self.cmd.set("label_size", 18)

    def render_png(
        self, path: str, width: int, height: int, dpi: int, ray: bool
    ) -> object | None:
        return self._require_renderer().render_png(path, width, height, dpi, ray)

    def publish_render(self, source: str, target: str, token: object) -> None:
        self._require_renderer().publish_render(source, target, token)

    def cancel_active_render(self) -> None:
        self._require_renderer().cancel_active_render()

    def cancel_render(self) -> None:
        self._require_renderer().cancel_render()

    def _require_renderer(self) -> CurrentProcessPyMOLAdapter:
        if self._renderer is None:
            raise EngineError(
                ErrorCategory.CONFLICT,
                "embedded PyMOL adapter has not been started",
            )
        return self._renderer

    def save_session(self, path: str) -> None:
        self.cmd.save(path, format="pse")

    def restore_session(self, path: str) -> None:
        self.cmd.load(path, format="pse")

    def execute_pml(self, command: str) -> Any:
        return self._require_renderer().execute_pml(command)

    def clear(self) -> None:
        self.cmd.delete("all")
