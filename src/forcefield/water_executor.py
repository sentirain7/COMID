"""Water model executor — applies explicit water model parameters to topology.

Currently supports TIP3P (Jorgensen et al. 1983) only. The parameters
are stored as curated artifacts under ``data/forcefield_artifacts/water_tip3p/``.

This module mirrors the organic_typing_executor pattern but does NOT depend
on antechamber/parmed — water model params are hand-curated, not auto-generated.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common.logging import get_logger

logger = get_logger("forcefield.water_executor")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_WATER_ARTIFACT_DIR = _PROJECT_ROOT / "data" / "forcefield_artifacts" / "water_tip3p"


class WaterAssignmentError(RuntimeError):
    """Raised when water model assignment fails."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


@dataclass(frozen=True)
class WaterAssignmentResult:
    """Result of water model parameter assignment."""

    cache_hit: bool
    charge_model: str
    bonded_overrides: dict[str, Any] | None = None


def assign_water(
    *,
    topology: Any,
    source_id: str,
) -> WaterAssignmentResult:
    """Apply TIP3P water model parameters to topology in-place.

    Loads the curated water artifact JSON, applies ff_type/charge to
    each atom, and returns bonded + LJ overrides for MolTopologyBuilder.

    Args:
        topology: Live MolTopology to mutate.
        source_id: Artifact filename stem (e.g., "H2O").

    Returns:
        WaterAssignmentResult with bonded_overrides dict.

    Raises:
        WaterAssignmentError: If artifact is missing or malformed.
    """
    artifact_path = _WATER_ARTIFACT_DIR / f"{source_id}.json"
    if not artifact_path.exists():
        raise WaterAssignmentError(
            f"Water model artifact not found: {artifact_path}",
            details={"source_id": source_id},
        )

    try:
        with open(artifact_path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        raise WaterAssignmentError(
            f"Failed to load water artifact: {exc}",
            details={"source_id": source_id},
        ) from exc

    art_atoms = data.get("atoms", [])
    if len(art_atoms) != len(topology.atoms):
        raise WaterAssignmentError(
            f"Water artifact atom count {len(art_atoms)} != topology {len(topology.atoms)}",
            details={"source_id": source_id},
        )

    # Apply ff_type and charge to topology atoms
    for cached, atom in zip(art_atoms, topology.atoms, strict=True):
        atom.ff_type = cached["ff_type"]
        atom.charge = float(cached["charge"])
        atom.charge_defined = True

    # Build overrides (same structure as organic artifact)
    from contracts.policies.forcefield import (
        AngleTypeParams,
        BondTypeParams,
    )
    from forcefield.uff_element_fallback import UFF_ELEMENT_FALLBACKS

    overrides: dict[str, Any] = {
        "bond_types": {},
        "angle_types": {},
        "dihedral_types": {},
        "improper_types": {},
        "atom_types": {},
        "improper_instances": [],
    }

    for bt in data.get("bond_types", []):
        overrides["bond_types"][bt["key"]] = BondTypeParams(k=bt["k"], r0=bt["r0"])
    for at in data.get("angle_types", []):
        overrides["angle_types"][at["key"]] = AngleTypeParams(k=at["k"], theta0=at["theta0"])

    # Per-atom-type LJ overrides
    for cached in art_atoms:
        ft = cached["ff_type"]
        if ft not in overrides["atom_types"]:
            eps = cached.get("epsilon", 0.0)
            sig = cached.get("sigma", 0.0)
            elem = cached["element"]
            mass = UFF_ELEMENT_FALLBACKS.get(elem, {}).get("mass", 16.0)
            overrides["atom_types"][ft] = {
                "mass": mass,
                "epsilon": eps,
                "sigma": sig,
                "charge": 0.0,
                "element": elem,
            }

    logger.info(
        "Water model applied: source_id=%s atoms=%d charge_model=%s",
        source_id,
        len(art_atoms),
        data.get("charge_model", "tip3p_fixed"),
    )

    return WaterAssignmentResult(
        cache_hit=True,
        charge_model=data.get("charge_model", "tip3p_fixed"),
        bonded_overrides=overrides,
    )
