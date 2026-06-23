"""Canonical feature builder for training and inference contracts.

This module centralizes feature assembly so training loaders, serving adapters,
and inverse-design utilities share the same ordered feature construction logic.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np

from common.hashing import compute_content_hash
from contracts.policies.ml_policy import FeatureSetVersion
from contracts.policies.tier import DEFAULT_SCREENING_TARGET_ATOMS

from .feature_registry import FeatureRegistry


@dataclass(slots=True)
class FeatureBuildInput:
    """Structured input for canonical feature construction."""

    asphaltene_wt: float = 0.0
    resin_wt: float = 0.0
    aromatic_wt: float = 0.0
    saturate_wt: float = 0.0
    additive_wt: float = 0.0
    temperature_k: float = 298.0
    pressure_atm: float = 1.0
    target_atoms: float = float(DEFAULT_SCREENING_TARGET_ATOMS)
    material_id: str | None = None
    binder_type: str | None = None
    structure_size: str | None = None
    aging_state: str | None = None
    force_field_name: str | None = None
    force_field_version: str | None = None
    tensile_strain_rate_1_per_ps: float | None = None
    tensile_pull_velocity_a_per_fs: float | None = None
    shear_rate_1_per_ps: float | None = None
    additive_type: str | None = None
    additive_mol_id: str | None = None
    molecule_features: Mapping[str, float] | None = None
    crystal_features: Mapping[str, float] | None = None
    amorphous_features: Mapping[str, float] | None = None
    stack_features: Mapping[str, float] | None = None
    structural_features: Mapping[str, float] | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    @classmethod
    def from_prediction_composition(
        cls,
        composition: Mapping[str, float],
        *,
        additive_type: str | None = None,
        additive_mol_id: str | None = None,
        temperature_k: float = 298.0,
        pressure_atm: float = 1.0,
        target_atoms: int = DEFAULT_SCREENING_TARGET_ATOMS,
        molecule_features: Mapping[str, float] | None = None,
        crystal_features: Mapping[str, float] | None = None,
        amorphous_features: Mapping[str, float] | None = None,
        stack_features: Mapping[str, float] | None = None,
        structural_features: Mapping[str, float] | None = None,
    ) -> FeatureBuildInput:
        """Create canonical input from serving/inverse-design composition keys."""
        return cls(
            asphaltene_wt=float(composition.get("asphaltene", 0.0)),
            resin_wt=float(composition.get("resin", 0.0)),
            aromatic_wt=float(composition.get("aromatic", 0.0)),
            saturate_wt=float(composition.get("saturate", 0.0)),
            additive_wt=float(composition.get("additive", 0.0)),
            temperature_k=float(composition.get("temperature_k", temperature_k)),
            pressure_atm=float(composition.get("pressure_atm", pressure_atm)),
            target_atoms=float(composition.get("target_atoms", target_atoms)),
            material_id=composition.get("material_id"),
            binder_type=composition.get("binder_type"),
            structure_size=composition.get("structure_size"),
            aging_state=composition.get("aging_state"),
            force_field_name=composition.get("force_field_name"),
            force_field_version=composition.get("force_field_version"),
            tensile_strain_rate_1_per_ps=composition.get("tensile_strain_rate_1_per_ps"),
            tensile_pull_velocity_a_per_fs=composition.get("tensile_pull_velocity_a_per_fs"),
            shear_rate_1_per_ps=composition.get("shear_rate_1_per_ps"),
            additive_type=additive_type or composition.get("additive_type"),
            additive_mol_id=additive_mol_id or composition.get("additive_mol_id"),
            molecule_features=molecule_features,
            crystal_features=crystal_features,
            amorphous_features=amorphous_features,
            stack_features=stack_features,
            structural_features=structural_features,
        )


def _stable_code(value: str | None) -> float:
    """Encode categorical context into a deterministic numeric code."""
    if not value:
        return 0.0
    token = compute_content_hash(str(value), algorithm="md5", length=8)
    return int(token, 16) / 0xFFFFFFFF


@dataclass(slots=True)
class FeatureBuildResult:
    """Built feature payload for a specific contract version."""

    version: FeatureSetVersion
    feature_names: list[str]
    values: np.ndarray
    schema_hash: str
    record: dict[str, float]


def build_feature_record(build_input: FeatureBuildInput) -> dict[str, float]:
    """Build a canonical feature record containing all currently supported features."""
    from .additive_features import AdditiveFeatureExtractor
    from .amorphous_features import AMORPHOUS_FEATURE_NAMES
    from .crystal_features import CRYSTAL_FEATURE_NAMES
    from .molecule_features import MOLECULE_FEATURE_NAMES
    from .structural_features import STRUCTURAL_FEATURE_NAMES

    record: dict[str, float] = {
        "asphaltene_wt": float(build_input.asphaltene_wt),
        "resin_wt": float(build_input.resin_wt),
        "aromatic_wt": float(build_input.aromatic_wt),
        "saturate_wt": float(build_input.saturate_wt),
        "additive_wt": float(build_input.additive_wt),
    }
    record["polar_fraction"] = record["asphaltene_wt"] + record["resin_wt"]
    record["nonpolar_fraction"] = record["aromatic_wt"] + record["saturate_wt"]
    record["asphaltene_resin_ratio"] = (
        record["asphaltene_wt"] / record["resin_wt"] if record["resin_wt"] > 0 else 0.0
    )
    record["temperature_k"] = float(build_input.temperature_k)
    record["pressure_atm"] = float(build_input.pressure_atm)
    record["target_atoms"] = float(build_input.target_atoms)
    aging_state = (build_input.aging_state or "").strip().lower()
    record["material_id_code"] = _stable_code(build_input.material_id)
    record["binder_type_code"] = _stable_code(build_input.binder_type)
    record["structure_size_code"] = _stable_code(build_input.structure_size)
    record["aging_state_non_aging"] = 1.0 if aging_state in {"non_aging", "u"} else 0.0
    record["aging_state_short_aging"] = 1.0 if aging_state in {"short_aging", "s"} else 0.0
    record["aging_state_long_aging"] = 1.0 if aging_state in {"long_aging", "l"} else 0.0
    record["force_field_name_code"] = _stable_code(build_input.force_field_name)
    record["force_field_version_code"] = _stable_code(build_input.force_field_version)
    record["tensile_strain_rate_1_per_ps"] = float(build_input.tensile_strain_rate_1_per_ps or 0.0)
    record["tensile_pull_velocity_a_per_fs"] = float(
        build_input.tensile_pull_velocity_a_per_fs or 0.0
    )
    record["shear_rate_1_per_ps"] = float(build_input.shear_rate_1_per_ps or 0.0)

    additive_extractor = AdditiveFeatureExtractor()
    additive_features = additive_extractor.extract(
        additive_type=build_input.additive_type,
        additive_mol_id=build_input.additive_mol_id,
        additive_wt=record["additive_wt"],
        asphaltene_wt=record["asphaltene_wt"],
        polar_fraction=record["polar_fraction"],
    )
    record.update(additive_features)

    molecule_features = build_input.molecule_features or {}
    for name in MOLECULE_FEATURE_NAMES:
        record[name] = float(molecule_features.get(name, 0.0))

    crystal_features = build_input.crystal_features or {}
    for name in CRYSTAL_FEATURE_NAMES:
        record[name] = float(crystal_features.get(name, 0.0))

    amorphous_features = build_input.amorphous_features or {}
    for name in AMORPHOUS_FEATURE_NAMES:
        record[name] = float(amorphous_features.get(name, 0.0))

    stack_features = build_input.stack_features or {}
    for name, value in stack_features.items():
        record[name] = float(value)

    structural_features = build_input.structural_features or {}
    for name in STRUCTURAL_FEATURE_NAMES:
        record[name] = float(structural_features.get(name, 0.0))

    return record


def build_feature_result(
    build_input: FeatureBuildInput,
    version: FeatureSetVersion,
) -> FeatureBuildResult:
    """Build ordered features and schema hash for a contract version."""
    record = build_feature_record(build_input)
    feature_names = FeatureRegistry.get_features(version)
    values = np.array([float(record.get(name, 0.0)) for name in feature_names], dtype=float)
    return FeatureBuildResult(
        version=version,
        feature_names=feature_names,
        values=values,
        schema_hash=FeatureRegistry.compute_schema_hash(feature_names),
        record=record,
    )


def build_feature_results(
    build_input: FeatureBuildInput,
    versions: list[FeatureSetVersion],
) -> dict[str, FeatureBuildResult]:
    """Build multiple feature-set payloads from the same canonical input."""
    record = build_feature_record(build_input)
    results: dict[str, FeatureBuildResult] = {}
    for version in versions:
        feature_names = FeatureRegistry.get_features(version)
        values = np.array([float(record.get(name, 0.0)) for name in feature_names], dtype=float)
        results[version.value] = FeatureBuildResult(
            version=version,
            feature_names=feature_names,
            values=values,
            schema_hash=FeatureRegistry.compute_schema_hash(feature_names),
            record=dict(record),
        )
    return results
