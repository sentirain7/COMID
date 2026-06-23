"""
Isothermal bulk modulus calculator via NPT volume fluctuations.

    K_T = k_B · T · <V> / (<V²> − <V>²)

No extra simulation is required: the NPT volume time series already
collected for density is reused (RadonPy-style volume-fluctuation method,
cf. PolyJarvis bulk-modulus stage).

The same trailing time window as the density average (tier policy
``density_window_ps``, default 200 ps) is applied so the estimate comes
from the equilibrated portion of the run.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from common.logging import get_logger
from contracts.schemas import MetricResult

logger = get_logger("metrics.bulk_modulus")

_METRIC_NAME = "bulk_modulus"

# Boltzmann constant (J/K) and Å³ → m³ conversion.
_KB_J_PER_K = 1.380649e-23
_A3_TO_M3 = 1.0e-30


@dataclass
class BulkModulusResult:
    """Result from volume-fluctuation bulk modulus estimation."""

    bulk_modulus_gpa: float | None  # Isothermal bulk modulus (GPa)
    mean_volume_A3: float | None = None
    volume_variance_A6: float | None = None
    temperature_K: float | None = None
    n_samples: int = 0
    relative_volume_std: float | None = None  # std(V)/<V>, sanity indicator
    method: str = "npt_volume_fluctuation"
    error: str | None = None


class BulkModulusCalculator:
    """Isothermal bulk modulus from NPT volume fluctuations."""

    def __init__(self, min_samples: int = 50):
        """
        Args:
            min_samples: Minimum windowed volume samples required for a
                statistically meaningful variance estimate.
        """
        self.min_samples = min_samples

    def compute(
        self,
        volume_series_A3: list[float],
        temperature_K: float,
    ) -> BulkModulusResult:
        """Estimate K_T from a windowed NPT volume time series.

        Args:
            volume_series_A3: Volume samples (Å³), already time-windowed.
            temperature_K: Mean temperature over the same window (K).

        Returns:
            BulkModulusResult; ``bulk_modulus_gpa`` is None with ``error``
            set when input is insufficient or degenerate.
        """
        n = len(volume_series_A3)
        if n < self.min_samples:
            return BulkModulusResult(
                bulk_modulus_gpa=None,
                n_samples=n,
                error=f"insufficient volume samples: {n} < {self.min_samples}",
            )
        if temperature_K <= 0:
            return BulkModulusResult(
                bulk_modulus_gpa=None,
                n_samples=n,
                error=f"non-physical temperature: {temperature_K} K",
            )

        vol = np.asarray(volume_series_A3, dtype=float)
        mean_v = float(np.mean(vol))
        var_v = float(np.var(vol))  # population variance, standard for fluctuations

        if mean_v <= 0 or var_v <= 0:
            return BulkModulusResult(
                bulk_modulus_gpa=None,
                mean_volume_A3=mean_v,
                volume_variance_A6=var_v,
                temperature_K=temperature_K,
                n_samples=n,
                error="degenerate volume series (zero mean or variance)",
            )

        # K_T [Pa] = k_B·T·<V> / var(V) with volumes in m³.
        k_t_pa = _KB_J_PER_K * temperature_K * (mean_v * _A3_TO_M3) / (var_v * _A3_TO_M3**2)
        k_t_gpa = k_t_pa / 1.0e9

        return BulkModulusResult(
            bulk_modulus_gpa=k_t_gpa,
            mean_volume_A3=mean_v,
            volume_variance_A6=var_v,
            temperature_K=temperature_K,
            n_samples=n,
            relative_volume_std=float(np.std(vol) / mean_v),
        )

    @staticmethod
    def create_metric(result: BulkModulusResult) -> MetricResult | None:
        """Convert a successful result into a registry MetricResult."""
        if result.bulk_modulus_gpa is None:
            if result.error:
                logger.warning("bulk_modulus skipped: %s", result.error)
            return None
        return MetricResult(
            metric_name=_METRIC_NAME,
            value=result.bulk_modulus_gpa,
            unit="GPa",
            namespace="bulk_ff_gaff2",
        )
