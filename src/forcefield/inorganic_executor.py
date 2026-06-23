"""Cache-aware execution helper for inorganic profile assignments.

This module provides a single entry point that both the structure builder
and the precompute endpoint use to assign inorganic profile parameters to a
topology, with persistent cache reuse. It is the only place that knows how
to translate an InorganicAssignmentResult into a cache payload and vice
versa, so the build path and the precompute path produce identical state
on cache hit.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common.logging import get_logger
from forcefield.inorganic_parameter_service import (
    InorganicParameterizationError,
    InorganicParameterService,
)
from forcefield.inorganic_typing_cache import (
    InorganicTypingCache,
    apply_cached_inorganic_assignment,
    build_inorganic_cache_key,
    serialize_inorganic_assignment,
)

logger = get_logger("forcefield.inorganic_executor")


@dataclass(frozen=True)
class InorganicAssignmentBundle:
    """Result of applying an inorganic profile to a topology.

    Whether produced by a fresh InorganicParameterService.assign() call
    or a cache hit, the bundle has the same shape so callers do not need
    to differentiate.
    """

    profile_id: str
    profile_version: str
    total_charge: float
    atom_type_coeffs: dict[str, dict[str, float]]
    bond_type_coeffs: dict[str, dict[str, float]]
    angle_type_coeffs: dict[str, dict[str, float]]
    dihedral_policy: str
    cache_hit: bool
    bonded_philosophy: str = "full"  # "full" or "nonbonded_lattice"


def _extract_profile_version(
    service: InorganicParameterService,
    profile_id: str,
) -> str:
    """Best-effort extraction of profile_version from the loaded profile."""
    profile = service.get_profile(profile_id)
    if not profile:
        return "unknown"
    return str(profile.get("profile_version") or "unknown")


def assign_inorganic_with_cache(
    *,
    topology: Any,
    mol_file: Path,
    additive_def: dict[str, Any],
    service: InorganicParameterService | None = None,
    cache: InorganicTypingCache | None = None,
) -> InorganicAssignmentBundle:
    """Assign inorganic profile params to ``topology`` with persistent cache.

    Workflow:
        1. Resolve profile_id from additive_def.
        2. Build cache key (mol_file_hash + profile_id + profile_version).
        3. Try cache hit; if valid, mutate topology and return bundle.
        4. On miss, call InorganicParameterService.assign() and persist
           the result for next time.

    Raises:
        InorganicParameterizationError: when the profile is missing,
            blocked, or assignment fails. Callers are expected to catch
            this and convert to an API/build issue.
    """
    service = service or InorganicParameterService()
    cache = cache or InorganicTypingCache()

    param = additive_def.get("parameterization") or {}
    profile_id = param.get("profile_id")
    if not profile_id:
        raise InorganicParameterizationError(
            "Inorganic additive missing parameterization.profile_id"
        )

    profile_version = _extract_profile_version(service, profile_id)
    cache_key = build_inorganic_cache_key(
        mol_file=mol_file,
        profile_id=profile_id,
        profile_version=profile_version,
    )

    # Cache lookup
    if cache_key is not None:
        cached_payload = cache.get(cache_key)
        if cached_payload is not None:
            applied = apply_cached_inorganic_assignment(
                topology,
                cached_payload,
                expected_profile_id=profile_id,
                expected_profile_version=profile_version,
            )
            if applied is not None:
                logger.debug(
                    "Inorganic typing cache HIT for %s (profile=%s)",
                    getattr(topology, "mol_id", "?"),
                    profile_id,
                )
                return InorganicAssignmentBundle(
                    profile_id=profile_id,
                    profile_version=profile_version,
                    total_charge=applied["total_charge"],
                    atom_type_coeffs=applied["atom_type_coeffs"],
                    bond_type_coeffs=applied["bond_type_coeffs"],
                    angle_type_coeffs=applied["angle_type_coeffs"],
                    dihedral_policy=applied["dihedral_policy"],
                    cache_hit=True,
                    bonded_philosophy=applied.get("bonded_philosophy", "full"),
                )

    # Cache miss → recompute
    result = service.assign(topology, additive_def)

    bundle = InorganicAssignmentBundle(
        profile_id=result.profile_id,
        profile_version=profile_version,
        total_charge=result.total_charge,
        atom_type_coeffs=dict(result.atom_type_coeffs),
        bond_type_coeffs=dict(result.bond_type_coeffs),
        angle_type_coeffs=dict(result.angle_type_coeffs),
        dihedral_policy=result.dihedral_policy,
        cache_hit=False,
        bonded_philosophy=result.bonded_philosophy,
    )

    if cache_key is not None:
        payload = serialize_inorganic_assignment(
            topology=topology,
            profile_id=bundle.profile_id,
            profile_version=bundle.profile_version,
            total_charge=bundle.total_charge,
            atom_type_coeffs=bundle.atom_type_coeffs,
            bond_type_coeffs=bundle.bond_type_coeffs,
            angle_type_coeffs=bundle.angle_type_coeffs,
            dihedral_policy=bundle.dihedral_policy,
            bonded_philosophy=bundle.bonded_philosophy,
        )
        cache.set(cache_key, payload)

    return bundle
