# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast


def test_mcp_real_engine_rejects_code_and_completes_typed_workflow(
    tmp_path: Path,
) -> None:
    descriptor = tmp_path / "engine.json"
    structure = tmp_path / "model.pdb"
    structure.write_text(
        "ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00 20.00           N\n"
        "ATOM      2  CA  ALA A   1       1.500   0.000   0.000  1.00 20.00           C\n"
        "END\n",
        encoding="utf-8",
    )
    marker = tmp_path / "executed"
    executable_input = tmp_path / "untrusted.py"
    executable_input.write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('executed', encoding='utf-8')\n",
        encoding="utf-8",
    )
    png = tmp_path / "view.png"
    session = tmp_path / "state.pse"
    env = _test_env()

    _run_cli(
        "engine",
        "start",
        "--embedded",
        "--descriptor",
        str(descriptor),
        "--token",
        "secret",
        "--json",
        env=env,
    )
    try:
        requests: list[dict[str, Any]] = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "acceptance-test", "version": "1"},
                },
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "structure_load",
                    "arguments": {
                        "path": str(executable_input),
                        "object_name": "probe",
                    },
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "structure_load",
                    "arguments": {"path": str(structure), "object_name": "prot"},
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "scene_show",
                    "arguments": {"representation": "sticks", "selection": "prot"},
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {
                    "name": "atoms_count",
                    "arguments": {"selection": "prot"},
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {
                    "name": "render_png",
                    "arguments": {
                        "path": str(png),
                        "width": 320,
                        "height": 240,
                        "dpi": 100,
                        "ray": False,
                    },
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 8,
                "method": "tools/call",
                "params": {
                    "name": "session_save",
                    "arguments": {"path": str(session)},
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {
                    "name": "structure_load",
                    "arguments": {"path": str(structure), "object_name": "model"},
                },
            },
        ]
        responses = _run_mcp(requests, descriptor=descriptor, env=env)
        by_id = {response["id"]: response for response in responses}

        listed = by_id[2]["result"]["tools"]
        names = {tool["name"] for tool in listed}
        assert "session_restore" not in names
        assert "structure_load" in names

        rejected = by_id[3]["result"]
        assert rejected["isError"] is True
        assert not marker.exists()

        loaded = _tool_payload(by_id[4])
        assert loaded["object_name"] == "prot"
        assert _tool_payload(by_id[6])["count"] == 2
        assert _tool_payload(by_id[7])["path"] == str(png)
        assert _tool_payload(by_id[8])["path"] == str(session)
        assert by_id[9]["result"]["isError"] is True
        assert png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        assert session.is_file()

        status = _run_cli(
            "engine",
            "status",
            "--descriptor",
            str(descriptor),
            "--json",
            env=env,
        )
        assert json.loads(status.stdout)["ok"] is True
    finally:
        _run_cli(
            "engine",
            "stop",
            "--descriptor",
            str(descriptor),
            env=env,
            check=False,
        )


def _run_mcp(
    requests: list[dict[str, Any]], *, descriptor: Path, env: dict[str, str]
) -> list[dict[str, Any]]:
    input_text = "".join(json.dumps(request) + "\n" for request in requests)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pymol_cli.mcp",
            "--descriptor",
            str(descriptor),
        ],
        input=input_text,
        check=True,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
    )
    return [json.loads(line) for line in proc.stdout.splitlines()]


def _tool_payload(response: dict[str, Any]) -> dict[str, Any]:
    result = response["result"]
    assert result.get("isError") is not True
    payload: object = json.loads(result["content"][0]["text"])
    assert isinstance(payload, dict)
    return cast(dict[str, Any], payload)


def _run_cli(
    *args: str, env: dict[str, str], check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pymol_cli.main", *args],
        check=check,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
    )


def _test_env() -> dict[str, str]:
    env = os.environ.copy()
    package_root = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = f"{package_root}{os.pathsep}{env.get('PYTHONPATH', '')}"
    return env
