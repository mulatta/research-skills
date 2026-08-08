# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import os
import subprocess
import sys

import pytest

from pymol_cli.cli import engine_lifecycle
from pymol_cli.lifecycle.process import get_process_identity


def test_current_process_identity_is_stable() -> None:
    first = get_process_identity(os.getpid())
    second = get_process_identity(os.getpid())

    if first is None:
        pytest.skip("platform does not expose process creation identity")
    assert second == first


def test_termination_refuses_reused_pid_identity() -> None:
    process = _sleeping_process()
    try:
        identity = get_process_identity(process.pid)
        if identity is None:
            pytest.skip("platform does not expose process creation identity")

        assert engine_lifecycle.terminate_process_by_pid(
            process.pid,
            expected_identity=f"{identity}-replacement",
            timeout=0.2,
        )
        assert process.poll() is None
    finally:
        process.terminate()
        process.wait(timeout=3)


def test_termination_refuses_pid_without_creation_identity() -> None:
    process = _sleeping_process()
    try:
        assert not engine_lifecycle.terminate_process_by_pid(
            process.pid, expected_identity=None, timeout=0.2
        )
        assert process.poll() is None
    finally:
        process.terminate()
        process.wait(timeout=3)


def test_termination_stops_matching_process_identity_when_handle_api_exists() -> None:
    process = _sleeping_process()
    try:
        identity = get_process_identity(process.pid)
        if identity is None:
            pytest.skip("platform does not expose process creation identity")

        stopped = engine_lifecycle.terminate_process_by_pid(
            process.pid, expected_identity=identity, timeout=2
        )
        if os.name == "nt" or sys.platform.startswith("linux"):
            assert stopped
            assert process.wait(timeout=3) is not None
        else:
            assert not stopped
            assert process.poll() is None
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=3)


def _sleeping_process() -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
