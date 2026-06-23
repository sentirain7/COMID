"""Multi-target predictor — per-target EnsemblePredictor management + UQ.

Phase 5.2: Thin wrapper around dict of EnsemblePredictor instances.
Each target gets its own ensemble, enabling target-specific hyperparameters
and independent feature importance analysis.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from contracts.policies.ml_policy import DEFAULT_ML_POLICY

from .data_loader import TargetVariable, TrainingDataset
from .models import EnsemblePredictor, ModelConfig, ModelType, PropertyPredictor

_logger = logging.getLogger(__name__)


@dataclass
class MultiTargetConfig:
    """Configuration for multi-target prediction.

    Attributes:
        targets: Target variables to predict.
        ensemble_size: Number of models per target ensemble.
        model_type: Default model type for all targets.
        target_configs: Per-target ModelConfig overrides (keyed by target value).
        target_feature_sets: Per-target feature set version override.
    """

    targets: list[TargetVariable] = field(default_factory=lambda: list(TargetVariable))
    ensemble_size: int = DEFAULT_ML_POLICY.default_ensemble_size
    model_type: ModelType = ModelType.XGBOOST
    target_configs: dict[str, ModelConfig] = field(default_factory=dict)
    target_feature_sets: dict[str, str] = field(default_factory=dict)

    def get_config_for_target(self, target: TargetVariable) -> ModelConfig:
        """Get ModelConfig for a specific target, with fallback to defaults.

        Args:
            target: Target variable.

        Returns:
            ModelConfig instance.
        """
        if target.value in self.target_configs:
            return self.target_configs[target.value]
        return ModelConfig(
            model_type=self.model_type,
            target_name=target.value,
        )

    def get_feature_set_for_target(self, target_name: str) -> str:
        """Get feature set version for a target.

        Args:
            target_name: Target variable name.

        Returns:
            Feature set version string (e.g. 'v3', 'v4').
        """
        return self.target_feature_sets.get(
            target_name,
            DEFAULT_ML_POLICY.target_feature_sets.get_version(target_name).value,
        )


@dataclass
class MultiTargetResult:
    """Result of multi-target prediction.

    Attributes:
        predictions: Per-target predicted values.
        uncertainties: Per-target uncertainty (ensemble std).
        confidence_intervals: Per-target (lower, upper) CI bounds.
        ood_results: Per-target OOD detection results (if available).
    """

    predictions: dict[str, float] = field(default_factory=dict)
    uncertainties: dict[str, float] = field(default_factory=dict)
    confidence_intervals: dict[str, tuple[float, float]] = field(default_factory=dict)
    ood_results: dict[str, Any] | None = None


@dataclass
class TrainingResult:
    """Result of training a single target.

    Attributes:
        target: Target variable name.
        n_samples: Number of training samples.
        n_features: Number of features.
        ensemble_size: Number of models in ensemble.
    """

    target: str
    n_samples: int = 0
    n_features: int = 0
    ensemble_size: int = 0


class MultiTargetPredictor:
    """Multi-target predictor with per-target ensembles.

    Manages a dictionary of EnsemblePredictor instances, one per target.
    Integrates UncertaintyEstimator and OODDetector when available.

    Args:
        config: Multi-target configuration.
        model_dir: Directory for model persistence.
    """

    def __init__(
        self,
        config: MultiTargetConfig | None = None,
        model_dir: Path | None = None,
    ) -> None:
        self.config = config or MultiTargetConfig()
        self.model_dir = model_dir
        self._ensembles: dict[str, EnsemblePredictor] = {}
        self._ood_detector: Any = None  # OODDetector (opt-in)
        self._ood_detectors: dict[str, Any] = {}
        self._uncertainty_estimators: dict[str, Any] = {}  # UncertaintyEstimator
        self._feature_masks: dict[str, np.ndarray] = {}  # per-target feature index masks
        self._target_transforms: dict[str, dict] = {}  # per-target transform params
        self._requested_feature_set: str | None = None
        self._actual_feature_set: str | None = None
        self._feature_schema_hash: str | None = None
        self._per_target_feature_schema_hashes: dict[str, str] = {}
        self._capability_manifest: dict[str, Any] | None = None
        self._per_target_feature_sets_from_registry: dict[str, str] = {}

    @property
    def fitted_targets(self) -> list[str]:
        """Return list of fitted target names."""
        return [t for t, e in self._ensembles.items() if e.is_fitted]

    def train(
        self,
        datasets: dict[str, TrainingDataset],
    ) -> dict[str, TrainingResult]:
        """Train per-target ensembles.

        Args:
            datasets: Dict mapping target name to TrainingDataset.

        Returns:
            Dict mapping target name to TrainingResult.
        """
        results: dict[str, TrainingResult] = {}

        for target in self.config.targets:
            target_name = target.value
            if target_name not in datasets:
                _logger.warning(f"No data for target '{target_name}', skipping")
                continue

            dataset = datasets[target_name]
            if dataset.n_samples < 2:
                _logger.warning(
                    f"Insufficient samples for '{target_name}' ({dataset.n_samples}), skipping"
                )
                continue

            config = self.config.get_config_for_target(target)
            config.feature_names = dataset.feature_names

            # Create ensemble with different random seeds
            predictors = []
            for i in range(self.config.ensemble_size):
                member_config = ModelConfig(
                    model_type=config.model_type,
                    target_name=config.target_name,
                    n_estimators=config.n_estimators,
                    max_depth=config.max_depth,
                    learning_rate=config.learning_rate,
                    random_state=config.random_state + i,
                    feature_names=config.feature_names,
                )
                predictors.append(PropertyPredictor(member_config))

            ensemble = EnsemblePredictor(predictors=predictors)
            ensemble.fit(dataset.X, dataset.y)
            self._ensembles[target_name] = ensemble

            results[target_name] = TrainingResult(
                target=target_name,
                n_samples=dataset.n_samples,
                n_features=dataset.n_features,
                ensemble_size=len(predictors),
            )
            _logger.info(
                f"Trained {target_name}: {dataset.n_samples} samples, "
                f"{self.config.ensemble_size} models"
            )

        return results

    def predict(
        self,
        X: np.ndarray,
        targets: list[str] | None = None,
    ) -> MultiTargetResult:
        """Predict all (or selected) targets with a single shared input matrix.

        The single matrix is keyed under ``"default"`` *and* under each target's
        resolved feature set, so feature-set-specific routing (e.g. ``v7``,
        whose fallback is strictly ``["v7"]`` to avoid composition contamination)
        still finds the input. The per-target dimension guard in ``predict_multi``
        rejects any width mismatch, so this never feeds wrong-width data to a
        model — it only restores the missing key for single-matrix callers
        (``predict_batch``, parity/residual visualization, champion comparison).
        """
        inputs_by_feature_set = {"default": X}
        for target_name in targets or self.fitted_targets:
            feature_set = self.config.get_feature_set_for_target(target_name)
            if feature_set:
                inputs_by_feature_set.setdefault(feature_set, X)
        return self.predict_multi(inputs_by_feature_set, targets=targets)

    def predict_multi(
        self,
        inputs_by_feature_set: dict[str, np.ndarray],
        targets: list[str] | None = None,
    ) -> MultiTargetResult:
        """Predict targets using feature-set-keyed input matrices."""
        target_list = targets or self.fitted_targets
        result = MultiTargetResult()
        result.ood_results = {}

        for target_name in target_list:
            ensemble = self._ensembles.get(target_name)
            if ensemble is None or not ensemble.is_fitted:
                _logger.warning(f"No fitted ensemble for '{target_name}'")
                continue

            requested_feature_set, actual_feature_set, X_target = self._select_input_for_target(
                inputs_by_feature_set,
                target_name,
            )
            if X_target is None:
                _logger.warning(
                    "Skipping %s: no feature input for contract %s",
                    target_name,
                    requested_feature_set,
                )
                continue

            n_trained = self._get_ensemble_n_features(ensemble)
            if n_trained is not None and X_target.shape[1] != n_trained:
                # Trailing-context truncation is only valid within the
                # composition lineage (v1-v6 share a growing prefix). v7 is a
                # distinct RDKit feature space, so any width mismatch means
                # wrong-feature-set data — reject instead of silently slicing.
                if X_target.shape[1] > n_trained and requested_feature_set != "v7":
                    X_target = X_target[:, :n_trained]
                else:
                    _logger.warning(
                        "Skipping %s: input has %d features but model expects %d",
                        target_name,
                        X_target.shape[1],
                        n_trained,
                    )
                    continue

            pred_value, pred_std = self._predict_single_target(ensemble, X_target, target_name)
            result.predictions[target_name] = pred_value
            result.uncertainties[target_name] = pred_std

            estimator = self._uncertainty_estimators.get(target_name)
            if estimator is not None:
                unc_result = estimator.estimate(pred_value, pred_std)
                result.confidence_intervals[target_name] = (
                    unc_result.ci_lower,
                    unc_result.ci_upper,
                )
            else:
                result.confidence_intervals[target_name] = (
                    pred_value - 2.0 * pred_std,
                    pred_value + 2.0 * pred_std,
                )

            detector = self._get_ood_detector_for_feature_set(actual_feature_set)
            if detector is not None:
                try:
                    result.ood_results[target_name] = detector.detect(X_target)[0]
                except Exception as e:
                    _logger.warning(
                        "OOD detection failed for %s (%s): %s",
                        target_name,
                        actual_feature_set,
                        e,
                    )

        if result.ood_results == {}:
            result.ood_results = None
        return result

    @staticmethod
    def _get_ensemble_n_features(ensemble: EnsemblePredictor) -> int | None:
        """Get the number of features an ensemble was trained on.

        Returns:
            Number of features, or None if indeterminate.
        """
        if not ensemble.predictors:
            return None
        first = ensemble.predictors[0]
        # 1) Check feature_names from config (saved/loaded)
        if first.config.feature_names:
            return len(first.config.feature_names)
        # 2) Check sklearn-style n_features_in_ on the underlying model
        model = getattr(first, "_model", None)
        if model is not None and hasattr(model, "n_features_in_"):
            return int(model.n_features_in_)
        return None

    def _predict_single_target(
        self,
        ensemble: EnsemblePredictor,
        X: np.ndarray,
        target_name: str,
    ) -> tuple[float, float]:
        """Predict a single target, returning (mean, std) in original scale.

        For transformed targets, each ensemble member's prediction is
        inverse-transformed before computing mean and std, so that both
        the point estimate and uncertainty are in the original scale.
        """
        transform_params = self._target_transforms.get(target_name)
        needs_inverse = bool(transform_params and transform_params.get("type") != "identity")

        if needs_inverse:
            from .target_transform import TargetTransformer

            tf = TargetTransformer()
            # Collect per-member predictions and inverse-transform each
            member_preds = np.array(
                [p.predict(X) for p in ensemble.predictors]
            )  # shape: (n_members, n_samples)
            # Inverse-transform each member's predictions
            member_preds_orig = np.array(
                [tf.inverse_transform(target_name, mp, transform_params) for mp in member_preds]
            )
            pred_value = float(np.mean(member_preds_orig[:, 0]))
            pred_std = float(np.std(member_preds_orig[:, 0]))
        else:
            mean, std = ensemble.predict(X, return_std=True)
            pred_value = float(mean[0])
            pred_std = float(std[0])

        return pred_value, pred_std

    @staticmethod
    def _normalize_input_matrix(X: np.ndarray) -> np.ndarray:
        """Ensure inputs are 2D matrices."""
        if X.ndim == 1:
            return X.reshape(1, -1)
        return X

    def _select_input_for_target(
        self,
        inputs_by_feature_set: dict[str, np.ndarray],
        target_name: str,
    ) -> tuple[str | None, str | None, np.ndarray | None]:
        """Select the best available feature matrix for a target contract."""
        feature_set = self.config.get_feature_set_for_target(target_name)
        fallback_order: dict[str, list[str]] = {
            # v7 = bulk structural (RDKit) — distinct branch, no cross-fallback
            # into composition feature sets (different dimension/philosophy).
            "v7": ["v7"],
            "v6": ["v6", "v4", "v5", "v3", "default"],
            "v5": ["v5", "v3", "v2", "default"],
            "v4": ["v4", "v3", "default"],
            "v3": ["v3", "v5", "v2", "default"],
            "v2": ["v2", "v3", "v5", "default"],
            "v1": ["v1", "v2", "v3", "v5", "default"],
        }
        for candidate in fallback_order.get(feature_set, [feature_set, "default"]):
            if candidate in inputs_by_feature_set:
                return (
                    feature_set,
                    candidate,
                    self._normalize_input_matrix(inputs_by_feature_set[candidate]),
                )
        return feature_set, None, None

    def _get_ood_detector_for_feature_set(self, feature_set: str | None) -> Any:
        """Resolve feature-set-specific OOD detector with legacy fallback."""
        if feature_set and feature_set in self._ood_detectors:
            return self._ood_detectors[feature_set]
        return self._ood_detector

    def predict_dual(
        self,
        X_v3: np.ndarray,
        X_v4: np.ndarray | None = None,
        targets: list[str] | None = None,
    ) -> MultiTargetResult:
        """Compatibility wrapper for V3/V4 dispatch."""
        inputs_by_feature_set = {"default": X_v3, "v3": X_v3}
        if X_v4 is not None:
            inputs_by_feature_set["v4"] = X_v4
        return self.predict_multi(inputs_by_feature_set, targets=targets)

    def predict_batch(
        self,
        X: np.ndarray,
        targets: list[str] | None = None,
    ) -> list[MultiTargetResult]:
        """Predict for multiple samples.

        Args:
            X: Feature matrix (n_samples x n_features).
            targets: Subset of targets to predict.

        Returns:
            List of MultiTargetResult, one per sample.
        """
        if X.ndim == 1:
            X = X.reshape(1, -1)

        results = []
        for i in range(X.shape[0]):
            results.append(self.predict(X[i : i + 1], targets=targets))
        return results

    def predict_multi_batch(
        self,
        inputs_by_feature_set: dict[str, np.ndarray],
        targets: list[str] | None = None,
    ) -> list[MultiTargetResult]:
        """Batch prediction for multiple feature-set-keyed matrices."""
        normalized = {
            key: self._normalize_input_matrix(value) for key, value in inputs_by_feature_set.items()
        }
        n_rows = next(iter(normalized.values())).shape[0]
        return [
            self.predict_multi(
                {key: value[i : i + 1] for key, value in normalized.items()},
                targets=targets,
            )
            for i in range(n_rows)
        ]

    def set_uncertainty_estimator(self, target_name: str, estimator: Any) -> None:
        """Register an UncertaintyEstimator for a target.

        Args:
            target_name: Target variable name.
            estimator: UncertaintyEstimator instance.
        """
        self._uncertainty_estimators[target_name] = estimator

    def set_ood_detector(self, detector: Any, feature_set_version: str | None = None) -> None:
        """Register an OODDetector, optionally bound to a feature contract."""
        self._ood_detector = detector
        if feature_set_version is not None:
            self._ood_detectors[feature_set_version] = detector

    def save(self, model_dir: Path | None = None) -> None:
        """Save all ensembles and metadata.

        Args:
            model_dir: Override model directory.
        """
        dirpath = Path(model_dir or self.model_dir or "models/multi_target")
        dirpath.mkdir(parents=True, exist_ok=True)

        meta = {
            "targets": [t.value for t in self.config.targets],
            "ensemble_size": self.config.ensemble_size,
            "model_type": self.config.model_type.value,
            "fitted_targets": self.fitted_targets,
            "target_feature_sets": self.config.target_feature_sets,
        }
        if self._requested_feature_set is not None:
            meta["requested_feature_set"] = self._requested_feature_set
        if self._actual_feature_set is not None:
            meta["actual_feature_set"] = self._actual_feature_set
        if self._feature_schema_hash is not None:
            meta["feature_schema_hash"] = self._feature_schema_hash
        if self._per_target_feature_schema_hashes:
            meta["per_target_feature_schema_hashes"] = self._per_target_feature_schema_hashes
        if self._capability_manifest is not None:
            meta["capability_manifest"] = self._capability_manifest
        if self._ood_detectors:
            meta["ood_detector_feature_sets"] = sorted(self._ood_detectors)

        # Persist per-target feature masks
        if self._feature_masks:
            meta["feature_masks"] = {t: m.tolist() for t, m in self._feature_masks.items()}

        # Persist per-target transform params
        if self._target_transforms:
            meta["target_transforms"] = self._target_transforms

        for target_name, ensemble in self._ensembles.items():
            if ensemble.is_fitted:
                ensemble.save(dirpath / target_name)

        # Save OOD detector(s) if fitted
        if self._ood_detector is not None and hasattr(self._ood_detector, "save"):
            self._ood_detector.save(dirpath / "ood_detector.json")
            meta["has_ood_detector"] = True
        if self._ood_detectors:
            ood_dir = dirpath / "ood_detectors"
            ood_dir.mkdir(parents=True, exist_ok=True)
            for feature_set_version, detector in self._ood_detectors.items():
                if hasattr(detector, "save"):
                    detector.save(ood_dir / f"{feature_set_version}.json")

        (dirpath / "multi_target_meta.json").write_text(json.dumps(meta, indent=2))
        _logger.info(f"Saved MultiTargetPredictor to {dirpath}")

    @classmethod
    def load(cls, model_dir: Path) -> MultiTargetPredictor:
        """Load from directory.

        Args:
            model_dir: Directory containing saved model.

        Returns:
            Loaded MultiTargetPredictor.
        """
        dirpath = Path(model_dir)
        meta = json.loads((dirpath / "multi_target_meta.json").read_text())

        targets = [TargetVariable(t) for t in meta["targets"]]
        config = MultiTargetConfig(
            targets=targets,
            ensemble_size=meta["ensemble_size"],
            model_type=ModelType(meta["model_type"]),
            target_feature_sets=meta.get("target_feature_sets", {}),
        )

        predictor = cls(config=config, model_dir=dirpath)
        predictor._requested_feature_set = meta.get("requested_feature_set")
        predictor._actual_feature_set = meta.get("actual_feature_set")
        predictor._feature_schema_hash = meta.get("feature_schema_hash")
        predictor._per_target_feature_schema_hashes = meta.get(
            "per_target_feature_schema_hashes", {}
        )
        predictor._capability_manifest = meta.get("capability_manifest")

        for target_name in meta.get("fitted_targets", []):
            target_dir = dirpath / target_name
            if target_dir.exists():
                predictor._ensembles[target_name] = EnsemblePredictor.load(target_dir)

        # Load OOD detector if present
        if meta.get("has_ood_detector"):
            ood_path = dirpath / "ood_detector.json"
            if ood_path.exists():
                from .ood_detector import OODDetector

                predictor._ood_detector = OODDetector.load(ood_path)
        ood_feature_sets = meta.get("ood_detector_feature_sets", [])
        if ood_feature_sets:
            from .ood_detector import OODDetector

            for feature_set_version in ood_feature_sets:
                ood_path = dirpath / "ood_detectors" / f"{feature_set_version}.json"
                if ood_path.exists():
                    predictor._ood_detectors[feature_set_version] = OODDetector.load(ood_path)

        # Load per-target feature masks
        feature_masks = meta.get("feature_masks")
        if feature_masks:
            predictor._feature_masks = {t: np.array(m, dtype=int) for t, m in feature_masks.items()}

        # Load per-target transform params
        target_transforms = meta.get("target_transforms")
        if target_transforms:
            predictor._target_transforms = target_transforms

        return predictor
