# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Self, cast

import pytest

from pymol_cli import main
from pymol_cli.cli import engine_commands, engine_lifecycle
from pymol_cli.cli import parser as cli_parser
from pymol_cli.cli.errors import CLIError
from pymol_cli.rpc.client import EngineClientError
from pymol_cli.rpc.descriptor import EngineDescriptor, read_descriptor, write_descriptor


class _Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def load_structure(self, *args: Any) -> dict[str, Any]:
        self.calls.append(("load", args))
        return {"object_name": args[1]}

    def save_session(self, *args: Any) -> dict[str, Any]:
        self.calls.append(("save", args))
        return {"path": args[0]}

    def restore_session(self, *args: Any) -> dict[str, Any]:
        self.calls.append(("restore", args))
        return {"path": args[0]}

    def render_png(self, *args: Any) -> dict[str, Any]:
        self.calls.append(("render", args))
        return {"path": args[0]}

    def label_residues(self, *args: Any) -> dict[str, Any]:
        self.calls.append(("label", args))
        return {"revision": 1}


def test_windows_liveness_never_calls_os_kill(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine_lifecycle.os, "name", "nt")
    monkeypatch.setattr(
        engine_lifecycle, "_is_process_alive_windows", lambda pid: pid == 42
    )

    def forbidden_kill(_pid: int, _signal: int) -> None:
        raise AssertionError("os.kill(pid, 0) is unsafe on Windows")

    monkeypatch.setattr(engine_lifecycle.os, "kill", forbidden_kill)

    assert engine_lifecycle.is_process_alive(42) is True
    assert engine_lifecycle.is_process_alive(43) is False


def test_liveness_probe_never_terminates_live_process() -> None:
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert engine_lifecycle.is_process_alive(process.pid)
        assert process.poll() is None
    finally:
        process.terminate()
        process.wait(timeout=5)


@pytest.mark.parametrize(
    ("handler", "namespace", "kind", "argument_index"),
    [
        (
            engine_commands.cmd_structure_load_engine,
            {"path": "inputs/model.pdb", "object": "prot"},
            "load",
            0,
        ),
        (engine_commands.cmd_session_save, {"path": "outputs/state.pse"}, "save", 0),
        (
            engine_commands.cmd_session_restore,
            {"path": "inputs/state.pse"},
            "restore",
            0,
        ),
        (
            engine_commands.cmd_render_png_engine,
            {
                "output": "outputs/view.png",
                "width": 10,
                "height": 20,
                "dpi": 72,
                "ray": False,
            },
            "render",
            0,
        ),
    ],
)
def test_typed_rpc_paths_are_resolved_in_caller(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    handler: Any,
    namespace: dict[str, Any],
    kind: str,
    argument_index: int,
) -> None:
    client = _Client()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(engine_commands, "connect_engine_client", lambda _ns: client)
    ns = argparse.Namespace(json=True, **namespace)

    handler(ns)

    assert client.calls[0][0] == kind
    sent_path = Path(client.calls[0][1][argument_index])
    assert sent_path.is_absolute()
    source_path = namespace.get("path", namespace.get("output"))
    assert isinstance(source_path, str)
    assert sent_path == (tmp_path / source_path).resolve()
    json.loads(capsys.readouterr().out)


def test_scene_label_residues_parser_and_handler(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    client = _Client()
    monkeypatch.setattr(engine_commands, "connect_engine_client", lambda _ns: client)
    ns = cli_parser.build_parser().parse_args(
        ["scene", "label-residues", "prot and name CA", "--json"]
    )

    ns.func(ns)

    assert client.calls == [("label", ("prot and name CA",))]
    assert json.loads(capsys.readouterr().out) == {"revision": 1}


def test_engine_operation_errors_are_concise_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class BrokenClient(_Client):
        def count_atoms(self, *_args: Any) -> dict[str, Any]:
            raise EngineClientError("selection rejected")

    descriptor = tmp_path / "engine.json"
    descriptor.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        engine_commands, "connect_engine_client", lambda _ns: BrokenClient()
    )

    with pytest.raises(SystemExit, match="1"):
        main.main(["atoms", "count", "all", "--descriptor", str(descriptor)])

    stderr = capsys.readouterr().err
    assert stderr == "pymol-cli: engine operation failed: selection rejected\n"
    assert "Traceback" not in stderr


