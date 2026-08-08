# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

from pathlib import Path

import pytest

from pymol_cli.lifecycle.lock import EngineStartLocked, engine_start_lock


def test_engine_start_lock_rejects_concurrent_holder(tmp_path: Path) -> None:
    descriptor = tmp_path / "engine.json"
    with (
        engine_start_lock(descriptor),
        pytest.raises(EngineStartLocked),
        engine_start_lock(descriptor),
    ):
        raise AssertionError("second lock must not be acquired")

    with engine_start_lock(descriptor):
        pass
