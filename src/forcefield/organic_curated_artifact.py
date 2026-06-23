"""GAFF2 curated artifact schema and loader.

This module is the SSOT for high-accuracy organic force-field data,
supporting GAFF2 curated artifacts via a unified schema. The
``organic_curated_artifact`` route in :mod:`forcefield.typing_router`
consumes JSON files under ``data/forcefield_artifacts/organic_gaff2/``.

The contract is:

* artifacts are **repo-tracked**, not generated at runtime.
* the admin workflow (``scripts/generate_gaff2_artifact.py``) is the
  only place that may call antechamber, and it writes the JSON artifact
  to the catalog after manual review.
* the runtime consumer (this module + :mod:`forcefield.organic_typing_executor`)
  treats a missing or malformed artifact as a hard build failure
  (``ArtifactMissingError`` / ``ArtifactSchemaError``) — no silent
  fallback. Routing to a different path belongs to the typing router.

Schema v1 (legacy format, backward-compatible parsing):

    {
      "schema_version": 1,
      "mol_id": "Toluene",
      "generator": "ligpargen_cm1a_lbcc",
      ...
      "dihedral_types": [
          {"key": "CA-CA-CA-CA", "k1": 0.0, "k2": 7.25, "k3": 0.0, "k4": 0.0}
      ],
      "improper_types": [
          {"key": "CA-CA-CA-HA", "k": 1.1, "phi0": 180.0}
      ]
    }

Schema v2 (FF-neutral, style + coeffs):

    {
      "schema_version": 2,
      "ff_family": "organic_gaff2",
      "charge_model": "am1_bcc",
      ...
      "dihedral_types": [
          {"key": "ca-ca-ca-ca", "style": "fourier", "coeffs": [3.625, 2, 180.0]}
      ],
      "improper_types": [
          {"key": "ca-ca-ca-ha", "style": "cvff", "coeffs": [1.1, -1, 2]}
      ]
    }

Hit-validation rules (mirrored in ``apply_artifact_to_topology``):

* ``schema_version`` must be 1 or 2.
* ``len(atoms) == len(topology.atoms)``.
* per-atom ``index`` and ``element`` must match the live topology.
* every atom must declare ``ff_type`` and ``charge``.

If any check fails, the loader raises ``ArtifactSchemaError`` and the
caller propagates a ``BuildError`` / ``TopologyError``. The artifact is
NOT a cache — there is no fallback recompute, by design.

References:
* Wang et al., JCIM 2006, 46, 2030 (GAFF2 / AM1-BCC)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from common.logging import get_logger
from common.pathing import get_project_root

logger = get_logger("forcefield.organic_curated_artifact")

ARTIFACT_SCHEMA_VERSION = 2  # v2 supports FF-neutral style+coeffs
ARTIFACT_DIR_GAFF2 = "data/forcefield_artifacts/organic_gaff2"

# Default artifact directory (GAFF2 is the sole organic FF)
ARTIFACT_DIR_NAME = ARTIFACT_DIR_GAFF2


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ArtifactError(RuntimeError):
    """Base class for organic curated artifact errors."""


class ArtifactMissingError(ArtifactError):
    """The requested artifact does not exist on disk.

    Raised by :func:`load_artifact` when the JSON file is absent. The
    fail-closed contract: callers must NOT fall back to the legacy
    RDKit path on this error — that decision belongs to the typing
    router, which already chose ``organic_curated_artifact`` for this
    molecule.
    """


class ArtifactIncompleteError(ArtifactError):
    """Curated artifact exists but is incomplete (missing LJ, bonded, etc.).

    Raised when the artifact JSON is present but fails completeness validation
    (missing epsilon/sigma, charge mismatch, etc.). The artifact must be
    regenerated via admin/batch procedure before the molecule can be submitted.
    """


class ArtifactSchemaError(ArtifactError):
    """The artifact JSON exists but does not match the SSOT schema."""


# ---------------------------------------------------------------------------
# Schema dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ArtifactAtom:
    """One atom in a curated artifact."""

    index: int  # 1-based, must match topology.atoms[i].index
    element: str
    ff_type: str
    charge: float
    epsilon: float | None = None  # LJ epsilon (kcal/mol), optional for v2 compat
    sigma: float | None = None  # LJ sigma (Angstrom), optional for v2 compat


@dataclass(frozen=True)
class ArtifactBondType:
    key: str  # canonical "A-B" string (alphabetized at write time)
    k: float
    r0: float


@dataclass(frozen=True)
class ArtifactAngleType:
    key: str  # canonical "A-B-C" string
    k: float
    theta0: float


@dataclass(frozen=True)
class ArtifactDihedralType:
    """FF-neutral dihedral type from curated artifact."""

    key: str  # canonical "A-B-C-D" string
    style: str = "fourier"  # "fourier" | "opls" | "harmonic"
    coeffs: tuple[float, ...] = (0.0, 0.0, 0.0, 0.0)

    # Backward compat for v1 OPLS artifacts
    @property
    def k1(self) -> float:
        return self.coeffs[0] if len(self.coeffs) > 0 else 0.0

    @property
    def k2(self) -> float:
        return self.coeffs[1] if len(self.coeffs) > 1 else 0.0

    @property
    def k3(self) -> float:
        return self.coeffs[2] if len(self.coeffs) > 2 else 0.0

    @property
    def k4(self) -> float:
        return self.coeffs[3] if len(self.coeffs) > 3 else 0.0


@dataclass(frozen=True)
class ArtifactImproperType:
    """FF-neutral improper type from curated artifact."""

    key: str  # canonical "A-B-C-D" string
    style: str = "harmonic"  # "harmonic" | "cvff"
    coeffs: tuple[float, ...] = (0.0, 180.0)

    # Backward compat
    @property
    def k(self) -> float:
        return self.coeffs[0] if len(self.coeffs) > 0 else 0.0

    @property
    def phi0(self) -> float:
        return self.coeffs[1] if len(self.coeffs) > 1 else 180.0


@dataclass(frozen=True)
class ArtifactImproperInstance:
    """One improper torsion instance (4 atom indices, 1-based)."""

    atom1: int
    atom2: int
    atom3: int
    atom4: int


@dataclass(frozen=True)
class OrganicCuratedArtifact:
    """A curated FF-neutral force-field artifact for one molecule."""

    schema_version: int
    mol_id: str
    generator: str
    generator_version: str
    provenance: str
    canonical_smiles: str
    formal_charge: int
    topology_hash: str
    atoms: tuple[ArtifactAtom, ...]
    bond_types: tuple[ArtifactBondType, ...] = field(default_factory=tuple)
    angle_types: tuple[ArtifactAngleType, ...] = field(default_factory=tuple)
    dihedral_types: tuple[ArtifactDihedralType, ...] = field(default_factory=tuple)
    improper_types: tuple[ArtifactImproperType, ...] = field(default_factory=tuple)
    improper_instances: tuple[ArtifactImproperInstance, ...] = field(default_factory=tuple)
    ff_family: str = "organic_gaff2"
    charge_model: str = ""

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "mol_id": self.mol_id,
            "generator": self.generator,
            "generator_version": self.generator_version,
            "provenance": self.provenance,
            "canonical_smiles": self.canonical_smiles,
            "formal_charge": self.formal_charge,
            "topology_hash": self.topology_hash,
            "ff_family": self.ff_family,
            "charge_model": self.charge_model,
            "atoms": [
                {
                    "index": a.index,
                    "element": a.element,
                    "ff_type": a.ff_type,
                    "charge": a.charge,
                    **({"epsilon": a.epsilon} if a.epsilon is not None else {}),
                    **({"sigma": a.sigma} if a.sigma is not None else {}),
                }
                for a in self.atoms
            ],
            "bond_types": [{"key": b.key, "k": b.k, "r0": b.r0} for b in self.bond_types],
            "angle_types": [{"key": a.key, "k": a.k, "theta0": a.theta0} for a in self.angle_types],
            "dihedral_types": [
                {"key": d.key, "style": d.style, "coeffs": list(d.coeffs)}
                for d in self.dihedral_types
            ],
            "improper_types": [
                {"key": i.key, "style": i.style, "coeffs": list(i.coeffs)}
                for i in self.improper_types
            ],
            "improper_instances": [
                {
                    "atom1": ii.atom1,
                    "atom2": ii.atom2,
                    "atom3": ii.atom3,
                    "atom4": ii.atom4,
                }
                for ii in self.improper_instances
            ],
        }
        return result


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def _require_keys(payload: dict[str, Any], keys: tuple[str, ...], where: str) -> None:
    missing = [k for k in keys if k not in payload]
    if missing:
        raise ArtifactSchemaError(f"Artifact {where} missing required keys: {sorted(missing)}")


def _parse_atoms(payload_atoms: Any, mol_id: str) -> tuple[ArtifactAtom, ...]:
    if not isinstance(payload_atoms, list) or not payload_atoms:
        raise ArtifactSchemaError(f"Artifact for '{mol_id}' has empty or non-list atoms field")
    parsed: list[ArtifactAtom] = []
    for raw in payload_atoms:
        if not isinstance(raw, dict):
            raise ArtifactSchemaError(f"Artifact for '{mol_id}' has non-dict atom entry: {raw!r}")
        _require_keys(raw, ("index", "element", "ff_type", "charge"), f"atom in '{mol_id}'")
        try:
            parsed.append(
                ArtifactAtom(
                    index=int(raw["index"]),
                    element=str(raw["element"]),
                    ff_type=str(raw["ff_type"]),
                    charge=float(raw["charge"]),
                    epsilon=float(raw["epsilon"]) if raw.get("epsilon") is not None else None,
                    sigma=float(raw["sigma"]) if raw.get("sigma") is not None else None,
                )
            )
        except (TypeError, ValueError) as exc:
            raise ArtifactSchemaError(
                f"Artifact for '{mol_id}' has malformed atom entry {raw!r}: {exc}"
            ) from exc
    return tuple(parsed)


def _parse_bond_types(payload: Any, mol_id: str) -> tuple[ArtifactBondType, ...]:
    if payload is None:
        return ()
    if not isinstance(payload, list):
        raise ArtifactSchemaError(f"Artifact for '{mol_id}' has non-list bond_types field")
    parsed: list[ArtifactBondType] = []
    for raw in payload:
        if not isinstance(raw, dict):
            raise ArtifactSchemaError(
                f"Artifact for '{mol_id}' has non-dict bond_type entry: {raw!r}"
            )
        _require_keys(raw, ("key", "k", "r0"), f"bond_type in '{mol_id}'")
        parsed.append(
            ArtifactBondType(
                key=str(raw["key"]),
                k=float(raw["k"]),
                r0=float(raw["r0"]),
            )
        )
    return tuple(parsed)


def _parse_angle_types(payload: Any, mol_id: str) -> tuple[ArtifactAngleType, ...]:
    if payload is None:
        return ()
    if not isinstance(payload, list):
        raise ArtifactSchemaError(f"Artifact for '{mol_id}' has non-list angle_types field")
    parsed: list[ArtifactAngleType] = []
    for raw in payload:
        if not isinstance(raw, dict):
            raise ArtifactSchemaError(
                f"Artifact for '{mol_id}' has non-dict angle_type entry: {raw!r}"
            )
        _require_keys(raw, ("key", "k", "theta0"), f"angle_type in '{mol_id}'")
        parsed.append(
            ArtifactAngleType(
                key=str(raw["key"]),
                k=float(raw["k"]),
                theta0=float(raw["theta0"]),
            )
        )
    return tuple(parsed)


def _parse_dihedral_types(payload: Any, mol_id: str) -> tuple[ArtifactDihedralType, ...]:
    if payload is None:
        return ()
    if not isinstance(payload, list):
        raise ArtifactSchemaError(f"Artifact for '{mol_id}' has non-list dihedral_types field")
    parsed: list[ArtifactDihedralType] = []
    for raw in payload:
        if not isinstance(raw, dict):
            raise ArtifactSchemaError(
                f"Artifact for '{mol_id}' has non-dict dihedral_type entry: {raw!r}"
            )
        _require_keys(raw, ("key",), f"dihedral_type in '{mol_id}'")
        if "style" in raw:
            # v2 format: FF-neutral style + coeffs
            style = str(raw["style"])
            coeffs = tuple(float(c) for c in raw.get("coeffs", []))
        else:
            # v1 OPLS format (backward compat)
            _require_keys(
                raw,
                ("k1", "k2", "k3", "k4"),
                f"dihedral_type in '{mol_id}'",
            )
            style = "opls"
            coeffs = (
                float(raw["k1"]),
                float(raw["k2"]),
                float(raw["k3"]),
                float(raw["k4"]),
            )
        parsed.append(ArtifactDihedralType(key=str(raw["key"]), style=style, coeffs=coeffs))
    return tuple(parsed)


def _parse_improper_types(payload: Any, mol_id: str) -> tuple[ArtifactImproperType, ...]:
    if payload is None:
        return ()
    if not isinstance(payload, list):
        raise ArtifactSchemaError(f"Artifact for '{mol_id}' has non-list improper_types field")
    parsed: list[ArtifactImproperType] = []
    for raw in payload:
        if not isinstance(raw, dict):
            raise ArtifactSchemaError(
                f"Artifact for '{mol_id}' has non-dict improper_type entry: {raw!r}"
            )
        _require_keys(raw, ("key",), f"improper_type in '{mol_id}'")
        if "style" in raw:
            # v2 format: FF-neutral style + coeffs
            style = str(raw["style"])
            coeffs = tuple(float(c) for c in raw.get("coeffs", []))
        else:
            # v1 harmonic format (backward compat)
            style = "harmonic"
            coeffs = (float(raw.get("k", 0.0)), float(raw.get("phi0", 180.0)))
        parsed.append(ArtifactImproperType(key=str(raw["key"]), style=style, coeffs=coeffs))
    return tuple(parsed)


def _parse_improper_instances(payload: Any, mol_id: str) -> tuple[ArtifactImproperInstance, ...]:
    """Parse improper instances (atom 4-tuples) from artifact JSON."""
    if payload is None:
        return ()
    if not isinstance(payload, list):
        return ()
    parsed: list[ArtifactImproperInstance] = []
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        try:
            parsed.append(
                ArtifactImproperInstance(
                    atom1=int(raw["atom1"]),
                    atom2=int(raw["atom2"]),
                    atom3=int(raw["atom3"]),
                    atom4=int(raw["atom4"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(parsed)


def parse_artifact_payload(payload: dict[str, Any]) -> OrganicCuratedArtifact:
    """Validate a raw artifact dict and return an :class:`OrganicCuratedArtifact`.

    Supports both v1 (OPLS-specific k1-k4) and v2 (FF-neutral style+coeffs)
    artifact schemas.

    Raises:
        ArtifactSchemaError: on any structural / type / version mismatch.
    """
    if not isinstance(payload, dict):
        raise ArtifactSchemaError("Artifact payload is not a JSON object")

    _require_keys(
        payload,
        (
            "schema_version",
            "mol_id",
            "generator",
            "canonical_smiles",
            "formal_charge",
            "topology_hash",
            "atoms",
        ),
        "artifact root",
    )

    try:
        schema_version = int(payload["schema_version"])
    except (TypeError, ValueError) as exc:
        raise ArtifactSchemaError(
            f"Artifact schema_version is not an integer: {payload.get('schema_version')!r}"
        ) from exc

    if schema_version not in (1, 2):
        raise ArtifactSchemaError(
            f"Unsupported artifact schema_version={schema_version}; "
            f"this build expects 1 or 2. Regenerate via "
            f"scripts/generate_organic_artifact.py."
        )

    mol_id = str(payload["mol_id"])
    if not mol_id:
        raise ArtifactSchemaError("Artifact mol_id is empty")

    try:
        formal_charge = int(payload["formal_charge"])
    except (TypeError, ValueError) as exc:
        raise ArtifactSchemaError(
            f"Artifact for '{mol_id}' formal_charge is not an integer"
        ) from exc

    # v2 fields with v1 defaults
    ff_family = str(payload.get("ff_family", "organic_gaff2"))
    charge_model = str(payload.get("charge_model", ""))

    return OrganicCuratedArtifact(
        schema_version=schema_version,
        mol_id=mol_id,
        generator=str(payload["generator"]),
        generator_version=str(payload.get("generator_version") or ""),
        provenance=str(payload.get("provenance") or ""),
        canonical_smiles=str(payload["canonical_smiles"]),
        formal_charge=formal_charge,
        topology_hash=str(payload["topology_hash"]),
        atoms=_parse_atoms(payload["atoms"], mol_id),
        bond_types=_parse_bond_types(payload.get("bond_types"), mol_id),
        angle_types=_parse_angle_types(payload.get("angle_types"), mol_id),
        dihedral_types=_parse_dihedral_types(payload.get("dihedral_types"), mol_id),
        improper_types=_parse_improper_types(payload.get("improper_types"), mol_id),
        improper_instances=_parse_improper_instances(payload.get("improper_instances"), mol_id),
        ff_family=ff_family,
        charge_model=charge_model,
    )


# ---------------------------------------------------------------------------
# Loader (with in-memory cache)
# ---------------------------------------------------------------------------


def get_artifact_directory(ff_family: str = "organic_gaff2") -> Path:
    """Return the absolute path of the curated artifact catalog directory.

    Args:
        ff_family: Force field family key. Currently only
            ``"organic_gaff2"`` is supported.
    """
    _DIRS: dict[str, str] = {
        "organic_gaff2": ARTIFACT_DIR_GAFF2,
    }
    rel = _DIRS.get(ff_family, ARTIFACT_DIR_GAFF2)
    return get_project_root() / rel


def artifact_filename_for(source_id: str) -> str:
    """Resolve a source_id to its artifact filename.

    ``ff_assignment.source_id`` holds the artifact filename relative to
    ``data/forcefield_artifacts/organic_gaff2/`` (e.g., ``Toluene.json``).
    If the source_id has no extension, ``.json`` is appended.
    """
    name = source_id.strip()
    if not name:
        return name
    if "/" in name or "\\" in name or ".." in name:
        # Defense in depth: source_id must not escape the catalog dir.
        raise ArtifactSchemaError(
            f"Artifact source_id contains a path separator or '..': {source_id!r}"
        )
    if not name.lower().endswith(".json"):
        name = f"{name}.json"
    return name


# Process-local in-memory cache: artifact bytes are deterministic per file,
# so it is safe to memoize. The catalog itself is the persistent SSOT.
# Key format: "{ff_family}:{source_id}" for multi-family support.
_ARTIFACT_CACHE: dict[str, OrganicCuratedArtifact] = {}


def clear_artifact_cache() -> None:
    """Test helper: drop the in-memory artifact cache."""
    _ARTIFACT_CACHE.clear()


def _cache_key(source_id: str, ff_family: str = "organic_gaff2") -> str:
    """Build the composite cache key for a given source_id and FF family."""
    return f"{ff_family}:{source_id}"


def load_artifact(
    source_id: str,
    ff_family: str = "organic_gaff2",
) -> OrganicCuratedArtifact:
    """Load and validate the artifact identified by ``source_id``.

    Args:
        source_id: Artifact filename (or stem) relative to the catalog
            directory for *ff_family*.
        ff_family: Force field family key (``"organic_gaff2"``).
            Determines which catalog directory to search.

    Raises:
        ArtifactMissingError: if the file does not exist on disk.
        ArtifactSchemaError: if the file exists but is malformed.
    """
    ck = _cache_key(source_id, ff_family)
    cached = _ARTIFACT_CACHE.get(ck)
    if cached is not None:
        return cached

    filename = artifact_filename_for(source_id)
    if not filename:
        raise ArtifactSchemaError("source_id is empty")

    artifact_path = get_artifact_directory(ff_family) / filename
    if not artifact_path.exists():
        raise ArtifactMissingError(
            f"Curated artifact not found: {artifact_path}. "
            "Generate it via scripts/generate_gaff2_artifact.py and commit "
            f"the JSON file under data/forcefield_artifacts/{ff_family}/."
        )

    try:
        raw = json.loads(artifact_path.read_text())
    except json.JSONDecodeError as exc:
        raise ArtifactSchemaError(f"Artifact JSON parse failed for {artifact_path}: {exc}") from exc

    artifact = parse_artifact_payload(raw)
    _ARTIFACT_CACHE[ck] = artifact
    logger.info(
        "Loaded curated artifact: ff_family=%s source_id=%s mol_id=%s atoms=%d generator=%s",
        ff_family,
        source_id,
        artifact.mol_id,
        len(artifact.atoms),
        artifact.generator,
    )
    return artifact


# ---------------------------------------------------------------------------
# Topology application
# ---------------------------------------------------------------------------


def apply_artifact_to_topology(
    topology: Any,
    artifact: OrganicCuratedArtifact,
) -> dict[str, Any]:
    """Apply a curated artifact to ``topology`` in place.

    Validates atom-by-atom shape match (count, index, element) before
    mutating any field. On success the topology atoms have ``ff_type``
    and ``charge`` set with ``charge_defined=True``.

    Returns:
        Dict of bonded parameter overrides for MolTopologyBuilder::

            {
                "bond_types": {key: BondTypeParams(...)},
                "angle_types": {key: AngleTypeParams(...)},
                "dihedral_types": {key: DihedralTypeParams(...)},
                "improper_types": {key: ImproperTypeParams(...)},
            }

    Raises:
        ArtifactSchemaError: on any shape / element mismatch.
    """
    n_artifact_atoms = len(artifact.atoms)
    n_topology_atoms = len(topology.atoms)
    if n_artifact_atoms != n_topology_atoms:
        raise ArtifactSchemaError(
            f"Artifact for '{artifact.mol_id}' atom count {n_artifact_atoms} "
            f"does not match live topology {n_topology_atoms}"
        )

    for cached, atom in zip(artifact.atoms, topology.atoms, strict=True):
        if int(cached.index) != int(atom.index):
            raise ArtifactSchemaError(
                f"Artifact for '{artifact.mol_id}' atom index mismatch: "
                f"artifact={cached.index} topology={atom.index}"
            )
        if str(cached.element) != str(atom.element):
            raise ArtifactSchemaError(
                f"Artifact for '{artifact.mol_id}' atom #{cached.index} element "
                f"mismatch: artifact={cached.element!r} topology={atom.element!r}"
            )

    # Mutate after the full pre-check passes so partial-failures cannot
    # leave the topology in a half-applied state.
    for cached, atom in zip(artifact.atoms, topology.atoms, strict=True):
        atom.ff_type = cached.ff_type
        atom.charge = float(cached.charge)
        atom.charge_defined = True

    # Set improper instances on topology if artifact provides them
    if artifact.improper_instances:
        topology.improper_instances = [
            (ii.atom1, ii.atom2, ii.atom3, ii.atom4) for ii in artifact.improper_instances
        ]

    # Build bonded param overrides from artifact
    from contracts.policies.forcefield import (
        AngleTypeParams,
        BondTypeParams,
        DihedralTypeParams,
        ImproperTypeParams,
    )

    overrides: dict[str, Any] = {
        "bond_types": {},
        "angle_types": {},
        "dihedral_types": {},
        "improper_types": {},
        "atom_types": {},
    }
    for bt in artifact.bond_types:
        overrides["bond_types"][bt.key] = BondTypeParams(k=bt.k, r0=bt.r0)
    for at in artifact.angle_types:
        overrides["angle_types"][at.key] = AngleTypeParams(k=at.k, theta0=at.theta0)
    for dt in artifact.dihedral_types:
        overrides["dihedral_types"][dt.key] = DihedralTypeParams(style=dt.style, coeffs=dt.coeffs)
    for it in artifact.improper_types:
        overrides["improper_types"][it.key] = ImproperTypeParams(style=it.style, coeffs=it.coeffs)

    # Build per-atom-type LJ overrides from artifact (GAFF2 epsilon/sigma)
    from forcefield.uff_element_fallback import UFF_ELEMENT_FALLBACKS

    for cached in artifact.atoms:
        if cached.epsilon is not None and cached.sigma is not None:
            if cached.ff_type not in overrides["atom_types"]:
                element_mass = UFF_ELEMENT_FALLBACKS.get(cached.element, {}).get("mass", 12.011)
                overrides["atom_types"][cached.ff_type] = {
                    "mass": element_mass,
                    "epsilon": cached.epsilon,
                    "sigma": cached.sigma,
                    "charge": 0.0,
                    "element": cached.element,
                }

    # Pass improper instances for topology builder
    overrides["improper_instances"] = [
        (ii.atom1, ii.atom2, ii.atom3, ii.atom4) for ii in artifact.improper_instances
    ]

    return overrides


__all__ = [
    "ARTIFACT_SCHEMA_VERSION",
    "ARTIFACT_DIR_NAME",
    "ARTIFACT_DIR_GAFF2",
    "ArtifactError",
    "ArtifactMissingError",
    "ArtifactIncompleteError",
    "ArtifactSchemaError",
    "ArtifactAtom",
    "ArtifactBondType",
    "ArtifactAngleType",
    "ArtifactDihedralType",
    "ArtifactImproperType",
    "OrganicCuratedArtifact",
    "parse_artifact_payload",
    "get_artifact_directory",
    "artifact_filename_for",
    "load_artifact",
    "clear_artifact_cache",
    "apply_artifact_to_topology",
]