def test_corrupt_descriptor_missing_fields_is_removed_as_stale(tmp_path: Path) -> None:
    descriptor = tmp_path / "engine.json"
    descriptor.write_text("{}", encoding="utf-8")

    assert engine_lifecycle.remove_stale_descriptor_if_dead(descriptor) is True
    assert not descriptor.exists()


def test_engine_readiness_requires_matching_launch_nonce(tmp_path: Path) -> None:
    descriptor_path = tmp_path / "engine.json"
    write_descriptor(
        descriptor_path,
        EngineDescriptor(
            protocol_versions=[1],
            instance_id="other",
            pid=123,
            mode="embedded",
            host="127.0.0.1",
            port=1,
            token="token",
            started_at="now",
        ),
    )
    descriptor = engine_lifecycle.read_matching_launch_descriptor(
        descriptor_path, instance_id="ours"
    )
    assert descriptor is None

    write_descriptor(
        descriptor_path,
        EngineDescriptor(
            protocol_versions=[1],
            instance_id="ours",
            pid=999,
            mode="embedded",
            host="127.0.0.1",
            port=1,
            token="token",
            started_at="now",
        ),
    )
    descriptor = engine_lifecycle.read_matching_launch_descriptor(
        descriptor_path, instance_id="ours"
    )
    assert descriptor is not None
    assert descriptor.pid == 999


def test_launch_defaults_to_detached_popen_without_pueue(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    captured: dict[str, Any] = {}

    class Process:
        pid = 4321

    def popen(command: list[str], **kwargs: Any) -> Process:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr(engine_lifecycle.subprocess, "Popen", popen)
    monkeypatch.setattr(
        engine_lifecycle.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("pueue must be opt-in")
        ),
    )
    ns = cli_parser.build_parser().parse_args(["launch", "--json"])

    ns.func(ns)

    payload = json.loads(capsys.readouterr().out)
    assert payload["pid"] == 4321
    assert payload["detached"] is True
    assert captured["command"] == ["pymol", "-R"]
    if os.name == "posix":
        assert captured["kwargs"]["start_new_session"] is True
    assert captured["kwargs"]["stdin"] is engine_lifecycle.subprocess.DEVNULL


def test_launch_uses_pueue_only_when_requested(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Completed:
        returncode = 0
        stdout = "17\n"
        stderr = ""

    captured: list[str] = []

    def run(command: list[str], **_kwargs: Any) -> Completed:
        captured.extend(command)
        return Completed()

    monkeypatch.setattr(engine_lifecycle.subprocess, "run", run)
    monkeypatch.setattr(
        engine_lifecycle.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("direct Popen must not run with --pueue")
        ),
    )
    ns = cli_parser.build_parser().parse_args(["launch", "--pueue", "--json"])

    ns.func(ns)

    assert captured[:5] == ["pueue", "add", "--print-task-id", "--", "pymol"]
    assert json.loads(capsys.readouterr().out)["task_id"] == "17"


def test_bootstrap_files_are_unique(tmp_path: Path) -> None:
    descriptor = tmp_path / "engine.json"
    first = engine_lifecycle.write_pymol_bootstrap(
        descriptor_path=descriptor,
        token="token",
        background=True,
        instance_id="one",
    )
    second = engine_lifecycle.write_pymol_bootstrap(
        descriptor_path=descriptor,
        token="token",
        background=True,
        instance_id="two",
    )

    assert first != second
    assert "instance_id='one'" in first.read_text(encoding="utf-8")
    assert "instance_id='two'" in second.read_text(encoding="utf-8")
    if os.name == "posix":
        assert first.stat().st_mode & 0o777 == 0o600
        assert second.stat().st_mode & 0o777 == 0o600


def test_timeout_termination_waits_then_kills() -> None:
    events: list[str] = []

    class Process:
        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            events.append("terminate")

        def wait(self, timeout: float | None = None) -> int:
            assert timeout is not None
            events.append(f"wait:{timeout}")
            if events.count(f"wait:{timeout}") == 1:
                raise engine_lifecycle.subprocess.TimeoutExpired("engine", timeout)
            return 0

        def kill(self) -> None:
            events.append("kill")

    engine_lifecycle.terminate_launched_process(Process(), grace=0.25)

    assert events == ["terminate", "wait:0.25", "kill", "wait:0.25"]


