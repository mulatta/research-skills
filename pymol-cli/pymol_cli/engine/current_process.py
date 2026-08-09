# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Adapter for PyMOL's current process `pymol.cmd` object."""

from __future__ import annotations

import importlib
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Protocol

from pymol_cli.engine.cancellation import request_is_cancelled
from pymol_cli.engine.errors import EngineError, ErrorCategory
from pymol_cli.engine.validation import (
    require_exact_runtime_name,
    require_exact_runtime_object_name,
    structure_format_for_path,
)

_LOGGER = logging.getLogger(__name__)
_PML_OUTPUT_LOCK = threading.Lock()


class _RenderProcess(Protocol):
    returncode: int | None

    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...


class CurrentProcessPyMOLAdapter:
    """Wrap the global PyMOL command API inside a GUI or headless PyMOL process."""

    def __init__(
        self,
        cmd: Any | None = None,
        *,
        headless_render_worker: bool | None = None,
    ) -> None:
        self._cmd = _import_current_cmd() if cmd is None else cmd
        self._headless_render_worker = (
            cmd is None if headless_render_worker is None else headless_render_worker
        )
        self._render_process: _RenderProcess | None = None
        self._render_process_lock = threading.Lock()
        self._render_cancelled = False
        self._render_cancel_generation = 0
        self._direct_render_active = False

    @property
    def cmd(self) -> Any:
        return self._cmd

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

    def create_selection(self, name: str, expression: str) -> None:
        require_exact_runtime_name(
            self.cmd, name, argument="name", operation="selection.create"
        )
        self.cmd.select(name, expression)

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

    def show_ball_and_stick(
        self, selection: str, stick_radius: float, sphere_scale: float
    ) -> None:
        self.cmd.show("sticks", selection)
        self.cmd.show("spheres", selection)
        self.cmd.set("stick_radius", stick_radius, selection)
        self.cmd.set("sphere_scale", sphere_scale, selection)

    def show_polar_contacts(
        self,
        name: str,
        selection1: str,
        selection2: str,
        cutoff: float,
        color: str,
        dash_width: float,
    ) -> None:
        require_exact_runtime_name(
            self.cmd, name, argument="name", operation="scene.polar_contacts"
        )
        self.cmd.distance(name, selection1, selection2, cutoff=cutoff, mode=2)
        self.cmd.hide("labels", name)
        self.cmd.set("dash_color", color, name)
        self.cmd.set("dash_width", dash_width, name)

    def set_background(self, color: str, opaque: bool) -> None:
        self.cmd.bg_color(color)
        self.cmd.set("opaque_background", int(opaque))
        self.cmd.set("ray_opaque_background", int(opaque))

    def render_png(
        self, path: str, width: int, height: int, dpi: int, ray: bool
    ) -> int:
        """Render from a headless snapshot, not the GUI framebuffer.

        GUI OpenGL framebuffers can be black or unavailable when the display is
        asleep, hidden, or called from a non-GUI thread. Snapshotting the current
        session and rendering it in a fresh `pymol -cq` worker makes PNG output
        independent of GUI visibility and keeps ray tracing out of the live GUI
        process.
        """
        with self._render_process_lock:
            if self._render_cancelled or request_is_cancelled():
                raise _render_cancelled_error()
            if self._render_process is not None or self._direct_render_active:
                raise EngineError(
                    ErrorCategory.BACKEND_FAILURE,
                    "another render is already running",
                    {"operation": "render.png"},
                )
            render_generation = self._render_cancel_generation
            if not self._headless_render_worker:
                self._direct_render_active = True
        if not self._headless_render_worker:
            try:
                self.cmd.png(path, width=width, height=height, dpi=dpi, ray=int(ray))
            except Exception as exc:
                if self._render_was_cancelled(render_generation):
                    raise _render_cancelled_error() from exc
                raise
            finally:
                with self._render_process_lock:
                    self._direct_render_active = False
            self._require_render_not_cancelled(render_generation)
            return render_generation
        pymol = shutil.which("pymol")
        worker_command = (
            [pymol] if pymol is not None else [sys.executable, "-m", "pymol"]
        )
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="pymol-render-") as tmpdir:
            tmp = Path(tmpdir)
            state = tmp / "snapshot.pse"
            script = tmp / "render.py"
            self.cmd.save(str(state), format="pse")
            self._require_render_not_cancelled(render_generation)
            script.write_text(
                "from pymol import cmd\n"
                f"cmd.load({str(state)!r}, format='pse')\n"
                f"cmd.viewport({width!r}, {height!r})\n"
                "cmd.refresh()\n"
                f"cmd.png({str(output_path)!r}, width={width!r}, height={height!r}, "
                f"dpi={dpi!r}, ray={int(ray)!r})\n"
                "cmd.quit()\n",
                encoding="utf-8",
            )
            command = [*worker_command, "-cq", str(script)]
            process: _RenderProcess | None = None
            try:
                process = subprocess.Popen(command)
                with self._render_process_lock:
                    cancelled = self._render_cancelled or (
                        self._render_cancel_generation != render_generation
                    )
                    already_running = (
                        self._render_process is not None or self._direct_render_active
                    )
                    if not cancelled and not already_running:
                        self._render_process = process
                if cancelled or already_running:
                    _terminate_render_process(process)
                    if cancelled:
                        raise _render_cancelled_error()
                    raise EngineError(
                        ErrorCategory.BACKEND_FAILURE,
                        "another render is already running",
                        {"operation": "render.png"},
                    )
                _wait_for_render_process(process, command=command, timeout=300)
                self._require_render_not_cancelled(render_generation)
            except subprocess.TimeoutExpired as exc:
                raise EngineError(
                    ErrorCategory.OPERATION_TIMEOUT,
                    "headless PyMOL render timed out",
                    {"operation": "render.png"},
                ) from exc
            except subprocess.CalledProcessError as exc:
                if self._render_was_cancelled(render_generation):
                    raise _render_cancelled_error() from exc
                raise EngineError(
                    ErrorCategory.BACKEND_FAILURE,
                    "headless PyMOL render failed",
                    {"operation": "render.png"},
                ) from exc
            except OSError as exc:
                raise EngineError(
                    ErrorCategory.BACKEND_FAILURE,
                    "headless PyMOL render failed",
                    {"operation": "render.png"},
                ) from exc
            finally:
                if process is not None:
                    with self._render_process_lock:
                        if self._render_process is process:
                            self._render_process = None
        return render_generation

    def publish_render(self, source: str, target: str, token: object) -> None:
        """Publish only while cancellation state still matches this render."""
        with self._render_process_lock:
            if (
                self._render_cancelled
                or request_is_cancelled()
                or not isinstance(token, int)
                or isinstance(token, bool)
                or self._render_cancel_generation != token
            ):
                raise _render_cancelled_error()
            os.replace(source, target)

    def cancel_active_render(self) -> None:
        """Cancel one request without disabling later render requests."""
        self._cancel_render(permanent=False)

    def cancel_render(self) -> None:
        """Cancel rendering permanently during GUI or engine shutdown."""
        self._cancel_render(permanent=True)

    def _cancel_render(self, *, permanent: bool) -> None:
        with self._render_process_lock:
            self._render_cancel_generation += 1
            if permanent:
                self._render_cancelled = True
            process = self._render_process
            direct_render_active = self._direct_render_active
        if process is not None:
            _terminate_render_process(process)
        if direct_render_active:
            interrupt = getattr(self.cmd, "interrupt", None)
            if callable(interrupt):
                try:
                    interrupt()
                except Exception:
                    _LOGGER.exception("PyMOL render interrupt failed")

    def _render_was_cancelled(self, generation: int) -> bool:
        with self._render_process_lock:
            return (
                self._render_cancelled
                or request_is_cancelled()
                or self._render_cancel_generation != generation
            )

    def _require_render_not_cancelled(self, generation: int) -> None:
        if self._render_was_cancelled(generation):
            raise _render_cancelled_error()

    def save_session(self, path: str) -> None:
        self.cmd.save(path, format="pse")

    def restore_session(self, path: str) -> None:
        self.cmd.load(path, format="pse")

    def execute_pml(self, command: str) -> Any:
        return _execute_pml_lines(self.cmd, command)

    def clear(self) -> None:
        self.cmd.delete("all")


