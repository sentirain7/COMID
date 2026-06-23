"""
Tests for TgCalculator — glass transition temperature from bilinear fitting.

Covers:
- Known Tg recovery from synthetic data
- Edge cases (too few points, noisy data, monotonic data)
- SSOT metric creation and registry validation
- Metadata generation (success/failure)
- Bootstrap CI sanity
- Integration with MetricsRegistry
"""

import warnings

import numpy as np

from common.numpy_compat import RankWarning
from contracts.policies.metrics import MetricsRegistry
from metrics.tg import DensityTemperaturePoint, TgCalculator, TgResult

# ======================================================================
# Helpers
# ======================================================================


def _make_bilinear_data(
    tg: float = 300.0,
    slope_glassy: float = -3e-4,
    slope_rubbery: float = -6e-4,
    rho_at_tg: float = 1.05,
    temperatures: list[float] | None = None,
    noise_std: float = 0.0,
    seed: int = 42,
) -> list[DensityTemperaturePoint]:
    """Generate synthetic density-temperature data with a known Tg.

    Below Tg: ρ = slope_glassy * (T - Tg) + rho_at_tg
    Above Tg: ρ = slope_rubbery * (T - Tg) + rho_at_tg
    """
    if temperatures is None:
        temperatures = [253.0, 273.0, 293.0, 313.0, 333.0, 353.0, 373.0, 393.0, 413.0, 433.0]

    rng = np.random.default_rng(seed)
    points = []
    for temp in temperatures:
        if temp <= tg:
            rho = slope_glassy * (temp - tg) + rho_at_tg
        else:
            rho = slope_rubbery * (temp - tg) + rho_at_tg
        if noise_std > 0:
            rho += rng.normal(0, noise_std)
        points.append(
            DensityTemperaturePoint(
                temperature_k=temp,
                density_gcc=rho,
                exp_id=f"exp_{temp:.0f}K",
            )
        )
    return points


# ======================================================================
# TestTgCalculator — basic bilinear fitting
# ======================================================================


class TestTgCalculator:
    """Test Tg recovery from ideal and near-ideal data."""

    def test_known_tg_recovery(self):
        """Ideal bilinear data: Tg should be recovered within ±5 K."""
        true_tg = 310.0
        points = _make_bilinear_data(tg=true_tg)
        calc = TgCalculator(bootstrap_n=0)  # skip bootstrap for speed
        result = calc.compute(points)

        assert result.tg_k is not None
        assert result.error is None
        assert abs(result.tg_k - true_tg) < 5.0

    def test_slopes_sign(self):
        """Both slopes should be negative (density decreases with T)."""
        points = _make_bilinear_data(tg=300.0)
        calc = TgCalculator(bootstrap_n=0)
        result = calc.compute(points)

        assert result.slope_glassy is not None
        assert result.slope_rubbery is not None
        assert result.slope_glassy < 0
        assert result.slope_rubbery < 0

    def test_rubbery_slope_steeper(self):
        """Rubbery (high-T) segment should have a steeper slope."""
        points = _make_bilinear_data(
            tg=300.0,
            slope_glassy=-3e-4,
            slope_rubbery=-6e-4,
        )
        calc = TgCalculator(bootstrap_n=0)
        result = calc.compute(points)

        assert result.slope_glassy is not None
        assert result.slope_rubbery is not None
        # |slope_rubbery| > |slope_glassy|
        assert abs(result.slope_rubbery) > abs(result.slope_glassy)

    def test_r_squared_near_1_ideal(self):
        """Ideal data: R² should be close to 1."""
        points = _make_bilinear_data(tg=300.0, noise_std=0.0)
        calc = TgCalculator(bootstrap_n=0)
        result = calc.compute(points)

        assert result.r_squared is not None
        assert result.r_squared > 0.99

    def test_density_at_tg_reasonable(self):
        """Density at Tg should be close to the specified value."""
        rho_tg = 1.05
        points = _make_bilinear_data(tg=300.0, rho_at_tg=rho_tg)
        calc = TgCalculator(bootstrap_n=0)
        result = calc.compute(points)

        assert result.density_at_tg is not None
        assert abs(result.density_at_tg - rho_tg) < 0.01

    def test_n_points_and_temperatures(self):
        """Should report correct point and temperature counts."""
        temps = [273.0, 293.0, 313.0, 333.0, 353.0, 373.0]
        points = _make_bilinear_data(tg=310.0, temperatures=temps)
        calc = TgCalculator(bootstrap_n=0)
        result = calc.compute(points)

        assert result.n_points == 6
        assert result.n_temperatures == 6


# ======================================================================
# TestEdgeCases
# ======================================================================