def test_stop_falls_back_to_descriptor_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    descriptor_path = tmp_path / "engine.json"
    write_descriptor(
        descriptor_path,
        EngineDescriptor(
            protocol_versions=[1],
            instance_id="ours",
            pid=123,
            mode="embedded",
            host="127.0.0.1",
            port=1,
            token="token",
            started_at="now",
            process_identity="identity",
        ),
    )

    class Client:
        @classmethod
        def connect(cls, *_args: Any, **_kwargs: Any) -> Any:
            raise EngineClientError("connection closed")

    monkeypatch.setattr("pymol_cli.rpc.client.EngineClient", Client)
    monkeypatch.setattr(
        engine_lifecycle,
        "descriptor_process_is_alive",
        lambda descriptor: descriptor.pid == 123,
    )
    killed: list[tuple[int, str | None, float]] = []

    def terminate(pid: int, *, expected_identity: str | None, timeout: float) -> bool:
        killed.append((pid, expected_identity, timeout))
        return True

    monkeypatch.setattr(engine_lifecycle, "terminate_process_by_pid", terminate)
    ns = argparse.Namespace(descriptor=descriptor_path, timeout=0.2, json=True)

    engine_lifecycle.cmd_engine_stop(ns)

    assert killed == [(123, "identity", 0.2)]
    assert not descriptor_path.exists()
    assert json.loads(capsys.readouterr().out) == {"forced": True, "ok": True}


def test_engine_start_reports_concurrent_lock_before_spawning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pymol_cli.lifecycle.lock import engine_start_lock

    descriptor = tmp_path / "engine.json"
    monkeypatch.setattr(
        engine_lifecycle.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("locked start must not spawn")
        ),
    )
    ns = cli_parser.build_parser().parse_args(
        ["engine", "start", "--embedded", "--descriptor", str(descriptor)]
    )

    with (
        engine_start_lock(descriptor),
        pytest.raises(CLIError, match="already in progress"),
    ):
        ns.func(ns)


def test_stop_refuses_pid_only_legacy_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    descriptor_path = tmp_path / "engine.json"
    write_descriptor(
        descriptor_path,
        EngineDescriptor(
            protocol_versions=[1],
            instance_id="legacy",
            pid=123,
            mode="embedded",
            host="127.0.0.1",
            port=1,
            token="token",
            started_at="now",
        ),
    )

    class Client:
        @classmethod
        def connect(cls, *_args: Any, **_kwargs: Any) -> Any:
            raise EngineClientError("connection closed")

    monkeypatch.setattr("pymol_cli.rpc.client.EngineClient", Client)
    monkeypatch.setattr(
        engine_lifecycle, "descriptor_process_is_alive", lambda _value: True
    )
    monkeypatch.setattr(
        engine_lifecycle.os,
        "kill",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("legacy PID must never receive a signal")
        ),
    )
    ns = argparse.Namespace(descriptor=descriptor_path, timeout=0.1, json=True)

    with pytest.raises(CLIError, match="engine shutdown failed"):
        engine_lifecycle.cmd_engine_stop(ns)

    assert descriptor_path.exists()


