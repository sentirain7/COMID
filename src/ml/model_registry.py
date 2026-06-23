"""Model registry for champion/challenger lifecycle."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np

from common.hashing import compute_content_hash
from common.pathing import get_project_root
from contracts.errors import ErrorCode, MLOpsError
from contracts.policies.ml_policy import DEFAULT_ML_POLICY
from database.models import MLModelVersionModel
from database.repositories.model_version_repo import ModelVersionRepository
from ml.multi_target import MultiTargetPredictor


@dataclass
class ComparisonResult:
    """Champion/challenger comparison result."""

    test_type: str
    statistic: float
    p_value: float
    effect_size: float
    challenger_rmse: float
    champion_rmse: float
    improvement_pct: float
    promoted: bool
    reason: str


class ModelRegistry:
    """Persistent model registry backed by DB metadata + filesystem artifacts."""

    def __init__(self, session: Any):
        self._session = session
        self._repo = ModelVersionRepository(session)
        self._policy = DEFAULT_ML_POLICY
        self._base_dir = get_project_root() / "models" / "registry"
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def generate_version_id(self) -> str:
        stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        return f"mt_{stamp}_{uuid4().hex[:6]}"

    def _normal_cdf(self, z: float) -> float:
        return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))

    def _inv_normal_cdf(self, p: float) -> float:
        """Inverse normal CDF via Abramowitz & Stegun 26.2.23 rational approximation."""
        if p <= 0.0:
            return -6.0
        if p >= 1.0:
            return 6.0
        if abs(p - 0.5) < 1e-15:
            return 0.0

        if p < 0.5:
            sign = -1.0
            q = p
        else:
            sign = 1.0
            q = 1.0 - p

        t = math.sqrt(-2.0 * math.log(q))
        c0, c1, c2 = 2.515517, 0.802853, 0.010328
        d1, d2, d3 = 1.432788, 0.189269, 0.001308
        numerator = c0 + c1 * t + c2 * t * t
        denominator = 1.0 + d1 * t + d2 * t * t + d3 * t * t * t
        return sign * (t - numerator / denominator)

    def _paired_t_test(self, a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
        d = np.asarray(a) - np.asarray(b)
        n = len(d)
        if n < 2:
            return 0.0, 1.0
        mean_d = float(np.mean(d))
        std_d = float(np.std(d, ddof=1))
        if std_d <= 1e-12:
            return 0.0, 1.0
        t_stat = mean_d / (std_d / math.sqrt(n))
        p_value = 2.0 * (1.0 - self._normal_cdf(abs(t_stat)))
        return float(t_stat), float(max(0.0, min(1.0, p_value)))

    def _wilcoxon_signed_rank_test(self, a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
        d = np.asarray(a) - np.asarray(b)
        non_zero = d[np.abs(d) > 1e-12]
        n = len(non_zero)
        if n == 0:
            return 0.0, 1.0

        abs_d = np.abs(non_zero)
        order = np.argsort(abs_d, kind="mergesort")
        sorted_abs = abs_d[order]

        # Compute midranks for tied groups.
        ranks = np.empty(n, dtype=float)
        tie_correction = 0.0
        i = 0
        while i < n:
            j = i + 1
            while j < n and abs(sorted_abs[j] - sorted_abs[i]) <= 1e-12:
                j += 1
            midrank = (i + 1 + j) / 2.0
            t = j - i  # tie group size
            tie_correction += t * t * t - t
            for k in range(i, j):
                ranks[order[k]] = midrank
            i = j

        w_plus = float(np.sum(ranks[non_zero > 0]))
        w_minus = float(np.sum(ranks[non_zero < 0]))
        w_stat = min(w_plus, w_minus)

        # Normal approximation with tie correction: Σ(t³-t)/48
        mean_w = n * (n + 1) / 4.0
        var_w = n * (n + 1) * (2 * n + 1) / 24.0 - tie_correction / 48.0
        if var_w <= 1e-12:
            return w_stat, 1.0
        z = (w_stat - mean_w) / math.sqrt(var_w)
        p_value = 2.0 * (1.0 - self._normal_cdf(abs(z)))
        return float(w_stat), float(max(0.0, min(1.0, p_value)))

    def compute_ece(
        self,
        predicted_means: list[float],
        predicted_stds: list[float],
        actuals: list[float],
        n_bins: int | None = None,
    ) -> float:
        """Quantile-based regression ECE (Kuleshov et al. 2018).

        For each confidence level p in evenly spaced bins, compute the
        expected vs. observed coverage of the prediction interval
        mean ± Φ⁻¹((1+p)/2)·std.
        """
        if not predicted_means:
            return 0.0

        bins = n_bins or self._policy.calibration.ece_n_bins
        means = np.asarray(predicted_means, dtype=float)
        stds = np.asarray(predicted_stds, dtype=float)
        ys = np.asarray(actuals, dtype=float)
        stds = np.maximum(stds, 1e-8)
        n = len(means)

        confidence_levels = np.linspace(1.0 / (bins + 1), bins / (bins + 1), bins)
        ece = 0.0
        for p in confidence_levels:
            z_crit = self._inv_normal_cdf((1.0 + p) / 2.0)
            lower = means - z_crit * stds
            upper = means + z_crit * stds
            empirical_coverage = float(np.sum((ys >= lower) & (ys <= upper))) / n
            ece += abs(empirical_coverage - p)
        return float(ece / bins)

    def save_training_data_snapshot(self, payload: dict[str, Any], version_id: str) -> Path:
        path = self._base_dir / version_id / "training_snapshot.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, default=str))
        return path

    def register_model(
        self,
        predictor: MultiTargetPredictor,
        *,
        feature_set_version: str,
        actual_feature_set: str | None = None,
        per_target_feature_sets: dict[str, str] | None = None,
        feature_schema_hash: str | None = None,
        training_manifest_hash: str | None = None,
        capability_manifest: dict[str, Any] | None = None,
        training_samples: int,
        training_seed: int,
        train_metrics: dict[str, Any] | None = None,
        val_metrics: dict[str, Any] | None = None,
        test_metrics: dict[str, Any] | None = None,
        calibration_ece: float | None = None,
        calibration_coverage: float | None = None,
        calibration_sharpness: float | None = None,
        triggered_by: str | None = None,
        parent_version_id: str | None = None,
        training_snapshot: dict[str, Any] | None = None,
        e_intra_method: str | None = None,
    ) -> MLModelVersionModel:
        version_id = self.generate_version_id()
        model_dir = self._base_dir / version_id / "model"
        try:
            predictor.save(model_dir)
        except Exception as e:
            raise MLOpsError(
                ErrorCode.MODEL_REGISTRATION_FAILED,
                f"Failed to persist model artifact: {e}",
            ) from e

        snapshot_path = None
        data_hash = None
        if training_snapshot is not None:
            snapshot_path = self.save_training_data_snapshot(training_snapshot, version_id)
            data_hash = compute_content_hash(training_snapshot)
            if training_manifest_hash is None:
                training_manifest_hash = data_hash

        # PR 2 (Codex Round 4): persist E_intra method tag in training_config_json
        # so visualisation, promotion, and challenger comparison can resolve
        # CED label provenance from model lineage.  Default to Method 1 baseline
        # when caller does not specify (back-compat).
        training_config = {
            "e_intra_method": e_intra_method or "single_molecule_vacuum",
        }

        row = MLModelVersionModel(
            version_id=version_id,
            model_type="multi_target",
            target_names=predictor.fitted_targets,
            feature_set_version=feature_set_version,
            actual_feature_set=actual_feature_set,
            per_target_feature_sets_json=per_target_feature_sets,
            feature_schema_hash=feature_schema_hash,
            training_manifest_hash=training_manifest_hash,
            capability_manifest_json=capability_manifest,
            status="challenger",
            training_samples=training_samples,
            training_seed=training_seed,
            training_config_json=training_config,
            train_metrics_json=train_metrics,
            val_metrics_json=val_metrics,
            test_metrics_json=test_metrics,
            calibration_ece=calibration_ece,
            calibration_coverage=calibration_coverage,
            calibration_sharpness=calibration_sharpness,
            training_data_hash=data_hash,
            model_artifact_path=str(model_dir),
            training_data_snapshot_path=str(snapshot_path) if snapshot_path else None,
            triggered_by=triggered_by,
            parent_version_id=parent_version_id,
        )
        self._repo.save(row)
        self._session.flush()
        return row

    def _compute_rmse(self, y_true: np.ndarray, y_pred: np.ndarray) -> float:
        if len(y_true) == 0:
            return 0.0
        return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))

    def compare_with_champion(
        self,
        challenger_pred: np.ndarray,
        champion_pred: np.ndarray,
        y_true: np.ndarray,
    ) -> ComparisonResult:
        """Compare challenger with champion on holdout predictions."""
        errors_ch = np.abs(y_true - challenger_pred)
        errors_cp = np.abs(y_true - champion_pred)

        policy = self._policy.model_comparison
        if policy.comparison_test == "paired_t":
            stat, p_val = self._paired_t_test(errors_cp, errors_ch)
            test_type = "paired_t"
        else:
            stat, p_val = self._wilcoxon_signed_rank_test(errors_cp, errors_ch)
            test_type = "wilcoxon"

        rmse_ch = self._compute_rmse(y_true, challenger_pred)
        rmse_cp = self._compute_rmse(y_true, champion_pred)
        if rmse_cp <= 1e-12:
            improvement_pct = 0.0
        else:
            improvement_pct = float((rmse_cp - rmse_ch) / rmse_cp * 100.0)

        effect_size = float(np.mean(errors_cp - errors_ch))
        promoted = (
            p_val < policy.comparison_alpha
            and improvement_pct >= policy.promotion_rmse_improvement_pct
        )
        reason = "promoted" if promoted else "insufficient improvement"

        return ComparisonResult(
            test_type=test_type,
            statistic=float(stat),
            p_value=float(p_val),
            effect_size=effect_size,
            challenger_rmse=rmse_ch,
            champion_rmse=rmse_cp,
            improvement_pct=improvement_pct,
            promoted=promoted,
            reason=reason,
        )

    def promote(self, version_id: str) -> MLModelVersionModel:
        row = self._repo.promote_to_champion(version_id)
        if row is None:
            raise MLOpsError(ErrorCode.MODEL_NOT_FOUND, f"Unknown model version: {version_id}")
        self._session.flush()
        return row

    def rollback(self) -> MLModelVersionModel:
        row = self._repo.rollback_to_previous()
        if row is None:
            raise MLOpsError(ErrorCode.ROLLBACK_FAILED, "No previous champion available")
        self._session.flush()
        return row

    def get_champion_predictor(self) -> MultiTargetPredictor | None:
        champion = self._repo.get_champion()
        if champion is None:
            return None
        model_dir = Path(champion.model_artifact_path)
        if not model_dir.exists():
            return None
        predictor = MultiTargetPredictor.load(model_dir)
        predictor._requested_feature_set = champion.feature_set_version
        predictor._actual_feature_set = champion.actual_feature_set
        predictor._capability_manifest = champion.capability_manifest_json
        predictor._per_target_feature_sets_from_registry = dict(
            champion.per_target_feature_sets_json or {}
        )
        predictor._feature_schema_hash = champion.feature_schema_hash
        return predictor
