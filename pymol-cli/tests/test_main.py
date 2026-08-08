# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import pytest

from pymol_cli.cli.errors import CLIError
from pymol_cli.cli.pml import (
    generate_ligand_pocket_pml,
    generate_load_pml,
    require_mark_residues,
    resolve_ligand_chains,
)


def test_load_rejects_urls_without_opt_in() -> None:
    with pytest.raises(CLIError, match="--allow-url"):
        generate_load_pml(
            path="https://example.org/model.cif",
            object_name="prot",
            style="none",
            color=None,
            orient=False,
            zoom_buffer=0,
            allow_url=False,
        )


def test_ligand_chain_resolution_handles_partial_and_missing_matches() -> None:
    present, missing = resolve_ligand_chains(
        {"A": 43, "B": 0, "C": 43, "D": 0}, strict=False, ligand="HEM"
    )
    assert (present, missing) == (["A", "C"], ["B", "D"])

    with pytest.raises(CLIError, match="ligand HEM not found in chains: A,B"):
        resolve_ligand_chains({"A": 0, "B": 0}, strict=False, ligand="HEM")
    with pytest.raises(CLIError, match="ligand HEM not found in chains: B"):
        resolve_ligand_chains({"A": 43, "B": 0}, strict=True, ligand="HEM")


def test_missing_marked_residue_fails() -> None:
    with pytest.raises(CLIError, match="marked residues not found: A:999"):
        require_mark_residues({"A:58": 10, "A:999": 0})


def test_ligand_pocket_generates_per_chain_views() -> None:
    pml = generate_ligand_pocket_pml(
        object_name="hb",
        ligand="HEM",
        chains=["A", "B"],
        distance=4.0,
        colors={"A": "red", "B": "marine"},
        marks={"A": "58,87", "B": "63,92"},
        grid=True,
        scene="heme_pockets",
        disable_source=True,
    )
    text = "\n".join(pml)
    assert (
        "delete site_A or site_B or pocket_A or pocket_B or mark_A or mark_B or pocket_all"
        in text
    )
    assert "set grid_mode, 1" in text
    assert "create site_A, (hb and chain A)" in text
    assert (
        "select pocket_A, site_A and byres (polymer within 4 of (site_A and resn HEM))"
        in text
    )
    assert "select mark_B, site_B and resi 63+92" in text
    assert 'label (site_A and resn HEM and name FE), "A HEM"' in text
    assert "scene heme_pockets, store" in text


def test_ligand_pocket_cleans_skipped_chain_helpers() -> None:
    pml = generate_ligand_pocket_pml(
        object_name="protein",
        ligand="LIG",
        chains=["A"],
        cleanup_chains=["A", "B"],
        distance=4.0,
        colors={},
        marks={},
        grid=True,
        scene=None,
        disable_source=True,
    )
    assert pml[0] == (
        "delete site_A or site_B or pocket_A or pocket_B or "
        "mark_A or mark_B or pocket_all"
    )
    assert "create site_A, (protein and chain A)" in pml
    assert all("create site_B" not in command for command in pml)


def test_ligand_pocket_rejects_command_like_tokens() -> None:
    with pytest.raises(CLIError):
        generate_ligand_pocket_pml(
            object_name="hb;delete_all",
            ligand="HEM",
            chains=["A"],
            distance=4.0,
            colors={},
            marks={},
            grid=False,
            scene=None,
            disable_source=False,
        )
