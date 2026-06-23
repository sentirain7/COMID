"""Tests for UncertaintyEstimator (Phase 5.2).

Covers CI estimation, calibration, coverage, and sharpness.
"""

from __future__ import annotations

from ml.uncertainty import UncertaintyEstimator, UncertaintyResult


class TestUncertaintyEstimator:
    def test_estimate_returns_ci(self):
        """estimate() produces a valid UncertaintyResult with CI."""
        estimator = UncertaintyEstimator(ci_level=0.95, ensemble_size=5)
        result = estimator.estimate(mean=1.0, std=0.1)

        assert isinstance(result, UncertaintyResult)
        assert result.ci_lower < result.mean
        assert result.ci_upper > result.mean
        assert result.ci_level == 0.95
        assert result.calibrated_std > 0

    def test_calibrate_improves_coverage(self):
        """Calibration should improve empirical coverage toward ci_level."""
        estimator = UncertaintyEstimator(ci_level=0.95, ensemble_size=5)

        # Generate synthetic prediction/actual pairs
        # Deliberately make std underestimate actual error
        means = [float(i) for i in range(60)]
        stds = [0.01] * 60  # very small std
        actuals = [m + 0.5 * ((-1) ** i) for i, m in enumerate(means)]  # actual error ~0.5

        # Before calibration: coverage should be low (std too small)
        coverage_before = estimator.compute_coverage(means, stds, actuals)

        # Calibrate
        estimator.calibrate(means, stds, actuals)
        assert estimator.is_calibrated

        # After calibration: coverage should improve
        coverage_after = estimator.compute_coverage(means, stds, actuals)
        assert coverage_after >= coverage_before

    def test_coverage_computation(self):
        """Coverage with known data matches expectation."""
        estimator = UncertaintyEstimator(ci_level=0.95, ensemble_size=10)

        # All actuals exactly at mean → 100% coverage
        means = [1.0, 2.0, 3.0, 4.0]
        stds = [0.5, 0.5, 0.5, 0.5]
        actuals = [1.0, 2.0, 3.0, 4.0]

        coverage = estimator.compute_coverage(means, stds, actuals)
        assert coverage == 1.0

    def test_sharpness_decreases_with_lower_std(self):
        """Lower std should produce lower sharpness (tighter CIs)."""
        estimator = UncertaintyEstimator(ci_level=0.95, ensemble_size=5)

        high_stds = [1.0, 1.0, 1.0]
        low_stds = [0.1, 0.1, 0.1]

        sharpness_high = estimator.compute_sharpness(high_stds)
        sharpness_low = estimator.compute_sharpness(low_stds)

        assert sharpness_low < sharpness_high

    def test_zero_std_handled(self):
        """Zero std doesn't cause division errors."""
        estimator = UncertaintyEstimator(ci_level=0.95, ensemble_size=5)
        result = estimator.estimate(mean=1.0, std=0.0)

        assert result.ci_lower <= result.mean
        assert result.ci_upper >= result.mean
        assert result.calibrated_std > 0  # clamped to minimum

    def test_empty_coverage(self):
        """Coverage of empty list returns 0."""
        estimator = UncertaintyEstimator()
        assert estimator.compute_coverage([], [], []) == 0.0

    def test_empty_sharpness(self):
        """Sharpness of empty list returns 0."""
        estimator = UncertaintyEstimator()
        assert estimator.compute_sharpness([]) == 0.0
