"""
Data Loader for ML training.

Loads and preprocesses experiment data for ML model training.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np

from common.hashing import compute_content_hash
from contracts.policies.metrics import DEFAULT_METRICS_REGISTRY
from contracts.policies.ml_policy import DEFAULT_ML_POLICY, FeatureSetVersion
from contracts.policies.tier import DEFAULT_SCREENING_TARGET_ATOMS

from .feature_builder import FeatureBuildInput, build_feature_result
from .feature_registry import (
    COMPOSITION_FEATURES as _COMPOSITION_FEATURES,
)
from .feature_registry import (
    SIMULATION_FEATURES as _SIMULATION_FEATURES,
)
from .feature_registry import V1_FEATURES, FeatureRegistry

_logger = logging.getLogger(__name__)


class TargetVariable(Enum):
    """Target variables for ML prediction.

    Phase 5.2: Extended from 4 to 13 targets.
    All values match contracts/policies/metrics.py DEFAULT_METRICS_REGISTRY.
    """

    # Existing (backward compatible)
    DENSITY = "density"
    CED = "cohesive_energy_density"
    MSD = "msd_diffusion_coefficient"
    ADHESION = "adhesion_energy"

    # Bulk additions (Phase 5.2)
    VISCOSITY = "viscosity"
    RDF_FIRST_PEAK_R = "rdf_first_peak_r"
    RDF_FIRST_PEAK_G = "rdf_first_peak_g"

    # Layer
    ORIENTATION_ORDER = "orientation_order"

    # Mechanical
    TENSILE_STRENGTH = "tensile_strength"
    ELASTIC_MODULUS = "elastic_modulus"
    INTERFACIAL_TENSILE_STRENGTH = "interfacial_tensile_strength"

    # Interfacial interaction
    E_INTER_INTERFACE_1 = "e_inter_interface_1"
    WORK_OF_SEPARATION = "work_of_separation"

    # Phase A: New trainable targets
    RDF_COORDINATION_NUMBER = "rdf_coordination_number"
    E_INTER_TOTAL = "e_inter_total"
    DUCTILITY = "ductility"
    TOUGHNESS = "toughness"

    @classmethod
    def trainable(cls) -> list[TargetVariable]:
        """Return targets that are marked trainable in the metric registry."""
        return [member for member in cls if DEFAULT_METRICS_REGISTRY.is_trainable(member.value)]


@dataclass
class TrainingDataset:
    """Training dataset container."""

    X: np.ndarray  # Feature matrix
    y: np.ndarray  # Target values
    exp_ids: list[str]  # Experiment IDs
    feature_names: list[str]
    target_name: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def n_samples(self) -> int:
        """Number of samples."""
        return len(self.exp_ids)

    @property
    def n_features(self) -> int:
        """Number of features."""
        return self.X.shape[1] if len(self.X.shape) > 1 else 0

    def __len__(self) -> int:
        return self.n_samples


@dataclass
class DataSplit:
    """Data split container."""

    train: TrainingDataset
    val: TrainingDataset
    test: TrainingDataset
    split_info: dict[str, Any] = field(default_factory=dict)


class DataSplitter:
    """
    Data splitter with group-based splitting.

    Supports splitting by additive type to prevent data leakage.
    """

    def __init__(
        self,
        train_ratio: float = 0.70,
        val_ratio: float = 0.15,
        test_ratio: float = 0.15,
        random_seed: int = 42,
    ):
        """
        Initialize splitter.

        Args:
            train_ratio: Fraction for training
            val_ratio: Fraction for validation
            test_ratio: Fraction for testing
            random_seed: Random seed for reproducibility
        """
        assert abs(train_ratio + val_ratio + test_ratio - 1.0) < 0.001
        self.train_ratio = train_ratio
        self.val_ratio = val_ratio
        self.test_ratio = test_ratio
        self.random_seed = random_seed

    def split(
        self,
        dataset: TrainingDataset,
        groups: np.ndarray | None = None,
    ) -> DataSplit:
        """
        Split dataset into train/val/test.

        Args:
            dataset: Dataset to split
            groups: Group labels for group-based splitting

        Returns:
            DataSplit with train, val, test datasets
        """
        np.random.seed(self.random_seed)

        if groups is not None:
            return self._group_split(dataset, groups)
        else:
            return self._random_split(dataset)

    def _random_split(self, dataset: TrainingDataset) -> DataSplit:
        """Random split without groups."""
        n = len(dataset)
        indices = np.random.permutation(n)

        n_train = int(n * self.train_ratio)
        n_val = int(n * self.val_ratio)

        train_idx = indices[:n_train]
        val_idx = indices[n_train : n_train + n_val]
        test_idx = indices[n_train + n_val :]

        return DataSplit(
            train=self._create_subset(dataset, train_idx),
            val=self._create_subset(dataset, val_idx),
            test=self._create_subset(dataset, test_idx),
            split_info={
                "method": "random",
                "train_size": len(train_idx),
                "val_size": len(val_idx),
                "test_size": len(test_idx),
            },
        )

    def _group_split(
        self,
        dataset: TrainingDataset,
        groups: np.ndarray,
    ) -> DataSplit:
        """Group-based split (e.g., by additive type)."""
        unique_groups = np.unique(groups)
        n_groups = len(unique_groups)

        # Shuffle groups
        np.random.shuffle(unique_groups)

        n_train_groups = int(n_groups * self.train_ratio)
        n_val_groups = int(n_groups * self.val_ratio)

        train_groups = set(unique_groups[:n_train_groups])
        val_groups = set(unique_groups[n_train_groups : n_train_groups + n_val_groups])
        test_groups = set(unique_groups[n_train_groups + n_val_groups :])

        train_idx = np.where(np.isin(groups, list(train_groups)))[0]
        val_idx = np.where(np.isin(groups, list(val_groups)))[0]
        test_idx = np.where(np.isin(groups, list(test_groups)))[0]

        # Attach per-sample group labels to train subset for downstream
        # GroupKFold CV usage.
        train_ds = self._create_subset(dataset, train_idx)
        train_ds.metadata["cv_groups"] = groups[train_idx]

        return DataSplit(
            train=train_ds,
            val=self._create_subset(dataset, val_idx),
            test=self._create_subset(dataset, test_idx),
            split_info={
                "method": "group",
                "train_size": len(train_idx),
                "val_size": len(val_idx),
                "test_size": len(test_idx),
                "train_groups": list(train_groups),
                "val_groups": list(val_groups),
                "test_groups": list(test_groups),
            },
        )

    def _create_subset(
        self,
        dataset: TrainingDataset,
        indices: np.ndarray,
    ) -> TrainingDataset:
        """Create a subset of the dataset."""
        return TrainingDataset(
            X=dataset.X[indices],
            y=dataset.y[indices],
            exp_ids=[dataset.exp_ids[i] for i in indices],
            feature_names=dataset.feature_names,
            target_name=dataset.target_name,
            metadata=dataset.metadata.copy(),
        )


class DataLoader:
    """
    Data loader for ML training.

    Loads experiment data and prepares it for ML training.
    """

    # Deprecated aliases — import from ml.feature_registry instead
    COMPOSITION_FEATURES = _COMPOSITION_FEATURES
    SIMULATION_FEATURES = _SIMULATION_FEATURES
    ML_V1_FEATURES = V1_FEATURES

    def __init__(self):
        """Initialize data loader."""
        self._cache: dict[str, Any] = {}

    def load_from_database(
        self,
        db_session: Any,
        target: TargetVariable = TargetVariable.DENSITY,
        ff_type: str = "bulk_ff_gaff2",
        run_tiers: list[str] | None = None,
        min_samples: int = 10,
        feature_set_version: FeatureSetVersion = FeatureSetVersion.V1,
        strict_feature_set: bool = False,
        e_intra_method: str | None = None,
    ) -> TrainingDataset | None:
        """
        Load training data from database.

        Args:
            db_session: Database session
            target: Target variable to predict
            ff_type: Force field type filter
            run_tiers: Run tier filter
            min_samples: Minimum samples required
            feature_set_version: Feature set version (V1 or V2).
            strict_feature_set: If True, raise ValueError instead of
                falling back to V1 when V2 data is insufficient.
            e_intra_method: Filter CED labels by E_intra method tag (PR 2
                Method 1a SSOT).  When ``target == CED`` and this is set,
                only metrics whose ``metadata_json["e_intra_method"]`` matches
                are kept — preventing Method 1 / Method 1a CED labels from
                contaminating the same training set.  ``None`` defaults to
                Method 1 (legacy ``single_molecule_vacuum``) for back-compat.

        Returns:
            TrainingDataset or None if insufficient data
        """
        if run_tiers is None:
            run_tiers = ["screening", "confirm"]
        requested_feature_set = feature_set_version

        try:
            from sqlalchemy.orm import joinedload

            from database.models import ExperimentModel

            # Query completed experiments with metrics
            query = (
                db_session.query(ExperimentModel)
                .filter(
                    ExperimentModel.status == "completed",
                    ExperimentModel.ff_type == ff_type,
                    ExperimentModel.run_tier.in_(run_tiers),
                    ExperimentModel.study_type == "bulk",
                )
                .options(joinedload(ExperimentModel.metrics))
            )

            experiments = query.all()
            if not experiments:
                _logger.warning(
                    "No completed bulk experiments found after study_type filtering. "
                    "Legacy/null study_type rows may require backfill before retraining."
                )

            if len(experiments) < min_samples:
                return None

            # V5 gate: require enough mechanical/material context diversity.
            actual_feature_set = feature_set_version
            if feature_set_version == FeatureSetVersion.V5:
                mechanical_context_count = sum(
                    1
                    for e in experiments
                    if any(
                        value is not None
                        for value in (
                            e.tensile_strain_rate_1_per_ps,
                            e.tensile_pull_velocity_a_per_fs,
                            e.shear_rate_1_per_ps,
                        )
                    )
                )
                distinct_binder_types = len({e.binder_type for e in experiments if e.binder_type})
                distinct_aging_states = len({e.aging_state for e in experiments if e.aging_state})
                if (
                    mechanical_context_count
                    < DEFAULT_ML_POLICY.min_mechanical_context_samples_for_v5
                    or distinct_binder_types < DEFAULT_ML_POLICY.min_distinct_binder_types_for_v5
                    or distinct_aging_states < DEFAULT_ML_POLICY.min_distinct_aging_states_for_v5
                ):
                    if strict_feature_set:
                        raise ValueError(
                            "V5 requires sufficient mechanical/material context coverage "
                            f"(mechanical={mechanical_context_count}, "
                            f"binder_types={distinct_binder_types}, "
                            f"aging_states={distinct_aging_states})"
                        )
                    _logger.warning(
                        "Insufficient context coverage for V5 "
                        "(mechanical=%d, binder_types=%d, aging_states=%d), falling back to V3",
                        mechanical_context_count,
                        distinct_binder_types,
                        distinct_aging_states,
                    )
                    feature_set_version = FeatureSetVersion.V3
                    actual_feature_set = FeatureSetVersion.V3

            # V3 gate: check molecule-level data availability within filtered experiments
            if feature_set_version in (FeatureSetVersion.V3, FeatureSetVersion.V4):
                from database.models import ExperimentMoleculeModel

                filtered_exp_ids = [e.id for e in experiments]
                mol_level_count = (
                    db_session.query(ExperimentMoleculeModel.experiment_id)
                    .filter(
                        ExperimentMoleculeModel.weight_fraction.isnot(None),
                        ExperimentMoleculeModel.experiment_id.in_(filtered_exp_ids),
                    )
                    .distinct()
                    .count()
                )
                if mol_level_count < DEFAULT_ML_POLICY.min_molecule_level_samples_for_v3:
                    if strict_feature_set:
                        raise ValueError(
                            f"V3 requires {DEFAULT_ML_POLICY.min_molecule_level_samples_for_v3} "
                            f"molecule-level samples, got {mol_level_count}"
                        )
                    _logger.warning(
                        "Insufficient molecule-level samples (%d < %d), falling back to V2",
                        mol_level_count,
                        DEFAULT_ML_POLICY.min_molecule_level_samples_for_v3,
                    )
                    feature_set_version = FeatureSetVersion.V2
                    actual_feature_set = FeatureSetVersion.V2

            # V2 gate: check additive sample count
            if feature_set_version in (
                FeatureSetVersion.V2,
                FeatureSetVersion.V3,
                FeatureSetVersion.V4,
            ):
                additive_count = sum(
                    1 for e in experiments if e.additive_type and (e.additive_wt or 0.0) > 0.0
                )
                if additive_count < DEFAULT_ML_POLICY.min_additive_samples_for_v2:
                    if strict_feature_set:
                        raise ValueError(
                            f"V2 requires {DEFAULT_ML_POLICY.min_additive_samples_for_v2} "
                            f"additive samples, got {additive_count}"
                        )
                    _logger.warning(
                        "Insufficient additive samples (%d < %d), falling back to V1",
                        additive_count,
                        DEFAULT_ML_POLICY.min_additive_samples_for_v2,
                    )
                    feature_set_version = FeatureSetVersion.V1
                    actual_feature_set = FeatureSetVersion.V1

            # V7 gate: structural (RDKit) features require RDKit. V7 is a
            # parallel bulk-chemistry branch — it does NOT fall back to V1-V5
            # (different feature philosophy / dimension). Fail-closed instead.
            if feature_set_version == FeatureSetVersion.V7:
                from .structural_features import RDKIT_AVAILABLE

                if not RDKIT_AVAILABLE:
                    if strict_feature_set:
                        raise ValueError("V7 requires RDKit, which is unavailable")
                    _logger.warning("V7 requested but RDKit unavailable — no dataset")
                    return None

            feature_names = FeatureRegistry.get_features(feature_set_version)

            # PR 2 (Method 1a SSOT): for CED targets, partition by
            # ``metadata_json["e_intra_method"]`` so Method 1 and Method 1a
            # labels are not silently mixed into the same training set.
            ced_method_filter: str | None = None
            if target == TargetVariable.CED:
                ced_method_filter = e_intra_method or "single_molecule_vacuum"

            # Feature extractors are hoisted out of the per-experiment loop so
            # the MoleculeDB / aging-yaml is loaded **once** (not rebuilt per
            # experiment — that was a ~200x slowdown: 85s → 0.4s for V7).
            _mol_extractor = None
            if feature_set_version in (FeatureSetVersion.V3, FeatureSetVersion.V4):
                from .molecule_features import MoleculeFeatureExtractor

                _mol_extractor = MoleculeFeatureExtractor()
            _struct_extractor = None
            if feature_set_version == FeatureSetVersion.V7:
                from .structural_features import StructuralFeatureExtractor

                _struct_extractor = StructuralFeatureExtractor()

            # Build dataset
            data = []
            method_drift_skipped = 0
            for exp in experiments:
                # Find target metric
                target_value = None
                for metric in exp.metrics:
                    if metric.metric_name == target.value:
                        if ced_method_filter is not None:
                            metric_meta = getattr(metric, "metadata_json", None) or {}
                            metric_method = metric_meta.get(
                                "e_intra_method", "single_molecule_vacuum"
                            )
                            if metric_method != ced_method_filter:
                                method_drift_skipped += 1
                                continue
                        target_value = metric.value
                        break

                if target_value is None:
                    continue

                molecule_features: dict[str, float] | None = None
                if _mol_extractor is not None:
                    molecule_features = _mol_extractor.extract_from_db(db_session, exp.id)

                structural_features: dict[str, float] | None = None
                if _struct_extractor is not None:
                    structural_features = _struct_extractor.extract_from_db(
                        db_session, exp.id, float(exp.temperature_K or 298.0)
                    )
                    # RDKit/.mol 미해석 시 이 실험은 V7 학습 표본에서 제외
                    if structural_features is None:
                        continue

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
                        molecule_features=molecule_features,
                        structural_features=structural_features,
                    ),
                    feature_set_version,
                )
                record: dict[str, Any] = {
                    "exp_id": exp.exp_id,
                    **built.record,
                    target.value: target_value,
                }

                data.append(record)

            if len(data) < min_samples:
                return None

            dataset = self.load_from_dict(data, target, feature_names)
            if dataset is not None:
                dataset.metadata["requested_feature_set"] = requested_feature_set.value
                dataset.metadata["actual_feature_set"] = actual_feature_set.value
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
                # FF governance metadata — from actual training samples only
                # (not the full query set, which may include label-less experiments).
                dataset.metadata["ff_type"] = ff_type
                _included_exp_ids = set(dataset.exp_ids)
                _included_exps = [e for e in experiments if e.exp_id in _included_exp_ids]
                _stack_counts: dict[str, int] = {}
                _val_counts: dict[str, int] = {}
                _prov_missing = 0
                for exp in _included_exps:
                    _meta = (
                        exp.metadata_json
                        if hasattr(exp, "metadata_json") and isinstance(exp.metadata_json, dict)
                        else {}
                    )
                    _ffp = _meta.get("ff_provenance", {})
                    if not _ffp:
                        _prov_missing += 1
                        continue
                    sid = _ffp.get("stack_id")
                    vlv = _ffp.get("validation_level")
                    if sid:
                        _stack_counts[sid] = _stack_counts.get(sid, 0) + 1
                    if vlv:
                        _val_counts[vlv] = _val_counts.get(vlv, 0) + 1
                if _stack_counts:
                    dataset.metadata["stack_ids"] = sorted(_stack_counts.keys())
                    # Dominant stack = most frequent (not alphabetical)
                    dataset.metadata["dominant_stack_id"] = max(
                        _stack_counts, key=_stack_counts.get
                    )
                else:
                    try:
                        from contracts.policies.forcefield import build_ff_provenance as _bfp

                        _prov = _bfp(study_type="bulk", ff_type=ff_type)
                        dataset.metadata["stack_ids"] = [
                            _prov["metadata"].get("stack_id", "unknown")
                        ]
                        dataset.metadata["dominant_stack_id"] = dataset.metadata["stack_ids"][0]
                    except Exception:
                        dataset.metadata["stack_ids"] = ["unknown"]
                        dataset.metadata["dominant_stack_id"] = "unknown"
                dataset.metadata["validation_levels"] = (
                    sorted(_val_counts.keys()) if _val_counts else ["research_only"]
                )
                dataset.metadata["ff_provenance_missing_count"] = _prov_missing
                dataset.metadata["ff_provenance_completeness"] = (
                    1.0 - (_prov_missing / len(_included_exps)) if _included_exps else 0.0
                )
            return dataset

        except ValueError:
            raise
        except Exception as e:
            _logger.warning("Failed to load from database: %s", e)
            return None

    def load_from_dict(
        self,
        data: list[dict[str, Any]],
        target: TargetVariable = TargetVariable.DENSITY,
        feature_names: list[str] | None = None,
    ) -> TrainingDataset:
        """
        Load training data from list of dictionaries.

        Args:
            data: List of experiment data dictionaries
            target: Target variable
            feature_names: Feature names to extract

        Returns:
            TrainingDataset
        """
        if feature_names is None:
            feature_names = self.ML_V1_FEATURES

        X = []
        y = []
        exp_ids = []

        for record in data:
            # Extract features
            features = []
            valid = True

            for fname in feature_names:
                if fname in record:
                    features.append(float(record[fname]))
                else:
                    valid = False
                    break

            # Extract target
            target_key = target.value
            if target_key not in record:
                valid = False

            if valid:
                X.append(features)
                y.append(float(record[target_key]))
                exp_ids.append(record.get("exp_id", f"exp_{len(exp_ids)}"))

        return TrainingDataset(
            X=np.array(X),
            y=np.array(y),
            exp_ids=exp_ids,
            feature_names=feature_names,
            target_name=target.value,
            metadata={"feature_schema_hash": compute_content_hash(feature_names)},
        )

    def load_from_csv(
        self,
        filepath: Path,
        target: TargetVariable = TargetVariable.DENSITY,
        feature_names: list[str] | None = None,
    ) -> TrainingDataset:
        """
        Load training data from CSV file.

        Args:
            filepath: Path to CSV file
            target: Target variable
            feature_names: Feature names to extract

        Returns:
            TrainingDataset
        """
        import csv

        with open(filepath) as f:
            reader = csv.DictReader(f)
            data = list(reader)

        return self.load_from_dict(data, target, feature_names)

    def normalize_features(
        self,
        dataset: TrainingDataset,
        method: str = "standard",
    ) -> tuple[TrainingDataset, dict[str, Any]]:
        """
        Normalize features.

        Args:
            dataset: Dataset to normalize
            method: "standard" (z-score) or "minmax"

        Returns:
            Tuple of (normalized_dataset, normalization_params)
        """
        X = dataset.X.copy()

        if method == "standard":
            mean = np.mean(X, axis=0)
            std = np.std(X, axis=0)
            std[std == 0] = 1  # Avoid division by zero
            X_norm = (X - mean) / std
            params = {"method": "standard", "mean": mean, "std": std}

        elif method == "minmax":
            min_val = np.min(X, axis=0)
            max_val = np.max(X, axis=0)
            range_val = max_val - min_val
            range_val[range_val == 0] = 1
            X_norm = (X - min_val) / range_val
            params = {"method": "minmax", "min": min_val, "max": max_val}

        else:
            raise ValueError(f"Unknown normalization method: {method}")

        normalized = TrainingDataset(
            X=X_norm,
            y=dataset.y.copy(),
            exp_ids=dataset.exp_ids.copy(),
            feature_names=dataset.feature_names.copy(),
            target_name=dataset.target_name,
            metadata={**dataset.metadata, "normalized": True},
        )

        return normalized, params

    def apply_normalization(
        self,
        X: np.ndarray,
        params: dict[str, Any],
    ) -> np.ndarray:
        """Apply normalization using saved parameters."""
        if params["method"] == "standard":
            return (X - params["mean"]) / params["std"]
        elif params["method"] == "minmax":
            range_val = params["max"] - params["min"]
            range_val[range_val == 0] = 1
            return (X - params["min"]) / range_val
        else:
            raise ValueError(f"Unknown normalization method: {params['method']}")

    def create_ml_v1_dataset(
        self,
        experiments: list[dict[str, Any]],
        metrics: dict[str, dict[str, float]],
        target: TargetVariable = TargetVariable.DENSITY,
    ) -> TrainingDataset:
        """
        Create ML v1 dataset from experiments and metrics.

        Args:
            experiments: List of experiment dictionaries
            metrics: Dict mapping exp_id to metric dict
            target: Target variable

        Returns:
            TrainingDataset ready for ML v1 training
        """
        data = []

        for exp in experiments:
            exp_id = exp.get("exp_id")
            if not exp_id or exp_id not in metrics:
                continue

            exp_metrics = metrics[exp_id]
            target_value = exp_metrics.get(target.value)
            if target_value is None:
                continue

            # Extract composition
            composition = exp.get("composition", {})

            built = build_feature_result(
                FeatureBuildInput.from_prediction_composition(
                    composition,
                    temperature_k=float(exp.get("temperature_k", 298.0)),
                    pressure_atm=float(exp.get("pressure_atm", 1.0)),
                    target_atoms=int(exp.get("target_atoms", DEFAULT_SCREENING_TARGET_ATOMS)),
                ),
                FeatureSetVersion.V1,
            )
            record = {"exp_id": exp_id, **built.record, target.value: target_value}

            data.append(record)

        return self.load_from_dict(data, target, self.ML_V1_FEATURES)

    def get_statistics(self, dataset: TrainingDataset) -> dict[str, Any]:
        """Get dataset statistics."""
        return {
            "n_samples": dataset.n_samples,
            "n_features": dataset.n_features,
            "feature_names": dataset.feature_names,
            "target_name": dataset.target_name,
            "target_stats": {
                "mean": float(np.mean(dataset.y)),
                "std": float(np.std(dataset.y)),
                "min": float(np.min(dataset.y)),
                "max": float(np.max(dataset.y)),
            },
            "feature_stats": {
                name: {
                    "mean": float(np.mean(dataset.X[:, i])),
                    "std": float(np.std(dataset.X[:, i])),
                    "min": float(np.min(dataset.X[:, i])),
                    "max": float(np.max(dataset.X[:, i])),
                }
                for i, name in enumerate(dataset.feature_names)
            },
        }
