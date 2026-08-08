# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_RPC_FOUNDATION_IMPORT_PREFIXES = (
    "argparse",
    "mcp",
    "pymol",
    "pymol2",
    "pymol_cli.cli",
    "pymol_cli.lifecycle",
    "pymol_cli.mcp",
)


def test_rpc_foundation_does_not_import_cli_mcp_or_pymol_modules() -> None:
    rpc_root = Path(__file__).resolve().parents[1] / "pymol_cli" / "rpc"
    offenders: list[str] = []
    for path in rpc_root.glob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                if any(
                    _matches_prefix(name, prefix)
                    for prefix in FORBIDDEN_RPC_FOUNDATION_IMPORT_PREFIXES
                ):
                    offenders.append(f"{path.name}: {name}")

    assert offenders == []


def _matches_prefix(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(f"{prefix}.")
