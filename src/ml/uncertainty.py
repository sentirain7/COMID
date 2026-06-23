"""Uncertainty estimation — calibrated CI from ensemble predictions.

Phase 5.2: Converts raw ensemble std into calibrated confidence intervals.
Uses t-distribution critical values from metrics.statistics (no scipy).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from contracts.policies.ml_policy import DEFAULT_ML_POLICY
from metrics.statistics import _t_critical_two_tailed

_logger = logging.getLogger(__name__)


@dataclass
class UncertaintyResult:
    """Result of uncertainty estimation.

    Attributes:
        mean: Predicted mean value.
        std: Raw ensemble standard deviation.
        calibrated_std: Calibrated standard deviation.
        ci_lower: Lower CI bound.
        ci_upper: Upper CI bound.
        ci_level: Confidence level used.
    """

    mean: float
    std: float
    calibrated_std: float
    ci_lower: float
    ci_upper: float
    ci_level: float


class UncertaintyEstimator:
    """Estimate calibrated uncertainty from ensemble predictions.

    Converts raw ensemble std into confidence intervals using t-distribution
    critical values. Optionally calibrates std using validation data.

    Args:
        ci_level: Confidence level for intervals (default: from policy).
        ensemble_size: Number of ensemble members (for df calculation).
    """

    def __init__(
        self,
        ci_level: float | None = None,
        ensemble_size: int | None = None,
    ) -> None:
        self.ci_level = ci_level or DEFAULT_ML_POLICY.uncertainty_ci_level
        self.ensemble_size = ensemble_size or DEFAULT_ML_POLICY.default_ensemble_size
        self._calibration_slope: float = 1.0
        self._calibration_intercept: float = 0.0
        self._is_calibrated: bool = False

    @property
    def is_calibrated(self) -> bool:
        """Whether calibration has been performed."""
        return self._is_calibrated

    def estimate(self, mean: float, std: float) -> UncertaintyResult:
        """Compute calibrated CI from prediction mean and ensemble std.

        Args:
            mean: Predicted mean value.
            std: Raw ensemble standard deviation.

        Returns:
            UncertaintyResult with calibrated CI.
        """
        calibrated_std = self._calibrate_std(std)
        alpha = 1.0 - self.ci_level
        df = max(1, self.ensemble_size - 1)
        t_crit = _t_critical_two_tailed(float(df), alpha)

        margin = t_crit * calibrated_std

        return UncertaintyResult(
            mean=mean,
            std=std,
            calibrated_std=calibrated_std,
            ci_lower=mean - margin,
            ci_upper=mean + margin,
            ci_level=self.ci_level,
        )

    def _calibrate_std(self, raw_std: float) -> float:
        """Apply calibration transform to raw std.

        Args:
            raw_std: Raw ensemble standard deviation.

        Returns:
            Calibrated standard deviation.
        """
        calibrated = self._calibration_slope * raw_std + self._calibration_intercept
        return max(calibrated, 1e-10)  # ensure positive

    def calibrate(
        self,
        predicted_means: list[float],
        predicted_stds: list[float],
        actual_values: list[float],
    ) -> None:
        """Calibrate std-to-error mapping from validation data.

        Fits a linear relationship: actual_error ≈ slope * predicted_std + intercept.

        Args:
            predicted_means: Predicted mean values from ensemble.
            predicted_stds: Predicted std values from ensemble.
            actual_values: True observed values.

        Raises:
            ValueError: If fewer than calibration_min_samples are provided.
        """
        n = len(predicted_means)
        min_samples = DEFAULT_ML_POLICY.calibration_min_samples
        if n < min_samples:
            raise ValueError(
                f"Calibration requires at least {min_samples} samples "
                f"(calibration_min_samples policy), got {n}"
            )

        # Compute absolute errors
        errors = [
            abs(pred - actual) for pred, actual in zip(predicted_means, actual_values, strict=True)
        ]

        # Simple linear regression: error = slope * std + intercept
        mean_std = sum(predicted_stds) / n
        mean_err = sum(errors) / n

        numerator = sum(
            (s - mean_std) * (e - mean_err) for s, e in zip(predicted_stds, errors, strict=True)
        )
        denominator = sum((s - mean_std) ** 2 for s in predicted_stds)

        if denominator > 1e-12:
            self._calibration_slope = numerator / denominator
            self._calibration_intercept = mean_err - self._calibration_slope * mean_std
        else:
            # All stds are the same — use mean error as intercept
            self._calibration_slope = 1.0
            self._calibration_intercept = mean_err

        # Ensure slope is positive (error should increase with uncertainty)
        if self._calibration_slope < 0:
            self._calibration_slope = 1.0
            self._calibration_intercept = mean_err

        self._is_calibrated = True
        _logger.info(
            f"Calibrated: slope={self._calibration_slope:.4f}, "
            f"intercept={self._calibration_intercept:.4f}"
        )

    def compute_coverage(
        self,
        predicted_means: list[float],
        predicted_stds: list[float],
        actuals: list[float],
    ) -> float:
        """Compute empirical coverage of CI.

        Coverage = fraction of actuals falling within CI.
        Ideal coverage ≈ ci_level.

        Args:
            predicted_means: Predicted mean values.
            predicted_stds: Predicted std values.
            actuals: True observed values.

        Returns:
            Coverage fraction in [0, 1].
        """
        if not predicted_means:
            return 0.0

        count_in = 0
        for mean, std, actual in zip(predicted_means, predicted_stds, actuals, strict=True):
            result = self.estimate(mean, std)
            if result.ci_lower <= actual <= result.ci_upper:
                count_in += 1

        return count_in / len(predicted_means)

    def compute_sharpness(self, predicted_stds: list[float]) -> float:
        """Compute mean CI width (sharpness).

        Lower sharpness = tighter CIs = better, as long as coverage is maintained.

        Args:
            predicted_stds: Predicted std values.

        Returns:
            Mean CI width.
        """
        if not predicted_stds:
            return 0.0

        alpha = 1.0 - self.ci_level
        df = max(1, self.ensemble_size - 1)
        t_crit = _t_critical_two_tailed(float(df), alpha)

        widths = []
        for std in predicted_stds:
            calibrated = self._calibrate_std(std)
            width = 2.0 * t_crit * calibrated
            widths.append(width)

        return sum(widths) / len(widths)
