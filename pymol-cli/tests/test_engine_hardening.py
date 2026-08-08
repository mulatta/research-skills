# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest

from pymol_cli.engine.errors import EngineError, ErrorCategory
from pymol_cli.engine.service import (
    MAX_RENDER_DPI,
    MAX_RENDER_HEIGHT,
    MAX_RENDER_PIXELS,
    MAX_RENDER_WIDTH,
    EngineService,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"test-payload"


class RecordingAdapter:
    def __init__(self) -> None:
        self.loaded: list[tuple[str, str]] = []
        self.rendered: list[str] = []
        self.saved: list[str] = []
        self.restored: list[str] = []

    def get_version(self) -> str:
        return "test"

    def get_object_names(self) -> list[str]:
        return []

    def count_atoms(self, selection: str) -> int:
        return 1

    def load_structure(self, path: str, object_name: str) -> None:
        self.loaded.append((path, object_name))

    def show_representation(self, representation: str, selection: str) -> None:
        return None

    def hide_representation(self, representation: str, selection: str) -> None:
        return None

    def color_selection(self, color: str, selection: str) -> None:
        return None

    def zoom_selection(self, selection: str, buffer: float) -> None:
        return None

    def label_residues(self, selection: str) -> None:
        return None

    def render_png(
        self, path: str, width: int, height: int, dpi: int, ray: bool
    ) -> None:
        self.rendered.append(path)
        Path(path).write_bytes(PNG)

    def save_session(self, path: str) -> None:
        self.saved.append(path)
        Path(path).write_bytes(b"session")

    def restore_session(self, path: str) -> None:
        self.restored.append(path)

    def execute_pml(self, command: str) -> Any:
        return None

    def clear(self) -> None:
        return None


@pytest.mark.parametrize("suffix", [".pdb", ".ent", ".cif", ".mmcif", ".PDB"])
def test_structure_load_accepts_existing_absolute_safe_formats(
    tmp_path: Path, suffix: str
) -> None:
    structure = tmp_path / f"model{suffix}"
    structure.write_text("HEADER test\n", encoding="utf-8")
    adapter = RecordingAdapter()

    result = EngineService(adapter).load_structure(
        path=str(structure), object_name="1abc_model"
    )

    assert result.object_name == "1abc_model"
    assert adapter.loaded == [(str(structure), "1abc_model")]


@pytest.mark.parametrize("suffix", [".py", ".pml", ".pse", ".psw", ".txt", ".gz"])
def test_structure_load_rejects_unsafe_extensions_without_executing_them(
    tmp_path: Path, suffix: str
) -> None:
    marker = tmp_path / "executed"
    structure = tmp_path / f"model{suffix}"
    structure.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n",
        encoding="utf-8",
    )
    adapter = RecordingAdapter()

    with pytest.raises(EngineError) as exc_info:
        EngineService(adapter).load_structure(path=str(structure), object_name="model")

    assert exc_info.value.category is ErrorCategory.INVALID_ARGUMENT
    assert not marker.exists()
    assert adapter.loaded == []


def test_structure_load_rejects_url_relative_and_missing_paths(tmp_path: Path) -> None:
    adapter = RecordingAdapter()
    engine = EngineService(adapter)
    relative = Path("model.pdb")

    with pytest.raises(EngineError) as url_error:
        engine.load_structure(path="https://example.invalid/model.pdb", object_name="x")
    with pytest.raises(EngineError) as relative_error:
        engine.load_structure(path=str(relative), object_name="x")
    with pytest.raises(EngineError) as missing_error:
        engine.load_structure(path=str(tmp_path / "missing.pdb"), object_name="x")

    assert url_error.value.category is ErrorCategory.INVALID_ARGUMENT
    assert relative_error.value.category is ErrorCategory.INVALID_ARGUMENT
    assert missing_error.value.category is ErrorCategory.NOT_FOUND
    assert adapter.loaded == []


@pytest.mark.parametrize(
    "name",
    [
        "all",
        "NONE",
        "sele",
        "model",
        "OBJECT",
        "enabled",
        "visible",
        "in",
        "like",
        "bad name",
        "bad-name",
        "x; delete all",
        "",
    ],
)
def test_structure_load_rejects_reserved_or_unsafe_object_names(
    tmp_path: Path, name: str
) -> None:
    structure = tmp_path / "model.pdb"
    structure.write_text("HEADER test\n", encoding="utf-8")
    adapter = RecordingAdapter()

    with pytest.raises(EngineError) as exc_info:
        EngineService(adapter).load_structure(path=str(structure), object_name=name)

    assert exc_info.value.category is ErrorCategory.INVALID_ARGUMENT
    assert adapter.loaded == []


@pytest.mark.parametrize("buffer", [math.inf, -math.inf, math.nan, -1.0])
def test_zoom_rejects_non_finite_and_negative_buffers(buffer: float) -> None:
    with pytest.raises(EngineError) as exc_info:
        EngineService(RecordingAdapter()).zoom_selection("all", buffer=buffer)

    assert exc_info.value.category is ErrorCategory.INVALID_ARGUMENT


@pytest.mark.parametrize(
    ("width", "height", "dpi"),
    [
        (MAX_RENDER_WIDTH + 1, 1, 100),
        (1, MAX_RENDER_HEIGHT + 1, 100),
        (MAX_RENDER_WIDTH, MAX_RENDER_HEIGHT, 100),
        (1, 1, MAX_RENDER_DPI + 1),
    ],
)
def test_render_rejects_resource_exhausting_dimensions(
    tmp_path: Path, width: int, height: int, dpi: int
) -> None:
    assert (
        width * height > MAX_RENDER_PIXELS
        or width > MAX_RENDER_WIDTH
        or height > MAX_RENDER_HEIGHT
        or dpi > MAX_RENDER_DPI
    )
    adapter = RecordingAdapter()

    with pytest.raises(EngineError) as exc_info:
        EngineService(adapter).render_png(
            path=str(tmp_path / "view.png"),
            width=width,
            height=height,
            dpi=dpi,
            ray=False,
        )

    assert exc_info.value.category is ErrorCategory.INVALID_ARGUMENT
    assert adapter.rendered == []


