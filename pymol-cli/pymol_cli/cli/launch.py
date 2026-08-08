# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import argparse
import os
import shlex
import subprocess
from collections.abc import Sequence
from typing import Any

from pymol_cli.cli.common import emit
from pymol_cli.cli.errors import CLIError


def build_launch_command(
    pymol_command: str,
    *,
    remote: bool,
    headless: bool,
    script: str | None,
    extra_args: Sequence[str],
) -> list[str]:
    command = shlex.split(pymol_command)
    if not command:
        raise CLIError("pymol command is empty")
    args = list(extra_args)
    if args and args[0] == "--":
        args = args[1:]
    if remote:
        command.append("-R")
    if headless:
        command.append("-cq")
    command.extend(args)
    if script:
        command.append(script)
    return command


def cmd_launch(ns: argparse.Namespace) -> None:
    command = build_launch_command(
        ns.pymol_command,
        remote=not ns.no_remote,
        headless=ns.headless,
        script=ns.script,
        extra_args=ns.extra_args,
    )
    runner = "pueue" if ns.pueue else "foreground" if ns.foreground else "detached"
    if ns.dry_run:
        payload = {"command": command, "runner": runner}
        emit(payload if ns.json else shlex.join(command), use_json=ns.json)
        return
    if ns.pueue:
        try:
            run_proc = subprocess.run(
                ["pueue", "add", "--print-task-id", "--", *command],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise CLIError(f"pueue launch failed: {exc}") from exc
        if run_proc.returncode != 0:
            raise CLIError(run_proc.stderr.strip() or "pueue launch failed")
        task_id = run_proc.stdout.strip()
        emit(
            {"task_id": task_id, "command": command} if ns.json else task_id,
            use_json=ns.json,
        )
        return

    popen_options: dict[str, Any] = {}
    if not ns.foreground:
        popen_options.update(
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        if os.name == "nt":
            popen_options["creationflags"] = getattr(
                subprocess, "DETACHED_PROCESS", 0x00000008
            ) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        else:
            popen_options["start_new_session"] = True
    try:
        popen_proc = subprocess.Popen(command, **popen_options)
    except OSError as exc:
        raise CLIError(f"PyMOL launch failed: {exc}") from exc
    launch_payload: dict[str, Any] = {"pid": popen_proc.pid, "command": command}
    if not ns.foreground:
        launch_payload["detached"] = True
    emit(launch_payload if ns.json else popen_proc.pid, use_json=ns.json)
