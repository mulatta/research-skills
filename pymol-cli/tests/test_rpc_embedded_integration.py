# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

from pymol_cli.engine.embedded import EmbeddedPyMOLAdapter
from pymol_cli.engine.service import EngineService
from pymol_cli.rpc.client import EngineClient
from pymol_cli.rpc.server import RpcServer


def test_rpc_server_controls_real_embedded_pymol() -> None:
    with EmbeddedPyMOLAdapter() as adapter:
        server = RpcServer(EngineService(adapter), token="secret")
        server.start()
        try:
            with EngineClient.connect(
                "127.0.0.1", server.port, token="secret"
            ) as client:
                assert client.unsafe_execute_pml("fragment ala, smoke")["revision"] == 1
                assert client.count_atoms("smoke")["count"] == 10
                assert client.session_summary()["object_names"] == ["smoke"]
                assert client.shutdown() == {"ok": True}
            assert server.wait_stopped(timeout=2)
        finally:
            server.stop()
