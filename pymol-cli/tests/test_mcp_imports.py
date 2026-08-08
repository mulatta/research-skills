# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

from pymol_cli import mcp
from pymol_cli.mcp import cli, protocol, server, stdio, tools


def test_mcp_package_preserves_public_facade_aliases() -> None:
    assert mcp.McpServer is server.McpServer
    assert mcp.build_tools is tools.build_tools
    assert mcp.run_stdio is stdio.run_stdio
    assert mcp.main is cli.main
    assert mcp.MCP_PROTOCOL_VERSION is protocol.MCP_PROTOCOL_VERSION
