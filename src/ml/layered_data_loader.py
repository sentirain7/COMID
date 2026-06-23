"""
Layered data loader for V4 ML training.

Loads layered experiment data with crystal + amorphous features
joined via the layered_experiment_sources lineage table.
"""

from __future__ import annotations

import logging
from typing import Any

from common.hashing import compute_content_hash
from contracts.policies.ml_policy import DEFAULT_ML_POLICY, FeatureSetVersion

from .amorphous_features import AmorphousFeatureExtractor
from .crystal_features import CrystalFeatureExtractor
from .data_loader import DataLoader, TargetVariable, TrainingDataset
from .feature_builder import FeatureBuildInput, build_feature_result
from .feature_registry import FeatureRegistry
from .molecule_features import MoleculeFeatureExtractor

_logger = logging.getLogger(__name__)


class LayeredDataLoader:
    """Data loader for V4 (layered structure) training data.

    Extends DataLoader with crystal + amorphous features from the
    layered_experiment_sources lineage table.
    """

    def __init__(self) -> None:
        self._base_loader = DataLoader()
        self._crystal_extractor = CrystalFeatureExtractor()
        self._amorphous_extractor = AmorphousFeatureExtractor()
        self._molecule_extractor = MoleculeFeatureExtractor()

    def load_from_database(
        self,
        db_session: Any,
        target: TargetVariable = TargetVariable.ADHESION,
        min_samples: int = 20,
        feature_set_version: FeatureSetVersion = FeatureSetVersion.V4,
        strict_feature_set: bool = False,
    ) -> TrainingDataset | None:
        """Load layered training data from layered experiments.

        Args:
            db_session: Database session.
            target: Target variable to predict.
            min_samples: Minimum samples required.
            strict_feature_set: If True, raise on insufficient data.

        Returns:
            TrainingDataset with V4/V6 features or None.
        """
        try:
            from sqlalchemy.orm import joinedload

            from database.models import (
                AmorphousCellModel,
                CrystalStructureModel,
                ExperimentModel,
            )
            from database.repositories.layered_source_repo import LayeredSourceRepository

            # Query completed layered experiments
            experiments = (
                db_session.query(ExperimentModel)
                .filter(
                    ExperimentModel.status == "completed",
                    ExperimentModel.study_type == "layer_bulkff",
                )
                .options(joinedload(ExperimentModel.metrics))
                .all()
            )
            if not experiments:
                _logger.warning(
                    "No completed layered experiments found after study_type filtering. "
                    "Legacy/null study_type rows may require backfill before retraining."
                )

            if len(experiments) < min_samples:
                if strict_feature_set:
                    raise ValueError(
                        f"{feature_set_version.value.upper()} requires {min_samples} layered samples, "
                        f"got {len(experiments)}"
                    )
                _logger.warning(
                    "Insufficient layered samples (%d < %d), %s not available",
                    len(experiments),
                    min_samples,
                    feature_set_version.value.upper(),
                )
                return None

            source_repo = LayeredSourceRepository(db_session)
            from contracts.policies.tier import DEFAULT_SCREENING_TARGET_ATOMS

            requested_feature_set = feature_set_version
            actual_feature_set = feature_set_version
            sources_by_exp = {
                exp.exp_id: source_repo.get_sources(exp.exp_id) for exp in experiments
            }

            if feature_set_version == FeatureSetVersion.V6:
                valid_experiments = []
                three_plus_layer_count = 0
                stack_signatures: set[str] = set()
                for exp in experiments:
                    sources = sources_by_exp.get(exp.exp_id, [])
                    meta = exp.metadata_json or {}
                    if not sources or meta.get("lineage_incomplete"):
                        continue
                    valid_experiments.append(exp)
                    if len(sources) >= 3:
                        three_plus_layer_count += 1
                    stack_signatures.add(self._build_stack_signature(sources))

                if (
                    len(valid_experiments) < DEFAULT_ML_POLICY.min_layered_samples_for_v6
                    or three_plus_layer_count
                    < DEFAULT_ML_POLICY.min_three_plus_layer_samples_for_v6
                    or len(stack_signatures)
                    < DEFAULT_ML_POLICY.min_distinct_stack_signatures_for_v6
                ):
                    if strict_feature_set:
                        raise ValueError(
                            "V6 requires sufficient layered stack coverage "
                            f"(samples={len(valid_experiments)}, three_plus={three_plus_layer_count}, "
                            f"stack_signatures={len(stack_signatures)})"
                        )
                    _logger.warning(
                        "Insufficient stack coverage for V6 "
                        "(samples=%d, three_plus=%d, stack_signatures=%d), falling back to V4",
                        len(valid_experiments),
                        three_plus_layer_count,
                        len(stack_signatures),
                    )
                    feature_set_version = FeatureSetVersion.V4
                    actual_feature_set = FeatureSetVersion.V4

            feature_names = FeatureRegistry.get_features(feature_set_version)
            data = []

            for exp in experiments:
                # Find target metric
                target_value = None
                for metric in exp.metrics:
                    if metric.metric_name == target.value:
                        target_value = metric.value
                        break
                if target_value is None:
                    continue

                # V4: crystal + amorphous from lineage
                sources = sources_by_exp.get(exp.exp_id, [])
                if not sources:
                    _logger.debug("Skipping %s: no lineage sources", exp.exp_id)
                    continue

                meta = exp.metadata_json or {}
                if meta.get("lineage_incomplete"):
                    _logger.debug("Skipping %s: lineage_incomplete flag", exp.exp_id)
                    continue

                crystal_feats = CrystalFeatureExtractor.zeros()
                amorphous_feats = AmorphousFeatureExtractor.zeros()

                # Primary source selection: first of each type (layer_index 최소, 이미 정렬됨)
                from features.common.source_compat import is_interface_like_source

                crystal_sources = [s for s in sources if s.source_type == "crystal_structure"]
                amorphous_sources = [s for s in sources if is_interface_like_source(s.source_type)]

                if crystal_sources:
                    primary_crystal = crystal_sources[0]
                    crystal = (
                        db_session.query(CrystalStructureModel)
                        .filter(CrystalStructureModel.crystal_id == primary_crystal.source_id)
                        .first()
                    )
                    if crystal:
                        crystal_feats = self._crystal_extractor.extract_from_model(crystal)

                if amorphous_sources:
                    primary_amorphous = amorphous_sources[0]
                    # Try legacy DB first
                    amorphous = (
                        db_session.query(AmorphousCellModel)
                        .filter(AmorphousCellModel.amorphous_id == primary_amorphous.source_id)
                        .first()
                    )
                    if amorphous:
                        amorphous_feats = self._amorphous_extractor.extract_from_model(amorphous)
                    else:
                        # YAML interface cell: build adapter dict
                        from features.common.interface_sources import resolve_interface_source

                        cell = resolve_interface_source(
                            primary_amorphous.source_id, session=db_session
                        )
                        if cell:
                            amorphous_feats = self._amorphous_extractor.extract(
                                {
                                    "density": cell.get("actual_density")
                                    or cell.get("target_density", 0),
                                    "atom_count": cell.get("atom_count", 0),
                                }
                            )

                stack_features = (
                    self._build_stack_features(sources)
                    if feature_set_version == FeatureSetVersion.V6
                    else None
                )

                built = build_feature_result(
                    FeatureBuildInput(
                        asphaltene_wt=exp.comp_asphaltene_wt,
                        resin_wt=exp.comp_resin_wt,
                        aromatic_wt=exp.comp_aromatic_wt,
                        saturate_wt=exp.comp_saturate_wt,
                        additive_wt=exp.additive_wt or 0.0,
                        temperature_k=exp.temperature_K or 298.0,
                        pressure_atm=exp.pressure_atm or 1.0,
                        target_atoms=float(exp.target_atoms or DEFAULT_SCREENING_TARGET_ATOMS),
                        material_id=exp.material_id,
                        binder_type=exp.binder_type,
                        structure_size=exp.structure_size,
                        aging_state=exp.aging_state,
                        force_field_name=exp.force_field_name,
                        force_field_version=exp.force_field_version,
                        tensile_strain_rate_1_per_ps=exp.tensile_strain_rate_1_per_ps,
                        tensile_pull_velocity_a_per_fs=exp.tensile_pull_velocity_a_per_fs,
                        shear_rate_1_per_ps=exp.shear_rate_1_per_ps,
                        additive_type=exp.additive_type,
                        additive_mol_id=exp.additive_mol_id,
                        molecule_features=self._molecule_extractor.extract_from_db(
                            db_session, exp.id
                        ),
                        crystal_features=crystal_feats,
                        amorphous_features=amorphous_feats,
                        stack_features=stack_features,
                    ),
                    feature_set_version,
                )
                record: dict[str, Any] = {"exp_id": exp.exp_id, **built.record}
                record[target.value] = target_value
                data.append(record)

            if len(data) < min_samples:
                return None

            dataset = self._base_loader.load_from_dict(data, target, feature_names)
            if dataset is not None:
                dataset.metadata["requested_feature_set"] = requested_feature_set.value
                dataset.metadata["actual_feature_set"] = actual_feature_set.value
                dataset.metadata["layered_samples"] = len(data)
                temps = [float(e.temperature_K or 298.0) for e in experiments]
                dataset.metadata["temperature_range_k"] = (
                    [min(temps), max(temps)] if temps else None
                )
                dataset.metadata["binder_types"] = sorted(
                    {str(e.binder_type) for e in experiments if e.binder_type}
                )
                dataset.metadata["aging_states"] = sorted(
                    {str(e.aging_state) for e in experiments if e.aging_state}
                )
                dataset.metadata["additive_types"] = sorted(
                    {str(e.additive_type) for e in experiments if e.additive_type}
                )
                dataset.metadata["supported_layer_counts"] = sorted(
                    {
                        len(sources_by_exp.get(e.exp_id, []))
                        for e in experiments
                        if sources_by_exp.get(e.exp_id)
                    }
                )
                dataset.metadata["stack_signatures"] = sorted(
                    {
                        self._build_stack_signature(sources_by_exp.get(e.exp_id, []))
                        for e in experiments
                        if sources_by_exp.get(e.exp_id)
                    }
                )
            return dataset

        except ValueError:
            raise
        except Exception as e:
            _logger.warning("Failed to load layered data: %s", e)
            return None

    @staticmethod
    def _build_stack_signature(sources: list[Any]) -> str:
        """Build a stable stack signature from normalized source roles."""
        parts: list[str] = []
        for source in sources:
            source_type = str(source.source_type)
            if source_type == "crystal_structure":
                parts.append("crystal")
            elif source_type == "binder_cell":
                parts.append("binder")
            else:
                parts.append("interface")
        return "|".join(parts)

    @classmethod
    def _build_stack_features(cls, sources: list[Any]) -> dict[str, float]:
        """Build V6 stack-aware summary features from ordered lineage sources."""
        signature = cls._build_stack_signature(sources)
        roles = signature.split("|") if signature else []
        n_crystal = sum(1 for role in roles if role == "crystal")
        n_binder = sum(1 for role in roles if role == "binder")
        n_interface = sum(1 for role in roles if role == "interface")
        features: dict[str, float] = {
            "stack_n_layers": float(len(roles)),
            "stack_n_crystal_layers": float(n_crystal),
            "stack_n_binder_layers": float(n_binder),
            "stack_n_interface_layers": float(n_interface),
            "stack_has_top_crystal": 1.0 if roles and roles[-1] == "crystal" else 0.0,
            "stack_has_bottom_crystal": 1.0 if roles and roles[0] == "crystal" else 0.0,
            "stack_has_any_interface": 1.0 if n_interface > 0 else 0.0,
            "stack_terminal_crystal_symmetry": 1.0
            if len(roles) >= 2 and roles[0] == "crystal" and roles[-1] == "crystal"
            else 0.0,
            "stack_signature_code": int(
                compute_content_hash(signature, algorithm="md5", length=8), 16
            )
            / 0xFFFFFFFF,
        }
        for idx in range(5):
            role = roles[idx] if idx < len(roles) else None
            gap = (
                float(getattr(sources[idx], "gap_after_angstrom", 0.0) or 0.0)
                if idx < len(sources)
                else 0.0
            )
            features[f"layer_{idx}_is_crystal"] = 1.0 if role == "crystal" else 0.0
            features[f"layer_{idx}_is_binder"] = 1.0 if role == "binder" else 0.0
            features[f"layer_{idx}_is_interface"] = 1.0 if role == "interface" else 0.0
            features[f"layer_{idx}_gap_after_norm"] = gap / 10.0
        return features
