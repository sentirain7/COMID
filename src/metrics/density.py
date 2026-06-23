"""
Density calculator.

Calculates and validates density from simulation data.
"""

from dataclasses import dataclass

from common.logging import get_logger
from contracts.policies.failure import DEFAULT_FAILURE_POLICY
from contracts.schemas import MetricResult
from parsers.stats_utils import (
    apply_time_window,
    compute_mean_std,
    get_default_dt_fs,
    get_default_thermo_interval,
    get_default_window_ps,
)

logger = get_logger("metrics.density")


@dataclass
class DensityTimeSeries:
    """Density time series data."""

    time_ps: list[float]
    density_gcc: list[float]
    avg_density: float
    std_density: float
    window_start_ps: float  # Start of averaging window
    n_total_samples: int
    n_window_samples: int


class DensityCalculator:
    """
    Calculator for density metrics.

    Handles density calculation from various sources and
    validates against expected ranges.
    """

    def __init__(
        self,
        min_density: float = 0.5,
        max_density: float = 2.0,
    ):
        """
        Initialize density calculator.

        Args:
            min_density: Minimum valid density (g/cm³)
            max_density: Maximum valid density (g/cm³)
        """
        self.min_density = min_density
        self.max_density = max_density

    def calculate_from_box(
        self,
        volume_A3: float,
        total_mass_amu: float,
    ) -> float:
        """
        Calculate density from box volume and mass.

        Args:
            volume_A3: Box volume in Angstrom³
            total_mass_amu: Total mass in atomic mass units

        Returns:
            Density in g/cm³
        """
        # Convert A³ to cm³: 1 A³ = 1e-24 cm³
        # Convert amu to g: 1 amu = 1.66054e-24 g
        # density = mass / volume

        volume_cm3 = volume_A3 * 1e-24
        mass_g = total_mass_amu * 1.66054e-24

        if volume_cm3 <= 0:
            return 0.0

        return mass_g / volume_cm3

    def calculate_from_thermo(
        self,
        density_values: list[float],
        window_ps: float | None = None,
        dt_fs: float | None = None,
        thermo_interval: int | None = None,
        skip_fraction: float | None = None,
    ) -> tuple[float, float]:
        """
        Calculate average density from thermo output.

        Uses the last window_ps of NPT data for stable density calculation.
        This avoids contamination from NVT equilibration phase.

        Args:
            density_values: List of density values from thermo
            window_ps: Time window from end of simulation (ps).
                       If None and skip_fraction is None, uses SSOT default (200 ps).
            dt_fs: Timestep in femtoseconds. Default from SSOT.
            thermo_interval: Steps between thermo output. Default: 1000.
            skip_fraction: Deprecated. Fraction of data to skip from start.
                          If provided, uses old behavior for backward compatibility.

        Returns:
            Tuple of (average_density, std_dev)
        """
        if not density_values:
            return 0.0, 0.0

        # Use SSOT defaults
        eff_dt_fs = dt_fs if dt_fs is not None else get_default_dt_fs()
        eff_thermo_interval = (
            thermo_interval if thermo_interval is not None else get_default_thermo_interval()
        )

        # Apply time window using shared utility
        values = apply_time_window(
            density_values,
            window_ps=window_ps,
            dt_fs=eff_dt_fs,
            thermo_interval=eff_thermo_interval,
            skip_fraction=skip_fraction,
        )

        if not values:
            return 0.0, 0.0

        return compute_mean_std(values)

    def calculate_time_series(
        self,
        density_values: list[float],
        time_values: list[float] | None = None,
        window_ps: float | None = None,
        dt_fs: float | None = None,
        thermo_interval: int | None = None,
    ) -> DensityTimeSeries:
        """
        Calculate density statistics and return full time series.

        Args:
            density_values: List of density values from thermo
            time_values: List of time values in ps (optional, calculated if None)
            window_ps: Time window from end for averaging (ps). Default from SSOT.
            dt_fs: Timestep in femtoseconds. Default from SSOT.
            thermo_interval: Steps between thermo output. Default: 1000.

        Returns:
            DensityTimeSeries with full trajectory and statistics
        """
        if not density_values:
            return DensityTimeSeries(
                time_ps=[],
                density_gcc=[],
                avg_density=0.0,
                std_density=0.0,
                window_start_ps=0.0,
                n_total_samples=0,
                n_window_samples=0,
            )

        # Use SSOT defaults
        eff_dt_fs = dt_fs if dt_fs is not None else get_default_dt_fs()
        eff_thermo_interval = (
            thermo_interval if thermo_interval is not None else get_default_thermo_interval()
        )
        eff_window_ps = window_ps if window_ps is not None else get_default_window_ps()

        # Calculate time values if not provided
        ps_per_sample = (eff_dt_fs * eff_thermo_interval) / 1000.0
        if time_values is None:
            time_values = [i * ps_per_sample for i in range(len(density_values))]

        # Apply window using shared utility
        window_values = apply_time_window(
            density_values,
            window_ps=eff_window_ps,
            dt_fs=eff_dt_fs,
            thermo_interval=eff_thermo_interval,
        )

        # Determine window start time
        n_window_samples = len(window_values)
        if len(density_values) > n_window_samples:
            window_start_ps = time_values[-n_window_samples] if time_values else 0.0
        else:
            window_start_ps = time_values[0] if time_values else 0.0

        # Calculate statistics using shared utility
        avg, std = compute_mean_std(window_values)

        return DensityTimeSeries(
            time_ps=list(time_values),
            density_gcc=list(density_values),
            avg_density=avg,
            std_density=std,
            window_start_ps=window_start_ps,
            n_total_samples=len(density_values),
            n_window_samples=n_window_samples,
        )

    def create_metric(
        self,
        density_gcc: float,
        std_dev: float = 0.0,
        temperature_K: float = 298.0,
        pressure_atm: float = 1.0,
        namespace: str = "bulk_ff_gaff2",
        exp_id: str | None = None,
    ) -> MetricResult:
        """
        Create a density MetricResult.

        Args:
            exp_id: Experiment ID
            density_gcc: Density in g/cm³
            std_dev: Standard deviation
            temperature_K: Temperature at which measured
            pressure_atm: Pressure at which measured
            namespace: Metric namespace

        Returns:
            MetricResult for density
        """
        return MetricResult(
            exp_id=exp_id,
            metric_name="density",
            value=density_gcc,
            unit="g/cm3",
            namespace=namespace,
        )

    def is_valid(self, density: float) -> bool:
        """
        Check if density is in valid range.

        Args:
            density: Density in g/cm³

        Returns:
            True if valid
        """
        return self.min_density <= density <= self.max_density

    def check_asphalt_range(self, density: float) -> str:
        """Check if density is in typical asphalt range.

        Args:
            density: Density in g/cm³

        Returns:
            Status string
        """
        _policy = DEFAULT_FAILURE_POLICY
        if density < _policy.asphalt_density_min:
            return "too_low"
        elif density > _policy.asphalt_density_max:
            return "too_high"
        else:
            return "ok"
