# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Cross-platform process identity and Windows process-handle operations."""

from __future__ import annotations

import ctypes
import os
import select
import signal
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Any, Protocol, cast

MAX_WINDOWS_PID = 0xFFFFFFFF


class _WindowsCtypes(Protocol):
    def WinDLL(self, name: str, *, use_last_error: bool) -> Any: ...

    def get_last_error(self) -> int: ...


_WINDOWS_CTYPES = cast(_WindowsCtypes, ctypes)


def get_process_identity(pid: int) -> str | None:
    """Return stable creation identity for current occupant of a PID."""
    if pid <= 0:
        return None
    if os.name == "nt":
        if pid > MAX_WINDOWS_PID:
            return None
        return _windows_process_identity(pid)
    if sys.platform.startswith("linux"):
        try:
            stat_text = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
            # comm can contain spaces or parentheses, so parse after its last ')'.
            tail = stat_text[stat_text.rindex(")") + 2 :].split()
            start_ticks = tail[19]  # field 22, with tail beginning at field 3
            boot_id = (
                Path("/proc/sys/kernel/random/boot_id")
                .read_text(encoding="ascii")
                .strip()
            )
            if not boot_id:
                return None
            return f"linux:{boot_id}:{start_ticks}"
        except (FileNotFoundError, IndexError, OSError, UnicodeError, ValueError):
            return None
    return _posix_ps_identity(pid)


def process_identity_matches(pid: int, expected: str | None) -> bool:
    return expected is not None and get_process_identity(pid) == expected


def is_process_alive_posix(pid: int) -> bool:
    """Treat zombie processes as exited rather than kill(0)-alive."""
    if pid <= 0:
        return False
    if sys.platform.startswith("linux"):
        try:
            stat_text = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
            state = stat_text[stat_text.rindex(")") + 2 :].split()[0]
            return state != "Z"
        except FileNotFoundError:
            return False
        except (IndexError, OSError, UnicodeError, ValueError):
            pass
    else:
        state = _posix_ps_value(pid, field="stat")
        if state is not None:
            return not state.startswith("Z")
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def is_process_alive_windows(pid: int) -> bool:
    """Check signaled process state without interpreting an exit-code sentinel."""
    if pid <= 0 or pid > MAX_WINDOWS_PID:
        return False
    kernel32 = _WINDOWS_CTYPES.WinDLL("kernel32", use_last_error=True)
    process_query_limited_information = 0x1000
    synchronize = 0x00100000
    wait_object_0 = 0
    wait_timeout = 258
    wait_failed = 0xFFFFFFFF
    error_invalid_parameter = 87

    open_process = kernel32.OpenProcess
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_process.restype = wintypes.HANDLE
    wait_for_single_object = kernel32.WaitForSingleObject
    wait_for_single_object.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    wait_for_single_object.restype = wintypes.DWORD
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    handle = open_process(process_query_limited_information | synchronize, False, pid)
    if not handle:
        error = _WINDOWS_CTYPES.get_last_error()
        return error != error_invalid_parameter
    try:
        result = int(wait_for_single_object(handle, 0))
        if result == wait_timeout:
            return True
        if result == wait_object_0:
            return False
        if result == wait_failed:
            return True  # Fail closed rather than delete or kill an unknown PID.
        return True
    finally:
        close_handle(handle)


