# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Authenticated JSON-RPC session dispatcher."""

from __future__ import annotations

import logging
import secrets
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from typing import Any

from pymol_cli.engine.errors import EngineError, ErrorCategory
from pymol_cli.engine.models import PROTOCOL_VERSION, EngineInfo
from pymol_cli.engine.service import EngineService
from pymol_cli.rpc.protocol import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    JsonRpcError,
    JsonRpcRequest,
    build_error,
    build_result,
    parse_request,
)

AUTH_REQUIRED = -32001
AUTH_FAILED = -32002
ENGINE_ERROR = -32010
_LOGGER = logging.getLogger(__name__)


class RpcSession:
    """Dispatch JSON-RPC messages for one authenticated client connection."""

    def __init__(
        self,
        engine: EngineService,
        *,
        token: str,
        instance_id: str = "standalone",
        initialization_info: EngineInfo | None = None,
    ) -> None:
        self._engine = engine
        self._token = token
        self._instance_id = instance_id
        self._initialization_info = initialization_info or engine.get_info()
        self._initialized = False
        self.should_close = False
        self.should_shutdown = False

    @property
    def initialized(self) -> bool:
        return self._initialized

    def handle(self, message: dict[str, Any]) -> dict[str, Any]:
        try:
            request = parse_request(message)
            result = self._dispatch(request)
            return build_result(request.id, _to_json_value(result))
        except JsonRpcError as exc:
            return build_error(exc)
        except EngineError as exc:
            request_id = message.get("id") if isinstance(message, dict) else None
            return build_error(_engine_error(exc, request_id))
        except Exception:
            # Backend adapters should normalize expected failures to EngineError.
            # This boundary keeps programming or serialization defects isolated
            # to one request while preserving diagnostics in the local log.
            _LOGGER.exception("unexpected exception while handling RPC request")
            request_id = message.get("id") if isinstance(message, dict) else None
            return build_error(
                JsonRpcError(INTERNAL_ERROR, "internal error", _safe_id(request_id))
            )

    def _dispatch(self, request: JsonRpcRequest) -> Any:
        if not self._initialized:
            if request.method != "engine.initialize":
                raise JsonRpcError(
                    AUTH_REQUIRED,
                    "engine.initialize must be the first request",
                    request.id,
                )
            return self._initialize(request)
        if request.method == "engine.initialize":
            return {"ok": True, "already_initialized": True}
        methods: dict[str, Callable[[JsonRpcRequest], Any]] = {
            "engine.health": self._health,
            "engine.info": self._info,
            "engine.shutdown": self._shutdown,
            "session.summary": self._session_summary,
            "session.clear": self._session_clear,
            "objects.list": self._objects_list,
            "structure.load": self._structure_load,
            "atoms.count": self._atoms_count,
            "selection.create": self._selection_create,
            "scene.show": self._scene_show,
            "scene.hide": self._scene_hide,
            "scene.color": self._scene_color,
            "scene.zoom": self._scene_zoom,
            "scene.label_residues": self._scene_label_residues,
            "scene.ball_and_stick": self._scene_ball_and_stick,
            "scene.polar_contacts": self._scene_polar_contacts,
            "scene.background": self._scene_background,
            "render.png": self._render_png,
            "session.save": self._session_save,
            "session.restore": self._session_restore,
            "unsafe.execute_pml": self._unsafe_execute_pml,
        }
        handler = methods.get(request.method)
        if handler is None:
            raise JsonRpcError(METHOD_NOT_FOUND, "method not found", request.id)
        return handler(request)

    def _initialize(self, request: JsonRpcRequest) -> dict[str, Any]:
        token = request.params.get("token")
        versions = request.params.get("protocol_versions")
        if not isinstance(token, str) or not secrets.compare_digest(
            token.encode("utf-8", errors="surrogatepass"),
            self._token.encode("utf-8", errors="surrogatepass"),
        ):
            self.should_close = True
            raise JsonRpcError(AUTH_FAILED, "authentication failed", request.id)
        if not isinstance(versions, list) or PROTOCOL_VERSION not in versions:
            raise JsonRpcError(
                INVALID_PARAMS,
                "compatible protocol version not offered",
                request.id,
            )
        self._initialized = True
        info = self._initialization_info
        return {
            "protocol_version": PROTOCOL_VERSION,
            "instance_id": self._instance_id,
            "engine_version": info.engine_version,
            "backend": info.backend,
            "backend_version": info.backend_version,
            "capabilities": list(info.capabilities),
        }

    @staticmethod
    def _health(request: JsonRpcRequest) -> dict[str, Any]:
        _require_no_params(request)
        return {"ok": True}

    def _info(self, request: JsonRpcRequest) -> Any:
        _require_no_params(request)
        return self._engine.get_info()

    def _shutdown(self, request: JsonRpcRequest) -> dict[str, bool]:
        _require_no_params(request)
        self.should_shutdown = True
        return {"ok": True}

    def _session_summary(self, request: JsonRpcRequest) -> Any:
        _require_no_params(request)
        return self._engine.get_session_summary()

    def _session_clear(self, request: JsonRpcRequest) -> Any:
        _require_no_params(request)
        return self._engine.clear_session()

    def _objects_list(self, request: JsonRpcRequest) -> Any:
        _require_no_params(request)
        return self._engine.list_objects()

    def _structure_load(self, request: JsonRpcRequest) -> Any:
        path = _require_string_param(request, "path")
        object_name = _require_string_param(request, "object_name")
        return self._engine.load_structure(path=path, object_name=object_name)

    def _atoms_count(self, request: JsonRpcRequest) -> Any:
        selection = _require_string_param(request, "selection")
        return self._engine.count_atoms(selection)

    def _selection_create(self, request: JsonRpcRequest) -> Any:
        return self._engine.create_selection(
            _require_string_param(request, "name"),
            _require_string_param(request, "expression"),
        )

    def _scene_show(self, request: JsonRpcRequest) -> Any:
        return self._engine.show_representation(
            _require_string_param(request, "representation"),
            _require_string_param(request, "selection"),
        )

    def _scene_hide(self, request: JsonRpcRequest) -> Any:
        return self._engine.hide_representation(
            _require_string_param(request, "representation"),
            _require_string_param(request, "selection"),
        )

    def _scene_color(self, request: JsonRpcRequest) -> Any:
        return self._engine.color_selection(
            _require_string_param(request, "color"),
            _require_string_param(request, "selection"),
        )

    def _scene_zoom(self, request: JsonRpcRequest) -> Any:
        buffer = request.params.get("buffer", 0.0)
        if not isinstance(buffer, int | float):
            raise JsonRpcError(INVALID_PARAMS, "buffer must be a number", request.id)
        return self._engine.zoom_selection(
            _require_string_param(request, "selection"), buffer=float(buffer)
        )

    def _scene_label_residues(self, request: JsonRpcRequest) -> Any:
        return self._engine.label_residues(_require_string_param(request, "selection"))

    def _scene_ball_and_stick(self, request: JsonRpcRequest) -> Any:
        return self._engine.show_ball_and_stick(
            _require_string_param(request, "selection"),
            stick_radius=_require_number_param(request, "stick_radius"),
            sphere_scale=_require_number_param(request, "sphere_scale"),
        )

    def _scene_polar_contacts(self, request: JsonRpcRequest) -> Any:
        return self._engine.show_polar_contacts(
            _require_string_param(request, "name"),
            _require_string_param(request, "selection1"),
            _require_string_param(request, "selection2"),
            cutoff=_require_number_param(request, "cutoff"),
            color=_require_string_param(request, "color"),
            dash_width=_require_number_param(request, "dash_width"),
        )

    def _scene_background(self, request: JsonRpcRequest) -> Any:
        return self._engine.set_background(
            _require_string_param(request, "color"),
            opaque=_require_bool_param(request, "opaque"),
        )

    def _render_png(self, request: JsonRpcRequest) -> Any:
        return self._engine.render_png(
            path=_require_string_param(request, "path"),
            width=_require_int_param(request, "width"),
            height=_require_int_param(request, "height"),
            dpi=_require_int_param(request, "dpi"),
            ray=_require_bool_param(request, "ray"),
        )

    def _session_save(self, request: JsonRpcRequest) -> Any:
        return self._engine.save_session(_require_string_param(request, "path"))

    def _session_restore(self, request: JsonRpcRequest) -> Any:
        return self._engine.restore_session(_require_string_param(request, "path"))

    def _unsafe_execute_pml(self, request: JsonRpcRequest) -> Any:
        command = request.params.get("command")
        if not isinstance(command, str):
            raise JsonRpcError(INVALID_PARAMS, "command must be a string", request.id)
        return self._engine.execute_pml(command)


