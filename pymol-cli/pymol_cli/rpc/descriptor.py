# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Engine endpoint descriptor persistence."""

from __future__ import annotations

import ctypes
import json
import os
import secrets
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, BinaryIO, Protocol, cast

_ALLOWED_MODES = frozenset({"embedded", "current-process", "gui", "headless"})
_DESCRIPTOR_KEYS = frozenset(
    {
        "protocol_versions",
        "instance_id",
        "pid",
        "mode",
        "host",
        "port",
        "token",
        "started_at",
        "supervisor_pid",
        "process_identity",
    }
)


class _Msvcrt(Protocol):
    def open_osfhandle(self, handle: int, flags: int) -> int: ...


class _WindowsCtypes(Protocol):
    def WinDLL(self, name: str, *, use_last_error: bool) -> Any: ...

    def get_last_error(self) -> int: ...


_WINDOWS_CTYPES = cast(_WindowsCtypes, ctypes)


@dataclass(frozen=True)
class EngineDescriptor:
    protocol_versions: list[int]
    instance_id: str
    pid: int
    mode: str
    host: str
    port: int
    token: str
    started_at: str
    supervisor_pid: int | None = None
    process_identity: str | None = None


def write_descriptor(path: Path, descriptor: EngineDescriptor) -> None:
    """Atomically publish a descriptor that is private from creation onward."""
    with descriptor_mutation_lock(path):
        _write_descriptor_unlocked(path, descriptor)


def _write_descriptor_unlocked(path: Path, descriptor: EngineDescriptor) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(asdict(descriptor), indent=2, sort_keys=True) + "\n"
    descriptor_fd, temp_path = create_private_temp_file(
        path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor_fd, "w", encoding="utf-8") as handle:
            descriptor_fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if descriptor_fd >= 0:
            os.close(descriptor_fd)
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def read_descriptor(path: Path) -> EngineDescriptor:
    with descriptor_mutation_lock(path):
        return _read_descriptor_unlocked(path)


def _read_descriptor_unlocked(path: Path) -> EngineDescriptor:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError("engine descriptor must be a JSON object")
    unknown_keys = set(data) - _DESCRIPTOR_KEYS
    if unknown_keys:
        raise ValueError("engine descriptor contains unknown fields")
    protocol_versions = _int_list(_field(data, "protocol_versions"))
    instance_id = _nonempty_string(_field(data, "instance_id"), "instance_id")
    pid = _pid(_field(data, "pid"), "pid")
    mode = _nonempty_string(_field(data, "mode"), "mode")
    if mode not in _ALLOWED_MODES:
        raise ValueError("engine descriptor mode is invalid")
    host = _nonempty_string(_field(data, "host"), "host")
    if host != "127.0.0.1":
        raise ValueError("engine descriptor host must be 127.0.0.1")
    port = _positive_int(_field(data, "port"), "port")
    if port > 65535:
        raise ValueError("engine descriptor port is out of range")
    token = _nonempty_string(_field(data, "token"), "token")
    started_at = _nonempty_string(_field(data, "started_at"), "started_at")
    supervisor_pid = _optional_pid(data.get("supervisor_pid"))
    process_identity = _optional_string(
        data.get("process_identity"), "process_identity"
    )
    return EngineDescriptor(
        protocol_versions=protocol_versions,
        instance_id=instance_id,
        pid=pid,
        mode=mode,
        host=host,
        port=port,
        token=token,
        started_at=started_at,
        supervisor_pid=supervisor_pid,
        process_identity=process_identity,
    )


def _field(data: dict[str, Any], name: str) -> Any:
    try:
        return data[name]
    except KeyError as exc:
        raise ValueError(f"engine descriptor is missing {name}") from exc


def _int_list(value: object) -> list[int]:
    if not isinstance(value, list) or not value:
        raise TypeError("protocol_versions must be a nonempty list")
    versions: list[int] = []
    for item in value:
        versions.append(_positive_int(item, "protocol_versions item"))
    return versions


def _positive_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise TypeError(f"{name} must be a positive integer")
    return value


def _pid(value: object, name: str) -> int:
    pid = _positive_int(value, name)
    if pid > 0xFFFFFFFF:
        raise ValueError(f"{name} is out of range")
    return pid


def _optional_pid(value: object) -> int | None:
    return None if value is None else _pid(value, "supervisor_pid")


def _optional_string(value: object, name: str) -> str | None:
    return None if value is None else _nonempty_string(value, name)


def _nonempty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError(f"{name} must be a nonempty string")
    return value


def descriptor_mutation_lock_path(descriptor_path: Path) -> Path:
    return descriptor_path.with_name(f".{descriptor_path.name}.mutation.lock")