def terminate_linux_process(
    pid: int, *, expected_identity: str, timeout: float
) -> bool:
    """Signal one pidfd-bound process, never a later occupant of its numeric PID."""
    pidfd_open = getattr(os, "pidfd_open", None)
    pidfd_send_signal = getattr(signal, "pidfd_send_signal", None)
    if not callable(pidfd_open) or not callable(pidfd_send_signal):
        return False
    try:
        pidfd = int(pidfd_open(pid, 0))
    except ProcessLookupError:
        return True
    except OSError:
        return False
    try:
        identity = get_process_identity(pid)
        if identity is None:
            return not is_process_alive_posix(pid)
        if identity != expected_identity:
            return True
        try:
            pidfd_send_signal(pidfd, signal.SIGTERM, None, 0)
        except ProcessLookupError:
            return True
        except OSError:
            return False
        grace = min(1.0, max(0.0, timeout))
        ready, _writable, _exceptional = select.select([pidfd], [], [], grace)
        if ready:
            return True
        try:
            pidfd_send_signal(pidfd, signal.SIGKILL, None, 0)
        except ProcessLookupError:
            return True
        except OSError:
            return False
        ready, _writable, _exceptional = select.select([pidfd], [], [], grace)
        return bool(ready)
    finally:
        os.close(pidfd)


def terminate_windows_process(
    pid: int, *, expected_identity: str, timeout: float
) -> bool:
    """Terminate only the process whose creation identity matches descriptor."""
    if pid <= 0 or pid > MAX_WINDOWS_PID:
        return False
    kernel32 = _WINDOWS_CTYPES.WinDLL("kernel32", use_last_error=True)
    process_terminate = 0x0001
    process_query_limited_information = 0x1000
    synchronize = 0x00100000
    wait_object_0 = 0
    wait_timeout = 258

    open_process = kernel32.OpenProcess
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_process.restype = wintypes.HANDLE
    terminate_process = kernel32.TerminateProcess
    terminate_process.argtypes = [wintypes.HANDLE, wintypes.UINT]
    terminate_process.restype = wintypes.BOOL
    wait_for_single_object = kernel32.WaitForSingleObject
    wait_for_single_object.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    wait_for_single_object.restype = wintypes.DWORD
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    access = process_terminate | process_query_limited_information | synchronize
    handle = open_process(access, False, pid)
    if not handle:
        return False
    try:
        if _windows_process_identity_from_handle(handle, kernel32) != expected_identity:
            return False
        state = int(wait_for_single_object(handle, 0))
        if state == wait_object_0:
            return True
        if state != wait_timeout:
            return False
        if not terminate_process(handle, 1):
            return False
        milliseconds = min(0xFFFFFFFE, max(0, int(timeout * 1000)))
        return int(wait_for_single_object(handle, milliseconds)) == wait_object_0
    finally:
        close_handle(handle)


def _windows_process_identity(pid: int) -> str | None:
    kernel32 = _WINDOWS_CTYPES.WinDLL("kernel32", use_last_error=True)
    process_query_limited_information = 0x1000
    open_process = kernel32.OpenProcess
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_process.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    handle = open_process(process_query_limited_information, False, pid)
    if not handle:
        return None
    try:
        return _windows_process_identity_from_handle(handle, kernel32)
    finally:
        close_handle(handle)


def _windows_process_identity_from_handle(handle: Any, kernel32: Any) -> str | None:
    get_process_times = kernel32.GetProcessTimes
    get_process_times.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    get_process_times.restype = wintypes.BOOL
    creation = wintypes.FILETIME()
    exit_time = wintypes.FILETIME()
    kernel_time = wintypes.FILETIME()
    user_time = wintypes.FILETIME()
    if not get_process_times(
        handle,
        ctypes.byref(creation),
        ctypes.byref(exit_time),
        ctypes.byref(kernel_time),
        ctypes.byref(user_time),
    ):
        return None
    value = (int(creation.dwHighDateTime) << 32) | int(creation.dwLowDateTime)
    return f"windows-filetime:{value}"


def _posix_ps_identity(pid: int) -> str | None:
    value = _posix_ps_value(pid, field="lstart")
    return None if value is None else f"posix-lstart:{value}"


def _posix_ps_value(pid: int, *, field: str) -> str | None:
    ps = Path("/bin/ps")
    command = str(ps) if ps.exists() else "ps"
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    try:
        result = subprocess.run(
            [command, "-o", f"{field}=", "-p", str(pid)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=1,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = result.stdout.strip()
    if result.returncode != 0 or not value:
        return None
    return value
