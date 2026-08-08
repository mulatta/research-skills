# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

from pathlib import Path

from pymol_cli.lifecycle.paths import default_descriptor_path


def test_default_descriptor_paths_follow_platform_state_conventions() -> None:
    cases = [
        (
            {"XDG_RUNTIME_DIR": "/run/user/1000"},
            Path("/home/me"),
            "posix",
            "/run/user/1000/research-skills/pymol-engine.json",
        ),
        (
            {"XDG_STATE_HOME": "/home/me/.state"},
            Path("/home/me"),
            "posix",
            "/home/me/.state/research-skills/pymol-engine.json",
        ),
        (
            {},
            Path("/home/me"),
            "posix",
            "/home/me/.local/state/research-skills/pymol-engine.json",
        ),
        (
            {"LOCALAPPDATA": "C:/Users/me/AppData/Local"},
            Path("C:/Users/me"),
            "nt",
            "C:/Users/me/AppData/Local/research-skills/pymol-engine.json",
        ),
        (
            {"LOCALAPPDATA": ""},
            Path("C:/Users/me"),
            "nt",
            "C:/Users/me/AppData/Local/research-skills/pymol-engine.json",
        ),
    ]

    for env, home, os_name, expected in cases:
        assert default_descriptor_path(env=env, home=home, os_name=os_name) == Path(
            expected
        )
