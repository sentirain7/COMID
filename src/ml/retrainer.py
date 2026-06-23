"""Model retraining orchestrator for continuous learning."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from common.hashing import compute_content_hash
from contracts.errors import ErrorCode, MLOpsError
from contracts.policies.ml_policy import DEFAULT_ML_POLICY, FeatureSetVersion
from ml.data_loader import DataSplitter, TargetVariable, TrainingDataset
from ml.feature_selector import PerTargetFeatureSelector
from ml.model_registry import ComparisonResult, ModelRegistry
from ml.multi_target import MultiTargetConfig, MultiTargetPredictor
from ml.ood_detector import OODDetector
from ml.recommendation_evaluator import RecommendationEvalInput, RecommendationEvaluator
from ml.target_transform import TargetTransformer
from ml.uncertainty import UncertaintyEstimator


@dataclass
class RetrainingResult:
    """Result of retraining run."""

    success: bool
    version_id: str | None
    trigger_reason: str
    training_samples: int
    comparison_result: ComparisonResult | None
    promoted: bool
    duration_seconds: float


def should_retrain(
    *,
    current_samples: int,
    new_samples: int,
    drift_should_retrain: bool,
    force: bool,
) -> tuple[bool, str]:
    """Evaluate retraining trigger from policy and runtime signals."""
    policy = DEFAULT_ML_POLICY.retraining
    if force:
        return True, "force"
    if current_samples < DEFAULT_ML_POLICY.min_training_samples:
        return False, "insufficient_total_samples"
    if new_samples >= policy.min_new_samples:
        return True, "new_samples_threshold"
    if drift_should_retrain:
        return True, "drift_detected"
    return False, "no_trigger"


class ModelRetrainer:
    """Retraining pipeline for multi-target predictor.

    PR 2 (Method 1a SSOT): when training the CED target, the optional
    ``e_intra_method`` constructor argument forwards through to the dataset
    router so the (metric_name, e_intra_method) pair acts as the SSOT label
    contract.  ``None`` defaults to Method 1
    (``single_molecule_vacuum``) for back-compat.
    """

    def __init__(
        self,
        db_session: Any,
        model_registry: ModelRegistry,
        *,
        e_intra_method: str | None = None,
    ):
        self._session = db_session
        self._registry = model_registry
        self._policy = DEFAULT_ML_POLICY
        self._e_intra_method = e_intra_method

    def _select_targets(self) -> list[TargetVariable]:
        return TargetVariable.trainable()

    @staticmethod
    def _has_complete_promotion_metadata(predictor: MultiTargetPredictor) -> bool:
        """Require lineage/capability metadata before champion promotion."""
        return bool(
            getattr(predictor, "_requested_feature_set", None)
            and getattr(predictor, "_actual_feature_set", None)
            and getattr(predictor, "_feature_schema_hash", None)
            and getattr(predictor, "_capability_manifest", None)
        )

    @staticmethod
    def _overlapping_targets_not_degraded(
        challenger_rmse_by_target: dict[str, float],
        champion_rmse_by_target: dict[str, float],
    ) -> bool:
        """Require no RMSE regression on overlapping targets considered for promotion."""
        if not champion_rmse_by_target:
            return False
        return all(
            challenger_rmse_by_target.get(target_name, float("inf"))
            <= champion_rmse_by_target[target_name]
            for target_name in champion_rmse_by_target
        )

    def _load_datasets(self, feature_set: FeatureSetVersion) -> dict[str, TrainingDataset]:
        from ml.dataset_router import load_training_dataset

        datasets: dict[str, TrainingDataset] = {}
        for target in self._select_targets():
            ds = load_training_dataset(
                self._session,
                target=target,
                min_samples=2,
                requested_feature_set=feature_set,
                e_intra_method=self._e_intra_method,
            )
            if ds is not None and ds.n_samples >= 2:
                datasets[target.value] = ds
        return datasets

    def _subset_dataset(
        self,
        dataset: TrainingDataset,
        allowed_exp_ids: set[str],
    ) -> TrainingDataset:
        idx = [i for i, eid in enumerate(dataset.exp_ids) if eid in allowed_exp_ids]
        if not idx:
            return TrainingDataset(
                X=np.zeros((0, dataset.X.shape[1])),
                y=np.zeros((0,)),
                exp_ids=[],
                feature_names=dataset.feature_names,
                target_name=dataset.target_name,
            )
        arr_idx = np.array(idx, dtype=int)
        return TrainingDataset(
            X=dataset.X[arr_idx],
            y=dataset.y[arr_idx],
            exp_ids=[dataset.exp_ids[i] for i in arr_idx],
            feature_names=dataset.feature_names,
            target_name=dataset.target_name,
        )

    def _split_with_holdout_rotation(
        self,
        dataset: TrainingDataset,
        cycle: int,
    ) -> tuple[set[str], set[str], set[str]]:
        cl = self._policy.continuous_learning
        seed = cl.deterministic_seed_base + (cycle // max(1, cl.holdout_rotation_interval))
        test_ratio = cl.holdout_fraction
        val_ratio = min(0.15, max(0.05, cl.holdout_fraction / 2.0))
        train_ratio = max(0.6, 1.0 - test_ratio - val_ratio)
        total = train_ratio + val_ratio + test_ratio
        train_ratio /= total
        val_ratio /= total
        test_ratio /= total

        splitter = DataSplitter(
            train_ratio=train_ratio,
            val_ratio=val_ratio,
            test_ratio=test_ratio,
            random_seed=seed,
        )

        # Group-aware split: prevent additive leakage across splits
        groups = self._extract_groups(dataset)
        split = splitter.split(dataset, groups=groups)
        return set(split.train.exp_ids), set(split.val.exp_ids), set(split.test.exp_ids)

    def _extract_groups(self, dataset: TrainingDataset) -> np.ndarray | None:
        """Extract group labels from exp_ids for group-aware splitting.

        Groups are based on additive_mol_id to prevent data leakage.
        Experiments without additives are grouped under "__control__".

        Returns:
            Group label array, or None if DB lookup fails.
        """
        try:
            from database.models import ExperimentModel

            exp_id_set = set(dataset.exp_ids)
            rows = (
                self._session.query(
                    ExperimentModel.exp_id,
                    ExperimentModel.additive_mol_id,
                )
                .filter(ExperimentModel.exp_id.in_(exp_id_set))
                .all()
            )
            if not rows:
                return None
            lookup = {r.exp_id: r.additive_mol_id or "__control__" for r in rows}
            groups = np.array(
                [lookup.get(eid, "__control__") for eid in dataset.exp_ids],
                dtype=object,
            )
            # Fall back to random split if only one group exists
            if len(set(groups)) <= 1:
                return None
            return groups
        except Exception:
            return None

    def _rmse(self, y_true: np.ndarray, y_pred: np.ndarray) -> float:
        if len(y_true) == 0:
            return 0.0
        return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))

    def run(
        self,
        *,
        force: bool = False,
        triggered_by: str = "scheduled",
        drift_report: Any = None,
        cycle: int = 0,
        new_samples: int = 0,
        training_snapshot_extra: dict[str, Any] | None = None,
        auto_select: bool = False,
    ) -> RetrainingResult:
        start = time.time()

        # Attempt highest available bulk feature set, with fallback chain: V5 -> V3 -> V2 -> V1
        feature_set = FeatureSetVersion.V5
        datasets = self._load_datasets(feature_set)
        if not datasets:
            feature_set = FeatureSetVersion.V3
            datasets = self._load_datasets(feature_set)
        if not datasets:
            feature_set = FeatureSetVersion.V2
            datasets = self._load_datasets(feature_set)
        if not datasets:
            feature_set = self._policy.default_feature_set
            datasets = self._load_datasets(feature_set)
        if not datasets:
            raise MLOpsError(
                ErrorCode.INSUFFICIENT_TRAINING_DATA,
                "No trainable datasets found for retraining",
            )

        per_target_actual_feature_sets = {
            name: str(ds.metadata.get("actual_feature_set", feature_set.value))
            for name, ds in datasets.items()
        }
        per_target_feature_schema_hashes = {
            name: str(
                ds.metadata.get("feature_schema_hash", compute_content_hash(ds.feature_names))
            )
            for name, ds in datasets.items()
        }
        distinct_actual_feature_sets = sorted(set(per_target_actual_feature_sets.values()))
        actual_feature_set = (
            distinct_actual_feature_sets[0] if len(distinct_actual_feature_sets) == 1 else "mixed"
        )

        base_dataset = next(iter(datasets.values()))
        total_samples = base_dataset.n_samples
        trigger_ok, reason = should_retrain(
            current_samples=total_samples,
            new_samples=new_samples,
            drift_should_retrain=bool(getattr(drift_report, "should_retrain", False)),
            force=force,
        )
        if not trigger_ok:
            return RetrainingResult(
                success=True,
                version_id=None,
                trigger_reason=reason,
                training_samples=total_samples,
                comparison_result=None,
                promoted=False,
                duration_seconds=time.time() - start,
            )

        train_ids, val_ids, test_ids = self._split_with_holdout_rotation(base_dataset, cycle)

        train_sets: dict[str, TrainingDataset] = {}
        val_sets: dict[str, TrainingDataset] = {}
        test_sets: dict[str, TrainingDataset] = {}
        for name, ds in datasets.items():
            train_sets[name] = self._subset_dataset(ds, train_ids)
            val_sets[name] = self._subset_dataset(ds, val_ids)
            test_sets[name] = self._subset_dataset(ds, test_ids)

        trainable_targets = [
            TargetVariable(tname)
            for tname, ds in train_sets.items()
            if ds.n_samples >= 2 and tname in {t.value for t in TargetVariable.trainable()}
        ]
        if not trainable_targets:
            raise MLOpsError(
                ErrorCode.INSUFFICIENT_TRAINING_DATA,
                "Not enough train samples after holdout split",
            )

        # Apply target transforms (log for viscosity, MSD, etc.)
        # Keep original y for evaluation (predict_batch returns original scale)
        transformer = TargetTransformer()
        transform_params: dict[str, dict] = {}
        original_y: dict[str, dict[str, np.ndarray]] = {}  # {tname: {split: y_orig}}
        for tname, ds in train_sets.items():
            if ds.n_samples < 2:
                continue
            ttype = transformer.get_transform_type(tname)
            if ttype != "identity":
                original_y[tname] = {
                    "train": ds.y.copy(),
                    "val": val_sets[tname].y.copy()
                    if tname in val_sets and val_sets[tname].n_samples > 0
                    else np.array([]),
                    "test": test_sets[tname].y.copy()
                    if tname in test_sets and test_sets[tname].n_samples > 0
                    else np.array([]),
                }
                y_t, params = transformer.fit_transform(tname, ds.y)
                transform_params[tname] = params
                train_sets[tname] = TrainingDataset(
                    X=ds.X,
                    y=y_t,
                    exp_ids=ds.exp_ids,
                    feature_names=ds.feature_names,
                    target_name=ds.target_name,
                    metadata=ds.metadata,
                )
                # Also transform val/test sets
                if tname in val_sets and val_sets[tname].n_samples > 0:
                    ds_v = val_sets[tname]
                    val_sets[tname] = TrainingDataset(
                        X=ds_v.X,
                        y=transformer.transform(tname, ds_v.y, params),
                        exp_ids=ds_v.exp_ids,
                        feature_names=ds_v.feature_names,
                        target_name=ds_v.target_name,
                        metadata=ds_v.metadata,
                    )
                if tname in test_sets and test_sets[tname].n_samples > 0:
                    ds_t = test_sets[tname]
                    test_sets[tname] = TrainingDataset(
                        X=ds_t.X,
                        y=transformer.transform(tname, ds_t.y, params),
                        exp_ids=ds_t.exp_ids,
                        feature_names=ds_t.feature_names,
                        target_name=ds_t.target_name,
                        metadata=ds_t.metadata,
                    )

        # Determine best model type per target if auto_select is enabled
        target_configs: dict[str, Any] = {}
        min_auto_select_samples = 200
        max_auto_select_seconds = 300.0
        if auto_select and total_samples >= min_auto_select_samples:
            from ml.models import ModelType as MT

            candidates: list[tuple[str, MT]] = []
            try:
                import xgboost  # noqa: F401

                candidates.append(("xgboost", MT.XGBOOST))
            except ImportError:
                pass
            try:
                import lightgbm  # noqa: F401

                candidates.append(("lightgbm", MT.LIGHTGBM))
            except ImportError:
                pass
            candidates.append(("random_forest", MT.RANDOM_FOREST))

            if len(candidates) > 1:
                import time as _time

                auto_start = _time.time()
                for tname in [t.value for t in trainable_targets]:
                    ds_tr = train_sets.get(tname)
                    ds_vl = val_sets.get(tname)
                    if ds_tr is None or ds_vl is None or ds_tr.n_samples < 2 or ds_vl.n_samples < 1:
                        continue
                    if _time.time() - auto_start > max_auto_select_seconds:
                        break
                    best_rmse = float("inf")
                    best_mt = candidates[0][1]
                    for _name, mt in candidates:
                        try:
                            from ml.models import ModelConfig as MC
                            from ml.models import PropertyPredictor as PP

                            cfg = MC(
                                model_type=mt, target_name=tname, feature_names=ds_tr.feature_names
                            )
                            model = PP(cfg)
                            model.fit(ds_tr.X, ds_tr.y)
                            preds = model.predict(ds_vl.X)
                            rmse = float(np.sqrt(np.mean((ds_vl.y - preds) ** 2)))
                            if rmse < best_rmse:
                                best_rmse = rmse
                                best_mt = mt
                        except Exception:
                            continue
                    if best_mt != candidates[0][1]:
                        from ml.models import ModelConfig as MC

                        target_configs[tname] = MC(model_type=best_mt, target_name=tname)

        predictor = MultiTargetPredictor(
            config=MultiTargetConfig(
                targets=trainable_targets,
                target_configs=target_configs,
                target_feature_sets={
                    target_name: per_target_actual_feature_sets[target_name]
                    for target_name in train_sets.keys()
                    if target_name in per_target_actual_feature_sets
                },
            ),
        )
        predictor.train({k: v for k, v in train_sets.items() if v.n_samples >= 2})
        predictor._requested_feature_set = feature_set.value
        predictor._actual_feature_set = actual_feature_set
        predictor._per_target_feature_schema_hashes = dict(per_target_feature_schema_hashes)
        predictor._feature_schema_hash = compute_content_hash(
            {
                name: per_target_feature_schema_hashes[name]
                for name in sorted(per_target_feature_schema_hashes)
            }
        )
        temperature_ranges = [
            ds.metadata.get("temperature_range_k")
            for ds in train_sets.values()
            if ds.metadata.get("temperature_range_k")
        ]
        supported_temperatures = None
        if temperature_ranges:
            supported_temperatures = [
                min(float(r[0]) for r in temperature_ranges),
                max(float(r[1]) for r in temperature_ranges),
            ]
        supported_layer_counts = sorted(
            {
                int(layer_count)
                for ds in train_sets.values()
                for layer_count in (ds.metadata.get("supported_layer_counts") or [])
            }
        )
        supported_binder_types = sorted(
            {
                str(binder_type)
                for ds in train_sets.values()
                for binder_type in (ds.metadata.get("binder_types") or [])
            }
        )
        supported_aging_states = sorted(
            {
                str(aging_state)
                for ds in train_sets.values()
                for aging_state in (ds.metadata.get("aging_states") or [])
            }
        )
        supported_additives = sorted(
            {
                str(additive_type)
                for ds in train_sets.values()
                for additive_type in (ds.metadata.get("additive_types") or [])
            }
        )
        predictor._capability_manifest = {
            "supported_targets": list(predictor.fitted_targets),
            "per_target_feature_set": {
                name: predictor.config.target_feature_sets.get(name)
                for name in sorted(predictor.fitted_targets)
            },
            "supported_temperature_range_k": supported_temperatures,
            "supported_layer_counts": supported_layer_counts,
            "supported_binder_types": supported_binder_types,
            "supported_aging_states": supported_aging_states,
            "supported_additives": supported_additives,
            "uncertainty_enabled": False,
            "ood_enabled": False,
            "ood_artifacts_by_feature_set": {},
            "extrapolation_policy": {
                "in_domain": "allowed",
                "combinatorial_generalization": "warn",
                "hard_extrapolation": "blocked_by_default",
            },
            # FF governance metadata — from actual training datasets
            "ff_stack_ids": sorted(
                {
                    sid
                    for ds in train_sets.values()
                    if hasattr(ds, "metadata")
                    for sid in ds.metadata.get("stack_ids", ["unknown"])
                }
            )
            if train_sets
            else [],
            "ff_validation_levels": sorted(
                {
                    vl
                    for ds in train_sets.values()
                    if hasattr(ds, "metadata")
                    for vl in ds.metadata.get("validation_levels", ["research_only"])
                }
            )
            if train_sets
            else [],
            "dataset_ff_type": next(iter(train_sets.values())).metadata.get(
                "ff_type", "bulk_ff_gaff2"
            )
            if train_sets
            else "unknown",
            "ff_provenance_completeness": min(
                (
                    ds.metadata.get("ff_provenance_completeness", 0.0)
                    for ds in train_sets.values()
                    if hasattr(ds, "metadata")
                ),
                default=0.0,
            ),
        }

        # Store transform params in predictor for prediction-time inverse transform
        predictor._target_transforms = transform_params

        # Per-target feature selection based on ensemble importances
        selector = PerTargetFeatureSelector()
        for tname in predictor.fitted_targets:
            ensemble = predictor._ensembles.get(tname)
            if ensemble is None:
                continue
            # Average importance across ensemble members
            all_fi: list[dict[str, float]] = []
            for member in ensemble.predictors:
                fi = member.get_feature_importances()
                if fi:
                    all_fi.append(fi)
            if not all_fi:
                continue
            # Merge importances
            merged: dict[str, float] = {}
            for fi in all_fi:
                for k, v in fi.items():
                    merged[k] = merged.get(k, 0.0) + v / len(all_fi)
            ds_t = train_sets.get(tname)
            if ds_t is not None:
                selector.select(tname, merged, ds_t.feature_names)
        if selector.masks:
            predictor._feature_masks = selector.masks

        # Fit one OOD detector per actual feature contract.
        rep_train_by_feature_set: dict[str, TrainingDataset] = {}
        for ds in train_sets.values():
            if ds.n_samples < 2:
                continue
            actual_fsv = str(ds.metadata.get("actual_feature_set", feature_set.value))
            rep_train_by_feature_set.setdefault(actual_fsv, ds)
        for actual_fsv, rep_train in rep_train_by_feature_set.items():
            ood = OODDetector()
            ood.fit(rep_train.X)
            ood.metadata = {
                "feature_set_version": actual_fsv,
                "feature_schema_hash": str(
                    rep_train.metadata.get(
                        "feature_schema_hash", compute_content_hash(rep_train.feature_names)
                    )
                ),
                "target_scope": "multi_target",
                "stack_ids": rep_train.metadata.get("stack_ids", ["unknown"]),
                "dominant_stack_id": rep_train.metadata.get("dominant_stack_id", "unknown"),
            }
            predictor.set_ood_detector(ood, feature_set_version=actual_fsv)
            predictor._capability_manifest["ood_artifacts_by_feature_set"][actual_fsv] = {
                "feature_schema_hash": ood.metadata["feature_schema_hash"]
            }
        predictor._capability_manifest["ood_enabled"] = bool(rep_train_by_feature_set)

        train_metrics: dict[str, dict[str, float]] = {}
        val_metrics: dict[str, dict[str, float]] = {}
        test_metrics: dict[str, dict[str, float]] = {}
        ece_values: list[float] = []
        coverage_values: list[float] = []
        sharpness_values: list[float] = []
        recommender = RecommendationEvaluator()

        for tname in predictor.fitted_targets:
            estimator = UncertaintyEstimator()
            ds_train = train_sets[tname]
            ds_val = val_sets[tname]
            ds_test = test_sets[tname]

            # Resolve original-scale y for each split.
            # predict_batch returns original-scale predictions (inverse-transformed),
            # so all evaluation must use original-scale y_true consistently.
            def _get_original_y(target: str, split: str, ds: TrainingDataset) -> np.ndarray:
                if target in original_y:
                    y_orig = original_y[target].get(split)
                    if y_orig is not None and len(y_orig) == ds.n_samples:
                        return y_orig
                return ds.y

            val_y_orig = _get_original_y(tname, "val", ds_val)

            # Calibration uses validation split when sufficiently large.
            if ds_val.n_samples >= self._policy.calibration_min_samples:
                pred_val = predictor.predict_batch(ds_val.X, targets=[tname])
                means = [p.predictions.get(tname, 0.0) for p in pred_val]
                stds = [p.uncertainties.get(tname, 1e-6) for p in pred_val]
                # Use original-scale y for calibration (means are original-scale)
                estimator.calibrate(means, stds, val_y_orig.tolist())
                ece_values.append(
                    self._registry.compute_ece(
                        means,
                        stds,
                        val_y_orig.tolist(),
                        n_bins=self._policy.calibration.ece_n_bins,
                    )
                )
                coverage_values.append(estimator.compute_coverage(means, stds, val_y_orig.tolist()))
                sharpness_values.append(estimator.compute_sharpness(stds))

            predictor.set_uncertainty_estimator(tname, estimator)
            predictor._capability_manifest["uncertainty_enabled"] = True

            for _split_name, split_ds, store in (
                ("train", ds_train, train_metrics),
                ("val", ds_val, val_metrics),
                ("test", ds_test, test_metrics),
            ):
                if split_ds.n_samples == 0:
                    store[tname] = {"rmse": 0.0}
                    continue
                preds = predictor.predict_batch(split_ds.X, targets=[tname])
                yhat = np.array([p.predictions.get(tname, 0.0) for p in preds], dtype=float)
                # Use original-scale y for RMSE (predictions are already original-scale)
                y_true = _get_original_y(tname, _split_name, split_ds)
                store[tname] = {"rmse": self._rmse(y_true, yhat)}

        champion = self._registry.get_champion_predictor()
        comparison = None
        promoted = False
        challenger_recommendation_metrics: dict[str, float] | None = None
        champion_recommendation_metrics: dict[str, float] | None = None

        comparable_targets = [
            t
            for t in predictor.fitted_targets
            if t in test_sets
            and test_sets[t].n_samples >= self._policy.model_comparison.min_comparison_samples
        ]

        if comparable_targets:
            challenger_eval_inputs: dict[str, RecommendationEvalInput] = {}
            champion_eval_inputs: dict[str, RecommendationEvalInput] = {}

            for tname in comparable_targets:
                ds_t = test_sets[tname]
                # Use original-scale y_true for recommendation evaluation
                test_y_orig = _get_original_y(tname, "test", ds_t)
                pred_new = predictor.predict_batch(ds_t.X, targets=[tname])
                yhat_new = np.array([p.predictions.get(tname, 0.0) for p in pred_new], dtype=float)
                std_new = np.array([p.uncertainties.get(tname, 0.0) for p in pred_new], dtype=float)
                ood_new = np.array(
                    [
                        bool(
                            p.ood_results
                            and p.ood_results.get(tname) is not None
                            and getattr(p.ood_results.get(tname), "is_ood", False)
                        )
                        for p in pred_new
                    ],
                    dtype=bool,
                )
                challenger_eval_inputs[tname] = RecommendationEvalInput(
                    y_true=test_y_orig,
                    y_pred=yhat_new,
                    uncertainties=std_new,
                    ood_flags=ood_new,
                )

                if champion is not None and tname in champion.fitted_targets:
                    pred_old = champion.predict_batch(ds_t.X, targets=[tname])
                    yhat_old = np.array(
                        [p.predictions.get(tname, 0.0) for p in pred_old],
                        dtype=float,
                    )
                    std_old = np.array(
                        [p.uncertainties.get(tname, 0.0) for p in pred_old],
                        dtype=float,
                    )
                    ood_old = np.array(
                        [
                            bool(
                                p.ood_results
                                and p.ood_results.get(tname) is not None
                                and getattr(p.ood_results.get(tname), "is_ood", False)
                            )
                            for p in pred_old
                        ],
                        dtype=bool,
                    )
                    champion_eval_inputs[tname] = RecommendationEvalInput(
                        y_true=test_y_orig,
                        y_pred=yhat_old,
                        uncertainties=std_old,
                        ood_flags=ood_old,
                    )

            challenger_recommendation_metrics = recommender.evaluate(challenger_eval_inputs)
            if champion_eval_inputs:
                champion_recommendation_metrics = recommender.evaluate(champion_eval_inputs)

        if challenger_recommendation_metrics is not None:
            test_metrics["__recommendation__"] = challenger_recommendation_metrics

        # PR 2 (Codex Round 4): record E_intra method tag in both the
        # snapshot (artefact) and the registry row (training_config_json)
        # so visualisation/promotion can read it from lineage.  Default to
        # Method 1 baseline when unset.
        e_intra_method_tag = self._e_intra_method or "single_molecule_vacuum"

        training_snapshot = {
            "train_exp_ids": sorted(train_ids),
            "val_exp_ids": sorted(val_ids),
            "test_exp_ids": sorted(test_ids),
            "targets": predictor.fitted_targets,
            "requested_feature_set": feature_set.value,
            "actual_feature_set": actual_feature_set,
            "per_target_feature_sets": per_target_actual_feature_sets,
            "feature_schema_hash": predictor._feature_schema_hash,
            "e_intra_method": e_intra_method_tag,
        }
        if training_snapshot_extra:
            training_snapshot.update(training_snapshot_extra)

        reg_row = self._registry.register_model(
            predictor,
            feature_set_version=feature_set.value,
            actual_feature_set=actual_feature_set,
            per_target_feature_sets=per_target_actual_feature_sets,
            feature_schema_hash=predictor._feature_schema_hash,
            capability_manifest=predictor._capability_manifest,
            training_samples=total_samples,
            training_seed=self._policy.continuous_learning.deterministic_seed_base,
            train_metrics=train_metrics,
            val_metrics=val_metrics,
            test_metrics=test_metrics,
            calibration_ece=float(np.mean(ece_values)) if ece_values else None,
            calibration_coverage=float(np.mean(coverage_values)) if coverage_values else None,
            calibration_sharpness=float(np.mean(sharpness_values)) if sharpness_values else None,
            triggered_by=triggered_by,
            parent_version_id=None,
            training_snapshot=training_snapshot,
            e_intra_method=e_intra_method_tag,
        )

        # Compare on all available targets using weighted RMSE.
        weights = self._policy.target_comparison_weights

        if champion is not None and comparable_targets:
            # Compute weighted average RMSE for challenger and champion
            challenger_weighted_rmse = 0.0
            champion_weighted_rmse = 0.0
            total_weight = 0.0
            challenger_rmse_by_target: dict[str, float] = {}
            champion_rmse_by_target: dict[str, float] = {}

            for tname in comparable_targets:
                w = weights.get_weight(tname)
                if w <= 0.0:
                    continue
                ds_t = test_sets[tname]
                cmp_y_orig = _get_original_y(tname, "test", ds_t)
                pred_new = predictor.predict_batch(ds_t.X, targets=[tname])
                pred_old = champion.predict_batch(ds_t.X, targets=[tname])
                yhat_new = np.array([p.predictions.get(tname, 0.0) for p in pred_new], dtype=float)
                yhat_old = np.array([p.predictions.get(tname, 0.0) for p in pred_old], dtype=float)
                challenger_rmse = self._rmse(cmp_y_orig, yhat_new)
                champion_rmse = self._rmse(cmp_y_orig, yhat_old)
                challenger_rmse_by_target[tname] = challenger_rmse
                champion_rmse_by_target[tname] = champion_rmse
                challenger_weighted_rmse += w * challenger_rmse
                champion_weighted_rmse += w * champion_rmse
                total_weight += w

            if total_weight > 0:
                challenger_weighted_rmse /= total_weight
                champion_weighted_rmse /= total_weight

            # Fall back to density-only statistical comparison for promotion decision
            if "density" in comparable_targets:
                ds_test = test_sets["density"]
                density_y_orig = _get_original_y("density", "test", ds_test)
                pred_ch = predictor.predict_batch(ds_test.X, targets=["density"])
                pred_cp = champion.predict_batch(ds_test.X, targets=["density"])
                yhat_ch = np.array(
                    [p.predictions.get("density", 0.0) for p in pred_ch], dtype=float
                )
                yhat_cp = np.array(
                    [p.predictions.get("density", 0.0) for p in pred_cp], dtype=float
                )
                comparison = self._registry.compare_with_champion(yhat_ch, yhat_cp, density_y_orig)
                # Only promote if both statistical test passes AND weighted RMSE improves
                promoted = (
                    comparison.promoted
                    and challenger_weighted_rmse <= champion_weighted_rmse
                    and self._has_complete_promotion_metadata(predictor)
                    and self._overlapping_targets_not_degraded(
                        challenger_rmse_by_target,
                        champion_rmse_by_target,
                    )
                    and recommender.not_degraded(
                        challenger_recommendation_metrics,
                        champion_recommendation_metrics,
                    )
                )
                if promoted:
                    self._registry.promote(reg_row.version_id)
            else:
                promoted = False
        elif champion is None:
            # First successful model becomes champion.
            self._registry.promote(reg_row.version_id)
            promoted = True
        else:
            promoted = False

        self._session.flush()

        return RetrainingResult(
            success=True,
            version_id=reg_row.version_id,
            trigger_reason=reason,
            training_samples=total_samples,
            comparison_result=comparison,
            promoted=promoted,
            duration_seconds=time.time() - start,
        )
