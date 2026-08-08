# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Command-line entry point for pymol-cli."""

from __future__ import annotations

import argparse
import json
import xmlrpc.client
from collections.abc import Sequence
from typing import NoReturn

from pymol_cli.cli.errors import CLIError, die
from pymol_cli.cli.parser import build_parser
from pymol_cli.rpc.client import EngineClientError


def _die_for_namespace(ns: argparse.Namespace, message: str) -> NoReturn:
    if getattr(ns, "json", False):
        print(json.dumps({"error": message, "ok": False}, sort_keys=True))
    die(message)


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    ns = parser.parse_args(argv)
    try:
        ns.func(ns)
    except CLIError as exc:
        _die_for_namespace(ns, str(exc))
    except xmlrpc.client.Error as exc:
        _die_for_namespace(ns, f"xml-rpc error: {exc}")
    except (EngineClientError, OSError, TimeoutError) as exc:
        _die_for_namespace(ns, f"engine operation failed: {exc}")


if __name__ == "__main__":
    main()
