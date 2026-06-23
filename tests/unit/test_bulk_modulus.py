"""Tests for the NPT volume-fluctuation bulk modulus calculator (v01.05.02)."""

from __future__ import annotations

import numpy as np
import pytest

from contracts.policies.metrics import DEFAULT_METRICS_REGISTRY
from metrics.bulk_modulus import BulkModulusCalculator

_KB = 1.380649e-23
_A3_TO_M3 = 1.0e-30


def _synthetic_volume_series(mean_A3: float, std_A3: float, n: int, seed: int = 42) -> list[float]:
    rng = np.random.default_rng(seed)
    return list(rng.normal(mean_A3, std_A3, size=n))


class TestBulkModulusCompute:
    def test_known_fluctuation_recovers_expected_kt(self) -> None:
        """K_T computed from the series must match the analytic formula."""
        calc = BulkModulusCalculator(min_samples=50)
        series = _synthetic_volume_series(mean_A3=1.0e6, std_A3=1.0e3, n=2000)
        temperature = 298.0

        result = calc.compute(series, temperature_K=temperature)

        assert result.error is None
        assert result.bulk_modulus_gpa is not None
        vol = np.asarray(series)
        expected_pa = _KB * temperature * (vol.mean() * _A3_TO_M3) / (vol.var() * _A3_TO_M3**2)
        assert result.bulk_modulus_gpa == pytest.approx(expected_pa / 1e9, rel=1e-9)
        # Asphalt-like NPT cells land in the O(0.1–10) GPa range here.
        assert 0.01 < result.bulk_modulus_gpa < 100.0

    def test_larger_fluctuations_mean_softer_material(self) -> None:
        calc = BulkModulusCalculator(min_samples=50)
        stiff = calc.compute(_synthetic_volume_series(1.0e6, 5.0e2, 1000), temperature_K=298.0)
        soft = calc.compute(_synthetic_volume_series(1.0e6, 5.0e3, 1000), temperature_K=298.0)
        assert stiff.bulk_modulus_gpa > soft.bulk_modulus_gpa

    def test_insufficient_samples_fails_closed(self) -> None:
        calc = BulkModulusCalculator(min_samples=50)
        result = calc.compute([1.0e6] * 10, temperature_K=298.0)
        assert result.bulk_modulus_gpa is None
        assert "insufficient" in result.error

    def test_non_physical_temperature_fails_closed(self) -> None:
        calc = BulkModulusCalculator(min_samples=10)
        result = calc.compute([1.0e6 + i for i in range(20)], temperature_K=0.0)
        assert result.bulk_modulus_gpa is None
        assert "temperature" in result.error

    def test_zero_variance_fails_closed(self) -> None:
        calc = BulkModulusCalculator(min_samples=10)
        result = calc.compute([1.0e6] * 100, temperature_K=298.0)
        assert result.bulk_modulus_gpa is None
        assert "degenerate" in result.error


class TestBulkModulusMetric:
    def test_create_metric_round_trip(self) -> None:
        calc = BulkModulusCalculator(min_samples=50)
        result = calc.compute(_synthetic_volume_series(1.0e6, 1.0e3, 500), temperature_K=298.0)
        metric = calc.create_metric(result)
        assert metric is not None
        assert metric.metric_name == "bulk_modulus"
        assert metric.unit == "GPa"
        assert metric.namespace == "bulk_ff_gaff2"

    def test_failed_result_yields_no_metric(self) -> None:
        calc = BulkModulusCalculator(min_samples=50)
        result = calc.compute([], temperature_K=298.0)
        assert calc.create_metric(result) is None

    def test_registered_in_metrics_registry(self) -> None:
        assert DEFAULT_METRICS_REGISTRY.is_valid_metric("bulk_modulus")
        assert DEFAULT_METRICS_REGISTRY.get_unit("bulk_modulus") == "GPa"
