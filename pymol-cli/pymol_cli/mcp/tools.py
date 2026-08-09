# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Safe MCP tool catalog and argument validation."""

from __future__ import annotations

import math
from pathlib import Path

from pymol_cli.engine.service import (
    MAX_CONTACT_CUTOFF,
    MAX_DASH_WIDTH,
    MAX_RENDER_DPI,
    MAX_RENDER_HEIGHT,
    MAX_RENDER_WIDTH,
    MAX_SCENE_SCALE,
)

from .model import JsonObject, McpError, Tool

MIN_RENDER_DIMENSION = 1
MIN_RENDER_DPI = 1


def object_schema(
    properties: JsonObject, required: list[str] | None = None
) -> JsonObject:
    schema: JsonObject = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def string_arg(description: str) -> JsonObject:
    return {"type": "string", "description": description}


def number_arg(
    description: str,
    *,
    default: float | None = None,
    minimum: float | None = None,
    maximum: float | None = None,
) -> JsonObject:
    schema: JsonObject = {"type": "number", "description": description}
    if default is not None:
        schema["default"] = default
    if minimum is not None:
        schema["exclusiveMinimum"] = minimum
    if maximum is not None:
        schema["maximum"] = maximum
    return schema


def integer_arg(
    description: str,
    *,
    default: int | None = None,
    minimum: int | None = None,
    maximum: int | None = None,
) -> JsonObject:
    schema: JsonObject = {"type": "integer", "description": description}
    if default is not None:
        schema["default"] = default
    if minimum is not None:
        schema["minimum"] = minimum
    if maximum is not None:
        schema["maximum"] = maximum
    return schema


def boolean_arg(description: str, *, default: bool | None = None) -> JsonObject:
    schema: JsonObject = {"type": "boolean", "description": description}
    if default is not None:
        schema["default"] = default
    return schema


