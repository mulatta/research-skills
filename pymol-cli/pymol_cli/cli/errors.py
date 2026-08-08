# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import sys
from typing import NoReturn


class CLIError(Exception):
    """User-facing command error."""


def die(message: str, code: int = 1) -> NoReturn:
    print(f"pymol-cli: {message}", file=sys.stderr)
    raise SystemExit(code)
