# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import argparse
import socket
import sys
import time
import xmlrpc.client
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, cast

from pymol_cli.cli.common import (
    emit,
    is_url,
    parse_mapping,
    resolve_rpc_path,
    split_csv,
    warn,
)
from pymol_cli.cli.errors import CLIError
from pymol_cli.cli.pml import (
    generate_ligand_pocket_pml,
    generate_load_pml,
    generate_render_pml,
    require_mark_residues,
    resolve_ligand_chains,
    split_mark_residues,
    write_pml,
)


def server_url(host: str, port: int) -> str:
    return f"http://{host}:{port}/RPC2"


def make_server(host: str, port: int, timeout: float) -> xmlrpc.client.ServerProxy:
    socket.setdefaulttimeout(timeout)
    return xmlrpc.client.ServerProxy(server_url(host, port), allow_none=True)


def read_pml(path: str) -> list[str]:
    text = sys.stdin.read() if path == "-" else Path(path).read_text()
    return [line.rstrip() for line in text.splitlines() if line.strip()]


def connection_error(host: str, port: int, exc: OSError) -> CLIError:
    return CLIError(f"cannot connect to {server_url(host, port)}: {exc}")


def execute_commands(
    commands: Iterable[str], host: str, port: int, timeout: float
) -> list[Any]:
    server = make_server(host, port, timeout)
    results: list[Any] = []
    try:
        for command in commands:
            results.append(server.do(command))
    except OSError as exc:
        raise connection_error(host, port, exc) from exc
    return results


def validate_ligand_chains(
    *,
    object_name: str,
    ligand: str,
    chains: Sequence[str],
    host: str,
    port: int,
    timeout: float,
    strict: bool,
) -> tuple[list[str], list[str]]:
    server = make_server(host, port, timeout)
    counts: dict[str, int] = {}
    try:
        for chain in chains:
            selection = f"({object_name} and chain {chain} and resn {ligand})"
            counts[chain] = cast(int, server.count_atoms(selection))
    except OSError as exc:
        raise connection_error(host, port, exc) from exc
    return resolve_ligand_chains(counts, strict=strict, ligand=ligand)


def validate_mark_residues(
    *,
    object_name: str,
    marks: dict[str, str],
    chains: Sequence[str],
    host: str,
    port: int,
    timeout: float,
) -> None:
    server = make_server(host, port, timeout)
    counts: dict[str, int] = {}
    try:
        for chain in chains:
            for residue in split_mark_residues(marks.get(chain, "")):
                selection = f"({object_name} and chain {chain} and resi {residue})"
                counts[f"{chain}:{residue}"] = cast(int, server.count_atoms(selection))
    except OSError as exc:
        raise connection_error(host, port, exc) from exc
    require_mark_residues(counts)


def cmd_status(ns: argparse.Namespace) -> None:
    start = time.monotonic()
    try:
        server = make_server(ns.host, ns.port, ns.timeout)
        methods = cast(list[str], server.system.listMethods())
    except OSError as exc:
        raise CLIError(
            f"cannot connect to {server_url(ns.host, ns.port)}: {exc}"
        ) from exc
    elapsed_ms = round((time.monotonic() - start) * 1000, 1)
    payload = {
        "ok": True,
        "url": server_url(ns.host, ns.port),
        "method_count": len(methods),
        "has_do": "do" in methods,
        "elapsed_ms": elapsed_ms,
    }
    emit(
        payload if ns.json else f"connected {payload['url']} ({len(methods)} methods)",
        use_json=ns.json,
    )


def cmd_do(ns: argparse.Namespace) -> None:
    commands: list[str] = []
    commands.extend(ns.command)
    for file_path in ns.file:
        commands.extend(read_pml(file_path))
    if ns.stdin:
        commands.extend(read_pml("-"))
    if not commands:
        raise CLIError("no commands provided")
    if ns.dry_run:
        emit(commands, use_json=ns.json)
        return
    results = execute_commands(commands, ns.host, ns.port, ns.timeout)
    emit(results, use_json=ns.json)


