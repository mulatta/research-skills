# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import argparse
import os
import secrets
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, BinaryIO, Protocol

from pymol_cli.cli.common import PROCESS_POLL_INTERVAL, emit, resolve_local_path
from pymol_cli.cli.errors import CLIError
from pymol_cli.lifecycle.process import (
    get_process_identity,
    is_process_alive_posix,
    is_process_alive_windows,
    process_identity_matches,
    terminate_linux_process,
    terminate_windows_process,
)
from pymol_cli.rpc.descriptor import EngineDescriptor, open_private_lock_file


class ManagedProcess(Protocol):
    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...


def open_engine_log(path: Path) -> BinaryIO:
    """Open append-only diagnostics without exposing bootstrap secrets."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open_private_lock_file(path)
    handle.seek(0, os.SEEK_END)
    return handle


def build_engine_serve_command(
    *,
    descriptor_path: Path,
    token: str,
    mode: str,
    pymol_command: str = "pymol",
    instance_id: str | None = None,
) -> list[str]:
    launch_instance_id = instance_id or secrets.token_hex(16)
    if mode in {"gui", "headless"}:
        bootstrap = write_pymol_bootstrap(
            descriptor_path=descriptor_path,
            token=token,
            background=mode == "gui",
            instance_id=launch_instance_id,
        )
        flag = "-cq" if mode == "headless" else "-q"
        return [pymol_command, flag, str(bootstrap)]
    script = Path(sys.argv[0]).with_name("pymol-engine")
    command = (
        [str(script)]
        if script.exists()
        else [sys.executable, "-m", "pymol_cli.lifecycle.serve"]
    )
    command.append(f"--{mode}")
    command.extend(
        [
            "--descriptor",
            str(descriptor_path),
            "--token",
            token,
            "--instance-id",
            launch_instance_id,
        ]
    )
    return command


def write_pymol_bootstrap(
    *,
    descriptor_path: Path,
    token: str,
    background: bool,
    instance_id: str | None = None,
) -> Path:
    from pymol_cli.rpc.descriptor import create_private_temp_file

    descriptor_path.parent.mkdir(parents=True, exist_ok=True)
    fd, bootstrap = create_private_temp_file(
        descriptor_path.parent,
        prefix=f".{descriptor_path.stem}.",
        suffix=".bootstrap.py",
    )
    package_root = Path(__file__).resolve().parents[2]
    function_name = (
        "start_current_process_background" if background else "serve_current_process"
    )
    launch_instance_id = instance_id or secrets.token_hex(16)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(
                "import os\n"
                "import sys\n"
                "from pathlib import Path\n"
                f"sys.path.insert(0, {str(package_root)!r})\n"
                f"from pymol_cli.lifecycle.serve import {function_name}\n"
                f"{function_name}(descriptor_path=Path({str(descriptor_path)!r}), "
                f"token={token!r}, instance_id={launch_instance_id!r}, "
                "supervisor_pid=os.getppid())\n"
            )
    except BaseException:
        bootstrap.unlink(missing_ok=True)
        raise
    return bootstrap


def command_bootstrap_path(command: Sequence[str], *, mode: str) -> Path | None:
    if mode not in {"gui", "headless"} or not command:
        return None
    return Path(command[-1])


def remove_bootstrap_file(path: Path, *, timeout: float = 1.0) -> bool:
    """Retry briefly because Windows script readers can delay deletion."""
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        try:
            path.unlink(missing_ok=True)
            return True
        except OSError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(PROCESS_POLL_INTERVAL)


def is_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return _is_process_alive_windows(pid)
    return is_process_alive_posix(pid)


def _is_process_alive_windows(pid: int) -> bool:
    return is_process_alive_windows(pid)


def terminate_launched_process(proc: ManagedProcess, *, grace: float = 1.0) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
    except (OSError, ProcessLookupError):
        return
    try:
        proc.wait(timeout=max(0.0, grace))
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        proc.kill()
    except (OSError, ProcessLookupError):
        return
    try:
        proc.wait(timeout=max(0.0, grace))
    except subprocess.TimeoutExpired:
        pass


def terminate_process_by_pid(
    pid: int, *, expected_identity: str | None, timeout: float
) -> bool:
    """Terminate only descriptor-verified process occupant, never PID alone."""
    if pid <= 0 or pid == os.getpid() or expected_identity is None:
        return False
    actual_identity = get_process_identity(pid)
    if actual_identity is None:
        return not is_process_alive(pid)
    if actual_identity != expected_identity:
        return True  # Expected process exited and PID now belongs elsewhere.
    if os.name == "nt":
        stopped = terminate_windows_process(
            pid, expected_identity=expected_identity, timeout=timeout
        )
        if stopped:
            return True
        replacement_identity = get_process_identity(pid)
        if replacement_identity is None:
            return not is_process_alive(pid)
        return replacement_identity != expected_identity
    if sys.platform.startswith("linux"):
        return terminate_linux_process(
            pid, expected_identity=expected_identity, timeout=timeout
        )
    # macOS exposes no process-handle signal primitive equivalent to pidfd.
    # Refuse PID-only signals rather than race a reused process identifier.
    return False


def cleanup_failed_engine_launch(
    process: subprocess.Popen[Any],
    *,
    descriptor_path: Path,
    instance_id: str,
    token: str,
    timeout: float,
) -> bool:
    """Stop only launch-owned processes; preserve descriptor when safety is unknown."""
    from pymol_cli.rpc.client import EngineClient, EngineClientError

    descriptor = read_matching_launch_descriptor(
        descriptor_path, instance_id=instance_id
    )
    if descriptor is not None and descriptor.token == token:
        try:
            with EngineClient.connect(
                descriptor.host,
                descriptor.port,
                token=descriptor.token,
                timeout=min(1.0, max(0.1, timeout)),
                expected_instance_id=descriptor.instance_id,
            ) as client:
                client.shutdown()
        except (EngineClientError, OSError, TimeoutError, ValueError):
            pass
        deadline = time.monotonic() + min(1.0, max(0.0, timeout))
        while descriptor_process_is_alive(descriptor) and time.monotonic() < deadline:
            time.sleep(PROCESS_POLL_INTERVAL)

    terminate_launched_process(process, grace=min(1.0, timeout))
    latest = read_matching_launch_descriptor(descriptor_path, instance_id=instance_id)
    if latest is None or latest.token != token:
        return True
    if latest.pid != process.pid and descriptor_process_is_alive(latest):
        terminate_process_by_pid(
            latest.pid,
            expected_identity=latest.process_identity,
            timeout=max(0.1, timeout),
        )
    if descriptor_process_is_alive(latest):
        return False
    from pymol_cli.lifecycle.serve import remove_descriptor

    remove_descriptor(descriptor_path, instance_id=instance_id)
    return True


def read_matching_launch_descriptor(
    descriptor_path: Path, *, instance_id: str
) -> EngineDescriptor | None:
    from pymol_cli.rpc.descriptor import read_descriptor

    try:
        descriptor = read_descriptor(descriptor_path)
    except (KeyError, OSError, TypeError, ValueError):
        return None
    if descriptor.instance_id != instance_id:
        return None
    return descriptor


def descriptor_process_is_alive(descriptor: EngineDescriptor) -> bool:
    if not is_process_alive(descriptor.pid):
        return False
    if descriptor.process_identity is None:
        return True
    return process_identity_matches(descriptor.pid, descriptor.process_identity)


def remove_stale_descriptor_if_dead(descriptor_path: Path) -> bool:
    from pymol_cli.rpc.descriptor import (
        _read_descriptor_unlocked,
        descriptor_mutation_lock,
    )

    with descriptor_mutation_lock(descriptor_path):
        try:
            descriptor = _read_descriptor_unlocked(descriptor_path)
        except FileNotFoundError:
            return True
        except (KeyError, OSError, TypeError, ValueError):
            descriptor_path.unlink(missing_ok=True)
            return True
        if descriptor_process_is_alive(descriptor):
            return False
        descriptor_path.unlink(missing_ok=True)
        return True


def default_engine_log_path(descriptor_path: Path) -> Path:
    return descriptor_path.with_suffix(".log")


def cmd_engine_start(ns: argparse.Namespace) -> None:
    from pymol_cli.lifecycle.lock import EngineStartLocked, engine_start_lock
    from pymol_cli.lifecycle.paths import default_descriptor_path

    descriptor_path = resolve_local_path(ns.descriptor or default_descriptor_path())
    try:
        with engine_start_lock(descriptor_path):
            _cmd_engine_start_locked(ns, descriptor_path=descriptor_path)
    except EngineStartLocked as exc:
        raise CLIError(str(exc)) from exc


def _cmd_engine_start_locked(ns: argparse.Namespace, *, descriptor_path: Path) -> None:
    from pymol_cli.rpc.client import EngineClient, EngineClientError
    from pymol_cli.rpc.descriptor import read_descriptor

    if descriptor_path.exists():
        try:
            running_descriptor = read_descriptor(descriptor_path)
            with EngineClient.connect(
                running_descriptor.host,
                running_descriptor.port,
                token=running_descriptor.token,
                timeout=ns.timeout,
                expected_instance_id=running_descriptor.instance_id,
            ):
                current_descriptor = read_descriptor(descriptor_path)
                if current_descriptor.instance_id != running_descriptor.instance_id:
                    raise EngineClientError(
                        "engine descriptor changed during connection"
                    )
                emit(
                    {
                        "ok": True,
                        "already_running": True,
                        "descriptor": str(descriptor_path),
                        "mode": running_descriptor.mode,
                        "pid": running_descriptor.pid,
                    }
                    if ns.json
                    else f"engine already running: {descriptor_path}",
                    use_json=ns.json,
                )
                return
        except (
            EngineClientError,
            KeyError,
            OSError,
            TimeoutError,
            TypeError,
            ValueError,
        ):
            if not remove_stale_descriptor_if_dead(descriptor_path):
                raise CLIError(
                    f"engine descriptor exists but is not reachable: {descriptor_path}"
                )
    mode = (
        "embedded"
        if ns.embedded
        else "current-process"
        if ns.current_process
        else "headless"
        if ns.headless
        else "gui"
    )
    token = ns.token or secrets.token_urlsafe(32)
    instance_id = secrets.token_hex(16)
    log_path = resolve_local_path(ns.log or default_engine_log_path(descriptor_path))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor_path.parent.mkdir(parents=True, exist_ok=True)
    command = build_engine_serve_command(
        descriptor_path=descriptor_path,
        token=token,
        mode=mode,
        pymol_command=ns.pymol_command,
        instance_id=instance_id,
    )
    bootstrap_path = command_bootstrap_path(command, mode=mode)
    proc: subprocess.Popen[Any] | None = None
    try:
        with open_engine_log(log_path) as log_file:
            popen_options: dict[str, Any] = {
                "stdin": subprocess.DEVNULL,
                "stdout": log_file,
                "stderr": subprocess.STDOUT,
                "close_fds": True,
            }
            if os.name == "nt":
                popen_options["creationflags"] = getattr(
                    subprocess, "DETACHED_PROCESS", 0x00000008
                ) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            else:
                popen_options["start_new_session"] = True
            proc = subprocess.Popen(command, **popen_options)
        deadline = time.monotonic() + ns.timeout
        while time.monotonic() < deadline:
            launch_descriptor = read_matching_launch_descriptor(
                descriptor_path,
                instance_id=instance_id,
            )
            if launch_descriptor is not None and launch_descriptor.token == token:
                try:
                    remaining = max(0.05, deadline - time.monotonic())
                    with EngineClient.connect(
                        launch_descriptor.host,
                        launch_descriptor.port,
                        token=launch_descriptor.token,
                        timeout=min(0.5, remaining),
                        expected_instance_id=launch_descriptor.instance_id,
                    ):
                        ready_descriptor = read_matching_launch_descriptor(
                            descriptor_path,
                            instance_id=instance_id,
                        )
                        if (
                            ready_descriptor is None
                            or ready_descriptor.token != token
                            or ready_descriptor.port != launch_descriptor.port
                            or ready_descriptor.pid != launch_descriptor.pid
                            or ready_descriptor.process_identity
                            != launch_descriptor.process_identity
                        ):
                            raise EngineClientError(
                                "engine descriptor changed during readiness check"
                            )
                        emit(
                            {
                                "ok": True,
                                "descriptor": str(descriptor_path),
                                "log": str(log_path),
                                "mode": ready_descriptor.mode,
                                "pid": ready_descriptor.pid,
                            }
                            if ns.json
                            else f"engine started: {descriptor_path}",
                            use_json=ns.json,
                        )
                        return
                except (
                    EngineClientError,
                    KeyError,
                    OSError,
                    TimeoutError,
                    TypeError,
                    ValueError,
                ):
                    pass
            # A Windows shim or configured wrapper may exit after spawning PyMOL.
            # Launch nonce, not direct parent topology, owns readiness.
            time.sleep(PROCESS_POLL_INTERVAL)
        cleaned = cleanup_failed_engine_launch(
            proc,
            descriptor_path=descriptor_path,
            instance_id=instance_id,
            token=token,
            timeout=ns.timeout,
        )
        detail = "" if cleaned else "; live descriptor preserved for safe recovery"
        raise CLIError(
            f"engine did not become ready before timeout{detail}; see {log_path}"
        )
    except OSError as exc:
        if proc is not None:
            cleanup_failed_engine_launch(
                proc,
                descriptor_path=descriptor_path,
                instance_id=instance_id,
                token=token,
                timeout=ns.timeout,
            )
        raise CLIError(f"cannot start engine: {exc}") from exc
    finally:
        if bootstrap_path is not None:
            remove_bootstrap_file(bootstrap_path)


def cmd_engine_status(ns: argparse.Namespace) -> None:
    from pymol_cli.lifecycle.paths import default_descriptor_path
    from pymol_cli.rpc.client import EngineClient, EngineClientError
    from pymol_cli.rpc.descriptor import read_descriptor

    descriptor_path = resolve_local_path(ns.descriptor or default_descriptor_path())
    if not descriptor_path.exists():
        raise CLIError(f"engine is not running: {descriptor_path}")
    try:
        descriptor = read_descriptor(descriptor_path)
        with EngineClient.connect(
            descriptor.host,
            descriptor.port,
            token=descriptor.token,
            timeout=ns.timeout,
            expected_instance_id=descriptor.instance_id,
        ) as client:
            current_descriptor = read_descriptor(descriptor_path)
            if current_descriptor.instance_id != descriptor.instance_id:
                raise EngineClientError("engine descriptor changed during connection")
            info = client.info()
    except (
        EngineClientError,
        KeyError,
        OSError,
        TimeoutError,
        TypeError,
        ValueError,
    ) as exc:
        if remove_stale_descriptor_if_dead(descriptor_path):
            raise CLIError(
                f"engine is not running; removed stale descriptor: {descriptor_path}"
            ) from exc
        raise CLIError(f"engine is not reachable: {exc}") from exc
    payload = {
        "ok": True,
        "descriptor": str(descriptor_path),
        "mode": descriptor.mode,
        "pid": descriptor.pid,
        **info,
    }
    emit(
        payload
        if ns.json
        else f"engine running: {descriptor.mode} pid={descriptor.pid}",
        use_json=ns.json,
    )


def cmd_engine_logs(ns: argparse.Namespace) -> None:
    from pymol_cli.lifecycle.paths import default_descriptor_path

    descriptor_path = resolve_local_path(ns.descriptor or default_descriptor_path())
    log_path = resolve_local_path(ns.log or default_engine_log_path(descriptor_path))
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError as exc:
        raise CLIError(f"engine log not found: {log_path}") from exc
    selected = lines[-ns.lines :] if ns.lines > 0 else lines
    payload = {"path": str(log_path), "lines": selected}
    emit(payload if ns.json else "\n".join(selected), use_json=ns.json)


def _descriptor_has_instance(path: Path, instance_id: str) -> bool:
    from pymol_cli.rpc.descriptor import read_descriptor

    try:
        return read_descriptor(path).instance_id == instance_id
    except (KeyError, OSError, TypeError, ValueError):
        return False


def cmd_engine_stop(ns: argparse.Namespace) -> None:
    from pymol_cli.lifecycle.paths import default_descriptor_path
    from pymol_cli.lifecycle.serve import remove_descriptor
    from pymol_cli.rpc.client import EngineClient, EngineClientError
    from pymol_cli.rpc.descriptor import (
        _read_descriptor_unlocked,
        descriptor_mutation_lock,
        read_descriptor,
    )

    descriptor_path = resolve_local_path(ns.descriptor or default_descriptor_path())
    with descriptor_mutation_lock(descriptor_path):
        if not descriptor_path.exists():
            raise CLIError(f"engine is not running: {descriptor_path}")
        try:
            descriptor = _read_descriptor_unlocked(descriptor_path)
        except (KeyError, OSError, TypeError, ValueError) as exc:
            descriptor_path.unlink(missing_ok=True)
            raise CLIError(
                f"invalid engine descriptor removed: {descriptor_path}"
            ) from exc

    shutdown_error: BaseException | None = None
    try:
        with EngineClient.connect(
            descriptor.host,
            descriptor.port,
            token=descriptor.token,
            timeout=ns.timeout,
            expected_instance_id=descriptor.instance_id,
        ) as client:
            current_descriptor = read_descriptor(descriptor_path)
            if current_descriptor.instance_id != descriptor.instance_id:
                raise EngineClientError("engine descriptor changed during connection")
            client.shutdown()
    except (
        EngineClientError,
        KeyError,
        OSError,
        TimeoutError,
        TypeError,
        ValueError,
    ) as exc:
        shutdown_error = exc

    forced = False
    deadline = time.monotonic() + ns.timeout
    if shutdown_error is None:
        while time.monotonic() < deadline and descriptor_process_is_alive(descriptor):
            time.sleep(PROCESS_POLL_INTERVAL)

    still_owned = _descriptor_has_instance(descriptor_path, descriptor.instance_id)
    process_alive = descriptor_process_is_alive(descriptor)
    if shutdown_error is not None or process_alive:
        if process_alive:
            try:
                stopped = terminate_process_by_pid(
                    descriptor.pid,
                    expected_identity=descriptor.process_identity,
                    timeout=max(0.1, ns.timeout),
                )
            except OSError as exc:
                detail = shutdown_error or exc
                raise CLIError(f"engine shutdown failed: {detail}") from exc
            if not stopped:
                detail_text = f": {shutdown_error}" if shutdown_error else ""
                raise CLIError(f"engine shutdown failed{detail_text}")
            forced = True
        remove_descriptor(descriptor_path, instance_id=descriptor.instance_id)
    elif still_owned and not process_alive:
        remove_descriptor(descriptor_path, instance_id=descriptor.instance_id)

    if _descriptor_has_instance(descriptor_path, descriptor.instance_id):
        raise CLIError(f"engine stopped but descriptor remains: {descriptor_path}")
    payload = {"ok": True}
    if forced:
        payload["forced"] = True
    emit(payload if ns.json else "engine stopped", use_json=ns.json)