@pytest.mark.parametrize("case", ["relative", "extension"])
def test_render_rejects_relative_or_non_png_output(tmp_path: Path, case: str) -> None:
    adapter = RecordingAdapter()
    path = "view.png" if case == "relative" else str(tmp_path / "view.jpg")

    with pytest.raises(EngineError) as exc_info:
        EngineService(adapter).render_png(
            path=path, width=320, height=240, dpi=100, ray=False
        )

    assert exc_info.value.category is ErrorCategory.INVALID_ARGUMENT
    assert adapter.rendered == []


def test_render_uses_verified_temp_png_and_atomically_replaces_target(
    tmp_path: Path,
) -> None:
    target = tmp_path / "nested" / "view.png"
    adapter = RecordingAdapter()

    result = EngineService(adapter).render_png(
        path=str(target), width=320, height=240, dpi=100, ray=False
    )

    assert result.path == str(target)
    assert target.read_bytes() == PNG
    assert adapter.rendered[0] != str(target)
    assert Path(adapter.rendered[0]).parent == target.parent
    assert not Path(adapter.rendered[0]).exists()


class BrokenRenderAdapter(RecordingAdapter):
    def __init__(self, *, returns_without_output: bool = False) -> None:
        super().__init__()
        self.returns_without_output = returns_without_output

    def render_png(
        self, path: str, width: int, height: int, dpi: int, ray: bool
    ) -> None:
        self.rendered.append(path)
        if self.returns_without_output:
            Path(path).unlink(missing_ok=True)
            return
        raise RuntimeError("secret backend diagnostic")


@pytest.mark.parametrize("returns_without_output", [False, True])
def test_render_failure_never_reports_success_or_replaces_stale_output(
    tmp_path: Path, returns_without_output: bool
) -> None:
    target = tmp_path / "view.png"
    target.write_bytes(b"stale")
    adapter = BrokenRenderAdapter(returns_without_output=returns_without_output)

    with pytest.raises(EngineError) as exc_info:
        EngineService(adapter).render_png(
            path=str(target), width=320, height=240, dpi=100, ray=False
        )

    assert exc_info.value.category is ErrorCategory.BACKEND_FAILURE
    assert "secret backend diagnostic" not in exc_info.value.message
    assert "secret backend diagnostic" not in repr(exc_info.value.details)
    assert target.read_bytes() == b"stale"
    assert not Path(adapter.rendered[0]).exists()


@pytest.mark.parametrize("suffix", [".pse", ".psw", ".PSE"])
def test_session_paths_are_absolute_and_use_safe_extensions(
    tmp_path: Path, suffix: str
) -> None:
    adapter = RecordingAdapter()
    engine = EngineService(adapter)
    session = tmp_path / "nested" / f"state{suffix}"

    saved = engine.save_session(str(session))
    restored = engine.restore_session(str(session))

    assert saved.path == str(session)
    assert restored.path == str(session)
    assert len(adapter.saved) == 1
    assert adapter.saved[0] != str(session)
    assert Path(adapter.saved[0]).parent == session.parent
    assert not Path(adapter.saved[0]).exists()
    assert session.read_bytes() == b"session"
    assert adapter.restored == [str(session)]


class BrokenSessionSaveAdapter(RecordingAdapter):
    def save_session(self, path: str) -> None:
        self.saved.append(path)
        Path(path).unlink(missing_ok=True)


def test_session_save_requires_real_output_and_preserves_stale_target(
    tmp_path: Path,
) -> None:
    target = tmp_path / "state.pse"
    target.write_bytes(b"stale")
    adapter = BrokenSessionSaveAdapter()

    with pytest.raises(EngineError) as exc_info:
        EngineService(adapter).save_session(str(target))

    assert exc_info.value.category is ErrorCategory.BACKEND_FAILURE
    assert target.read_bytes() == b"stale"
    assert not Path(adapter.saved[0]).exists()


def test_session_rejects_relative_unsafe_and_missing_restore_paths(
    tmp_path: Path,
) -> None:
    engine = EngineService(RecordingAdapter())

    with pytest.raises(EngineError) as relative_error:
        engine.save_session("state.pse")
    with pytest.raises(EngineError) as unsafe_error:
        engine.save_session(str(tmp_path / "state.pml"))
    with pytest.raises(EngineError) as missing_error:
        engine.restore_session(str(tmp_path / "missing.pse"))

    assert relative_error.value.category is ErrorCategory.INVALID_ARGUMENT
    assert unsafe_error.value.category is ErrorCategory.INVALID_ARGUMENT
    assert missing_error.value.category is ErrorCategory.NOT_FOUND


class ExplodingAdapter(RecordingAdapter):
    def get_object_names(self) -> list[str]:
        raise ValueError("sensitive backend detail")


def test_backend_exceptions_become_safe_engine_errors() -> None:
    with pytest.raises(EngineError) as exc_info:
        EngineService(ExplodingAdapter()).list_objects()

    error = exc_info.value
    assert error.category is ErrorCategory.BACKEND_FAILURE
    assert error.details == {"operation": "objects.list"}
    assert "sensitive backend detail" not in error.message
