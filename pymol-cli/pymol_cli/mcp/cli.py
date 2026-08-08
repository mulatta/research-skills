# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""pymol-mcp command-line entry point."""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from pymol_cli.lifecycle.paths import default_descriptor_path
from pymol_cli.rpc.client import DEFAULT_RENDER_TIMEOUT, DEFAULT_TIMEOUT, EngineClient

from .server import McpServer
from .stdio import run_stdio


def positive_finite_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid number: {value}") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("timeout must be a positive finite number")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pymol-mcp")
    parser.add_argument("--descriptor", type=Path, default=default_descriptor_path())
    parser.add_argument(
        "--timeout", type=positive_finite_float, default=DEFAULT_TIMEOUT
    )
    parser.add_argument(
        "--render-timeout",
        type=positive_finite_float,
        default=DEFAULT_RENDER_TIMEOUT,
    )
    return parser


def die(message: str, code: int = 1) -> NoReturn:
    print(f"pymol-mcp: {message}", file=sys.stderr)
    raise SystemExit(code)


def main(argv: Sequence[str] | None = None) -> None:
    ns = build_parser().parse_args(argv)

    def client_factory() -> EngineClient:
        return EngineClient.connect_descriptor(
            ns.descriptor,
            timeout=ns.timeout,
            render_timeout=ns.render_timeout,
        )

    run_stdio(McpServer(client_factory), sys.stdin.buffer, sys.stdout.buffer)
