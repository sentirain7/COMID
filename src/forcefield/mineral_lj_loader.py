"""Wave 4: yaml loader for the mineral / element-level LJ catalog.

This module loads the editable SSOT at
``data/forcefields/mineral_lj_catalog.yaml`` and exposes two flat dicts
that mirror the legacy hardcoded values:

* :func:`load_interface_ff_params` →
  ``{element: {sigma, epsilon, description}, ...}``
* :func:`load_uff_fallback_params` →
  ``{element: {mass, sigma, epsilon, charge, description}, ...}``

The legacy hardcoded dicts in
:mod:`forcefield.interface_ff` and :mod:`forcefield.uff_element_fallback`
remain in place as a runtime safety net so module import never fails
in environments where the yaml is missing (tmp_path-based tests, fresh
checkouts before ``data/`` is populated). The Wave 4 numerical
equivalence regression in
``tests/unit/test_interface_ff_yaml_equivalence.py`` enforces that the
yaml and the hardcoded fallbacks stay in sync element by element.

Loader contract
===============

* Missing yaml file → :class:`MineralLJLoadError` (caller decides
  whether to fall back to the hardcoded dict).
* Malformed yaml → :class:`MineralLJLoadError`.
* Schema version mismatch → :class:`MineralLJLoadError`.
* Per-element parse errors are also wrapped as
  :class:`MineralLJLoadError` with the offending element id in the
  message so audit failures point at the right line.

The loader is intentionally side-effect free: it does NOT mutate the
legacy module-level dicts. Wave 4 keeps the legacy dicts as the
import-time runtime authority and treats the yaml as an editable
SSOT plus a numerical equivalence anchor.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from common.logging import get_logger
from common.pathing import get_project_root

logger = get_logger("forcefield.mineral_lj_loader")

MINERAL_LJ_CATALOG_PATH = "data/forcefields/mineral_lj_catalog.yaml"
SCHEMA_VERSION = 1


class MineralLJLoadError(RuntimeError):
    """Raised when the mineral LJ yaml catalog cannot be loaded.

    The caller decides whether to fall back to the hardcoded legacy
    dict — production code should fail-closed; tmp_path tests should
    use the hardcoded fallback.
    """


@dataclass(frozen=True)
class InterfaceFFEntry:
    """One INTERFACE FF mineral element entry."""

    element: str
    sigma: float
    epsilon: float
    description: str


@dataclass(frozen=True)
class UFFEntry:
    """One UFF fallback element entry."""

    element: str
    mass: float
    sigma: float
    epsilon: float
    charge: float
    description: str


def _catalog_path() -> Path:
    return get_project_root() / MINERAL_LJ_CATALOG_PATH


def _load_raw(path: Path | None = None) -> dict[str, Any]:
    """Read and validate the top-level structure of the catalog yaml."""
    yaml_path = path or _catalog_path()
    if not yaml_path.exists():
        raise MineralLJLoadError(
            f"Mineral LJ catalog yaml not found: {yaml_path}. "
            "The Wave 4 SSOT must exist before any layered or inorganic "
            "additive build can run yaml-driven."
        )

    try:
        payload = yaml.safe_load(yaml_path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise MineralLJLoadError(
            f"Mineral LJ catalog yaml parse failed at {yaml_path}: {exc}"
        ) from exc

    if not isinstance(payload, dict):
        raise MineralLJLoadError(
            f"Mineral LJ catalog yaml must contain a top-level mapping, got "
            f"{type(payload).__name__}"
        )

    schema_version = int(payload.get("schema_version") or 0)
    if schema_version != SCHEMA_VERSION:
        raise MineralLJLoadError(
            f"Mineral LJ catalog schema_version={schema_version} is unsupported "
            f"(this build expects {SCHEMA_VERSION})"
        )

    return payload


def _parse_interface_ff_entry(element: str, raw: Any) -> InterfaceFFEntry:
    if not isinstance(raw, dict):
        raise MineralLJLoadError(
            f"interface_ff entry {element!r} must be a mapping, got {type(raw).__name__}"
        )
    try:
        return InterfaceFFEntry(
            element=element,
            sigma=float(raw["sigma"]),
            epsilon=float(raw["epsilon"]),
            description=str(raw.get("description") or ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise MineralLJLoadError(f"interface_ff entry {element!r}: malformed: {exc}") from exc


def _parse_uff_entry(element: str, raw: Any) -> UFFEntry:
    if not isinstance(raw, dict):
        raise MineralLJLoadError(
            f"uff_fallback entry {element!r} must be a mapping, got {type(raw).__name__}"
        )
    try:
        return UFFEntry(
            element=element,
            mass=float(raw["mass"]),
            sigma=float(raw["sigma"]),
            epsilon=float(raw["epsilon"]),
            charge=float(raw.get("charge", 0.0)),
            description=str(raw.get("description") or ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise MineralLJLoadError(f"uff_fallback entry {element!r}: malformed: {exc}") from exc


def load_interface_ff_entries(
    path: Path | None = None,
) -> dict[str, InterfaceFFEntry]:
    """Load the INTERFACE FF mineral element table from the yaml catalog.

    Returns a dict keyed by element symbol; each value is a typed
    :class:`InterfaceFFEntry` so callers can rely on attribute access
    and float types.
    """
    payload = _load_raw(path)
    raw_section = payload.get("interface_ff")
    if not isinstance(raw_section, dict):
        raise MineralLJLoadError(
            "Mineral LJ catalog 'interface_ff' section is missing or not a mapping"
        )
    out: dict[str, InterfaceFFEntry] = {}
    for element, raw in raw_section.items():
        out[str(element)] = _parse_interface_ff_entry(str(element), raw)
    return out


def load_uff_fallback_entries(path: Path | None = None) -> dict[str, UFFEntry]:
    """Load the UFF element fallback table from the yaml catalog."""
    payload = _load_raw(path)
    raw_section = payload.get("uff_fallback")
    if not isinstance(raw_section, dict):
        raise MineralLJLoadError(
            "Mineral LJ catalog 'uff_fallback' section is missing or not a mapping"
        )
    out: dict[str, UFFEntry] = {}
    for element, raw in raw_section.items():
        out[str(element)] = _parse_uff_entry(str(element), raw)
    return out


def load_interface_ff_params(
    path: Path | None = None,
) -> dict[str, dict[str, float | str]]:
    """Return the INTERFACE FF table in the legacy dict-of-dicts shape.

    The legacy module-level dict
    :data:`forcefield.interface_ff.INTERFACE_FF_MINERAL_PARAMS` is
    structured as ``{element: {"sigma", "epsilon", "description"}}``.
    This helper produces the same shape from the yaml so callers can
    swap one for the other element by element. Used by the Wave 4
    numerical equivalence regression test.
    """
    entries = load_interface_ff_entries(path)
    return {
        element: {
            "sigma": entry.sigma,
            "epsilon": entry.epsilon,
            "description": entry.description,
        }
        for element, entry in entries.items()
    }


def load_uff_fallback_params(
    path: Path | None = None,
) -> dict[str, dict[str, float | str]]:
    """Return the UFF fallback table in the legacy dict-of-dicts shape.

    Mirrors the layout of
    :data:`forcefield.uff_element_fallback.UFF_ELEMENT_FALLBACKS`.
    """
    entries = load_uff_fallback_entries(path)
    return {
        element: {
            "mass": entry.mass,
            "sigma": entry.sigma,
            "epsilon": entry.epsilon,
            "charge": entry.charge,
            "description": entry.description,
        }
        for element, entry in entries.items()
    }


__all__ = [
    "MINERAL_LJ_CATALOG_PATH",
    "SCHEMA_VERSION",
    "MineralLJLoadError",
    "InterfaceFFEntry",
    "UFFEntry",
    "load_interface_ff_entries",
    "load_uff_fallback_entries",
    "load_interface_ff_params",
    "load_uff_fallback_params",
]
