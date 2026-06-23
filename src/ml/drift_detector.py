"""Concept drift detection utilities (numpy-only)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from contracts.policies.ml_policy import DEFAULT_ML_POLICY


class DriftType(StrEnum):
    """Detected drift category."""

    NONE = "none"
    VIRTUAL = "virtual"
    REAL = "real"
    BOTH = "both"


@dataclass
class FeatureDriftResult:
    """Per-feature KS drift result."""

    feature_index: int
    ks_statistic: float
    p_value: float
    is_drift: bool


@dataclass
class DriftReport:
    """Aggregate drift report."""

    drift_type: DriftType
    feature_drift_fraction: float
    rmse_baseline: float
    rmse_current: float
    rmse_drift_pct: float
    page_hinkley_detected: bool
    should_retrain: bool
    drifted_targets: list[str] | None = None


class DriftDetector:
    """Combined feature/prediction/sequential drift detector."""

    def __init__(self) -> None:
        policy = DEFAULT_ML_POLICY.drift_detection
        self.ks_alpha = policy.ks_test_alpha
        self.ks_min_samples = policy.ks_test_min_samples
        self.feature_drift_threshold = policy.feature_drift_threshold
        self.rmse_window_size = policy.rmse_window_size
        self.rmse_drift_pct = policy.rmse_drift_pct
        self.page_hinkley_delta = policy.page_hinkley_delta
        self.page_hinkley_lambda = policy.page_hinkley_lambda
        self._ph_mean = 0.0
        self._ph_cum_sum = 0.0
        self._ph_min_sum = 0.0
        self._ph_t = 0

    def reset_page_hinkley(self) -> None:
        self._ph_mean = 0.0
        self._ph_cum_sum = 0.0
        self._ph_min_sum = 0.0
        self._ph_t = 0

    def _ecdf(self, values: np.ndarray, x: np.ndarray) -> np.ndarray:
        values_sorted = np.sort(values)
        return np.searchsorted(values_sorted, x, side="right") / float(len(values_sorted))

    def _ks_2samp(self, x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
        """Two-sample KS statistic and asymptotic p-value (numpy-only)."""
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        all_vals = np.sort(np.concatenate([x, y]))
        cdf_x = self._ecdf(x, all_vals)
        cdf_y = self._ecdf(y, all_vals)
        d = float(np.max(np.abs(cdf_x - cdf_y)))

        n = len(x)
        m = len(y)
        n_eff = (n * m) / float(n + m)
        if n_eff <= 0:
            return d, 1.0

        # Kolmogorov asymptotic tail approximation.
        p_sum = 0.0
        for k in range(1, 200):
            term = ((-1) ** (k - 1)) * math.exp(-2.0 * (k**2) * n_eff * (d**2))
            p_sum += term
            if abs(term) < 1e-12:
                break
        p_value = float(max(0.0, min(1.0, 2.0 * p_sum)))
        return d, p_value

    def detect_feature_drift(
        self,
        x_train: np.ndarray,
        x_new: np.ndarray,
    ) -> list[FeatureDriftResult]:
        """Per-feature KS test for virtual drift."""
        if x_train.ndim != 2 or x_new.ndim != 2:
            raise ValueError("x_train and x_new must be 2D arrays")
        if x_train.shape[1] != x_new.shape[1]:
            raise ValueError("x_train and x_new feature dimensions must match")

        n_new = x_new.shape[0]
        n_train = x_train.shape[0]
        if n_new < self.ks_min_samples or n_train < self.ks_min_samples:
            return []

        out: list[FeatureDriftResult] = []
        for j in range(x_train.shape[1]):
            d, p = self._ks_2samp(x_train[:, j], x_new[:, j])
            out.append(
                FeatureDriftResult(
                    feature_index=j,
                    ks_statistic=d,
                    p_value=p,
                    is_drift=p < self.ks_alpha,
                )
            )
        return out

    def detect_prediction_drift(
        self, y_true: np.ndarray, y_pred: np.ndarray
    ) -> tuple[float, float, float]:
        """Rolling RMSE drift report as (baseline, current, drift_pct)."""
        y_true = np.asarray(y_true, dtype=float)
        y_pred = np.asarray(y_pred, dtype=float)
        if len(y_true) != len(y_pred):
            raise ValueError("y_true and y_pred length mismatch")
        if len(y_true) < 2:
            return 0.0, 0.0, 0.0

        errors = y_true - y_pred
        sq = errors**2
        if len(sq) < self.rmse_window_size * 2:
            rmse = float(np.sqrt(np.mean(sq)))
            return rmse, rmse, 0.0

        baseline = float(np.sqrt(np.mean(sq[: self.rmse_window_size])))
        current = float(np.sqrt(np.mean(sq[-self.rmse_window_size :])))

        if baseline <= 1e-12:
            drift_pct = 0.0 if current <= 1e-12 else 100.0
        else:
            drift_pct = float((current - baseline) / baseline * 100.0)
        return baseline, current, drift_pct

    def detect_sequential(self, residual: float) -> bool:
        """Page-Hinkley online drift update."""
        self._ph_t += 1
        self._ph_mean += (residual - self._ph_mean) / self._ph_t
        self._ph_cum_sum += residual - self._ph_mean - self.page_hinkley_delta
        self._ph_min_sum = min(self._ph_min_sum, self._ph_cum_sum)
        ph_stat = self._ph_cum_sum - self._ph_min_sum
        return ph_stat > self.page_hinkley_lambda

    def full_check(
        self,
        x_train: np.ndarray,
        x_new: np.ndarray,
        y_true: np.ndarray | None = None,
        y_pred: np.ndarray | None = None,
    ) -> DriftReport:
        """Run full drift checks and return consolidated report."""
        feature_results = self.detect_feature_drift(x_train, x_new)
        if feature_results:
            frac = sum(1 for r in feature_results if r.is_drift) / float(len(feature_results))
        else:
            frac = 0.0

        rmse_baseline = 0.0
        rmse_current = 0.0
        rmse_pct = 0.0
        ph_detected = False

        if y_true is not None and y_pred is not None and len(y_true) == len(y_pred):
            rmse_baseline, rmse_current, rmse_pct = self.detect_prediction_drift(y_true, y_pred)
            residuals = np.abs(np.asarray(y_true, dtype=float) - np.asarray(y_pred, dtype=float))
            for residual in residuals:
                if self.detect_sequential(float(residual)):
                    ph_detected = True
                    break

        has_virtual = frac >= self.feature_drift_threshold
        has_real = rmse_pct > self.rmse_drift_pct or ph_detected

        if has_virtual and has_real:
            drift_type = DriftType.BOTH
        elif has_virtual:
            drift_type = DriftType.VIRTUAL
        elif has_real:
            drift_type = DriftType.REAL
        else:
            drift_type = DriftType.NONE

        return DriftReport(
            drift_type=drift_type,
            feature_drift_fraction=float(frac),
            rmse_baseline=rmse_baseline,
            rmse_current=rmse_current,
            rmse_drift_pct=rmse_pct,
            page_hinkley_detected=ph_detected,
            should_retrain=drift_type != DriftType.NONE,
        )
