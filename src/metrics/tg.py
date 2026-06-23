"""
Glass transition temperature (Tg) calculator via bilinear fitting.

Computes Tg from density-temperature data across multiple experiments:
    ρ(T) = a₁·(T - Tg) + ρ_g    for T ≤ Tg   (glassy)
    ρ(T) = a₂·(T - Tg) + ρ_g    for T > Tg    (rubbery)

The breakpoint Tg is found by grid search over candidate temperatures,
selecting the value that minimises total residual sum of squares.
Bootstrap resampling provides a confidence interval.

Reference: Simha & Boyer (1962), standard MD protocol.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np

from common.logging import get_logger
from common.numpy_compat import RankWarning
from contracts.policies.metrics import MetricsRegistry
from contracts.schemas import MetricResult

logger = get_logger("metrics.tg")

_METRIC_NAME = "glass_transition_temperature_k"


@dataclass
class TgResult:
    """Result from Tg bilinear fitting."""

    tg_k: float | None  # Glass transition temperature (K)
    tg_ci_lower_k: float | None = None  # Bootstrap CI lower bound
    tg_ci_upper_k: float | None = None  # Bootstrap CI upper bound
    slope_glassy: float | None = None  # dρ/dT below Tg (g/cm3/K)
    slope_rubbery: float | None = None  # dρ/dT above Tg (g/cm3/K)
    density_at_tg: float | None = None  # ρ(Tg) (g/cm3)
    r_squared: float | None = None  # Overall R² of bilinear fit
    r_squared_glassy: float | None = None  # R² of low-T segment
    r_squared_rubbery: float | None = None  # R² of high-T segment
    n_points: int = 0  # Number of data points used
    n_temperatures: int = 0  # Number of distinct temperatures
    bootstrap_n: int = 0  # Bootstrap iterations performed
    method: str = "bilinear_breakpoint"
    error: str | None = None


@dataclass
class DensityTemperaturePoint:
    """A single (T, ρ) observation from an experiment."""

    temperature_k: float
    density_gcc: float
    exp_id: str = ""


class TgCalculator:
    """Calculator for glass transition temperature via bilinear fitting.

    Args:
        min_points_per_segment: Minimum data points per linear segment.
        grid_steps: Number of candidate breakpoints in the grid search.
        bootstrap_n: Number of bootstrap iterations for CI.
        confidence_level: Confidence level for bootstrap CI (e.g. 0.95).
        registry: MetricsRegistry for SSOT name/unit validation.
    """

    def __init__(
        self,
        min_points_per_segment: int = 2,
        grid_steps: int = 200,
        bootstrap_n: int = 1000,
        confidence_level: float = 0.95,
        registry: MetricsRegistry | None = None,
    ) -> None:
        self.min_points_per_segment = min_points_per_segment
        self.grid_steps = grid_steps
        self.bootstrap_n = bootstrap_n
        self.confidence_level = confidence_level
        self.registry = registry or MetricsRegistry()

    # ------------------------------------------------------------------
    # Core computation
    # ------------------------------------------------------------------

    def compute(
        self,
        points: list[DensityTemperaturePoint],
    ) -> TgResult:
        """Compute Tg from density-temperature data.

        Args:
            points: List of (T, ρ) observations. May include
                multiple observations per temperature (different seeds).

        Returns:
            TgResult with Tg and fit diagnostics.
        """
        if len(points) < 2 * self.min_points_per_segment:
            return TgResult(
                tg_k=None,
                n_points=len(points),
                n_temperatures=len({p.temperature_k for p in points}),
                error=f"Insufficient data points ({len(points)} < {2 * self.min_points_per_segment})",
            )

        temperatures = np.array([p.temperature_k for p in points], dtype=np.float64)
        densities = np.array([p.density_gcc for p in points], dtype=np.float64)

        # Remove NaN/Inf
        valid = np.isfinite(temperatures) & np.isfinite(densities)
        if valid.sum() < 2 * self.min_points_per_segment:
            return TgResult(
                tg_k=None,
                n_points=int(valid.sum()),
                n_temperatures=len(set(temperatures[valid])),
                error="Insufficient valid (non-NaN) data points",
            )
        temperatures = temperatures[valid]
        densities = densities[valid]

        n_unique_temps = len(set(temperatures))
        if n_unique_temps < 2 * self.min_points_per_segment:
            return TgResult(
                tg_k=None,
                n_points=len(temperatures),
                n_temperatures=n_unique_temps,
                error=f"Insufficient distinct temperatures ({n_unique_temps})",
            )

        # Grid search for optimal breakpoint
        tg_opt, fit_info = self._grid_search(temperatures, densities)
        if tg_opt is None:
            return TgResult(
                tg_k=None,
                n_points=len(temperatures),
                n_temperatures=n_unique_temps,
                error="Bilinear fit failed — no valid breakpoint found",
            )

        # Bootstrap CI
        ci_lower, ci_upper = self._bootstrap_ci(temperatures, densities)

        return TgResult(
            tg_k=float(tg_opt),
            tg_ci_lower_k=ci_lower,
            tg_ci_upper_k=ci_upper,
            slope_glassy=fit_info["slope_low"],
            slope_rubbery=fit_info["slope_high"],
            density_at_tg=fit_info["density_at_tg"],
            r_squared=fit_info["r2_total"],
            r_squared_glassy=fit_info["r2_low"],
            r_squared_rubbery=fit_info["r2_high"],
            n_points=len(temperatures),
            n_temperatures=n_unique_temps,
            bootstrap_n=self.bootstrap_n,
        )

    # ------------------------------------------------------------------
    # Grid search
    # ------------------------------------------------------------------

    def _grid_search(
        self,
        temperatures: np.ndarray,
        densities: np.ndarray,
    ) -> tuple[float | None, dict]:
        """Find optimal breakpoint by grid search.

        Returns:
            (breakpoint_T, fit_info_dict) or (None, {}).
        """
        t_min, t_max = temperatures.min(), temperatures.max()
        # Ensure at least min_points on each side
        sorted_t = np.sort(np.unique(temperatures))
        if len(sorted_t) < 2 * self.min_points_per_segment:
            return None, {}

        # Candidate range: must leave min_points on each side
        # Use midpoints between adjacent unique temperatures as boundaries
        lo_idx = self.min_points_per_segment - 1
        hi_idx = len(sorted_t) - self.min_points_per_segment
        if lo_idx >= hi_idx:
            # Tight case: try midpoint between the two middle temperatures
            mid = len(sorted_t) // 2
            if mid > 0 and mid < len(sorted_t):
                t_lo = (sorted_t[mid - 1] + sorted_t[mid]) / 2.0
                t_hi = t_lo  # single candidate
            else:
                return None, {}
        else:
            t_lo = (sorted_t[lo_idx] + sorted_t[lo_idx + 1]) / 2.0
            t_hi = (sorted_t[hi_idx - 1] + sorted_t[hi_idx]) / 2.0

        if t_lo > t_hi:
            return None, {}

        candidates = np.linspace(t_lo, t_hi, self.grid_steps)
        best_sse = np.inf
        best_tg: float | None = None
        best_info: dict = {}

        for tg_cand in candidates:
            info = self._fit_bilinear(temperatures, densities, tg_cand)
            if info is not None and info["sse"] < best_sse:
                best_sse = info["sse"]
                best_tg = tg_cand
                best_info = info

        # Refine: compute intersection of the two fitted lines
        # ρ = a₁·T + b₁  and  ρ = a₂·T + b₂  → T_intersect = (b₁-b₂)/(a₂-a₁)
        if best_info and best_tg is not None:
            a1 = best_info["slope_low"]
            b1 = best_info["intercept_low"]
            a2 = best_info["slope_high"]
            b2 = best_info["intercept_high"]
            denom = a2 - a1
            if abs(denom) > 1e-30:
                t_intersect = (b1 - b2) / denom
                # Only accept if intersection is within data range
                if t_min <= t_intersect <= t_max:
                    # Re-fit at the intersection point for updated stats
                    refined_info = self._fit_bilinear(
                        temperatures,
                        densities,
                        t_intersect,
                    )
                    if refined_info is not None:
                        best_tg = t_intersect
                        best_info = refined_info

        return best_tg, best_info

    # ------------------------------------------------------------------
    # Bilinear fit for a given breakpoint
    # ------------------------------------------------------------------

    def _fit_bilinear(
        self,
        temperatures: np.ndarray,
        densities: np.ndarray,
        tg: float,
    ) -> dict | None:
        """Fit two independent linear segments at a fixed breakpoint.

        Returns dict with slopes, intercepts, SSE, R² values, or None.
        """
        mask_low = temperatures <= tg
        mask_high = temperatures > tg

        n_low = mask_low.sum()
        n_high = mask_high.sum()
        if n_low < self.min_points_per_segment or n_high < self.min_points_per_segment:
            return None

        # Low segment fit
        try:
            coeffs_low = np.polyfit(temperatures[mask_low], densities[mask_low], 1)
        except (np.linalg.LinAlgError, ValueError):
            return None

        # High segment fit
        try:
            coeffs_high = np.polyfit(temperatures[mask_high], densities[mask_high], 1)
        except (np.linalg.LinAlgError, ValueError):
            return None

        # Predictions
        pred_low = np.polyval(coeffs_low, temperatures[mask_low])
        pred_high = np.polyval(coeffs_high, temperatures[mask_high])

        # SSE
        sse_low = float(np.sum((densities[mask_low] - pred_low) ** 2))
        sse_high = float(np.sum((densities[mask_high] - pred_high) ** 2))
        sse_total = sse_low + sse_high

        # R² per segment
        r2_low = self._r_squared(densities[mask_low], pred_low)
        r2_high = self._r_squared(densities[mask_high], pred_high)

        # Overall R²
        all_pred = np.concatenate([pred_low, pred_high])
        all_actual = np.concatenate([densities[mask_low], densities[mask_high]])
        r2_total = self._r_squared(all_actual, all_pred)

        # Density at Tg (average of both line extrapolations)
        rho_low_at_tg = float(np.polyval(coeffs_low, tg))
        rho_high_at_tg = float(np.polyval(coeffs_high, tg))
        density_at_tg = (rho_low_at_tg + rho_high_at_tg) / 2.0

        return {
            "slope_low": float(coeffs_low[0]),
            "slope_high": float(coeffs_high[0]),
            "intercept_low": float(coeffs_low[1]),
            "intercept_high": float(coeffs_high[1]),
            "density_at_tg": density_at_tg,
            "sse": sse_total,
            "r2_low": r2_low,
            "r2_high": r2_high,
            "r2_total": r2_total,
        }

    # ------------------------------------------------------------------
    # Bootstrap confidence interval
    # ------------------------------------------------------------------

    def _bootstrap_ci(
        self,
        temperatures: np.ndarray,
        densities: np.ndarray,
    ) -> tuple[float | None, float | None]:
        """Bootstrap CI for the breakpoint.

        Returns:
            (ci_lower, ci_upper) or (None, None) if bootstrap fails.
        """
        if self.bootstrap_n <= 0:
            return None, None

        n = len(temperatures)
        rng = np.random.default_rng(seed=42)
        tg_samples: list[float] = []

        for _ in range(self.bootstrap_n):
            idx = rng.choice(n, size=n, replace=True)
            t_boot = temperatures[idx]
            d_boot = densities[idx]

            # Need enough unique temperatures in each sample
            if len(set(t_boot)) < 2 * self.min_points_per_segment:
                continue

            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RankWarning)
                tg_boot, _ = self._grid_search(t_boot, d_boot)
            if tg_boot is not None:
                tg_samples.append(tg_boot)

        if len(tg_samples) < 10:
            return None, None

        alpha = (1.0 - self.confidence_level) / 2.0
        ci_lower = float(np.percentile(tg_samples, 100 * alpha))
        ci_upper = float(np.percentile(tg_samples, 100 * (1 - alpha)))
        return ci_lower, ci_upper

    # ------------------------------------------------------------------
    # Metric creation (SSOT)
    # ------------------------------------------------------------------

    def create_metric(
        self,
        result: TgResult,
        namespace: str = "bulk_ff_gaff2",
    ) -> MetricResult | None:
        """Create MetricResult for Tg.

        Args:
            result: Tg calculation result.
            namespace: Metric namespace.

        Returns:
            MetricResult or None if Tg not available.
        """
        if result.tg_k is None:
            return None

        name = _METRIC_NAME
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
            value=result.tg_k,
            unit=self.registry.get_unit(name),
            namespace=namespace,
        )

    # ------------------------------------------------------------------
    # Metadata for experiment record
    # ------------------------------------------------------------------

    @staticmethod
    def get_metadata(result: TgResult) -> dict[str, str | float | None]:
        """Build metadata dict for Tg calculation status.

        Args:
            result: Tg calculation result.

        Returns:
            Metadata dict suitable for experiment/batch-job record.
        """
        meta: dict[str, str | float | None] = {
            "tg_method": result.method,
            "tg_parse_status": ("success" if result.tg_k is not None else "failed"),
        }
        if result.error:
            meta["tg_error"] = result.error
        if result.tg_k is not None:
            meta["tg_k"] = result.tg_k
        if result.tg_ci_lower_k is not None:
            meta["tg_ci_lower_k"] = result.tg_ci_lower_k
        if result.tg_ci_upper_k is not None:
            meta["tg_ci_upper_k"] = result.tg_ci_upper_k
        if result.slope_glassy is not None:
            meta["tg_slope_glassy"] = result.slope_glassy
        if result.slope_rubbery is not None:
            meta["tg_slope_rubbery"] = result.slope_rubbery
        if result.r_squared is not None:
            meta["tg_r2_total"] = result.r_squared
        if result.n_points:
            meta["tg_n_points"] = result.n_points
        if result.n_temperatures:
            meta["tg_n_temperatures"] = result.n_temperatures
        return meta

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _r_squared(actual: np.ndarray, predicted: np.ndarray) -> float:
        """Compute R² (coefficient of determination)."""
        ss_res = float(np.sum((actual - predicted) ** 2))
        ss_tot = float(np.sum((actual - np.mean(actual)) ** 2))
        if ss_tot == 0:
            return 0.0
        return 1.0 - ss_res / ss_tot