@contextmanager
def descriptor_mutation_lock(descriptor_path: Path) -> Iterator[None]:
    """Serialize descriptor check-and-replace/unlink critical sections."""
    lock_path = descriptor_mutation_lock_path(descriptor_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open_private_lock_file(lock_path)
    try:
        _acquire_descriptor_file_lock(handle)
        try:
            yield
        finally:
            _release_descriptor_file_lock(handle)
    finally:
        handle.close()


def _acquire_descriptor_file_lock(handle: BinaryIO) -> None:
    if os.name == "nt":
        msvcrt: Any = __import__("msvcrt")
        _prepare_windows_lock_byte(handle)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _release_descriptor_file_lock(handle: BinaryIO) -> None:
    if os.name == "nt":
        msvcrt: Any = __import__("msvcrt")
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _prepare_windows_lock_byte(handle: BinaryIO) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)


def create_private_temp_file(
    directory: Path, *, prefix: str, suffix: str
) -> tuple[int, Path]:
    """Create a unique 0600/current-user file without a permissive ACL window."""
    if os.name != "nt":
        descriptor, name = tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=directory)
        os.fchmod(descriptor, 0o600)
        return descriptor, Path(name)
    return _create_private_temp_file_windows(directory, prefix=prefix, suffix=suffix)


def _create_private_temp_file_windows(
    directory: Path, *, prefix: str, suffix: str
) -> tuple[int, Path]:
    import msvcrt

    msvcrt_api = cast(_Msvcrt, msvcrt)
    kernel32 = _WINDOWS_CTYPES.WinDLL("kernel32", use_last_error=True)
    generic_read = 0x80000000
    generic_write = 0x40000000
    create_new = 1
    file_attribute_normal = 0x00000080
    invalid_handle = ctypes.c_void_p(-1).value

    class SecurityAttributes(ctypes.Structure):
        _fields_ = [
            ("nLength", wintypes.DWORD),
            ("lpSecurityDescriptor", wintypes.LPVOID),
            ("bInheritHandle", wintypes.BOOL),
        ]

    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(SecurityAttributes),
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    security_descriptor = _allocate_windows_security_descriptor()
    try:
        attributes = SecurityAttributes(
            ctypes.sizeof(SecurityAttributes), security_descriptor, False
        )
        for _attempt in range(100):
            path = directory / f"{prefix}{secrets.token_hex(16)}{suffix}"
            handle = create_file(
                str(path),
                generic_read | generic_write,
                0,
                ctypes.byref(attributes),
                create_new,
                file_attribute_normal,
                None,
            )
            if handle == invalid_handle:
                if _WINDOWS_CTYPES.get_last_error() == 80:  # ERROR_FILE_EXISTS
                    continue
                raise _windows_api_error()
            try:
                flags = os.O_RDWR | getattr(os, "O_BINARY", 0)
                descriptor = msvcrt_api.open_osfhandle(int(handle), flags)
            except BaseException:
                close_handle(handle)
                raise
            return descriptor, path
    finally:
        _windows_local_free(security_descriptor)
    raise FileExistsError("could not allocate a unique private temporary file")


def open_private_lock_file(path: Path) -> BinaryIO:
    """Open stable lock inode/handle with private permissions from creation."""
    if os.name != "nt":
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            return os.fdopen(descriptor, "r+b")
        except BaseException:
            os.close(descriptor)
            raise
    return _open_private_lock_file_windows(path)


def _open_private_lock_file_windows(path: Path) -> BinaryIO:
    import msvcrt

    msvcrt_api = cast(_Msvcrt, msvcrt)
    kernel32 = _WINDOWS_CTYPES.WinDLL("kernel32", use_last_error=True)
    generic_read = 0x80000000
    generic_write = 0x40000000
    share_read_write = 0x00000001 | 0x00000002
    open_always = 4
    file_attribute_normal = 0x00000080
    invalid_handle = ctypes.c_void_p(-1).value

    class SecurityAttributes(ctypes.Structure):
        _fields_ = [
            ("nLength", wintypes.DWORD),
            ("lpSecurityDescriptor", wintypes.LPVOID),
            ("bInheritHandle", wintypes.BOOL),
        ]

    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(SecurityAttributes),
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    security_descriptor = _allocate_windows_security_descriptor()
    try:
        attributes = SecurityAttributes(
            ctypes.sizeof(SecurityAttributes), security_descriptor, False
        )
        handle = create_file(
            str(path),
            generic_read | generic_write,
            share_read_write,
            ctypes.byref(attributes),
            open_always,
            file_attribute_normal,
            None,
        )
        if handle == invalid_handle:
            raise _windows_api_error()
    finally:
        _windows_local_free(security_descriptor)
    try:
        _set_windows_user_only_dacl(path)
        flags = os.O_RDWR | getattr(os, "O_BINARY", 0)
        descriptor = msvcrt_api.open_osfhandle(int(handle), flags)
    except BaseException:
        close_handle(handle)
        raise
    try:
        return os.fdopen(descriptor, "r+b")
    except BaseException:
        os.close(descriptor)
        raise