def test_stop_never_rereads_replaced_descriptor_for_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    descriptor_path = tmp_path / "engine.json"
    old = EngineDescriptor(
        protocol_versions=[1],
        instance_id="old",
        pid=123,
        mode="embedded",
        host="127.0.0.1",
        port=1,
        token="old-token",
        started_at="now",
        process_identity="old-process",
    )
    new = EngineDescriptor(
        protocol_versions=[1],
        instance_id="new",
        pid=456,
        mode="embedded",
        host="127.0.0.1",
        port=2,
        token="new-token",
        started_at="later",
        process_identity="new-process",
    )
    write_descriptor(descriptor_path, old)
    connected: list[tuple[str, int, str]] = []
    shutdown_called = False

    class Client:
        @classmethod
        def connect(cls, host: str, port: int, *, token: str, **_kwargs: Any) -> Client:
            connected.append((host, port, token))
            return cls()

        def __enter__(self) -> Self:
            write_descriptor(descriptor_path, new)
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def shutdown(self) -> dict[str, bool]:
            nonlocal shutdown_called
            shutdown_called = True
            return {"ok": True}

    monkeypatch.setattr("pymol_cli.rpc.client.EngineClient", Client)
    monkeypatch.setattr(
        engine_lifecycle, "descriptor_process_is_alive", lambda _value: False
    )
    ns = argparse.Namespace(descriptor=descriptor_path, timeout=0.1, json=True)

    engine_lifecycle.cmd_engine_stop(ns)

    assert connected == [("127.0.0.1", 1, "old-token")]
    assert not shutdown_called
    assert read_descriptor(descriptor_path).instance_id == "new"
    assert json.loads(capsys.readouterr().out) == {"ok": True}


def test_engine_start_accepts_nonce_handoff_after_wrapper_exits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    descriptor_path = tmp_path / "engine.json"
    launch_descriptor = EngineDescriptor(
        protocol_versions=[1],
        instance_id="launch-nonce",
        pid=456,
        mode="current-process",
        host="127.0.0.1",
        port=49152,
        token="token",
        started_at="now",
        supervisor_pid=888,
        process_identity="process-identity",
    )
    captured: dict[str, Any] = {}

    class Process:
        pid = 999

        def poll(self) -> int:
            return 0

    def popen(command: list[str], **kwargs: Any) -> Process:
        captured["command"] = command
        captured["kwargs"] = kwargs
        write_descriptor(descriptor_path, launch_descriptor)
        return Process()

    monkeypatch.setattr(engine_lifecycle.subprocess, "Popen", popen)
    monkeypatch.setattr(
        engine_lifecycle.secrets, "token_hex", lambda _size: "launch-nonce"
    )

    class Client:
        @classmethod
        def connect(cls, *_args: Any, **_kwargs: Any) -> Client:
            return cls()

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr("pymol_cli.rpc.client.EngineClient", Client)
    ns = cli_parser.build_parser().parse_args(
        [
            "engine",
            "start",
            "--headless",
            "--descriptor",
            str(descriptor_path),
            "--token",
            "token",
            "--timeout",
            "1",
            "--json",
        ]
    )

    ns.func(ns)

    assert captured["kwargs"]["stdin"] is subprocess.DEVNULL
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["pid"] == 456


def test_failed_wrapper_launch_preserves_live_unterminated_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    descriptor_path = tmp_path / "engine.json"
    descriptor = EngineDescriptor(
        protocol_versions=[1],
        instance_id="launch",
        pid=456,
        mode="current-process",
        host="127.0.0.1",
        port=49152,
        token="token",
        started_at="now",
        process_identity="child-identity",
    )
    write_descriptor(descriptor_path, descriptor)

    class Process:
        pid = 999

        def poll(self) -> int:
            return 0

    class Client:
        @classmethod
        def connect(cls, *_args: Any, **_kwargs: Any) -> Any:
            raise EngineClientError("not ready")

    monkeypatch.setattr("pymol_cli.rpc.client.EngineClient", Client)
    monkeypatch.setattr(
        engine_lifecycle, "descriptor_process_is_alive", lambda _value: True
    )
    monkeypatch.setattr(
        engine_lifecycle, "terminate_process_by_pid", lambda *_args, **_kwargs: False
    )

    cleaned = engine_lifecycle.cleanup_failed_engine_launch(
        cast(subprocess.Popen[Any], Process()),
        descriptor_path=descriptor_path,
        instance_id="launch",
        token="token",
        timeout=0,
    )

    assert not cleaned
    assert read_descriptor(descriptor_path) == descriptor


def test_engine_log_is_private_from_creation(tmp_path: Path) -> None:
    log_path = tmp_path / "engine.log"
    previous_umask = os.umask(0)
    try:
        with engine_lifecycle.open_engine_log(log_path) as handle:
            handle.write(b"diagnostic\n")
    finally:
        os.umask(previous_umask)

    assert log_path.read_bytes() == b"diagnostic\n"
    if os.name == "posix":
        assert log_path.stat().st_mode & 0o777 == 0o600