def _require_no_params(request: JsonRpcRequest) -> None:
    if request.params:
        raise JsonRpcError(INVALID_PARAMS, "method does not accept params", request.id)


def _require_string_param(request: JsonRpcRequest, name: str) -> str:
    value = request.params.get(name)
    if not isinstance(value, str):
        raise JsonRpcError(INVALID_PARAMS, f"{name} must be a string", request.id)
    return value


def _require_int_param(request: JsonRpcRequest, name: str) -> int:
    value = request.params.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise JsonRpcError(INVALID_PARAMS, f"{name} must be an integer", request.id)
    return value


def _require_number_param(request: JsonRpcRequest, name: str) -> float:
    value = request.params.get(name)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise JsonRpcError(INVALID_PARAMS, f"{name} must be a number", request.id)
    return float(value)


def _require_bool_param(request: JsonRpcRequest, name: str) -> bool:
    value = request.params.get(name)
    if not isinstance(value, bool):
        raise JsonRpcError(INVALID_PARAMS, f"{name} must be a boolean", request.id)
    return value


def _engine_error(error: EngineError, request_id: Any) -> JsonRpcError:
    return JsonRpcError(
        ENGINE_ERROR,
        error.message,
        _safe_id(request_id),
        {"category": error.category.value, "details": error.details},
    )


def _safe_id(value: Any) -> str | int | None:
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _to_json_value(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _to_json_value(asdict(value))
    if isinstance(value, dict):
        return {str(key): _to_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json_value(item) for item in value]
    if isinstance(value, ErrorCategory):
        return value.value
    return value
