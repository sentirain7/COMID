"""Recommendation-quality metrics for model promotion decisions."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_MINIMIZE_TARGETS = {"viscosity"}


@dataclass
class RecommendationEvalInput:
    """Per-target holdout predictions for recommendation-quality evaluation."""

    y_true: np.ndarray
    y_pred: np.ndarray
    uncertainties: np.ndarray | None = None
    ood_flags: np.ndarray | None = None
    direction: str = "maximize"


class RecommendationEvaluator:
    """Compute compact recommendation-quality metrics from holdout predictions."""

    def __init__(
        self,
        *,
        top_k: int = 5,
        feasibility_rel_error: float = 0.10,
        degradation_tolerance: float = 0.02,
    ) -> None:
        self.top_k = max(1, int(top_k))
        self.feasibility_rel_error = max(1e-6, float(feasibility_rel_error))
        self.degradation_tolerance = max(0.0, float(degradation_tolerance))

    def _relative_error(self, y_true: np.ndarray, y_pred: np.ndarray) -> np.ndarray:
        denom = np.maximum(np.abs(y_true), 1e-8)
        return np.abs(y_true - y_pred) / denom

    def _regression_ece(
        self,
        means: np.ndarray,
        stds: np.ndarray,
        actuals: np.ndarray,
        *,
        n_bins: int = 10,
    ) -> float:
        if means.size == 0:
            return 0.0

        stds = np.maximum(stds, 1e-8)
        bins = np.linspace(1.0 / (n_bins + 1), n_bins / (n_bins + 1), n_bins)
        ece = 0.0
        for p in bins:
            z = self._inv_normal_cdf((1.0 + p) / 2.0)
            lower = means - z * stds
            upper = means + z * stds
            empirical = float(np.mean((actuals >= lower) & (actuals <= upper)))
            ece += abs(empirical - p)
        return float(ece / len(bins))

    def _inv_normal_cdf(self, p: float) -> float:
        if p <= 0.0:
            return -6.0
        if p >= 1.0:
            return 6.0
        if abs(p - 0.5) < 1e-12:
            return 0.0

        if p < 0.5:
            sign = -1.0
            q = p
        else:
            sign = 1.0
            q = 1.0 - p

        t = np.sqrt(-2.0 * np.log(q))
        c0, c1, c2 = 2.515517, 0.802853, 0.010328
        d1, d2, d3 = 1.432788, 0.189269, 0.001308
        numerator = c0 + c1 * t + c2 * t * t
        denominator = 1.0 + d1 * t + d2 * t * t + d3 * t * t * t
        return float(sign * (t - numerator / denominator))

    def _rank_indices(self, values: np.ndarray, direction: str) -> np.ndarray:
        order = np.argsort(values)
        if direction != "minimize":
            order = order[::-1]
        return order

    def evaluate(
        self,
        target_inputs: dict[str, RecommendationEvalInput],
    ) -> dict[str, float]:
        """Aggregate recommendation-quality metrics across holdout targets."""
        total_points = 0
        feasible_points = 0
        topk_scores: list[float] = []
        ece_scores: list[float] = []
        ood_true_positive = 0
        ood_predicted_positive = 0

        for target_name, data in target_inputs.items():
            y_true = np.asarray(data.y_true, dtype=float)
            y_pred = np.asarray(data.y_pred, dtype=float)
            if y_true.size == 0 or y_true.shape != y_pred.shape:
                continue

            total_points += int(y_true.size)
            rel_error = self._relative_error(y_true, y_pred)
            feasible_points += int(np.sum(rel_error <= self.feasibility_rel_error))

            k = min(self.top_k, int(y_true.size))
            if k > 0:
                direction = data.direction or (
                    "minimize" if target_name in _MINIMIZE_TARGETS else "maximize"
                )
                pred_top = set(self._rank_indices(y_pred, direction)[:k].tolist())
                true_top = set(self._rank_indices(y_true, direction)[:k].tolist())
                topk_scores.append(len(pred_top & true_top) / float(k))

            if data.uncertainties is not None:
                stds = np.asarray(data.uncertainties, dtype=float)
                if stds.shape == y_true.shape:
                    ece_scores.append(self._regression_ece(y_pred, stds, y_true))

            if data.ood_flags is not None:
                ood_flags = np.asarray(data.ood_flags, dtype=bool)
                if ood_flags.shape == y_true.shape:
                    hard_cases = rel_error > self.feasibility_rel_error
                    ood_true_positive += int(np.sum(ood_flags & hard_cases))
                    ood_predicted_positive += int(np.sum(ood_flags))

        return {
            "feasibility_rate": (
                float(feasible_points) / float(total_points) if total_points else 0.0
            ),
            "top_k_hit_rate": float(np.mean(topk_scores)) if topk_scores else 0.0,
            "calibration_ece": float(np.mean(ece_scores)) if ece_scores else 0.0,
            "ood_precision": (
                float(ood_true_positive) / float(ood_predicted_positive)
                if ood_predicted_positive
                else 1.0
            ),
        }

    def not_degraded(
        self,
        challenger: dict[str, float] | None,
        champion: dict[str, float] | None,
    ) -> bool:
        """Return True when recommendation metrics are no worse than champion."""
        if not challenger or not champion:
            return True
        tol = self.degradation_tolerance
        return (
            challenger.get("feasibility_rate", 0.0) + tol >= champion.get("feasibility_rate", 0.0)
            and challenger.get("top_k_hit_rate", 0.0) + tol >= champion.get("top_k_hit_rate", 0.0)
            and challenger.get("calibration_ece", 0.0) <= champion.get("calibration_ece", 0.0) + tol
            and challenger.get("ood_precision", 0.0) + tol >= champion.get("ood_precision", 0.0)
        )
