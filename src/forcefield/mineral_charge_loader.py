"""yaml loader for the mineral partial-charge catalog (SSOT).

Mirrors :mod:`forcefield.mineral_lj_loader`. Reads
``data/forcefields/mineral_charge_catalog.yaml`` and exposes a flat
``material_value -> {element: charge}`` mapping consumed by the crystal-slab
generator (:class:`builder.crystal_builder.CrystalBuilder`).

The catalog is the editable SSOT for per-material mineral charges (CLAYFF
family). ``crystal_builder`` keeps a hardcoded fallback so module import never
depends on the yaml being present (tmp_path tests, fresh checkouts); the
regression ``tests/unit/test_mineral_charge_ssot.py`` keeps the two in sync and
binds the values to the curated CLAYFF profiles in ``inorganic_profiles.yaml``.

Error behaviour (caller decides how to react):
* Missing yaml file → :class:`MineralChargeLoadError`.
* Malformed yaml / wrong top-level type → :class:`MineralChargeLoadError`.
* Schema version mismatch → :class:`MineralChargeLoadError`.
* Malformed per-material entry → :class:`MineralChargeLoadError`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from common.logging import get_logger
from common.pathing import get_project_root

logger = get_logger("forcefield.mineral_charge_loader")

MINERAL_CHARGE_CATALOG_PATH = "data/forcefields/mineral_charge_catalog.yaml"
SCHEMA_VERSION = 1


class MineralChargeLoadError(RuntimeError):
    """Raised when the mineral charge yaml catalog cannot be loaded."""


def _catalog_path() -> Path:
    return get_project_root() / MINERAL_CHARGE_CATALOG_PATH


def _load_raw(path: Path | None = None) -> dict[str, Any]:
    """Read and validate the top-level structure of the catalog yaml."""
    yaml_path = path or _catalog_path()
    if not yaml_path.exists():
        raise MineralChargeLoadError(
            f"Mineral charge catalog yaml not found: {yaml_path}."
        )

    try:
        payload = yaml.safe_load(yaml_path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise MineralChargeLoadError(
            f"Mineral charge catalog yaml parse failed at {yaml_path}: {exc}"
        ) from exc

    if not isinstance(payload, dict):
        raise MineralChargeLoadError(
            f"Mineral charge catalog yaml must contain a top-level mapping, got "
            f"{type(payload).__name__}"
        )

    schema_version = int(payload.get("schema_version") or 0)
    if schema_version != SCHEMA_VERSION:
        raise MineralChargeLoadError(
            f"Mineral charge catalog schema_version={schema_version} is unsupported "
            f"(this build expects {SCHEMA_VERSION})"
        )

    return payload


def load_mineral_charges(path: Path | None = None) -> dict[str, dict[str, float]]:
    """Load per-material mineral charges from the yaml SSOT.

    Args:
        path: Optional explicit catalog path (defaults to the project SSOT).

    Returns:
        Mapping of ``material_value -> {element: charge}`` with float charges.

    Raises:
        MineralChargeLoadError: On missing/malformed yaml or schema mismatch.
    """
    payload = _load_raw(path)
    materials = payload.get("materials")
    if not isinstance(materials, dict) or not materials:
        raise MineralChargeLoadError(
            "Mineral charge catalog yaml has empty or non-mapping 'materials'"
        )

    result: dict[str, dict[str, float]] = {}
    for material, entry in materials.items():
        if not isinstance(entry, dict) or not entry:
            raise MineralChargeLoadError(
                f"Mineral charge entry {material!r} must be a non-empty mapping, "
                f"got {type(entry).__name__}"
            )
        try:
            result[str(material)] = {str(el): float(q) for el, q in entry.items()}
        except (TypeError, ValueError) as exc:
            raise MineralChargeLoadError(
                f"Mineral charge entry {material!r} has a non-numeric charge: {exc}"
            ) from exc

    return result