def restrict_file_to_current_user(path: Path) -> None:
    """Fail closed unless only current user can read a secret-bearing file."""
    if os.name == "nt":
        _set_windows_user_only_dacl(path)
    elif os.name == "posix":
        path.chmod(0o600)


def _windows_api_error(code: int | None = None) -> OSError:
    if code is None:
        code = int(_WINDOWS_CTYPES.get_last_error())
    return OSError(code, f"Windows API call failed with error {code}")


def _windows_current_user_sid() -> str:
    """Return current process token user SID as its canonical string."""
    if os.name != "nt":
        raise OSError("Windows SID lookup is unavailable on this platform")

    token_query = 0x0008
    token_user_class = 1
    kernel32 = _WINDOWS_CTYPES.WinDLL("kernel32", use_last_error=True)
    advapi32 = _WINDOWS_CTYPES.WinDLL("advapi32", use_last_error=True)

    class SidAndAttributes(ctypes.Structure):
        _fields_ = [("sid", wintypes.LPVOID), ("attributes", wintypes.DWORD)]

    class TokenUser(ctypes.Structure):
        _fields_ = [("user", SidAndAttributes)]

    open_process_token = advapi32.OpenProcessToken
    open_process_token.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    open_process_token.restype = wintypes.BOOL
    get_token_information = advapi32.GetTokenInformation
    get_token_information.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    get_token_information.restype = wintypes.BOOL
    convert_sid = advapi32.ConvertSidToStringSidW
    convert_sid.argtypes = [wintypes.LPVOID, ctypes.POINTER(wintypes.LPWSTR)]
    convert_sid.restype = wintypes.BOOL
    get_current_process = kernel32.GetCurrentProcess
    get_current_process.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    local_free = kernel32.LocalFree
    local_free.argtypes = [wintypes.HLOCAL]
    local_free.restype = wintypes.HLOCAL

    token = wintypes.HANDLE()
    if not open_process_token(get_current_process(), token_query, ctypes.byref(token)):
        raise _windows_api_error()
    sid_text = wintypes.LPWSTR()
    try:
        needed = wintypes.DWORD()
        get_token_information(token, token_user_class, None, 0, ctypes.byref(needed))
        error = _WINDOWS_CTYPES.get_last_error()
        if not needed.value or error != 122:  # ERROR_INSUFFICIENT_BUFFER
            raise _windows_api_error(error)
        buffer = ctypes.create_string_buffer(needed.value)
        if not get_token_information(
            token,
            token_user_class,
            ctypes.cast(buffer, wintypes.LPVOID),
            needed,
            ctypes.byref(needed),
        ):
            raise _windows_api_error()
        token_user = ctypes.cast(buffer, ctypes.POINTER(TokenUser)).contents
        if not convert_sid(token_user.user.sid, ctypes.byref(sid_text)):
            raise _windows_api_error()
        return str(sid_text.value)
    finally:
        if sid_text:
            local_free(ctypes.cast(sid_text, wintypes.HLOCAL))
        close_handle(token)


def _allocate_windows_security_descriptor() -> Any:
    sid = _windows_current_user_sid()
    sddl = f"D:P(A;;FA;;;{sid})"
    advapi32 = _WINDOWS_CTYPES.WinDLL("advapi32", use_last_error=True)
    convert = advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.ULONG),
    ]
    convert.restype = wintypes.BOOL
    security_descriptor = wintypes.LPVOID()
    if not convert(sddl, 1, ctypes.byref(security_descriptor), None):
        raise _windows_api_error()
    return security_descriptor


def _windows_local_free(value: Any) -> None:
    kernel32 = _WINDOWS_CTYPES.WinDLL("kernel32", use_last_error=True)
    local_free = kernel32.LocalFree
    local_free.argtypes = [wintypes.HLOCAL]
    local_free.restype = wintypes.HLOCAL
    local_free(ctypes.cast(value, wintypes.HLOCAL))


def _set_windows_user_only_dacl(path: Path) -> None:
    """Protect an existing file with a non-inherited current-user DACL."""
    dacl_security_information = 0x00000004
    protected_dacl_security_information = 0x80000000
    advapi32 = _WINDOWS_CTYPES.WinDLL("advapi32", use_last_error=True)
    set_file_security = advapi32.SetFileSecurityW
    set_file_security.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.LPVOID]
    set_file_security.restype = wintypes.BOOL
    security_descriptor = _allocate_windows_security_descriptor()
    try:
        security_information = (
            dacl_security_information | protected_dacl_security_information
        )
        if not set_file_security(str(path), security_information, security_descriptor):
            raise _windows_api_error()
    finally:
        _windows_local_free(security_descriptor)
