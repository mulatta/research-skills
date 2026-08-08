# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
"""Validation rules for data crossing into PyMOL."""

from __future__ import annotations

import re
import stat
from pathlib import Path
from typing import Any

from pymol_cli.engine.errors import EngineError, ErrorCategory

SAFE_STRUCTURE_FORMATS = {
    ".pdb": "pdb",
    ".ent": "pdb",
    ".cif": "cif",
    ".mmcif": "cif",
}
SAFE_SESSION_SUFFIXES = frozenset({".pse", ".psw"})
MAX_OBJECT_NAME_LENGTH = 255

_OBJECT_NAME_RE = re.compile(r"[A-Za-z0-9_]+", re.ASCII)
# PyMOL 3.1 appends an underscore to bare selection keywords. Reject every
# identifier keyword so returned object names remain identical to loaded names.
_RESERVED_OBJECT_NAMES = frozenset(
    {
        "acceptors",
        "all",
        "alt",
        "altloc",
        "and",
        "around",
        "b",
        "backbone",
        "beyond",
        "bonded",
        "bound_to",
        "bycalpha",
        "bycell",
        "bychain",
        "byfrag",
        "byfragment",
        "bymol",
        "bymolecule",
        "byobj",
        "byobject",
        "byres",
        "byresi",
        "byresidue",
        "byring",
        "byseg",
        "bysegi",
        "bysegment",
        "cartoon_color",
        "center",
        "chain",
        "color",
        "custom",
        "delocalized",
        "donors",
        "elem",
        "element",
        "enabled",
        "expand",
        "extend",
        "first",
        "fixed",
        "flag",
        "formal_charge",
        "gap",
        "guide",
        "het",
        "hetatm",
        "hydro",
        "hydrogens",
        "id",
        "in",
        "index",
        "inorganic",
        "label",
        "last",
        "like",
        "masked",
        "metals",
        "model",
        "name",
        "near_to",
        "neighbor",
        "none",
        "not",
        "nucleic",
        "numeric_type",
        "object",
        "or",
        "organic",
        "origin",
        "partial_charge",
        "pepseq",
        "polymer",
        "present",
        "protected",
        "protein",
        "q",
        "rank",
        "rep",
        "resi",
        "resid",
        "resident",
        "residue",
        "resn",
        "resname",
        "restrained",
        "ribbon_color",
        "same",
        "segi",
        "segid",
        "segment",
        "sele",
        "sidechain",
        "solvent",
        "ss",
        "state",
        "stereo",
        "symbol",
        "text_type",
        "visible",
        "within",
        "x",
        "y",
        "z",
    }
)


def require_text(value: object, name: str) -> str:
    """Return stripped nonempty text or a stable invalid-argument error."""
    if not isinstance(value, str):
        raise EngineError(
            ErrorCategory.INVALID_ARGUMENT,
            f"{name} must be text",
            {"argument": name},
        )
    normalized = value.strip()
    if not normalized:
        raise EngineError(
            ErrorCategory.INVALID_ARGUMENT,
            f"{name} must not be empty",
            {"argument": name},
        )
    return normalized


def structure_format_for_path(path: str) -> str:
    """Map an allowlisted filename suffix to an explicit PyMOL parser."""
    suffix = Path(path).suffix.lower()
    try:
        return SAFE_STRUCTURE_FORMATS[suffix]
    except KeyError as exc:
        raise EngineError(
            ErrorCategory.INVALID_ARGUMENT,
            "structure path must use a supported structure format",
            {"allowed_suffixes": sorted(SAFE_STRUCTURE_FORMATS)},
        ) from exc


def validate_structure_path(path: object) -> str:
    """Require an absolute, existing, regular allowlisted structure file."""
    normalized = require_text(path, "path")
    candidate = Path(normalized)
    if not candidate.is_absolute():
        raise EngineError(
            ErrorCategory.INVALID_ARGUMENT,
            "structure path must be absolute",
            {"argument": "path"},
        )
    structure_format_for_path(normalized)
    _require_regular_file(candidate, "structure")
    return normalized


def validate_object_name(object_name: object) -> str:
    """Require an unambiguous object identifier safe in PyMOL selections."""
    normalized = require_text(object_name, "object_name")
    if (
        len(normalized) > MAX_OBJECT_NAME_LENGTH
        or _OBJECT_NAME_RE.fullmatch(normalized) is None
    ):
        raise EngineError(
            ErrorCategory.INVALID_ARGUMENT,
            "object_name contains unsupported characters",
            {"argument": "object_name"},
        )
    if normalized.casefold() in _RESERVED_OBJECT_NAMES:
        raise EngineError(
            ErrorCategory.INVALID_ARGUMENT,
            "object_name is reserved by PyMOL",
            {"argument": "object_name"},
        )
    return normalized


def require_exact_runtime_object_name(cmd: Any, object_name: str) -> None:
    """Reject any name that this PyMOL runtime would silently rewrite."""
    try:
        legal_name = cmd.get_legal_name(object_name)
    except Exception as exc:
        raise EngineError(
            ErrorCategory.BACKEND_FAILURE,
            "PyMOL could not validate object_name",
            {"operation": "structure.load"},
        ) from exc
    if not isinstance(legal_name, str) or legal_name != object_name:
        raise EngineError(
            ErrorCategory.INVALID_ARGUMENT,
            "PyMOL would rewrite object_name",
            {"argument": "object_name"},
        )


def validate_session_path(path: object, *, must_exist: bool) -> str:
    """Require an absolute PSE/PSW path and optionally an existing file."""
    normalized = require_text(path, "path")
    candidate = Path(normalized)
    if not candidate.is_absolute():
        raise EngineError(
            ErrorCategory.INVALID_ARGUMENT,
            "session path must be absolute",
            {"argument": "path"},
        )
    if candidate.suffix.lower() not in SAFE_SESSION_SUFFIXES:
        raise EngineError(
            ErrorCategory.INVALID_ARGUMENT,
            "session path must end in .pse or .psw",
            {"allowed_suffixes": sorted(SAFE_SESSION_SUFFIXES)},
        )
    if must_exist:
        _require_regular_file(candidate, "session")
    return normalized


def _require_regular_file(path: Path, kind: str) -> None:
    try:
        mode = path.stat().st_mode
    except FileNotFoundError as exc:
        raise EngineError(
            ErrorCategory.NOT_FOUND,
            f"{kind} file was not found",
            {"argument": "path"},
        ) from exc
    except (OSError, ValueError) as exc:
        raise EngineError(
            ErrorCategory.NOT_FOUND,
            f"{kind} file is not accessible",
            {"argument": "path"},
        ) from exc
    if not stat.S_ISREG(mode):
        raise EngineError(
            ErrorCategory.INVALID_ARGUMENT,
            f"{kind} path must identify a regular file",
            {"argument": "path"},
        )
