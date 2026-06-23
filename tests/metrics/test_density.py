"""Tests for density calculator."""

import sys

import pytest

sys.path.insert(0, "src")

from metrics.density import DensityCalculator, DensityTimeSeries


class TestDensityCalculator:
    """Test density calculator."""

    @pytest.fixture
    def calculator(self):
        return DensityCalculator()

    def test_calculate_from_box(self, calculator):
        """Test density calculation from box volume."""
        # 1000 atoms of carbon (12 amu) in 10x10x10 nm box
        volume_A3 = 1000**3  # 10^9 A^3
        total_mass_amu = 1000 * 12.0  # 12000 amu

        density = calculator.calculate_from_box(volume_A3, total_mass_amu)

        # Should be very small density for this large box
        assert density > 0
        assert density < 0.1

    def test_calculate_from_thermo_skip_fraction(self, calculator):
        """Test density from thermo output with skip_fraction (backward compat)."""
        # Simulated density values during equilibration
        density_values = [1.2, 1.15, 1.1, 1.08, 1.06, 1.05, 1.05, 1.05, 1.05, 1.05]

        avg, std = calculator.calculate_from_thermo(density_values, skip_fraction=0.2)

        assert avg == pytest.approx(1.06, rel=0.05)
        assert std > 0

    def test_calculate_from_thermo_window_ps(self, calculator):
        """Test density uses last window_ps data (new behavior)."""
        # Simulate NVT (high variation) + NPT (stable at 1.05)
        # With dt=1.0fs, thermo_interval=10000 -> 10 ps per sample
        nvt_phase = [1.2, 1.15, 1.1, 1.08] * 10  # 40 samples = 400 ps unstable
        npt_phase = [1.05] * 20  # 20 samples = 200 ps stable
        density_values = nvt_phase + npt_phase

        # Using last 200 ps (20 samples) should give ~1.05
        avg, std = calculator.calculate_from_thermo(
            density_values,
            window_ps=200.0,
            dt_fs=1.0,
            thermo_interval=10000,  # 10 ps per sample
        )

        # Should be exactly from NPT phase (1.05)
        assert avg == pytest.approx(1.05, rel=0.01)
        assert std == pytest.approx(0.0, abs=0.001)

    def test_calculate_from_thermo_excludes_nvt(self, calculator):
        """Test that NVT phase data is excluded with window_ps."""
        # NVT phase: high fluctuation around 1.15
        # NPT phase: stable at 1.02
        nvt_phase = [1.2, 1.15, 1.1, 1.15, 1.2] * 6  # 30 samples = 300 ps
        npt_phase = [1.02, 1.02, 1.02, 1.02, 1.02] * 4  # 20 samples = 200 ps
        density_values = nvt_phase + npt_phase

        # With window_ps=200, dt_fs=1.0, thermo_interval=10000 (10 ps/sample)
        # Should only use last 20 samples
        avg, std = calculator.calculate_from_thermo(
            density_values,
            window_ps=200.0,
            dt_fs=1.0,
            thermo_interval=10000,
        )

        # Should be from NPT only, ~1.02
        assert avg == pytest.approx(1.02, rel=0.01)

    def test_calculate_from_thermo_default_window(self, calculator):
        """Test default 200 ps window when no skip_fraction provided."""
        # 100 samples at 1 ps each (dt=1.0fs, interval=1000)
        nvt_phase = [1.3] * 50  # 50 ps
        npt_phase = [1.0] * 50  # 50 ps
        density_values = nvt_phase + npt_phase

        # Default window=200 ps, but only 50 ps of NPT data
        # Should use all NPT data available
        avg, std = calculator.calculate_from_thermo(
            density_values,
            dt_fs=1.0,
            thermo_interval=1000,  # 1 ps per sample
        )

        # With 200 ps window but only 100 ps total, uses all data
        # But since window > total, it will use entire dataset
        assert avg > 0

    def test_create_metric(self, calculator):
        """Test metric creation."""
        metric = calculator.create_metric(
            exp_id="test_exp_001",
            density_gcc=1.05,
            std_dev=0.02,
            temperature_K=298.0,
        )

        assert metric.metric_name == "density"
        assert metric.value == 1.05
        assert metric.unit == "g/cm3"
        assert metric.exp_id == "test_exp_001"

    def test_is_valid(self, calculator):
        """Test density validation."""
        assert calculator.is_valid(1.0) is True
        assert calculator.is_valid(0.3) is False
        assert calculator.is_valid(2.5) is False

    def test_check_asphalt_range(self, calculator):
        """Test asphalt density range check."""
        assert calculator.check_asphalt_range(1.05) == "ok"
        assert calculator.check_asphalt_range(0.5) == "too_low"
        assert calculator.check_asphalt_range(1.5) == "too_high"