class TestEdgeCases:
    """Test error handling and boundary conditions."""

    def test_too_few_points(self):
        """Less than 4 points should fail (min 2 per segment)."""
        points = _make_bilinear_data(
            tg=300.0,
            temperatures=[273.0, 293.0, 313.0],
        )
        calc = TgCalculator(min_points_per_segment=2, bootstrap_n=0)
        result = calc.compute(points)

        assert result.tg_k is None
        assert "Insufficient" in (result.error or "")

    def test_single_temperature(self):
        """All same temperature — should fail."""
        points = [
            DensityTemperaturePoint(temperature_k=300.0, density_gcc=1.0 + i * 0.001)
            for i in range(10)
        ]
        calc = TgCalculator(bootstrap_n=0)
        result = calc.compute(points)

        assert result.tg_k is None
        assert "Insufficient distinct" in (result.error or "")

    def test_nan_values_filtered(self):
        """NaN values in input should be filtered out."""
        points = _make_bilinear_data(
            tg=300.0,
            temperatures=[253.0, 273.0, 293.0, 313.0, 333.0, 353.0, 373.0],
        )
        # Inject NaN
        points[2] = DensityTemperaturePoint(
            temperature_k=float("nan"),
            density_gcc=1.0,
        )
        calc = TgCalculator(bootstrap_n=0)
        result = calc.compute(points)

        # Should still work with 6 valid points
        assert result.n_points == 6

    def test_noisy_data_still_finds_tg(self):
        """Moderate noise: Tg should still be within ±20 K."""
        true_tg = 310.0
        points = _make_bilinear_data(tg=true_tg, noise_std=0.002, seed=123)
        calc = TgCalculator(bootstrap_n=0)
        result = calc.compute(points)

        assert result.tg_k is not None
        assert abs(result.tg_k - true_tg) < 20.0

    def test_empty_input(self):
        """Empty list should return error."""
        calc = TgCalculator(bootstrap_n=0)
        result = calc.compute([])

        assert result.tg_k is None
        assert result.error is not None

    def test_monotonic_no_breakpoint(self):
        """Perfectly linear data: fit should succeed but with poor differentiation."""
        # Uniform slope — no real breakpoint
        temps = [273.0, 293.0, 313.0, 333.0, 353.0, 373.0]
        points = [
            DensityTemperaturePoint(
                temperature_k=t,
                density_gcc=1.1 - 4e-4 * t,
            )
            for t in temps
        ]
        calc = TgCalculator(bootstrap_n=0)
        result = calc.compute(points)

        # Should still return a result (bilinear reduces to linear)
        # R² should be high since data is perfectly linear
        assert result.tg_k is not None
        assert result.r_squared is not None


# ======================================================================
# TestBootstrapCI
# ======================================================================


class TestBootstrapCI:
    """Test bootstrap confidence interval."""

    def test_ci_contains_true_tg(self):
        """95% CI should contain the true Tg for clean data."""
        true_tg = 310.0
        points = _make_bilinear_data(tg=true_tg, noise_std=0.001, seed=99)
        calc = TgCalculator(bootstrap_n=200)  # reduced for speed
        result = calc.compute(points)

        assert result.tg_ci_lower_k is not None
        assert result.tg_ci_upper_k is not None
        assert result.tg_ci_lower_k <= true_tg <= result.tg_ci_upper_k

    def test_ci_width_reasonable(self):
        """CI width should be < 100 K for reasonable data."""
        points = _make_bilinear_data(tg=310.0, noise_std=0.001)
        calc = TgCalculator(bootstrap_n=200)
        result = calc.compute(points)

        assert result.tg_ci_lower_k is not None
        assert result.tg_ci_upper_k is not None
        width = result.tg_ci_upper_k - result.tg_ci_lower_k
        assert width < 100.0

    def test_bootstrap_disabled(self):
        """bootstrap_n=0 → no CI."""
        points = _make_bilinear_data(tg=300.0)
        calc = TgCalculator(bootstrap_n=0)
        result = calc.compute(points)

        assert result.tg_ci_lower_k is None
        assert result.tg_ci_upper_k is None
        assert result.bootstrap_n == 0


# ======================================================================
# TestMetricCreation (SSOT)
# ======================================================================


class TestMetricCreation:
    """Test SSOT metric creation via registry."""

    def test_metric_name_and_unit(self):
        """Created metric should match registry SSOT."""
        registry = MetricsRegistry()
        calc = TgCalculator(registry=registry, bootstrap_n=0)

        result = TgResult(tg_k=305.0, n_points=10, n_temperatures=10)
        metric = calc.create_metric(result)

        assert metric is not None
        assert metric.metric_name == "glass_transition_temperature_k"
        assert metric.unit == "K"
        assert metric.namespace == "bulk_ff_gaff2"
        assert metric.value == 305.0

    def test_none_when_no_tg(self):
        """Should return None when Tg is not available."""
        calc = TgCalculator(bootstrap_n=0)
        result = TgResult(tg_k=None, error="test failure")
        metric = calc.create_metric(result)

        assert metric is None

    def test_registry_validates_name(self):
        """Metric name should be in the registry."""
        registry = MetricsRegistry()
        assert registry.is_valid_metric("glass_transition_temperature_k")
        assert registry.get_unit("glass_transition_temperature_k") == "K"


# ======================================================================
# TestMetadata
# ======================================================================


