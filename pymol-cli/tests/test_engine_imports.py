# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_CORE_IMPORT_PREFIXES = (
    "argparse",
    "socket",
    "xmlrpc",
    "mcp",
    "pymol_cli.cli",
    "pymol_cli.rpc",
    "pymol_cli.lifecycle",
    "pymol_cli.mcp",
)


def test_engine_core_does_not_import_transport_cli_or_mcp_modules() -> None:
    engine_root = Path(__file__).resolve().parents[1] / "pymol_cli" / "engine"
    offenders: list[str] = []
    for path in engine_root.glob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                if name.startswith(FORBIDDEN_CORE_IMPORT_PREFIXES):
                    offenders.append(f"{path.name}: {name}")

    assert offenders == []
