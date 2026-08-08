# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from pymol_cli.rpc import descriptor as descriptor_module
from pymol_cli.rpc.descriptor import (
    EngineDescriptor,
    descriptor_mutation_lock_path,
    read_descriptor,
    write_descriptor,
)


def test_descriptor_round_trip_uses_atomic_json(tmp_path: Path) -> None:
    descriptor = EngineDescriptor(
        protocol_versions=[1],
        instance_id="instance-1",
        pid=123,
        mode="gui",
        host="127.0.0.1",
        port=49152,
        token="secret-token",
        started_at="2026-08-07T04:00:00Z",
    )
    path = tmp_path / "engine.json"

    write_descriptor(path, descriptor)

    assert read_descriptor(path) == descriptor
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions only")
def test_descriptor_is_private_from_moment_of_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def reject_late_chmod(self: Path, mode: int) -> None:
        raise AssertionError("descriptor permissions must not rely on late chmod")

    monkeypatch.setattr(Path, "chmod", reject_late_chmod)
    path = tmp_path / "engine.json"

    write_descriptor(
        path,
        EngineDescriptor(
            protocol_versions=[1],
            instance_id="instance-1",
            pid=123,
            mode="headless",
            host="127.0.0.1",
            port=49152,
            token="secret-token",
            started_at="2026-08-07T04:00:00Z",
        ),
    )

    assert path.stat().st_mode & 0o777 == 0o600
    assert descriptor_mutation_lock_path(path).stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(os.name != "nt", reason="Windows DACL only")
def test_descriptor_windows_dacl_grants_only_current_user(tmp_path: Path) -> None:
    path = tmp_path / "engine.json"
    write_descriptor(
        path,
        EngineDescriptor(
            protocol_versions=[1],
            instance_id="instance-1",
            pid=123,
            mode="headless",
            host="127.0.0.1",
            port=49152,
            token="secret-token",
            started_at="2026-08-07T04:00:00Z",
        ),
    )

    expected = f"D:P(A;;FA;;;{descriptor_module._windows_current_user_sid()})"
    assert _windows_dacl_sddl(path) == expected
    assert _windows_dacl_sddl(descriptor_mutation_lock_path(path)) == expected


def _windows_dacl_sddl(path: Path) -> str:
    import ctypes
    from ctypes import wintypes

    ctypes_api = descriptor_module._WINDOWS_CTYPES
    advapi32 = ctypes_api.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes_api.WinDLL("kernel32", use_last_error=True)
    get_security = advapi32.GetNamedSecurityInfoW
    get_security.argtypes = [
        wintypes.LPCWSTR,
        ctypes.c_int,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
    ]
    get_security.restype = wintypes.DWORD
    convert = advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW
    convert.argtypes = [
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(wintypes.ULONG),
    ]
    convert.restype = wintypes.BOOL
    local_free = kernel32.LocalFree
    local_free.argtypes = [wintypes.HLOCAL]
    local_free.restype = wintypes.HLOCAL

    security_descriptor = wintypes.LPVOID()
    dacl = wintypes.LPVOID()
    result = get_security(
        str(path),
        1,
        0x00000004,
        None,
        None,
        ctypes.byref(dacl),
        None,
        ctypes.byref(security_descriptor),
    )
    if result != 0:
        raise OSError(result, "GetNamedSecurityInfoW failed")
    sddl = wintypes.LPWSTR()
    try:
        if not convert(security_descriptor, 1, 0x00000004, ctypes.byref(sddl), None):
            raise descriptor_module._windows_api_error()
        value = sddl.value
        if value is None:
            raise OSError("Windows returned an empty DACL string")
        return value
    finally:
        if sddl:
            local_free(sddl)
        if security_descriptor:
            local_free(security_descriptor)


def test_descriptor_rejects_pid_outside_windows_dword_range(tmp_path: Path) -> None:
    path = tmp_path / "engine.json"
    path.write_text(
        '{"protocol_versions":[1],"instance_id":"id",'
        '"pid":4294967296,"mode":"headless",'
        '"host":"127.0.0.1","port":1,"token":"token",'
        '"started_at":"now"}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="pid is out of range"):
        read_descriptor(path)


def test_descriptor_round_trips_process_creation_identity(tmp_path: Path) -> None:
    descriptor = EngineDescriptor(
        protocol_versions=[1],
        instance_id="instance-1",
        pid=123,
        mode="headless",
        host="127.0.0.1",
        port=49152,
        token="secret-token",
        started_at="2026-08-07T04:00:00Z",
        process_identity="windows-filetime:1234",
    )
    path = tmp_path / "engine.json"

    write_descriptor(path, descriptor)

    assert read_descriptor(path).process_identity == "windows-filetime:1234"


def test_descriptor_rejects_unknown_fields(tmp_path: Path) -> None:
    path = tmp_path / "engine.json"
    descriptor = EngineDescriptor(
        protocol_versions=[1],
        instance_id="instance-1",
        pid=123,
        mode="headless",
        host="127.0.0.1",
        port=49152,
        token="secret-token",
        started_at="now",
    )
    write_descriptor(path, descriptor)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["unexpected"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown fields"):
        read_descriptor(path)
