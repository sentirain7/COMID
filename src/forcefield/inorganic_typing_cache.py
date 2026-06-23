"""Persistent cache for inorganic profile typing/charge assignments.

Uses a file-backed :class:`TypingChargeCacheStore` (inlined from the former
``typing_charge_cache.py`` but defines a separate key recipe and payload
schema so inorganic and organic caches cannot collide. The router
(`forcefield.typing_router.resolve_typing_strategy`) determines which
cache to consult; this module owns the inorganic side.

Cache key inputs (sha256, 32 chars):
    - schema_version
    - mol_file_hash       (sha256 of the MOL file content)
    - routing_mode        ("inorganic_profile")
    - profile_id          (e.g., "silica_hydroxylated_v1")
    - profile_version     (from inorganic_profiles.yaml)

Cache payload schema:
    {
      "schema_version": int,
      "mol_id": str,
      "profile_id": str,
      "profile_version": str,
      "n_atoms": int,
      "total_charge": float,
      "dihedral_policy": str,
      "bonded_philosophy": str,  # "full" or "nonbonded_lattice"
      "atoms": [
          {"index": int (1-based), "element": str,
           "ff_type": str, "charge": float},
          ...
      ],
      "atom_type_coeffs": {site_type: {epsilon, sigma, mass}},
      "bond_type_coeffs": {bond_key: {k, r0}},
      "angle_type_coeffs": {angle_key: {k, theta0}},
      "cached_at": iso8601 string,
    }

Hit-validation rules (mirror typing_charge_assigner._apply_cached_assignment):
    - schema_version must match
    - n_atoms must match topology
    - per-atom (index, element) must match topology
    - profile_id / profile_version must match the requested profile

If any check fails, the cache is treated as a miss and the caller falls
back to recomputing via :class:`InorganicParameterService.assign`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from common.hashing import compute_content_hash, compute_file_hash
from common.logging import get_logger
from common.pathing import get_cache_path

logger = get_logger("forcefield.inorganic_typing_cache")


class TypingChargeCacheStore:
    """Simple file-backed cache store keyed by deterministic hash.

    Migrated from the deleted ``forcefield.typing_charge_cache`` module.
    """

    def __init__(self, cache_dir: Path | None = None) -> None:
        self._cache_dir = cache_dir

    def _get_cache_file(self, key: str) -> Path:
        if self._cache_dir is None:
            cache_file = get_cache_path("typing_charge", key, extension="json")
        else:
            cache_file = Path(self._cache_dir) / f"{key}.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        return cache_file

    def get(self, key: str) -> dict[str, Any] | None:
        """Load cached assignment payload if present."""
        cache_file = self._get_cache_file(key)
        if not cache_file.exists():
            return None
        try:
            data = json.loads(cache_file.read_text())
        except Exception as exc:
            logger.warning(f"Failed to read typing/charge cache '{cache_file}': {exc}")
            return None
        if not isinstance(data, dict):
            return None
        return data

    def set(self, key: str, payload: dict[str, Any]) -> None:
        """Persist assignment payload with atomic replace."""
        cache_file = self._get_cache_file(key)
        temp_file = cache_file.with_suffix(".tmp")
        temp_file.write_text(json.dumps(payload, indent=2, sort_keys=True))
        temp_file.replace(cache_file)


_SCHEMA_VERSION = 1
_ROUTING_MODE = "inorganic_profile"


def build_inorganic_cache_key(
    *,
    mol_file: Path,
    profile_id: str,
    profile_version: str,
) -> str | None:
    """Compute the persistent cache key for an inorganic assignment.

    Returns ``None`` if the MOL file cannot be hashed (caller should
    skip caching but proceed with computation).
    """
    try:
        mol_file_hash = compute_file_hash(mol_file, algorithm="sha256")
    except Exception:
        return None

    key_payload = {
        "schema_version": _SCHEMA_VERSION,
        "routing_mode": _ROUTING_MODE,
        "mol_file_hash": mol_file_hash,
        "profile_id": profile_id,
        "profile_version": profile_version,
    }
    return compute_content_hash(key_payload, algorithm="sha256", length=32)


def _atoms_match_topology(cached_atoms: Any, topology: Any) -> bool:
    """Strict shape check between cached payload and live topology."""
    if not isinstance(cached_atoms, list):
        return False
    if len(cached_atoms) != len(topology.atoms):
        return False
    for cached, atom in zip(cached_atoms, topology.atoms, strict=True):
        if not isinstance(cached, dict):
            return False
        try:
            if int(cached.get("index", 0) or 0) != int(atom.index):
                return False
        except (TypeError, ValueError):
            return False
        if str(cached.get("element", "")) != str(atom.element):
            return False
    return True


def apply_cached_inorganic_assignment(
    topology: Any,
    cache_payload: dict[str, Any],
    *,
    expected_profile_id: str,
    expected_profile_version: str,
) -> dict[str, Any] | None:
    """Apply a cached inorganic assignment to ``topology`` in place.

    Returns:
        The coefficient bundle dict ({atom_type_coeffs, bond_type_coeffs,
        angle_type_coeffs, dihedral_policy, total_charge, profile_id})
        on hit, or ``None`` if the cache entry must be ignored.
    """
    if not isinstance(cache_payload, dict):
        return None
    if int(cache_payload.get("schema_version", 0) or 0) != _SCHEMA_VERSION:
        return None
    if str(cache_payload.get("profile_id") or "") != expected_profile_id:
        return None
    if str(cache_payload.get("profile_version") or "") != expected_profile_version:
        return None

    atoms_payload = cache_payload.get("atoms")
    if not _atoms_match_topology(atoms_payload, topology):
        logger.warning(
            "Inorganic typing cache atom shape mismatch for %s; ignoring entry",
            getattr(topology, "mol_id", "?"),
        )
        return None

    # Mutate topology atoms in place (mirrors InorganicParameterService.assign)
    for cached, atom in zip(atoms_payload, topology.atoms, strict=True):
        atom.ff_type = str(cached.get("ff_type") or "")
        atom.charge = float(cached.get("charge", 0.0))
        atom.charge_defined = True

    return {
        "atom_type_coeffs": dict(cache_payload.get("atom_type_coeffs") or {}),
        "bond_type_coeffs": dict(cache_payload.get("bond_type_coeffs") or {}),
        "angle_type_coeffs": dict(cache_payload.get("angle_type_coeffs") or {}),
        "dihedral_policy": str(cache_payload.get("dihedral_policy") or "strict"),
        "bonded_philosophy": str(cache_payload.get("bonded_philosophy") or "full"),
        "total_charge": float(cache_payload.get("total_charge", 0.0)),
        "profile_id": expected_profile_id,
    }


def serialize_inorganic_assignment(
    *,
    topology: Any,
    profile_id: str,
    profile_version: str,
    total_charge: float,
    atom_type_coeffs: dict[str, dict[str, float]],
    bond_type_coeffs: dict[str, dict[str, float]],
    angle_type_coeffs: dict[str, dict[str, float]],
    dihedral_policy: str,
    bonded_philosophy: str = "full",
) -> dict[str, Any]:
    """Build the persistent payload for an inorganic assignment."""
    atoms_payload = [
        {
            "index": int(atom.index),
            "element": str(atom.element),
            "ff_type": str(atom.ff_type),
            "charge": float(atom.charge),
        }
        for atom in topology.atoms
    ]
    return {
        "schema_version": _SCHEMA_VERSION,
        "mol_id": getattr(topology, "mol_id", ""),
        "profile_id": profile_id,
        "profile_version": profile_version,
        "n_atoms": len(topology.atoms),
        "total_charge": float(total_charge),
        "dihedral_policy": dihedral_policy,
        "bonded_philosophy": bonded_philosophy,
        "atoms": atoms_payload,
        "atom_type_coeffs": dict(atom_type_coeffs),
        "bond_type_coeffs": dict(bond_type_coeffs),
        "angle_type_coeffs": dict(angle_type_coeffs),
        "cached_at": datetime.now(UTC).isoformat(),
    }


class InorganicTypingCache:
    """Thin wrapper that adapts TypingChargeCacheStore for inorganic payloads."""

    def __init__(self, store: TypingChargeCacheStore | None = None) -> None:
        # Reuse the same on-disk store; the key recipe ensures namespace
        # separation between organic and inorganic entries.
        self._store = store or TypingChargeCacheStore()

    def get(self, key: str) -> dict[str, Any] | None:
        return self._store.get(key)

    def set(self, key: str, payload: dict[str, Any]) -> None:
        try:
            self._store.set(key, payload)
        except Exception as exc:
            logger.warning("Failed to persist inorganic typing cache (key=%s): %s", key, exc)