class TestDensityTimeSeries:
    """Test density time series functionality."""

    @pytest.fixture
    def calculator(self):
        return DensityCalculator()

    def test_calculate_time_series_basic(self, calculator):
        """Test basic time series calculation."""
        # 50 samples at 10 ps each = 500 ps total
        density_values = [1.1] * 30 + [1.0] * 20  # NVT + NPT

        result = calculator.calculate_time_series(
            density_values=density_values,
            window_ps=200.0,
            dt_fs=1.0,
            thermo_interval=10000,  # 10 ps per sample
        )

        assert isinstance(result, DensityTimeSeries)
        assert len(result.time_ps) == 50
        assert len(result.density_gcc) == 50
        assert result.n_total_samples == 50
        assert result.n_window_samples == 20  # 200 ps / 10 ps = 20 samples
        assert result.avg_density == pytest.approx(1.0, rel=0.01)

    def test_calculate_time_series_all_data(self, calculator):
        """Test time series returns all data points."""
        # 100 samples with varying density
        density_values = [1.0 + 0.1 * (i % 5) for i in range(100)]

        result = calculator.calculate_time_series(
            density_values=density_values,
            window_ps=200.0,
            dt_fs=1.0,
            thermo_interval=1000,  # 1 ps per sample
        )

        # Should return ALL data points
        assert len(result.time_ps) == 100
        assert len(result.density_gcc) == 100
        assert result.n_total_samples == 100

    def test_calculate_time_series_time_values(self, calculator):
        """Test time values are calculated correctly."""
        density_values = [1.0] * 10

        result = calculator.calculate_time_series(
            density_values=density_values,
            dt_fs=1.0,
            thermo_interval=10000,  # 10 ps per sample
        )

        # Time should go from 0 to 90 ps (10 samples, 10 ps apart)
        assert result.time_ps[0] == 0.0
        assert result.time_ps[-1] == pytest.approx(90.0, rel=0.01)

    def test_calculate_time_series_window_start(self, calculator):
        """Test window start time is correct."""
        # 100 samples at 1 ps each = 100 ps total
        # Window = 50 ps, so window starts at 50 ps
        density_values = [1.1] * 50 + [1.0] * 50

        result = calculator.calculate_time_series(
            density_values=density_values,
            window_ps=50.0,
            dt_fs=1.0,
            thermo_interval=1000,  # 1 ps per sample
        )

        assert result.window_start_ps == pytest.approx(50.0, rel=0.01)
        assert result.n_window_samples == 50

    def test_calculate_time_series_with_provided_time(self, calculator):
        """Test with externally provided time values."""
        density_values = [1.0, 1.01, 1.02, 1.01, 1.0]
        time_values = [0.0, 100.0, 200.0, 300.0, 400.0]  # Custom time

        result = calculator.calculate_time_series(
            density_values=density_values,
            time_values=time_values,
        )

        assert result.time_ps == time_values
        assert len(result.density_gcc) == 5

    def test_calculate_time_series_empty(self, calculator):
        """Test with empty data."""
        result = calculator.calculate_time_series(density_values=[])

        assert result.time_ps == []
        assert result.density_gcc == []
        assert result.avg_density == 0.0
        assert result.n_total_samples == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
