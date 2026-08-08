# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Cross-platform runtime paths for local engine state."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

APP_DIR = "research-skills"
DESCRIPTOR_NAME = "pymol-engine.json"


def default_descriptor_path(
    *,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
    os_name: str | None = None,
) -> Path:
    values = os.environ if env is None else env
    user_home = Path.home() if home is None else home
    platform = os.name if os_name is None else os_name

    if platform == "nt":
        base = Path(values.get("LOCALAPPDATA") or user_home / "AppData" / "Local")
        return base / APP_DIR / DESCRIPTOR_NAME

    runtime_dir = values.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        return Path(runtime_dir) / APP_DIR / DESCRIPTOR_NAME

    state_home = values.get("XDG_STATE_HOME")
    if state_home:
        return Path(state_home) / APP_DIR / DESCRIPTOR_NAME

    return user_home / ".local" / "state" / APP_DIR / DESCRIPTOR_NAME
