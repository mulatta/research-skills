# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from pymol_cli.cli.common import is_url, validate_residue_list, validate_token
from pymol_cli.cli.errors import CLIError


def split_mark_residues(value: str) -> list[str]:
    return [residue for residue in re.split(r"[,+]", value) if residue]


def require_mark_residues(counts: dict[str, int]) -> None:
    missing = [residue for residue, count in counts.items() if count == 0]
    if missing:
        raise CLIError(f"marked residues not found: {','.join(missing)}")


def resolve_ligand_chains(
    counts: dict[str, int], *, strict: bool, ligand: str
) -> tuple[list[str], list[str]]:
    present = [chain for chain, count in counts.items() if count > 0]
    missing = [chain for chain, count in counts.items() if count == 0]
    if not present or (strict and missing):
        missing_text = ",".join(missing)
        raise CLIError(f"ligand {ligand} not found in chains: {missing_text}")
    return present, missing


def chain_objects(chains: Sequence[str]) -> list[str]:
    return [f"site_{chain}" for chain in chains]


def selection_union(names: Sequence[str]) -> str:
    return " or ".join(names)


def pml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def write_pml(path: str, commands: Sequence[str]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(commands) + "\n")
    return output


def generate_load_pml(
    *,
    path: str,
    object_name: str,
    style: str,
    color: str | None,
    orient: bool,
    zoom_buffer: float,
    allow_url: bool,
) -> list[str]:
    validate_token(object_name, "object")
    if color is not None:
        validate_token(color, "color")
    if zoom_buffer < 0:
        raise CLIError("zoom buffer must be non-negative")
    if is_url(path) and not allow_url:
        raise CLIError("remote load URLs require --allow-url")
    lines = [f"load {pml_quote(path)}, {object_name}"]
    if style != "none":
        lines.append(f"hide everything, {object_name}")
        if style == "cartoon":
            lines.append(f"show cartoon, {object_name} and polymer")
        else:
            lines.append(f"show {style}, {object_name}")
    if color is not None:
        lines.append(f"color {color}, {object_name}")
    if orient:
        lines.extend([f"orient {object_name}", f"zoom {object_name}, {zoom_buffer:g}"])
    return lines


def generate_render_pml(
    *, output: str, width: int, height: int, dpi: int, ray: bool
) -> list[str]:
    if width <= 0 or height <= 0:
        raise CLIError("width and height must be positive")
    if dpi <= 0:
        raise CLIError("dpi must be positive")
    lines: list[str] = []
    if ray:
        lines.append(f"ray {width},{height}")
    lines.append(f"png {pml_quote(output)}, {width}, {height}, dpi={dpi}")
    return lines


def generate_ligand_pocket_pml(
    *,
    object_name: str,
    ligand: str,
    chains: Sequence[str],
    distance: float,
    colors: dict[str, str],
    marks: dict[str, str],
    grid: bool,
    scene: str | None,
    disable_source: bool,
    cleanup_chains: Sequence[str] | None = None,
) -> list[str]:
    validate_token(object_name, "object")
    validate_token(ligand, "ligand")
    validated_chains = [validate_token(chain, "chain") for chain in chains]
    cleanup_source = validated_chains if cleanup_chains is None else cleanup_chains
    validated_cleanup_chains = [
        validate_token(chain, "cleanup chain") for chain in cleanup_source
    ]
    for color in colors.values():
        validate_token(color, "color")
    for residues in marks.values():
        validate_residue_list(residues)
    if distance <= 0:
        raise CLIError("distance must be positive")

    sites = chain_objects(validated_chains)
    site_union = selection_union(sites)
    pocket_names = [f"pocket_{chain}" for chain in validated_chains]
    pocket_union = selection_union(pocket_names)
    mark_names = [f"mark_{chain}" for chain in validated_chains if chain in marks]
    mark_union = selection_union(mark_names)
    cleanup_sites = chain_objects(validated_cleanup_chains)
    cleanup_pockets = [f"pocket_{chain}" for chain in validated_cleanup_chains]
    cleanup_marks = [f"mark_{chain}" for chain in validated_cleanup_chains]
    cleanup = [*cleanup_sites, *cleanup_pockets, *cleanup_marks, "pocket_all"]

    lines = [f"delete {selection_union(cleanup)}"]
    if grid:
        lines.extend(["set grid_mode, 1", "set grid_slot, -1"])
    for chain, site in zip(validated_chains, sites):
        lines.append(f"create {site}, ({object_name} and chain {chain})")
    if disable_source:
        lines.append(f"disable {object_name}")
    lines.extend(
        [
            f"hide everything, ({site_union})",
            f"show cartoon, ({site_union}) and polymer",
            f"set cartoon_transparency, 0.65, ({site_union})",
        ]
    )
    for chain, color in colors.items():
        if chain in validated_chains:
            lines.append(f"color {color}, site_{chain} and polymer")
    for chain in validated_chains:
        lines.append(
            f"select pocket_{chain}, site_{chain} and byres "
            f"(polymer within {distance:g} of (site_{chain} and resn {ligand}))"
        )
    lines.extend(
        [
            f"select pocket_all, {pocket_union}",
            "show sticks, pocket_all",
            "color yelloworange, pocket_all",
            f"show sticks, ({site_union}) and resn {ligand}",
            f"color orange, ({site_union}) and resn {ligand}",
            f"show spheres, ({site_union}) and resn {ligand} and name FE",
            f"color tv_red, ({site_union}) and resn {ligand} and name FE",
        ]
    )
    for chain, residues in marks.items():
        if chain in validated_chains:
            selector = residues.replace(",", "+")
            lines.append(f"select mark_{chain}, site_{chain} and resi {selector}")
    if mark_union:
        lines.extend(
            [
                f"show sticks, {mark_union}",
                f"color magenta, {mark_union}",
            ]
        )
    for chain in validated_chains:
        lines.append(
            f'label (site_{chain} and resn {ligand} and name FE), "{chain} {ligand}"'
        )
    for chain in validated_chains:
        if chain in marks:
            lines.append(
                f'label (mark_{chain} and name CA), "{chain} %s%s" % (resn,resi)'
            )
    lines.extend(
        [
            "set label_color, black",
            "set label_size, 18",
            "set stick_radius, 0.18",
            "set sphere_scale, 0.35",
            f"orient ({site_union})",
            f"zoom ({site_union}) and (resn {ligand} or pocket_all), 5",
        ]
    )
    if scene:
        validate_token(scene, "scene")
        lines.append(f"scene {scene}, store")
    return lines
