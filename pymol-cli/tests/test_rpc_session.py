# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import Any, cast

import pytest

from pymol_cli.engine.service import EngineService
from pymol_cli.rpc.session import RpcSession


class FakeAdapter:
    def get_version(self) -> str:
        return "3.1.0"


def make_session() -> RpcSession:
    return RpcSession(EngineService(cast(Any, FakeAdapter())), token="secret")


def request(
    method: str, params: dict[str, Any] | None = None, request_id: int = 1
) -> dict[str, Any]:
    message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


def initialize(session: RpcSession) -> dict[str, Any]:
    return session.handle(
        request(
            "engine.initialize",
            {"protocol_versions": [1], "token": "secret", "client": {"name": "test"}},
        )
    )


def test_rpc_session_requires_initialize_first() -> None:
    response = make_session().handle(request("engine.info"))

    assert response["error"]["code"] == -32001
    assert "initialize" in response["error"]["message"]


@pytest.mark.parametrize("token", ["wrong", "💥"])
def test_rpc_session_rejects_wrong_token(token: str) -> None:
    session = make_session()
    response = session.handle(
        request("engine.initialize", {"protocol_versions": [1], "token": token})
    )

    assert response["error"]["code"] == -32002
    assert session.should_close


def test_rpc_session_reports_unknown_method() -> None:
    session = make_session()
    initialize(session)

    response = session.handle(request("missing.method", request_id=9))

    assert response["error"]["code"] == -32601
    assert response["id"] == 9


def test_rpc_session_converts_unexpected_service_exception_to_internal_error(
    caplog: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = EngineService(cast(Any, FakeAdapter()))
    session = RpcSession(engine, token="secret")
    initialize(session)

    def explode(_selection: str) -> None:
        raise RuntimeError("service exploded")

    monkeypatch.setattr(engine, "count_atoms", explode)
    response = session.handle(
        request("atoms.count", {"selection": "smoke"}, request_id=10)
    )

    assert response == {
        "jsonrpc": "2.0",
        "id": 10,
        "error": {"code": -32603, "message": "internal error"},
    }
    assert "service exploded" in caplog.text

    health = session.handle(request("engine.health", request_id=11))
    assert health == {"jsonrpc": "2.0", "id": 11, "result": {"ok": True}}