def _execute_pml_lines(cmd: Any, command: str) -> Any:
    lines = [line for line in command.splitlines() if line.strip()]
    result: Any = None
    for line_number, line in enumerate(lines, start=1):
        _take_pymol_feedback(cmd)
        result, output = _execute_pml_line(cmd, line)
        feedback = _take_pymol_feedback(cmd)
        if (
            _pml_result_is_error(result)
            or any(_feedback_is_error(message) for message in feedback)
            or any(_feedback_is_error(message) for message in output.splitlines())
        ):
            raise EngineError(
                ErrorCategory.BACKEND_FAILURE,
                "unsafe.execute_pml failed in the PyMOL backend",
                {"operation": "unsafe.execute_pml", "line": line_number},
            )
    return result


def _execute_pml_line(cmd: Any, command: str) -> tuple[Any, str]:
    """Capture C-level feedback because PyMOL discards command failure status."""
    result: Any = None
    with _PML_OUTPUT_LOCK:
        sys.stdout.flush()
        sys.stderr.flush()
        saved_stdout = os.dup(1)
        saved_stderr = os.dup(2)
        try:
            with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
                os.dup2(stdout.fileno(), 1)
                os.dup2(stderr.fileno(), 2)
                try:
                    result = cmd.do(command)
                finally:
                    sys.stdout.flush()
                    sys.stderr.flush()
                    os.dup2(saved_stdout, 1)
                    os.dup2(saved_stderr, 2)
                stdout.seek(0)
                stderr.seek(0)
                stdout_output = stdout.read()
                stderr_output = stderr.read()
            _replay_pml_output(saved_stdout, stdout_output)
            _replay_pml_output(saved_stderr, stderr_output)
        finally:
            os.close(saved_stdout)
            os.close(saved_stderr)
    output = stdout_output + b"\n" + stderr_output
    return result, output.decode(errors="replace")


