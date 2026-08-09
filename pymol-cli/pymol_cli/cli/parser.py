# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import argparse
from pathlib import Path

from pymol_cli.cli.common import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_RENDER_TIMEOUT,
    positive_finite_float,
)
from pymol_cli.cli.engine_commands import (
    cmd_atoms_count_engine,
    cmd_objects_list_engine,
    cmd_render_png_engine,
    cmd_scene_background_engine,
    cmd_scene_ball_and_stick_engine,
    cmd_scene_color_engine,
    cmd_scene_hide_engine,
    cmd_scene_label_residues_engine,
    cmd_scene_polar_contacts_engine,
    cmd_scene_show_engine,
    cmd_scene_zoom_engine,
    cmd_selection_create_engine,
    cmd_session_clear,
    cmd_session_restore,
    cmd_session_save,
    cmd_session_summary,
    cmd_structure_load_engine,
    cmd_unsafe_command,
)
from pymol_cli.cli.engine_lifecycle import (
    cmd_engine_logs,
    cmd_engine_start,
    cmd_engine_status,
    cmd_engine_stop,
)
from pymol_cli.cli.launch import cmd_launch
from pymol_cli.cli.xmlrpc_commands import (
    cmd_count,
    cmd_do,
    cmd_ligand_pocket,
    cmd_load,
    cmd_script,
    cmd_status,
)


def add_engine_attach_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--descriptor", type=Path)
    parser.add_argument("--timeout", type=positive_finite_float, default=5.0)
    parser.add_argument(
        "--render-timeout", type=positive_finite_float, default=DEFAULT_RENDER_TIMEOUT
    )
    parser.add_argument("-j", "--json", action="store_true")