class TestMetadata:
    """Test metadata generation for experiment record."""

    def test_success_metadata(self):
        """Successful Tg: metadata should include all key fields."""
        result = TgResult(
            tg_k=310.0,
            tg_ci_lower_k=305.0,
            tg_ci_upper_k=315.0,
            slope_glassy=-3e-4,
            slope_rubbery=-6e-4,
            r_squared=0.998,
            n_points=10,
            n_temperatures=10,
        )
        meta = TgCalculator.get_metadata(result)

        assert meta["tg_parse_status"] == "success"
        assert meta["tg_method"] == "bilinear_breakpoint"
        assert meta["tg_k"] == 310.0
        assert meta["tg_ci_lower_k"] == 305.0
        assert meta["tg_ci_upper_k"] == 315.0
        assert meta["tg_slope_glassy"] == -3e-4
        assert meta["tg_r2_total"] == 0.998

    def test_failure_metadata(self):
        """Failed Tg: metadata should record error."""
        result = TgResult(
            tg_k=None,
            n_points=3,
            n_temperatures=3,
            error="Insufficient data points (3 < 4)",
        )
        meta = TgCalculator.get_metadata(result)

        assert meta["tg_parse_status"] == "failed"
        assert "Insufficient" in meta["tg_error"]
        assert "tg_k" not in meta


# ======================================================================
# TestSparseData (realistic MD temperature scan)
# ======================================================================


class TestSparseData:
    """Test with realistic sparse MD data (5 temperatures)."""

    def test_five_temperature_scan(self):
        """Standard 5-temperature scan should find Tg."""
        true_tg = 310.0
        temps = [273.0, 293.0, 313.0, 333.0, 373.0]
        points = _make_bilinear_data(
            tg=true_tg,
            temperatures=temps,
            slope_glassy=-3e-4,
            slope_rubbery=-7e-4,
        )
        calc = TgCalculator(min_points_per_segment=2, bootstrap_n=0)
        result = calc.compute(points)

        assert result.tg_k is not None
        assert abs(result.tg_k - true_tg) < 10.0

    def test_four_points_minimum(self):
        """Minimum 4 points (2 per segment) should work."""
        temps = [273.0, 293.0, 333.0, 373.0]
        points = _make_bilinear_data(
            tg=310.0,
            temperatures=temps,
            slope_glassy=-3e-4,
            slope_rubbery=-7e-4,
        )
        calc = TgCalculator(min_points_per_segment=2, bootstrap_n=0)
        result = calc.compute(points)

        assert result.tg_k is not None

    def test_replicate_seeds(self):
        """Multiple seeds per temperature should improve fitting."""
        true_tg = 310.0
        temps = [273.0, 293.0, 313.0, 333.0, 373.0]
        # 3 replicates per temperature with noise
        points = []
        rng = np.random.default_rng(42)
        for temp in temps:
            for _ in range(3):
                if temp <= true_tg:
                    rho = -3e-4 * (temp - true_tg) + 1.05
                else:
                    rho = -7e-4 * (temp - true_tg) + 1.05
                rho += rng.normal(0, 0.003)
                points.append(
                    DensityTemperaturePoint(
                        temperature_k=temp,
                        density_gcc=rho,
                    )
                )

        calc = TgCalculator(bootstrap_n=0)
        result = calc.compute(points)

        assert result.tg_k is not None
        assert result.n_points == 15
        assert result.n_temperatures == 5
        assert abs(result.tg_k - true_tg) < 25.0


# ======================================================================
# TestAsphaltRealistic — literature-like values
# ======================================================================


class TestAsphaltRealistic:
    """Test with asphalt-like density and Tg values."""

    def test_typical_asphalt_tg(self):
        """Asphalt Tg ≈ 250-310 K, density ≈ 0.95-1.10 g/cm3."""
        true_tg = 270.0
        points = _make_bilinear_data(
            tg=true_tg,
            slope_glassy=-2.5e-4,
            slope_rubbery=-5.5e-4,
            rho_at_tg=1.02,
            temperatures=[213.0, 233.0, 253.0, 273.0, 293.0, 313.0, 333.0, 373.0, 413.0, 433.0],
        )
        calc = TgCalculator(bootstrap_n=0)
        result = calc.compute(points)

        assert result.tg_k is not None
        assert 250.0 < result.tg_k < 290.0
        assert result.density_at_tg is not None
        assert 0.95 < result.density_at_tg < 1.10


# ======================================================================
# TestRankWarningSuppressed
# ======================================================================


class TestRankWarningSuppressed:
    """Test that np.RankWarning is suppressed during bootstrap."""

    def test_no_warning_during_bootstrap(self):
        """Bootstrap should not emit np.RankWarning even with sparse data."""
        # Use 5 temperatures with noise to provoke potential RankWarning
        # during bootstrap resampling (duplicate samples reduce rank)
        points = _make_bilinear_data(
            tg=310.0,
            temperatures=[273.0, 293.0, 313.0, 333.0, 373.0],
            noise_std=0.001,
            seed=7,
        )
        calc = TgCalculator(bootstrap_n=50, min_points_per_segment=2)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            calc.compute(points)

        rank_warnings = [w for w in caught if issubclass(w.category, RankWarning)]
        assert len(rank_warnings) == 0