def _replay_pml_output(file_descriptor: int, output: bytes) -> None:
    remaining = memoryview(output)
    try:
        while remaining:
            written = os.write(file_descriptor, remaining)
            remaining = remaining[written:]
    except OSError:
        _LOGGER.debug("PyMOL output destination closed before replay")


def _take_pymol_feedback(cmd: Any) -> list[str]:
    get_feedback = getattr(cmd, "_get_feedback", None)
    if not callable(get_feedback):
        return []
    feedback = get_feedback()
    if not isinstance(feedback, list):
        return []
    return [str(message) for message in feedback]


def _pml_result_is_error(result: Any) -> bool:
    return isinstance(result, int) and not isinstance(result, bool) and result < 0


def _feedback_is_error(message: str) -> bool:
    prefix = message.lstrip().split(":", 1)[0]
    return prefix == "Error" or prefix.endswith("-Error")


def _render_cancelled_error() -> EngineError:
    return EngineError(
        ErrorCategory.BACKEND_FAILURE,
        "headless PyMOL render was cancelled",
        {"operation": "render.png"},
    )


def _wait_for_render_process(
    process: _RenderProcess, *, command: list[str], timeout: float
) -> None:
    deadline = time.monotonic() + timeout
    while True:
        return_code = process.poll()
        if return_code is not None:
            if return_code != 0:
                raise subprocess.CalledProcessError(return_code, command)
            return
        if time.monotonic() >= deadline:
            _terminate_render_process(process)
            raise subprocess.TimeoutExpired(command, timeout)
        # Qt work is pumped only on its owner thread. Lifecycle pump rejects
        # reentrant RPC dispatch while still allowing repaint/close events.
        _process_qt_events()
        time.sleep(0.01)


def _terminate_render_process(process: _RenderProcess) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
    except OSError:
        return
    try:
        process.wait(timeout=1.0)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        process.kill()
    except OSError:
        return
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        pass


def _process_qt_events() -> None:
    try:
        qt_module: Any = importlib.import_module("pymol.Qt")
    except ImportError:
        return
    qt_core = qt_module.QtCore
    app = qt_core.QCoreApplication.instance()
    if app is None or qt_core.QThread.currentThread() != app.thread():
        return
    try:
        app.processEvents()
    except RuntimeError:
        # Qt objects may disappear while a window-close event is being handled.
        return


def _import_current_cmd() -> Any:
    try:
        pymol: Any = importlib.import_module("pymol")
    except ImportError as exc:
        raise EngineError(
            ErrorCategory.UNSUPPORTED_CAPABILITY,
            "pymol.cmd is not available in this process",
        ) from exc
    return pymol.cmd
