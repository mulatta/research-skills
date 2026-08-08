# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import cast


def test_cli_typed_workflow_uses_engine_descriptor(tmp_path: Path) -> None:
    descriptor = tmp_path / "engine.json"
    structure = tmp_path / "model.pdb"
    png = tmp_path / "view.png"
    session = tmp_path / "state.pse"
    structure.write_text(
        "ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00 20.00           N\n"
        "ATOM      2  CA  ALA A   1       1.500   0.000   0.000  1.00 20.00           C\n"
        "END\n",
        encoding="utf-8",
    )
    env = _test_env()
    _run_cli(
        "engine",
        "start",
        "--embedded",
        "--descriptor",
        str(descriptor),
        "--token",
        "secret",
        "--json",
        env=env,
    )
    try:
        loaded = _run_json(
            "structure",
            "load",
            str(structure),
            "--object",
            "prot",
            "--descriptor",
            str(descriptor),
            env=env,
        )
        assert (loaded["object_name"], loaded["atom_count"]) == ("prot", 2)

        shown = _run_json(
            "scene",
            "show",
            "sticks",
            "prot",
            "--descriptor",
            str(descriptor),
            env=env,
        )
        assert shown["revision"] == 2

        rendered = _run_json(
            "render",
            "png",
            str(png),
            "--width",
            "320",
            "--height",
            "240",
            "--descriptor",
            str(descriptor),
            env=env,
        )
        assert rendered["path"] == str(png)
        assert png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")

        saved = _run_json(
            "session",
            "save",
            str(session),
            "--descriptor",
            str(descriptor),
            env=env,
        )
        assert saved["path"] == str(session)
        _run_cli("session", "clear", "--descriptor", str(descriptor), env=env)
        _run_cli(
            "session", "restore", str(session), "--descriptor", str(descriptor), env=env
        )

        count = _run_json(
            "atoms",
            "count",
            "prot",
            "--descriptor",
            str(descriptor),
            env=env,
        )
        assert count["count"] == 2
    finally:
        _run_cli(
            "engine", "stop", "--descriptor", str(descriptor), env=env, check=False
        )


def test_cli_domain_requires_running_engine(tmp_path: Path) -> None:
    proc = _run_cli(
        "atoms",
        "count",
        "all",
        "--descriptor",
        str(tmp_path / "missing.json"),
        env=_test_env(),
        check=False,
    )

    assert proc.returncode == 1
    assert "engine is not running" in proc.stderr


def _run_json(*args: str, env: dict[str, str]) -> dict[str, object]:
    return cast(
        dict[str, object], json.loads(_run_cli(*args, "--json", env=env).stdout)
    )


def _run_cli(
    *args: str, env: dict[str, str], check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pymol_cli.main", *args],
        check=check,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _test_env() -> dict[str, str]:
    env = os.environ.copy()
    package_root = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = f"{package_root}{os.pathsep}{env.get('PYTHONPATH', '')}"
    return env
