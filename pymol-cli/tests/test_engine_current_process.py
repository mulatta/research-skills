# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import ast
import subprocess
from pathlib import Path
from typing import Any

import pytest

from pymol_cli.engine import current_process
from pymol_cli.engine.current_process import CurrentProcessPyMOLAdapter
from pymol_cli.engine.errors import EngineError


class FakeCmd:
    def __init__(self) -> None:
        self.objects: list[str] = []
        self.atom_count = 0
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.legal_name_suffix = ""

    def get_version(self) -> tuple[str]:
        return ("3.1.0",)

    def get_legal_name(self, name: str) -> str:
        self.calls.append(("get_legal_name", (name,), {}))
        return f"{name}{self.legal_name_suffix}"

    def get_names(self, mode: str) -> list[str]:
        self.calls.append(("get_names", (mode,), {}))
        return self.objects

    def count_atoms(self, selection: str) -> int:
        self.calls.append(("count_atoms", (selection,), {}))
        return self.atom_count

    def load(
        self,
        path: str,
        object_name: str | None = None,
        *,
        format: str | None = None,
    ) -> None:
        self.calls.append(
            (
                "load",
                (path,) if object_name is None else (path, object_name),
                {"format": format},
            )
        )
        if object_name is not None:
            self.objects = [object_name]
            self.atom_count = 2

    def show(self, representation: str, selection: str) -> None:
        self.calls.append(("show", (representation, selection), {}))

    def hide(self, representation: str, selection: str) -> None:
        self.calls.append(("hide", (representation, selection), {}))

    def color(self, color: str, selection: str) -> None:
        self.calls.append(("color", (color, selection), {}))

    def zoom(self, selection: str, *, buffer: float) -> None:
        self.calls.append(("zoom", (selection,), {"buffer": buffer}))

    def png(self, path: str, *, width: int, height: int, dpi: int, ray: int) -> None:
        self.calls.append(
            ("png", (path,), {"width": width, "height": height, "dpi": dpi, "ray": ray})
        )

    def save(self, path: str, *, format: str | None = None) -> None:
        self.calls.append(("save", (path,), {"format": format}))

    def do(self, command: str) -> Any:
        self.calls.append(("do", (command,), {}))
        return "ok"

    def delete(self, selection: str) -> None:
        self.calls.append(("delete", (selection,), {}))
        self.objects = []
        self.atom_count = 0


class _RenderProcess:
    def __init__(self, return_codes: list[int | None]) -> None:
        self._return_codes = iter(return_codes)
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        try:
            self.returncode = next(self._return_codes)
        except StopIteration:
            pass
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            raise subprocess.TimeoutExpired(
                "pymol", 0.0 if timeout is None else timeout
            )
        return self.returncode


def test_render_worker_pumps_qt_events_instead_of_blocking_owner_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cmd = FakeCmd()
    adapter = CurrentProcessPyMOLAdapter(cmd=cmd, headless_render_worker=True)
    output = tmp_path / "view.png"
    process = _RenderProcess([None, None, 0])
    qt_pumps: list[None] = []

    monkeypatch.setattr(current_process.shutil, "which", lambda _name: "/bin/pymol")
    monkeypatch.setattr(current_process.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        current_process, "_process_qt_events", lambda: qt_pumps.append(None)
    )

    def start_worker(command: list[str]) -> _RenderProcess:
        script = Path(command[-1]).read_text(encoding="utf-8")
        png_line = next(
            line for line in script.splitlines() if line.startswith("cmd.png(")
        )
        rendered_path = Path(
            ast.literal_eval(png_line.removeprefix("cmd.png(").split(", width=", 1)[0])
        )
        rendered_path.write_bytes(b"\x89PNG\r\n\x1a\nimage")
        return process

    monkeypatch.setattr(current_process.subprocess, "Popen", start_worker)

    adapter.render_png(str(output), 320, 240, 100, True)

    assert output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert len(qt_pumps) == 2
    assert not process.terminated


def test_render_worker_timeout_terminates_child_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _RenderProcess([None])
    monotonic_values = iter([0.0, 1.0])
    monkeypatch.setattr(
        current_process.time, "monotonic", lambda: next(monotonic_values)
    )

    with pytest.raises(subprocess.TimeoutExpired):
        current_process._wait_for_render_process(
            process,
            command=["pymol"],
            timeout=0.5,
        )

    assert process.terminated


def test_render_registration_observes_concurrent_shutdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = CurrentProcessPyMOLAdapter(cmd=FakeCmd(), headless_render_worker=True)
    process = _RenderProcess([None])
    monkeypatch.setattr(current_process.shutil, "which", lambda _name: "/bin/pymol")

    def start_worker(_command: list[str]) -> _RenderProcess:
        adapter.cancel_render()
        return process

    monkeypatch.setattr(current_process.subprocess, "Popen", start_worker)

    with pytest.raises(EngineError, match="render was cancelled"):
        adapter.render_png(str(tmp_path / "view.png"), 320, 240, 100, True)

    assert process.terminated


