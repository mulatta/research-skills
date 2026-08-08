# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pymol_cli.cli.errors import CLIError

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 9123
DEFAULT_RENDER_TIMEOUT = 305.0
PROCESS_POLL_INTERVAL = 0.05
TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
RESI_RE = re.compile(r"^[A-Za-z0-9_.:+,-]+$")
URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")


def validate_token(value: str, name: str) -> str:
    if not TOKEN_RE.fullmatch(value):
        raise CLIError(f"invalid {name}: {value!r}")
    return value


def validate_residue_list(value: str) -> str:
    if not RESI_RE.fullmatch(value):
        raise CLIError(f"invalid residue selector: {value!r}")
    return value


def split_csv(value: str) -> list[str]:
    parts = [item.strip() for item in value.split(",") if item.strip()]
    if not parts:
        raise CLIError("comma-separated value is empty")
    return parts


def is_url(value: str) -> bool:
    return bool(URL_RE.match(value))


def positive_finite_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid number: {value}") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive finite number")
    return parsed


def resolve_rpc_path(value: str | Path) -> str:
    """Resolve paths before crossing into engine process with different cwd."""
    return str(Path(value).expanduser().resolve())


def resolve_local_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def emit(data: Any, *, use_json: bool) -> None:
    if use_json:
        print(json.dumps(data, indent=2, sort_keys=True))
    elif isinstance(data, list):
        for item in data:
            print(item)
    else:
        print(data)


def warn(message: str) -> None:
    print(f"pymol-cli: warning: {message}", file=sys.stderr)


def parse_mapping(
    items: Sequence[str], *, allow_residues: bool = False
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in items:
        if ":" not in item:
            raise CLIError(f"expected CHAIN:VALUE mapping, got {item!r}")
        chain, value = item.split(":", 1)
        validate_token(chain, "chain")
        if allow_residues:
            validate_residue_list(value)
        else:
            validate_token(value, "value")
        mapping[chain] = value
    return mapping