def cmd_script(ns: argparse.Namespace) -> None:
    commands = read_pml(ns.path)
    if ns.dry_run:
        emit(commands, use_json=ns.json)
        return
    results = execute_commands(commands, ns.host, ns.port, ns.timeout)
    emit(results, use_json=ns.json)


def cmd_count(ns: argparse.Namespace) -> None:
    server = make_server(ns.host, ns.port, ns.timeout)
    try:
        count = server.count_atoms(ns.selection)
    except OSError as exc:
        raise connection_error(ns.host, ns.port, exc) from exc
    emit(
        {"selection": ns.selection, "count": count} if ns.json else count,
        use_json=ns.json,
    )


def cmd_load(ns: argparse.Namespace) -> None:
    load_path = ns.path if is_url(ns.path) else resolve_rpc_path(ns.path)
    commands = generate_load_pml(
        path=load_path,
        object_name=ns.object,
        style=ns.style,
        color=ns.color,
        orient=not ns.no_orient,
        zoom_buffer=ns.zoom_buffer,
        allow_url=ns.allow_url,
    )
    output_path = write_pml(ns.output, commands) if ns.output else None
    if ns.dry_run:
        payload = {
            "commands": commands,
            "output": str(output_path) if output_path else None,
        }
        emit(payload if ns.json else commands, use_json=ns.json)
        return
    results = execute_commands(commands, ns.host, ns.port, ns.timeout)
    payload = {"results": results, "output": str(output_path) if output_path else None}
    emit(
        payload if ns.json else (str(output_path) if output_path else results),
        use_json=ns.json,
    )


def cmd_render(ns: argparse.Namespace) -> None:
    commands = generate_render_pml(
        output=ns.output,
        width=ns.width,
        height=ns.height,
        dpi=ns.dpi,
        ray=ns.ray,
    )
    if ns.dry_run:
        emit(commands, use_json=ns.json)
        return
    results = execute_commands(commands, ns.host, ns.port, ns.timeout)
    payload = {"output": ns.output, "commands": commands, "results": results}
    emit(payload if ns.json else ns.output, use_json=ns.json)


def cmd_ligand_pocket(ns: argparse.Namespace) -> None:
    chains = split_csv(ns.chains)
    requested_chains = chains
    colors = parse_mapping(ns.color)
    marks = parse_mapping(ns.mark, allow_residues=True)
    if ns.send and not ns.no_validate:
        chains, missing = validate_ligand_chains(
            object_name=ns.object,
            ligand=ns.ligand,
            chains=chains,
            host=ns.host,
            port=ns.port,
            timeout=ns.timeout,
            strict=ns.strict_chains,
        )
        if missing:
            warn(
                f"ligand {ns.ligand} missing from chains {','.join(missing)}; "
                "skipping those chains"
            )
        validate_mark_residues(
            object_name=ns.object,
            marks=marks,
            chains=chains,
            host=ns.host,
            port=ns.port,
            timeout=ns.timeout,
        )
    commands = generate_ligand_pocket_pml(
        object_name=ns.object,
        ligand=ns.ligand,
        chains=chains,
        distance=ns.distance,
        colors=colors,
        marks=marks,
        grid=ns.grid,
        scene=ns.scene,
        disable_source=not ns.keep_source,
        cleanup_chains=requested_chains,
    )
    output_path = write_pml(ns.output, commands) if ns.output else None
    if ns.send:
        results = execute_commands(commands, ns.host, ns.port, ns.timeout)
        payload = {
            "results": results,
            "output": str(output_path) if output_path else None,
        }
        emit(
            payload if ns.json else (str(output_path) if output_path else results),
            use_json=ns.json,
        )
        return
    if output_path:
        emit(
            {"path": str(output_path)} if ns.json else str(output_path),
            use_json=ns.json,
        )
        return
    emit(commands, use_json=ns.json)
