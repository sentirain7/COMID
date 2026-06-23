"""
Mean Square Displacement (MSD) calculator.

Computes MSD(t) from atomic trajectories (unwrapped coordinates),
extracts the diffusion coefficient via the Einstein relation,
and produces scalar and array metrics compatible with the registry.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from common.logging import get_logger
from contracts.policies.metrics import MetricsRegistry
from contracts.schemas import ArrayMetricStorage, MetricResult

logger = get_logger("metrics.msd")

# Unit conversion: 1 Å²/ps = 1e-4 cm²/s
_A2_PER_PS_TO_CM2_PER_S = 1.0e-4


@dataclass
class MSDResult:
    """Result from MSD calculation."""

    time_ps: np.ndarray  # lag times (ps)
    msd: np.ndarray  # MSD values (Angstrom²)
    diffusion_coefficient: float | None  # D in cm²/s
    fit_r_squared: float | None  # R² of the linear fit
    fit_start_ps: float | None  # start of linear fit region (ps)
    fit_end_ps: float | None  # end of linear fit region (ps)
    used_unwrapped: bool  # whether unwrapped coords were used


class MSDCalculator:
    """Calculator for Mean Square Displacement and diffusion coefficient.

    Uses the Einstein relation: D = lim(t→∞) MSD(t) / (6t)
    with a linear fit over the diffusive regime.

    Args:
        skip_fraction: Fraction of frames to skip from the start
                       (equilibration period before computing MSD).
        fit_start_frac: Start of linear fit region as fraction of
                        total MSD curve length.
        fit_end_frac: End of linear fit region as fraction of
                      total MSD curve length.
        registry: MetricsRegistry for SSOT name/unit validation.
    """

    def __init__(
        self,
        skip_fraction: float = 0.0,
        fit_start_frac: float = 0.2,
        fit_end_frac: float = 0.8,
        registry: MetricsRegistry | None = None,
    ) -> None:
        self.skip_fraction = skip_fraction
        self.fit_start_frac = fit_start_frac
        self.fit_end_frac = fit_end_frac
        self.registry = registry or MetricsRegistry()

    # ------------------------------------------------------------------
    # Core computation
    # ------------------------------------------------------------------

    def compute(
        self,
        positions_per_frame: list[np.ndarray],
        timesteps: list[int],
        dt_fs: float = 1.0,
        used_unwrapped: bool = True,
    ) -> MSDResult:
        """Compute MSD curve and diffusion coefficient.

        MSD(τ) = <|r(t+τ) - r(t)|²> averaged over atoms and time origins.

        Args:
            positions_per_frame: List of (N, 3) arrays.
                Must be unwrapped coordinates for correct MSD.
            timesteps: Timestep integers per frame.
            dt_fs: Simulation timestep in femtoseconds.
            used_unwrapped: Whether the positions are unwrapped.

        Returns:
            MSDResult with MSD curve and diffusion coefficient.
        """
        n_frames = len(positions_per_frame)
        if n_frames < 2:
            return self._empty_result(used_unwrapped)

        # Skip equilibration frames
        start = int(n_frames * self.skip_fraction)
        if start >= n_frames - 1:
            start = max(0, n_frames - 2)

        positions = positions_per_frame[start:]
        steps = timesteps[start:]
        n_used = len(positions)

        if n_used < 2:
            return self._empty_result(used_unwrapped)

        if not used_unwrapped:
            logger.warning(
                "MSD computed with wrapped coordinates — "
                "diffusion coefficient will be suppressed (unreliable)"
            )

        # Build time axis from timesteps
        # dt between consecutive dumps (in steps)
        step_intervals = np.diff(steps)
        if len(step_intervals) > 0 and np.all(step_intervals == step_intervals[0]):
            dump_interval_steps = int(step_intervals[0])
        else:
            # Non-uniform dump intervals; use median
            dump_interval_steps = int(np.median(step_intervals)) if len(step_intervals) > 0 else 1

        dt_ps = dt_fs * 1e-3  # fs -> ps
        frame_dt_ps = dump_interval_steps * dt_ps

        # Compute MSD for each lag using windowed averaging
        max_lag = n_used - 1
        msd_values = np.zeros(max_lag, dtype=np.float64)
        time_lags = np.arange(1, max_lag + 1, dtype=np.float64) * frame_dt_ps

        for lag in range(1, max_lag + 1):
            # All valid time-origin pairs for this lag
            n_origins = n_used - lag
            displacement_sq_sum = 0.0
            for t0 in range(n_origins):
                delta = positions[t0 + lag] - positions[t0]  # (N, 3)
                displacement_sq_sum += np.mean(np.sum(delta**2, axis=1))
            msd_values[lag - 1] = displacement_sq_sum / n_origins

        # Fit diffusion coefficient from linear region
        diffusion, r_squared, fit_start_ps, fit_end_ps = self._fit_diffusion(time_lags, msd_values)

        # Suppress diffusion coefficient when using wrapped coordinates
        # (wrapped MSD plateaus at ~L²/6, producing a physically meaningless D)
        if not used_unwrapped:
            diffusion = None

        return MSDResult(
            time_ps=time_lags,
            msd=msd_values,
            diffusion_coefficient=diffusion,
            fit_r_squared=r_squared,
            fit_start_ps=fit_start_ps,
            fit_end_ps=fit_end_ps,
            used_unwrapped=used_unwrapped,
        )

    # ------------------------------------------------------------------
    # Diffusion coefficient fitting
    # ------------------------------------------------------------------

    def _fit_diffusion(
        self,
        time_ps: np.ndarray,
        msd: np.ndarray,
    ) -> tuple[float | None, float | None, float | None, float | None]:
        """Fit diffusion coefficient from MSD linear region.

        Einstein relation: MSD = 6 * D * t  (3D)
        => D = slope / 6

        Args:
            time_ps: Lag time array (ps).
            msd: MSD array (Angstrom²).

        Returns:
            (D in cm²/s, R², fit_start_ps, fit_end_ps) or all None.
        """
        n = len(time_ps)
        if n < 3:
            return None, None, None, None

        # Determine fit window
        i_start = max(1, int(n * self.fit_start_frac))
        i_end = min(n, int(n * self.fit_end_frac))
        if i_end <= i_start + 1:
            i_end = min(n, i_start + 2)

        t_fit = time_ps[i_start:i_end]
        msd_fit = msd[i_start:i_end]

        if len(t_fit) < 2:
            return None, None, None, None

        # Linear fit: MSD = slope * t + intercept
        coeffs = np.polyfit(t_fit, msd_fit, 1)
        slope = coeffs[0]  # Å²/ps

        # R² calculation
        msd_pred = np.polyval(coeffs, t_fit)
        ss_res = np.sum((msd_fit - msd_pred) ** 2)
        ss_tot = np.sum((msd_fit - np.mean(msd_fit)) ** 2)
        r_squared = float(1.0 - ss_res / ss_tot) if ss_tot > 0 else 0.0

        # D = slope / 6 (Einstein, 3D), convert units
        if slope <= 0:
            logger.warning(f"Negative MSD slope ({slope:.4g} Å²/ps) — D set to None")
            return None, r_squared, float(t_fit[0]), float(t_fit[-1])

        d_a2_per_ps = slope / 6.0
        d_cm2_per_s = d_a2_per_ps * _A2_PER_PS_TO_CM2_PER_S

        return (
            float(d_cm2_per_s),
            float(r_squared),
            float(t_fit[0]),
            float(t_fit[-1]),
        )

    # ------------------------------------------------------------------
    # Metric creation (registry-based SSOT)
    # ------------------------------------------------------------------

    _SCALAR_METRIC_NAME = "msd_diffusion_coefficient"
    _ARRAY_METRIC_NAME = "msd_curve"

    def create_scalar_metric(
        self,
        result: MSDResult,
        namespace: str = "bulk_ff_gaff2",
    ) -> MetricResult | None:
        """Create scalar MetricResult for diffusion coefficient.

        Args:
            result: MSD calculation result.
            namespace: Metric namespace.

        Returns:
            MetricResult or None if D not available.
        """
        if result.diffusion_coefficient is None:
            return None

        name = self._SCALAR_METRIC_NAME
        is_valid, error = self.registry.validate_metric(
            name=name,
            unit=self.registry.get_unit(name),
            namespace=namespace,
        )
        if not is_valid:
            logger.warning(f"Registry validation failed for {name}: {error}")
            return None

        return MetricResult(
            metric_name=name,
            value=result.diffusion_coefficient,
            unit=self.registry.get_unit(name),
            namespace=namespace,
        )

    def create_array_metric(
        self,
        result: MSDResult,
        array_storage: ArrayMetricStorage,
        namespace: str = "bulk_ff_gaff2",
    ) -> MetricResult:
        """Create array MetricResult for the MSD curve.

        Args:
            result: MSD calculation result.
            array_storage: Storage descriptor from ArrayStorage.store_metric().
            namespace: Metric namespace.

        Returns:
            MetricResult for msd_curve.
        """
        summary: dict[str, float] = {}
        if result.diffusion_coefficient is not None:
            summary["diffusion_coefficient_cm2s"] = result.diffusion_coefficient
        if result.fit_r_squared is not None:
            summary["fit_r_squared"] = result.fit_r_squared

        name = self._ARRAY_METRIC_NAME
        return MetricResult(
            metric_name=name,
            value=None,
            unit=self.registry.get_unit(name),
            namespace=namespace,
            array_storage=array_storage,
            array_summary=summary,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _empty_result(self, used_unwrapped: bool = True) -> MSDResult:
        return MSDResult(
            time_ps=np.array([], dtype=np.float64),
            msd=np.array([], dtype=np.float64),
            diffusion_coefficient=None,
            fit_r_squared=None,
            fit_start_ps=None,
            fit_end_ps=None,
            used_unwrapped=used_unwrapped,
        )