def test_render_worker_uses_current_python_when_pymol_is_absent_from_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cmd = FakeCmd()
    adapter = CurrentProcessPyMOLAdapter(cmd=cmd, headless_render_worker=True)
    process = _RenderProcess([0])
    commands: list[list[str]] = []
    monkeypatch.setattr(current_process.shutil, "which", lambda _name: None)

    def start_worker(command: list[str]) -> _RenderProcess:
        commands.append(command)
        return process

    monkeypatch.setattr(current_process.subprocess, "Popen", start_worker)

    adapter.render_png(str(tmp_path / "view.png"), 320, 240, 100, True)

    assert commands[0][:3] == [current_process.sys.executable, "-m", "pymol"]
    assert not any(name == "png" for name, _args, _kwargs in cmd.calls)


def test_registered_render_reports_shutdown_cancellation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = CurrentProcessPyMOLAdapter(cmd=FakeCmd(), headless_render_worker=True)
    process = _RenderProcess([None])
    monkeypatch.setattr(current_process.shutil, "which", lambda _name: "/bin/pymol")
    monkeypatch.setattr(current_process.subprocess, "Popen", lambda _command: process)
    monkeypatch.setattr(current_process, "_process_qt_events", adapter.cancel_render)
    monkeypatch.setattr(current_process.time, "sleep", lambda _seconds: None)

    with pytest.raises(EngineError, match="render was cancelled"):
        adapter.render_png(str(tmp_path / "view.png"), 320, 240, 100, True)

    assert process.terminated


def test_request_cancellation_does_not_poison_future_renders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = CurrentProcessPyMOLAdapter(cmd=FakeCmd(), headless_render_worker=True)
    cancelled_process = _RenderProcess([None])
    completed_process = _RenderProcess([0])
    processes = iter([cancelled_process, completed_process])
    starts = 0
    monkeypatch.setattr(current_process.shutil, "which", lambda _name: "/bin/pymol")

    def start_worker(_command: list[str]) -> _RenderProcess:
        nonlocal starts
        starts += 1
        process = next(processes)
        if starts == 1:
            adapter.cancel_active_render()
        return process

    monkeypatch.setattr(current_process.subprocess, "Popen", start_worker)

    with pytest.raises(EngineError, match="render was cancelled"):
        adapter.render_png(str(tmp_path / "cancelled.png"), 320, 240, 100, True)
    adapter.render_png(str(tmp_path / "completed.png"), 320, 240, 100, True)

    assert cancelled_process.terminated
    assert not completed_process.terminated


def test_cancelled_render_cannot_replace_existing_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = CurrentProcessPyMOLAdapter(cmd=FakeCmd(), headless_render_worker=True)
    process = _RenderProcess([0])
    temporary = tmp_path / "temporary.png"
    target = tmp_path / "view.png"
    target.write_bytes(b"existing")
    monkeypatch.setattr(current_process.shutil, "which", lambda _name: "/bin/pymol")

    def start_worker(_command: list[str]) -> _RenderProcess:
        temporary.write_bytes(b"\x89PNG\r\n\x1a\nnew")
        return process

    monkeypatch.setattr(current_process.subprocess, "Popen", start_worker)

    token = adapter.render_png(str(temporary), 320, 240, 100, True)
    adapter.cancel_active_render()

    with pytest.raises(EngineError, match="render was cancelled"):
        adapter.publish_render(str(temporary), str(target), token)

    assert target.read_bytes() == b"existing"


def test_adapter_rejects_name_that_runtime_would_rewrite() -> None:
    cmd = FakeCmd()
    cmd.legal_name_suffix = "_"
    adapter = CurrentProcessPyMOLAdapter(cmd=cmd)

    with pytest.raises(EngineError, match="would rewrite object_name"):
        adapter.load_structure("model.pdb", "future_keyword")

    assert not any(name == "load" for name, _args, _kwargs in cmd.calls)


class _FeedbackCmd(FakeCmd):
    def __init__(self) -> None:
        super().__init__()
        self.feedback: list[str] = []

    def do(self, command: str) -> None:
        self.calls.append(("do", (command,), {}))
        if command == "bad command":
            self.feedback.append("Parser-Error: invalid command")

    def _get_feedback(self) -> list[str]:
        feedback = self.feedback
        self.feedback = []
        return feedback


def test_pml_execution_stops_after_feedback_error() -> None:
    cmd = _FeedbackCmd()
    adapter = CurrentProcessPyMOLAdapter(cmd=cmd)

    with pytest.raises(EngineError) as exc_info:
        adapter.execute_pml("good command\nbad command\nnever executed")

    assert exc_info.value.details == {
        "operation": "unsafe.execute_pml",
        "line": 2,
    }
    assert [args[0] for name, args, _kwargs in cmd.calls if name == "do"] == [
        "good command",
        "bad command",
    ]


class _NegativeStatusCmd(FakeCmd):
    def do(self, command: str) -> int:
        self.calls.append(("do", (command,), {}))
        return -1


def test_pml_execution_rejects_negative_backend_status() -> None:
    adapter = CurrentProcessPyMOLAdapter(cmd=_NegativeStatusCmd())

    with pytest.raises(EngineError, match="PyMOL backend"):
        adapter.execute_pml("bad command")
