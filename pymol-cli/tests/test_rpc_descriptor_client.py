# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pymol_cli.engine.service import EngineService
from pymol_cli.rpc.client import EngineClient, EngineClientError
from pymol_cli.rpc.descriptor import EngineDescriptor, write_descriptor
from pymol_cli.rpc.server import RpcServer


class FakeAdapter:
    def get_version(self) -> str:
        return "3.1.0"

    def get_object_names(self) -> list[str]:
        return []

    def count_atoms(self, selection: str) -> int:
        return 0

    def load_structure(self, path: str, object_name: str) -> None:
        self.objects = [object_name]
        self.atom_count = 0

    def show_representation(self, representation: str, selection: str) -> None:
        return None

    def hide_representation(self, representation: str, selection: str) -> None:
        return None

    def color_selection(self, color: str, selection: str) -> None:
        return None

    def zoom_selection(self, selection: str, buffer: float) -> None:
        return None

    def label_residues(self, selection: str) -> None:
        return None

    def create_selection(self, name: str, expression: str) -> None:
        return None

    def show_ball_and_stick(
        self, selection: str, stick_radius: float, sphere_scale: float
    ) -> None:
        return None

    def show_polar_contacts(
        self,
        name: str,
        selection1: str,
        selection2: str,
        cutoff: float,
        color: str,
        dash_width: float,
    ) -> None:
        return None

    def set_background(self, color: str, opaque: bool) -> None:
        return None

    def render_png(
        self, path: str, width: int, height: int, dpi: int, ray: bool
    ) -> None:
        return None

    def save_session(self, path: str) -> None:
        return None

    def restore_session(self, path: str) -> None:
        return None

    def execute_pml(self, command: str) -> Any:
        return None

    def clear(self) -> None:
        pass


def test_engine_client_connects_from_descriptor(tmp_path: Path) -> None:
    server = RpcServer(
        EngineService(FakeAdapter()), token="secret", instance_id="instance-1"
    )
    server.start()
    descriptor_path = tmp_path / "engine.json"
    write_descriptor(
        descriptor_path,
        EngineDescriptor(
            protocol_versions=[1],
            instance_id="instance-1",
            pid=123,
            mode="gui",
            host="127.0.0.1",
            port=server.port,
            token="secret",
            started_at="2026-08-07T04:00:00Z",
        ),
    )

    try:
        with EngineClient.connect_descriptor(descriptor_path) as client:
            assert client.info()["backend_version"] == "3.1.0"
    finally:
        server.stop()


def test_descriptor_connection_rejects_authenticated_instance_mismatch(
    tmp_path: Path,
) -> None:
    server = RpcServer(
        EngineService(FakeAdapter()), token="secret", instance_id="actual-instance"
    )
    server.start()
    descriptor_path = tmp_path / "engine.json"
    write_descriptor(
        descriptor_path,
        EngineDescriptor(
            protocol_versions=[1],
            instance_id="replaced-instance",
            pid=123,
            mode="gui",
            host="127.0.0.1",
            port=server.port,
            token="secret",
            started_at="now",
        ),
    )

    try:
        with pytest.raises(EngineClientError, match="does not match descriptor"):
            EngineClient.connect_descriptor(descriptor_path)
    finally:
        server.stop()