def require_string(arguments: JsonObject, name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value:
        raise McpError(-32602, f"missing or invalid string argument: {name}")
    return value


def optional_string(arguments: JsonObject, name: str, default: str) -> str:
    value = arguments.get(name, default)
    if not isinstance(value, str) or not value:
        raise McpError(-32602, f"invalid string argument: {name}")
    return value


def optional_int(
    arguments: JsonObject,
    name: str,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    value = arguments.get(name, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise McpError(-32602, f"invalid integer argument: {name}")
    if minimum is not None and value < minimum:
        raise McpError(-32602, f"integer argument below minimum: {name}")
    if maximum is not None and value > maximum:
        raise McpError(-32602, f"integer argument above maximum: {name}")
    return value


def optional_float(
    arguments: JsonObject,
    name: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    value = arguments.get(name, default)
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise McpError(-32602, f"invalid number argument: {name}")
    result = float(value)
    if not math.isfinite(result):
        raise McpError(-32602, f"number argument must be finite: {name}")
    if minimum is not None and result <= minimum:
        raise McpError(-32602, f"number argument below minimum: {name}")
    if maximum is not None and result > maximum:
        raise McpError(-32602, f"number argument above maximum: {name}")
    return result


def optional_bool(arguments: JsonObject, name: str, default: bool) -> bool:
    value = arguments.get(name, default)
    if not isinstance(value, bool):
        raise McpError(-32602, f"invalid boolean argument: {name}")
    return value


def normalize_path(value: str) -> str:
    return str(Path(value).expanduser().resolve())


def build_tools() -> dict[str, Tool]:
    tools = [
        Tool(
            "atoms_count",
            "Count atoms matching a PyMOL selection.",
            object_schema(
                {"selection": string_arg("PyMOL selection expression")},
                ["selection"],
            ),
            lambda client, args: client.count_atoms(require_string(args, "selection")),
        ),
        Tool(
            "selection_create",
            "Create or replace a named PyMOL selection.",
            object_schema(
                {
                    "name": string_arg("Named selection identifier"),
                    "expression": string_arg("PyMOL selection expression"),
                },
                ["name", "expression"],
            ),
            lambda client, args: client.create_selection(
                require_string(args, "name"), require_string(args, "expression")
            ),
        ),
        Tool(
            "structure_load",
            "Load a local structure file into PyMOL.",
            object_schema(
                {
                    "path": string_arg("Local PDB, ENT, CIF, or mmCIF path"),
                    "object_name": string_arg("PyMOL object name"),
                },
                ["path", "object_name"],
            ),
            lambda client, args: client.load_structure(
                normalize_path(require_string(args, "path")),
                require_string(args, "object_name"),
            ),
        ),
        Tool(
            "objects_list",
            "List object names in the current PyMOL session.",
            object_schema({}),
            lambda client, args: client.list_objects(),
        ),
        Tool(
            "scene_show",
            "Show a representation for a selection.",
            object_schema(
                {
                    "representation": string_arg("Representation, e.g. cartoon"),
                    "selection": string_arg("PyMOL selection expression"),
                },
                ["representation", "selection"],
            ),
            lambda client, args: client.show_representation(
                require_string(args, "representation"),
                require_string(args, "selection"),
            ),
        ),
        Tool(
            "scene_hide",
            "Hide a representation for a selection.",
            object_schema(
                {
                    "representation": string_arg("Representation, e.g. lines"),
                    "selection": string_arg("PyMOL selection expression"),
                },
                ["representation", "selection"],
            ),
            lambda client, args: client.hide_representation(
                require_string(args, "representation"),
                require_string(args, "selection"),
            ),
        ),
        Tool(
            "scene_color",
            "Color a PyMOL selection.",
            object_schema(
                {
                    "color": string_arg("PyMOL color name"),
                    "selection": string_arg("PyMOL selection expression"),
                },
                ["color", "selection"],
            ),
            lambda client, args: client.color_selection(
                require_string(args, "color"), require_string(args, "selection")
            ),
        ),
        Tool(
            "scene_zoom",
            "Zoom to a PyMOL selection.",
            object_schema(
                {
                    "selection": string_arg("PyMOL selection expression"),
                    "buffer": number_arg("Zoom buffer in Angstroms", default=0.0),
                },
                ["selection"],
            ),
            lambda client, args: client.zoom_selection(
                require_string(args, "selection"), optional_float(args, "buffer", 0.0)
            ),
        ),
        Tool(
            "scene_label_residues",
            "Label CA atoms in a selection as residue name, residue id, and chain.",
            object_schema(
                {"selection": string_arg("PyMOL selection expression")},
                ["selection"],
            ),
            lambda client, args: client.label_residues(
                require_string(args, "selection")
            ),
        ),
        Tool(
            "scene_ball_and_stick",
            "Show scoped sticks and spheres with bounded radii.",
            object_schema(
                {
                    "selection": string_arg("PyMOL selection expression"),
                    "stick_radius": number_arg(
                        "Stick radius",
                        default=0.18,
                        minimum=0.0,
                        maximum=MAX_SCENE_SCALE,
                    ),
                    "sphere_scale": number_arg(
                        "Sphere scale",
                        default=0.25,
                        minimum=0.0,
                        maximum=MAX_SCENE_SCALE,
                    ),
                },
                ["selection"],
            ),
            lambda client, args: client.show_ball_and_stick(
                require_string(args, "selection"),
                optional_float(
                    args, "stick_radius", 0.18, minimum=0.0, maximum=MAX_SCENE_SCALE
                ),
                optional_float(
                    args, "sphere_scale", 0.25, minimum=0.0, maximum=MAX_SCENE_SCALE
                ),
            ),
        ),
        Tool(
            "scene_polar_contacts",
            "Show dashed PyMOL polar-contact geometry between two selections.",
            object_schema(
                {
                    "name": string_arg("Distance object identifier"),
                    "selection1": string_arg("First PyMOL selection"),
                    "selection2": string_arg("Second PyMOL selection"),
                    "cutoff": number_arg(
                        "Contact cutoff in Angstroms",
                        default=3.6,
                        minimum=0.0,
                        maximum=MAX_CONTACT_CUTOFF,
                    ),
                    "color": string_arg("Dash color"),
                    "dash_width": number_arg(
                        "Dash width",
                        default=2.0,
                        minimum=0.0,
                        maximum=MAX_DASH_WIDTH,
                    ),
                },
                ["name", "selection1", "selection2"],
            ),
            lambda client, args: client.show_polar_contacts(
                require_string(args, "name"),
                require_string(args, "selection1"),
                require_string(args, "selection2"),
                optional_float(
                    args, "cutoff", 3.6, minimum=0.0, maximum=MAX_CONTACT_CUTOFF
                ),
                optional_string(args, "color", "black"),
                optional_float(
                    args, "dash_width", 2.0, minimum=0.0, maximum=MAX_DASH_WIDTH
                ),
            ),
        ),
        Tool(
            "scene_background",
            "Set scene color and PNG background opacity.",
            object_schema(
                {
                    "color": string_arg("PyMOL background color"),
                    "opaque": boolean_arg("Render opaque PNG background", default=True),
                },
                ["color"],
            ),
            lambda client, args: client.set_background(
                require_string(args, "color"), optional_bool(args, "opaque", True)
            ),
        ),
        Tool(
            "render_png",
            "Render the current PyMOL view to a PNG file.",
            object_schema(
                {
                    "path": string_arg("Output PNG path"),
                    "width": integer_arg(
                        "Pixel width",
                        default=800,
                        minimum=MIN_RENDER_DIMENSION,
                        maximum=MAX_RENDER_WIDTH,
                    ),
                    "height": integer_arg(
                        "Pixel height",
                        default=600,
                        minimum=MIN_RENDER_DIMENSION,
                        maximum=MAX_RENDER_HEIGHT,
                    ),
                    "dpi": integer_arg(
                        "PNG DPI",
                        default=100,
                        minimum=MIN_RENDER_DPI,
                        maximum=MAX_RENDER_DPI,
                    ),
                    "ray": boolean_arg("Use ray tracing", default=False),
                },
                ["path"],
            ),
            lambda client, args: client.render_png(
                normalize_path(require_string(args, "path")),
                optional_int(
                    args,
                    "width",
                    800,
                    minimum=MIN_RENDER_DIMENSION,
                    maximum=MAX_RENDER_WIDTH,
                ),
                optional_int(
                    args,
                    "height",
                    600,
                    minimum=MIN_RENDER_DIMENSION,
                    maximum=MAX_RENDER_HEIGHT,
                ),
                optional_int(
                    args,
                    "dpi",
                    100,
                    minimum=MIN_RENDER_DPI,
                    maximum=MAX_RENDER_DPI,
                ),
                optional_bool(args, "ray", False),
            ),
        ),
        Tool(
            "session_summary",
            "Return a summary of the current PyMOL session.",
            object_schema({}),
            lambda client, args: client.session_summary(),
        ),
        Tool(
            "session_clear",
            "Clear the current PyMOL session.",
            object_schema({}),
            lambda client, args: client.clear_session(),
        ),
        Tool(
            "session_save",
            "Save the current PyMOL session to a PSE file.",
            object_schema({"path": string_arg("Output PSE path")}, ["path"]),
            lambda client, args: client.save_session(
                normalize_path(require_string(args, "path"))
            ),
        ),
    ]
    return {tool.name: tool for tool in tools}
