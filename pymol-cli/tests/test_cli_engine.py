# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_cli_engine_start_status_stop_embedded(tmp_path: Path) -> None:
    descriptor = tmp_path / "engine.json"
    env = _test_env()

    start = subprocess.run(
        [
            sys.executable,
            "-m",
            "pymol_cli.main",
            "engine",
            "start",
            "--embedded",
            "--descriptor",
            str(descriptor),
            "--token",
            "secret",
            "--json",
        ],
        check=True,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        start_payload = json.loads(start.stdout)
        assert start_payload["ok"] is True
        assert start_payload["mode"] == "embedded"
        assert start_payload["descriptor"] == str(descriptor)
        assert descriptor.exists()

        status = subprocess.run(
            [
                sys.executable,
                "-m",
                "pymol_cli.main",
                "engine",
                "status",
                "--descriptor",
                str(descriptor),
                "--json",
            ],
            check=True,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        status_payload = json.loads(status.stdout)
        assert status_payload["ok"] is True
        assert status_payload["backend"] == "pymol-open-source"

        stop = subprocess.run(
            [
                sys.executable,
                "-m",
                "pymol_cli.main",
                "engine",
                "stop",
                "--descriptor",
                str(descriptor),
                "--json",
            ],
            check=True,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert json.loads(stop.stdout) == {"ok": True}
        assert not descriptor.exists()
    finally:
        if descriptor.exists():
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pymol_cli.main",
                    "engine",
                    "stop",
                    "--descriptor",
                    str(descriptor),
                ],
                check=False,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )


def test_cli_engine_status_reports_missing_descriptor(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pymol_cli.main",
            "engine",
            "status",
            "--descriptor",
            str(missing),
        ],
        check=False,
        env=_test_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert proc.returncode == 1
    assert "engine is not running" in proc.stderr


def test_cli_engine_status_removes_dead_stale_descriptor(tmp_path: Path) -> None:
    from pymol_cli.rpc.descriptor import EngineDescriptor, write_descriptor

    descriptor = tmp_path / "engine.json"
    write_descriptor(
        descriptor,
        EngineDescriptor(
            protocol_versions=[1],
            instance_id="stale",
            pid=99999999,
            mode="current-process",
            host="127.0.0.1",
            port=9,
            token="secret",
            started_at="2026-01-01T00:00:00+00:00",
        ),
    )

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pymol_cli.main",
            "engine",
            "status",
            "--descriptor",
            str(descriptor),
            "--timeout",
            "0.1",
        ],
        check=False,
        env=_test_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert proc.returncode == 1
    assert "removed stale descriptor" in proc.stderr
    assert not descriptor.exists()


def _test_env() -> dict[str, str]:
    env = os.environ.copy()
    package_root = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = f"{package_root}{os.pathsep}{env.get('PYTHONPATH', '')}"
    return env
