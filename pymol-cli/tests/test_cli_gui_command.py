# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

from pathlib import Path

from pymol_cli.cli.engine_lifecycle import build_engine_serve_command


def test_engine_commands_use_mode_specific_pymol_flags(
    tmp_path: Path,
) -> None:
    descriptor = tmp_path / "engine.json"

    command = build_engine_serve_command(
        descriptor_path=descriptor,
        token="secret",
        mode="gui",
        pymol_command="pymol",
    )

    assert command[:2] == ["pymol", "-q"]
    bootstrap_path = Path(command[2])
    assert bootstrap_path.parent == descriptor.parent
    assert bootstrap_path.name.startswith(".engine.")
    assert bootstrap_path.name.endswith(".bootstrap.py")
    bootstrap = bootstrap_path.read_text()
    assert "start_current_process_background" in bootstrap
    assert "instance_id=" in bootstrap
    assert "supervisor_pid=os.getppid()" in bootstrap

    headless = build_engine_serve_command(
        descriptor_path=descriptor,
        token="secret",
        mode="headless",
        pymol_command="pymol",
    )
    assert headless[:2] == ["pymol", "-cq"]
