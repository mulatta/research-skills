# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from pymol_cli.rpc.client import EngineClient
from pymol_cli.rpc.descriptor import EngineDescriptor, read_descriptor


def test_current_process_serve_controls_pymol_cmd(tmp_path: Path) -> None:
    descriptor_path = tmp_path / "engine.json"
    env = os.environ.copy()
    package_root = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = f"{package_root}{os.pathsep}{env.get('PYTHONPATH', '')}"
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "pymol_cli.lifecycle.serve",
            "--current-process",
            "--descriptor",
            str(descriptor_path),
            "--token",
            "secret",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        descriptor = _wait_for_descriptor(descriptor_path)
        assert descriptor.mode == "current-process"
        assert descriptor.pid == proc.pid

        with EngineClient.connect_descriptor(descriptor_path) as client:
            assert client.unsafe_execute_pml("fragment ala, smoke")["revision"] == 1
            assert client.count_atoms("smoke")["count"] == 10
            assert client.shutdown() == {"ok": True}

        stdout, stderr = proc.communicate(timeout=5)
        assert proc.returncode == 0, stderr
        assert "engine ready" in stdout
        assert not descriptor_path.exists()
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.communicate(timeout=5)


def _wait_for_descriptor(path: Path) -> EngineDescriptor:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if path.exists():
            return read_descriptor(path)
        time.sleep(0.05)
    raise AssertionError(f"descriptor was not written: {path}")
