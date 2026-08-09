# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import pytest

from pymol_cli.engine.embedded import EmbeddedPyMOLAdapter
from pymol_cli.engine.errors import EngineError, ErrorCategory
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


def test_embedded_pml_failure_is_reported_and_stops_later_commands() -> None:
    with EmbeddedPyMOLAdapter() as adapter:
        engine = EngineService(adapter)
        engine.execute_pml("fragment ala, source")

        with pytest.raises(EngineError) as exc_info:
            engine.execute_pml("label source, resn; fragment ala, must_not_be_created")

        assert exc_info.value.category is ErrorCategory.BACKEND_FAILURE
        assert exc_info.value.details == {
            "operation": "unsafe.execute_pml",
            "line": 1,
        }
        assert engine.revision == 1
        assert adapter.get_object_names() == ["source"]


def test_embedded_pml_newlines_execute_as_separate_commands() -> None:
    with EmbeddedPyMOLAdapter() as adapter:
        engine = EngineService(adapter)

        result = engine.execute_pml("fragment ala, model_one\nfragment gly, model_two")

        assert result.revision == 1
        assert adapter.get_object_names() == ["model_one", "model_two"]