def add_connection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--timeout", type=positive_finite_float, default=5.0)
    parser.add_argument("-j", "--json", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pymol-cli")
    sub = parser.add_subparsers(dest="command_name", required=True)

    engine = sub.add_parser("engine", help="manage the local PyMOL engine")
    engine_sub = engine.add_subparsers(dest="engine_command", required=True)

    engine_start = engine_sub.add_parser("start", help="start the local PyMOL engine")
    engine_start.add_argument("--descriptor", type=Path)
    engine_start.add_argument("--log", type=Path)
    engine_start.add_argument("--timeout", type=positive_finite_float, default=30.0)
    mode_options = engine_start.add_mutually_exclusive_group()
    mode_options.add_argument("--embedded", action="store_true", help=argparse.SUPPRESS)
    mode_options.add_argument(
        "--current-process", action="store_true", help=argparse.SUPPRESS
    )
    mode_options.add_argument("--headless", action="store_true")
    engine_start.add_argument(
        "--pymol-command", default="pymol", help=argparse.SUPPRESS
    )
    engine_start.add_argument("--token", help=argparse.SUPPRESS)
    engine_start.add_argument("-j", "--json", action="store_true")
    engine_start.set_defaults(func=cmd_engine_start)

    engine_status = engine_sub.add_parser("status", help="check local engine status")
    engine_status.add_argument("--descriptor", type=Path)
    engine_status.add_argument("--timeout", type=positive_finite_float, default=5.0)
    engine_status.add_argument("-j", "--json", action="store_true")
    engine_status.set_defaults(func=cmd_engine_status)

    engine_logs = engine_sub.add_parser("logs", help="show local engine logs")
    engine_logs.add_argument("--descriptor", type=Path)
    engine_logs.add_argument("--log", type=Path)
    engine_logs.add_argument("--lines", type=int, default=80)
    engine_logs.add_argument("-j", "--json", action="store_true")
    engine_logs.set_defaults(func=cmd_engine_logs)

    engine_stop = engine_sub.add_parser("stop", help="stop the local PyMOL engine")
    engine_stop.add_argument("--descriptor", type=Path)
    engine_stop.add_argument("--timeout", type=positive_finite_float, default=5.0)
    engine_stop.add_argument("-j", "--json", action="store_true")
    engine_stop.set_defaults(func=cmd_engine_stop)

    unsafe = sub.add_parser("unsafe", help="run explicitly unsafe engine commands")
    unsafe_sub = unsafe.add_subparsers(dest="unsafe_command", required=True)
    unsafe_command = unsafe_sub.add_parser("command", help="send one raw PML command")
    unsafe_command.add_argument("pml_command")
    add_engine_attach_args(unsafe_command)
    unsafe_command.set_defaults(func=cmd_unsafe_command)

    atoms = sub.add_parser("atoms", help="query atoms through the local engine")
    atoms_sub = atoms.add_subparsers(dest="atoms_command", required=True)
    atoms_count = atoms_sub.add_parser("count", help="count atoms in a selection")
    atoms_count.add_argument("selection")
    add_engine_attach_args(atoms_count)
    atoms_count.set_defaults(func=cmd_atoms_count_engine)

    selection = sub.add_parser("selection", help="manage named selections")
    selection_sub = selection.add_subparsers(dest="selection_command", required=True)
    selection_create = selection_sub.add_parser(
        "create", help="create or replace a named selection"
    )
    selection_create.add_argument("name")
    selection_create.add_argument("expression")
    add_engine_attach_args(selection_create)
    selection_create.set_defaults(func=cmd_selection_create_engine)

    structure = sub.add_parser("structure", help="load structures through the engine")
    structure_sub = structure.add_subparsers(dest="structure_command", required=True)
    structure_load = structure_sub.add_parser("load", help="load a structure file")
    structure_load.add_argument("path")
    structure_load.add_argument("--object", required=True)
    add_engine_attach_args(structure_load)
    structure_load.set_defaults(func=cmd_structure_load_engine)

    objects = sub.add_parser("objects", help="list engine objects")
    objects_sub = objects.add_subparsers(dest="objects_command", required=True)
    objects_list = objects_sub.add_parser("list", help="list object names")
    add_engine_attach_args(objects_list)
    objects_list.set_defaults(func=cmd_objects_list_engine)

    scene = sub.add_parser("scene", help="change current scene")
    scene_sub = scene.add_subparsers(dest="scene_command", required=True)
    scene_show = scene_sub.add_parser("show", help="show a representation")
    scene_show.add_argument("representation")
    scene_show.add_argument("selection")
    add_engine_attach_args(scene_show)
    scene_show.set_defaults(func=cmd_scene_show_engine)
    scene_hide = scene_sub.add_parser("hide", help="hide a representation")
    scene_hide.add_argument("representation")
    scene_hide.add_argument("selection")
    add_engine_attach_args(scene_hide)
    scene_hide.set_defaults(func=cmd_scene_hide_engine)
    scene_color = scene_sub.add_parser("color", help="color a selection")
    scene_color.add_argument("color")
    scene_color.add_argument("selection")
    add_engine_attach_args(scene_color)
    scene_color.set_defaults(func=cmd_scene_color_engine)
    scene_zoom = scene_sub.add_parser("zoom", help="zoom to a selection")
    scene_zoom.add_argument("selection")
    scene_zoom.add_argument("--buffer", type=float, default=0.0)
    add_engine_attach_args(scene_zoom)
    scene_zoom.set_defaults(func=cmd_scene_zoom_engine)
    scene_label_residues = scene_sub.add_parser(
        "label-residues", help="label alpha-carbon residues"
    )
    scene_label_residues.add_argument("selection")
    add_engine_attach_args(scene_label_residues)
    scene_label_residues.set_defaults(func=cmd_scene_label_residues_engine)
    scene_ball_and_stick = scene_sub.add_parser(
        "ball-and-stick", help="show a scoped ball-and-stick representation"
    )
    scene_ball_and_stick.add_argument("selection")
    scene_ball_and_stick.add_argument(
        "--stick-radius", type=positive_finite_float, default=0.18
    )
    scene_ball_and_stick.add_argument(
        "--sphere-scale", type=positive_finite_float, default=0.25
    )
    add_engine_attach_args(scene_ball_and_stick)
    scene_ball_and_stick.set_defaults(func=cmd_scene_ball_and_stick_engine)
    scene_polar_contacts = scene_sub.add_parser(
        "polar-contacts", help="show dashed polar-contact geometry"
    )
    scene_polar_contacts.add_argument("name")
    scene_polar_contacts.add_argument("selection1")
    scene_polar_contacts.add_argument("selection2")
    scene_polar_contacts.add_argument(
        "--cutoff", type=positive_finite_float, default=3.6
    )
    scene_polar_contacts.add_argument("--color", default="black")
    scene_polar_contacts.add_argument(
        "--dash-width", type=positive_finite_float, default=2.0
    )
    add_engine_attach_args(scene_polar_contacts)
    scene_polar_contacts.set_defaults(func=cmd_scene_polar_contacts_engine)
    scene_background = scene_sub.add_parser(
        "background", help="set scene and rendered PNG background"
    )
    scene_background.add_argument("color")
    scene_background.add_argument(
        "--transparent", action="store_false", dest="opaque", default=True
    )
    add_engine_attach_args(scene_background)
    scene_background.set_defaults(func=cmd_scene_background_engine)

    session = sub.add_parser("session", help="inspect or mutate the engine session")
    session_sub = session.add_subparsers(dest="session_command", required=True)
    session_summary = session_sub.add_parser(
        "summary", help="summarize current session"
    )
    add_engine_attach_args(session_summary)
    session_summary.set_defaults(func=cmd_session_summary)
    session_clear = session_sub.add_parser("clear", help="clear the current session")
    add_engine_attach_args(session_clear)
    session_clear.set_defaults(func=cmd_session_clear)
    session_save = session_sub.add_parser("save", help="save current session")
    session_save.add_argument("path")
    add_engine_attach_args(session_save)
    session_save.set_defaults(func=cmd_session_save)
    session_restore = session_sub.add_parser("restore", help="restore a saved session")
    session_restore.add_argument("path")
    add_engine_attach_args(session_restore)
    session_restore.set_defaults(func=cmd_session_restore)

    status = sub.add_parser("status", help="check PyMOL XML-RPC connectivity")
    add_connection_args(status)
    status.set_defaults(func=cmd_status)

    do = sub.add_parser("do", help="send one or more PyMOL commands")
    add_connection_args(do)
    do.add_argument("command", nargs="*")
    do.add_argument("--file", action="append", default=[])
    do.add_argument("--stdin", action="store_true")
    do.add_argument("--dry-run", action="store_true")
    do.set_defaults(func=cmd_do)

    script = sub.add_parser("script", help="send a .pml file or '-' stdin")
    add_connection_args(script)
    script.add_argument("path")
    script.add_argument("--dry-run", action="store_true")
    script.set_defaults(func=cmd_script)

    count = sub.add_parser("count", help="count atoms for a PyMOL selection")
    add_connection_args(count)
    count.add_argument("selection")
    count.set_defaults(func=cmd_count)

    load = sub.add_parser("load", help="load a structure and apply basic styling")
    add_connection_args(load)
    load.add_argument("path")
    load.add_argument("--object", required=True)
    load.add_argument(
        "--style", choices=["none", "cartoon", "sticks", "surface"], default="cartoon"
    )
    load.add_argument("--color")
    load.add_argument("--no-orient", action="store_true")
    load.add_argument("--zoom-buffer", type=float, default=8.0)
    load.add_argument("--allow-url", action="store_true")
    load.add_argument("--output")
    load.add_argument("--dry-run", action="store_true")
    load.set_defaults(func=cmd_load)

    render = sub.add_parser("render", help="render current engine scene")
    render_sub = render.add_subparsers(dest="render_command", required=True)
    render_png = render_sub.add_parser("png", help="write a PNG from the current view")
    render_png.add_argument("output")
    render_png.add_argument("--width", type=int, default=1600)
    render_png.add_argument("--height", type=int, default=1200)
    render_png.add_argument("--dpi", type=int, default=200)
    render_png.add_argument("--ray", action="store_true")
    add_engine_attach_args(render_png)
    render_png.set_defaults(func=cmd_render_png_engine)

    launch = sub.add_parser("launch", help="start PyMOL with XML-RPC enabled")
    launch.add_argument("--pymol-command", default="pymol")
    launch.add_argument("--script")
    launch.add_argument("--headless", action="store_true")
    launch.add_argument("--no-remote", action="store_true")
    launch_runner = launch.add_mutually_exclusive_group()
    launch_runner.add_argument("--foreground", action="store_true")
    launch_runner.add_argument(
        "--pueue", action="store_true", help="submit launch through pueue"
    )
    launch.add_argument("--dry-run", action="store_true")
    launch.add_argument("-j", "--json", action="store_true")
    launch.add_argument("extra_args", nargs=argparse.REMAINDER)
    launch.set_defaults(func=cmd_launch)

    pocket = sub.add_parser("ligand-pocket", help="generate or send ligand-pocket view")
    add_connection_args(pocket)
    pocket.add_argument("--object", default="all")
    pocket.add_argument("--ligand", default="HEM")
    pocket.add_argument("--chains", required=True)
    pocket.add_argument("--distance", type=float, default=4.0)
    pocket.add_argument("--color", action="append", default=[], help="CHAIN:COLOR")
    pocket.add_argument("--mark", action="append", default=[], help="CHAIN:RESI[,RESI]")
    pocket.add_argument("--grid", action="store_true")
    pocket.add_argument("--scene")
    pocket.add_argument("--keep-source", action="store_true")
    pocket.add_argument("--output")
    validation = pocket.add_mutually_exclusive_group()
    validation.add_argument("--no-validate", action="store_true")
    validation.add_argument("--strict-chains", action="store_true")
    pocket.add_argument("--send", action="store_true")
    pocket.set_defaults(func=cmd_ligand_pocket)

    return parser
