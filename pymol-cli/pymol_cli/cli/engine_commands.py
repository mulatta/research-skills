# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import argparse

from pymol_cli.cli.common import (
    DEFAULT_RENDER_TIMEOUT,
    emit,
    resolve_local_path,
    resolve_rpc_path,
)
from pymol_cli.cli.errors import CLIError


def connect_engine_client(ns: argparse.Namespace):
    from pymol_cli.lifecycle.paths import default_descriptor_path
    from pymol_cli.rpc.client import EngineClient, EngineClientError
    from pymol_cli.rpc.descriptor import read_descriptor

    descriptor_path = resolve_local_path(ns.descriptor or default_descriptor_path())
    if not descriptor_path.exists():
        raise CLIError(f"engine is not running: {descriptor_path}")
    try:
        descriptor = read_descriptor(descriptor_path)
        client = EngineClient.connect(
            descriptor.host,
            descriptor.port,
            token=descriptor.token,
            timeout=ns.timeout,
            render_timeout=getattr(ns, "render_timeout", DEFAULT_RENDER_TIMEOUT),
            expected_instance_id=descriptor.instance_id,
        )
        try:
            current_descriptor = read_descriptor(descriptor_path)
            if current_descriptor.instance_id != descriptor.instance_id:
                raise EngineClientError("engine descriptor changed during connection")
        except BaseException:
            client.close()
            raise
        return client
    except (
        EngineClientError,
        KeyError,
        OSError,
        TimeoutError,
        TypeError,
        ValueError,
    ) as exc:
        raise CLIError(f"engine is not reachable: {exc}") from exc


def cmd_unsafe_command(ns: argparse.Namespace) -> None:
    with connect_engine_client(ns) as client:
        result = client.unsafe_execute_pml(ns.pml_command)
    emit(result if ns.json else result["revision"], use_json=ns.json)


def cmd_atoms_count_engine(ns: argparse.Namespace) -> None:
    with connect_engine_client(ns) as client:
        result = client.count_atoms(ns.selection)
    emit(result if ns.json else result["count"], use_json=ns.json)


def cmd_structure_load_engine(ns: argparse.Namespace) -> None:
    path = resolve_rpc_path(ns.path)
    with connect_engine_client(ns) as client:
        result = client.load_structure(path, ns.object)
    emit(result if ns.json else result["object_name"], use_json=ns.json)


def cmd_objects_list_engine(ns: argparse.Namespace) -> None:
    with connect_engine_client(ns) as client:
        result = client.list_objects()
    emit(result if ns.json else result["object_names"], use_json=ns.json)


def cmd_scene_show_engine(ns: argparse.Namespace) -> None:
    with connect_engine_client(ns) as client:
        result = client.show_representation(ns.representation, ns.selection)
    emit(result if ns.json else result["revision"], use_json=ns.json)


def cmd_scene_hide_engine(ns: argparse.Namespace) -> None:
    with connect_engine_client(ns) as client:
        result = client.hide_representation(ns.representation, ns.selection)
    emit(result if ns.json else result["revision"], use_json=ns.json)


def cmd_scene_color_engine(ns: argparse.Namespace) -> None:
    with connect_engine_client(ns) as client:
        result = client.color_selection(ns.color, ns.selection)
    emit(result if ns.json else result["revision"], use_json=ns.json)


def cmd_scene_zoom_engine(ns: argparse.Namespace) -> None:
    with connect_engine_client(ns) as client:
        result = client.zoom_selection(ns.selection, ns.buffer)
    emit(result if ns.json else result["revision"], use_json=ns.json)


def cmd_scene_label_residues_engine(ns: argparse.Namespace) -> None:
    with connect_engine_client(ns) as client:
        result = client.label_residues(ns.selection)
    emit(result if ns.json else result["revision"], use_json=ns.json)


def cmd_session_summary(ns: argparse.Namespace) -> None:
    with connect_engine_client(ns) as client:
        result = client.session_summary()
    emit(result, use_json=ns.json)


def cmd_session_clear(ns: argparse.Namespace) -> None:
    with connect_engine_client(ns) as client:
        result = client.call("session.clear")
    emit(result if ns.json else result["revision"], use_json=ns.json)


def cmd_session_save(ns: argparse.Namespace) -> None:
    path = resolve_rpc_path(ns.path)
    with connect_engine_client(ns) as client:
        result = client.save_session(path)
    emit(result if ns.json else result["path"], use_json=ns.json)


def cmd_session_restore(ns: argparse.Namespace) -> None:
    path = resolve_rpc_path(ns.path)
    with connect_engine_client(ns) as client:
        result = client.restore_session(path)
    emit(result if ns.json else result["path"], use_json=ns.json)


def cmd_render_png_engine(ns: argparse.Namespace) -> None:
    output = resolve_rpc_path(ns.output)
    with connect_engine_client(ns) as client:
        result = client.render_png(output, ns.width, ns.height, ns.dpi, ns.ray)
    emit(result if ns.json else result["path"], use_json=ns.json)
