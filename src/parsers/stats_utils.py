"""
Statistics utilities for thermodynamic data processing.

Provides common window and statistics functions for consistent
data processing across parsers and metrics modules.

SSOT Reference: contracts/policies/tier.py (density_window_ps, dt_fs)
"""

from contracts.policies.tier import DEFAULT_TIER_POLICY

# SSOT defaults from tier policy
_DEFAULT_WINDOW_PS = DEFAULT_TIER_POLICY.convergence_criteria.density_window_ps  # 200.0
_DEFAULT_DT_FS = 1.0  # Default for GAFF2
_DEFAULT_THERMO_INTERVAL = 1000


def apply_time_window(
    values: list[float],
    window_ps: float | None = None,
    dt_fs: float = _DEFAULT_DT_FS,
    thermo_interval: int = _DEFAULT_THERMO_INTERVAL,
    skip_fraction: float | None = None,
) -> list[float]:
    """
    Apply time window to extract relevant portion of time series data.

    Supports two modes:
    - window_ps (preferred): Use the last N ps of data
    - skip_fraction (deprecated): Skip a fraction from the start

    Args:
        values: Input time series data
        window_ps: Time window from end of simulation (ps).
                   If None and skip_fraction is None, uses SSOT default (200 ps).
        dt_fs: Timestep in femtoseconds. Default: 1.0 fs.
        thermo_interval: Steps between thermo outputs. Default: 1000.
        skip_fraction: Deprecated. Fraction of data to skip from start.
                      If provided, uses old behavior for backward compatibility.

    Returns:
        Windowed subset of values

    Examples:
        >>> data = [0.9, 0.95, 1.0, 1.01, 1.02]
        >>> apply_time_window(data, window_ps=200.0, dt_fs=1.0, thermo_interval=1000)
        [1.0, 1.01, 1.02]  # Last 200ps worth of samples
        >>> apply_time_window(data, skip_fraction=0.2)
        [0.95, 1.0, 1.01, 1.02]  # Skip first 20%
    """
    if not values:
        return []

    # Backward compatibility: if skip_fraction provided, use old behavior
    if skip_fraction is not None:
        n_skip = int(len(values) * skip_fraction)
        return values[n_skip:]

    # Default window from SSOT
    if window_ps is None:
        window_ps = _DEFAULT_WINDOW_PS

    # Calculate samples in window
    # ps_per_sample = (dt_fs * thermo_interval) / 1000.0
    # For dt_fs=1.0, thermo_interval=1000: 1ps per sample
    ps_per_sample = (dt_fs * thermo_interval) / 1000.0
    window_samples = int(window_ps / ps_per_sample) if ps_per_sample > 0 else len(values)

    # Return last window_samples from data
    if len(values) > window_samples:
        return values[-window_samples:]
    return values


def compute_mean_std(values: list[float]) -> tuple[float, float]:
    """
    Compute mean and sample standard deviation (Bessel's correction).

    Args:
        values: Input data values

    Returns:
        Tuple of (mean, std). Returns (0.0, 0.0) for empty list.
        Returns (mean, 0.0) for single value.

    Examples:
        >>> compute_mean_std([1.0, 2.0, 3.0, 4.0, 5.0])
        (3.0, 1.5811388300841898)
        >>> compute_mean_std([])
        (0.0, 0.0)
        >>> compute_mean_std([5.0])
        (5.0, 0.0)
    """
    if not values:
        return 0.0, 0.0

    mean = sum(values) / len(values)

    if len(values) < 2:
        return mean, 0.0

    # Bessel's correction: divide by (n-1) for sample std
    variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
    return mean, variance**0.5


def get_default_window_ps() -> float:
    """Get the SSOT default window size in ps."""
    return _DEFAULT_WINDOW_PS


def get_default_dt_fs() -> float:
    """Get the SSOT default timestep in fs."""
    return _DEFAULT_DT_FS


def get_default_thermo_interval() -> int:
    """Get the default thermo output interval in steps."""
    return _DEFAULT_THERMO_INTERVAL
