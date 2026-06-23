"""
Replicate statistics — aggregate seed replicates with CI and hypothesis testing.

Provides mean/std/CI calculation for n replicate measurements
and Welch's t-test for comparing two groups (e.g. additive vs control).

Reference: Allen & Tildesley (2017), Montgomery (2017)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from contracts.policies.replicate import DEFAULT_REPLICATE_POLICY, ReplicatePolicy


@dataclass
class AggregateResult:
    """Result of aggregating replicate measurements.

    Attributes:
        metric_name: Name of the metric
        values: Raw replicate values
        n: Number of replicates
        mean: Arithmetic mean (ensemble average over replicates)
        std: Sample standard deviation (ddof=1)
        standard_error: Standard error of the mean (SEM = std / sqrt(n))
        ci_lower: Lower bound of confidence interval
        ci_upper: Upper bound of confidence interval
        ci_level: Confidence level used (e.g. 0.95)
    """

    metric_name: str
    values: list[float]
    n: int
    mean: float
    std: float
    standard_error: float
    ci_lower: float
    ci_upper: float
    ci_level: float = 0.95


@dataclass
class TTestResult:
    """Result of Welch's t-test between two groups.

    Attributes:
        metric_name: Name of the metric compared
        group_a: Aggregate of group A (e.g. additive)
        group_b: Aggregate of group B (e.g. control)
        delta_mean: Difference in means (A - B)
        delta_ci_lower: Lower bound of delta CI
        delta_ci_upper: Upper bound of delta CI
        t_statistic: Welch's t statistic
        df: Degrees of freedom (Welch-Satterthwaite)
        p_value: Two-tailed p-value
        significant: Whether p < alpha
        significance_stars: Star notation (*, **, ***)
    """

    metric_name: str
    group_a: AggregateResult
    group_b: AggregateResult
    delta_mean: float
    delta_ci_lower: float
    delta_ci_upper: float
    t_statistic: float
    df: float
    p_value: float
    significant: bool
    significance_stars: str = ""


# ── t-distribution critical values (two-tailed, selected df) ──
# Pre-computed for 95% CI to avoid scipy dependency.
# For df not in table, linear interpolation is used.
_T_CRITICAL_95: dict[int, float] = {
    1: 12.706,
    2: 4.303,
    3: 3.182,
    4: 2.776,
    5: 2.571,
    6: 2.447,
    7: 2.365,
    8: 2.306,
    9: 2.262,
    10: 2.228,
    12: 2.179,
    15: 2.131,
    20: 2.086,
    25: 2.060,
    30: 2.042,
    40: 2.021,
    60: 2.000,
    120: 1.980,
}

_T_CRITICAL_99: dict[int, float] = {
    1: 63.657,
    2: 9.925,
    3: 5.841,
    4: 4.604,
    5: 4.032,
    6: 3.707,
    7: 3.499,
    8: 3.355,
    9: 3.250,
    10: 3.169,
    12: 3.055,
    15: 2.947,
    20: 2.845,
    25: 2.787,
    30: 2.750,
    40: 2.704,
    60: 2.660,
    120: 2.617,
}

_T_CRITICAL_999: dict[int, float] = {
    1: 636.619,
    2: 31.599,
    3: 12.924,
    4: 8.610,
    5: 6.869,
    6: 5.959,
    7: 5.408,
    8: 5.041,
    9: 4.781,
    10: 4.587,
    12: 4.318,
    15: 4.073,
    20: 3.850,
    25: 3.725,
    30: 3.646,
    40: 3.551,
    60: 3.460,
    120: 3.373,
}


def _lookup_t_critical(df: float, table: dict[int, float]) -> float:
    """Look up t-critical value with interpolation.

    Args:
        df: Degrees of freedom (can be fractional from Welch-Satterthwaite)
        table: t-critical value table

    Returns:
        Interpolated t-critical value
    """
    sorted_keys = sorted(table.keys())
    min_df = float(sorted_keys[0])
    max_df = float(sorted_keys[-1])

    # Clamp to tabulated range
    if df <= min_df:
        return table[sorted_keys[0]]
    if df >= max_df:
        return table[sorted_keys[-1]]

    # Exact match for integer df
    if float(df).is_integer() and int(df) in table:
        return table[int(df)]

    # Linear interpolation for non-tabulated (including fractional) df
    lower_df = sorted_keys[0]
    upper_df = sorted_keys[-1]
    for i in range(len(sorted_keys) - 1):
        lo = sorted_keys[i]
        hi = sorted_keys[i + 1]
        if lo <= df <= hi:
            lower_df = lo
            upper_df = hi
            break

    t_lower = table[lower_df]
    t_upper = table[upper_df]

    if upper_df == lower_df:
        return t_lower

    fraction = (df - lower_df) / (upper_df - lower_df)
    return t_lower + fraction * (t_upper - t_lower)


def _t_critical_two_tailed(df: float, alpha: float = 0.05) -> float:
    """Get two-tailed t-critical value.

    Args:
        df: Degrees of freedom
        alpha: Significance level (0.05, 0.01, or 0.001)

    Returns:
        t-critical value for two-tailed test
    """
    if alpha <= 0.001:
        return _lookup_t_critical(df, _T_CRITICAL_999)
    elif alpha <= 0.01:
        return _lookup_t_critical(df, _T_CRITICAL_99)
    else:
        return _lookup_t_critical(df, _T_CRITICAL_95)


@dataclass
class ReplicateAggregator:
    """Aggregate seed replicate measurements with CI and hypothesis testing.

    Args:
        policy: ReplicatePolicy for configuration (defaults to global)
    """

    policy: ReplicatePolicy = field(default_factory=lambda: DEFAULT_REPLICATE_POLICY)

    def aggregate(
        self,
        metric_name: str,
        values: list[float],
        ci_level: float | None = None,
    ) -> AggregateResult:
        """Compute mean, std, and confidence interval for replicate values.

        Args:
            metric_name: Name of the metric
            values: List of replicate measurement values
            ci_level: Confidence level override (default: policy ci_level)

        Returns:
            AggregateResult with statistics

        Raises:
            ValueError: If fewer than 1 value is provided
        """
        if len(values) == 0:
            raise ValueError(f"No values provided for metric '{metric_name}'")

        n = len(values)
        level = ci_level if ci_level is not None else self.policy.ci_level

        mean = sum(values) / n

        if n == 1:
            # Single replicate: mean is the value; std/SE are undefined but
            # reported as 0.0 so downstream always receives mean + SE fields.
            return AggregateResult(
                metric_name=metric_name,
                values=list(values),
                n=n,
                mean=mean,
                std=0.0,
                standard_error=0.0,
                ci_lower=mean,
                ci_upper=mean,
                ci_level=level,
            )

        # Sample standard deviation (ddof=1)
        variance = sum((x - mean) ** 2 for x in values) / (n - 1)
        std = math.sqrt(variance)

        # Standard error of the mean (SEM = std / sqrt(n))
        se = std / math.sqrt(n)

        # t-critical for CI
        df = n - 1
        alpha = 1.0 - level
        t_crit = _t_critical_two_tailed(df, alpha)

        margin = t_crit * se

        return AggregateResult(
            metric_name=metric_name,
            values=list(values),
            n=n,
            mean=mean,
            std=std,
            standard_error=se,
            ci_lower=mean - margin,
            ci_upper=mean + margin,
            ci_level=level,
        )

    def welch_ttest(
        self,
        metric_name: str,
        group_a_values: list[float],
        group_b_values: list[float],
        alpha: float | None = None,
    ) -> TTestResult:
        """Perform Welch's t-test comparing two independent groups.

        Tests H0: mean(A) == mean(B) vs H1: mean(A) != mean(B).

        Args:
            metric_name: Name of the metric
            group_a_values: Values from group A (e.g. with additive)
            group_b_values: Values from group B (e.g. control)
            alpha: Significance level override (default: policy alpha)

        Returns:
            TTestResult with test statistics and significance

        Raises:
            ValueError: If either group has fewer than 2 values
        """
        n_a = len(group_a_values)
        n_b = len(group_b_values)

        if n_a < 2 or n_b < 2:
            raise ValueError(
                f"Welch's t-test requires at least 2 values per group. Got n_a={n_a}, n_b={n_b}"
            )

        sig_alpha = alpha if alpha is not None else self.policy.significance_alpha

        agg_a = self.aggregate(metric_name, group_a_values)
        agg_b = self.aggregate(metric_name, group_b_values)

        delta_mean = agg_a.mean - agg_b.mean

        var_a = agg_a.std**2
        var_b = agg_b.std**2

        # Welch-Satterthwaite degrees of freedom
        se_a = var_a / n_a
        se_b = var_b / n_b
        se_combined = math.sqrt(se_a + se_b)

        if se_combined == 0.0:
            # Both groups have zero variance — means are either equal or not
            return TTestResult(
                metric_name=metric_name,
                group_a=agg_a,
                group_b=agg_b,
                delta_mean=delta_mean,
                delta_ci_lower=delta_mean,
                delta_ci_upper=delta_mean,
                t_statistic=0.0 if delta_mean == 0.0 else float("inf"),
                df=float(n_a + n_b - 2),
                p_value=1.0 if delta_mean == 0.0 else 0.0,
                significant=delta_mean != 0.0,
                significance_stars="***" if delta_mean != 0.0 else "",
            )

        t_stat = delta_mean / se_combined

        # Welch-Satterthwaite df
        numerator = (se_a + se_b) ** 2
        denominator = (se_a**2 / (n_a - 1)) + (se_b**2 / (n_b - 1))
        df = numerator / denominator if denominator > 0 else float(n_a + n_b - 2)

        # Approximate two-tailed p-value using t-distribution tables
        p_value = self._approximate_p_value(abs(t_stat), df)

        # Delta CI
        t_crit_delta = _t_critical_two_tailed(df, sig_alpha)
        margin = t_crit_delta * se_combined
        delta_ci_lower = delta_mean - margin
        delta_ci_upper = delta_mean + margin

        # Significance stars
        stars = ""
        if p_value < 0.001:
            stars = "***"
        elif p_value < 0.01:
            stars = "**"
        elif p_value < 0.05:
            stars = "*"

        return TTestResult(
            metric_name=metric_name,
            group_a=agg_a,
            group_b=agg_b,
            delta_mean=delta_mean,
            delta_ci_lower=delta_ci_lower,
            delta_ci_upper=delta_ci_upper,
            t_statistic=t_stat,
            df=df,
            p_value=p_value,
            significant=p_value < sig_alpha,
            significance_stars=stars,
        )

    @staticmethod
    def _approximate_p_value(t_abs: float, df: float) -> float:
        """Approximate two-tailed p-value from |t| and df.

        Uses pre-computed critical value tables to bracket the p-value.
        This avoids scipy dependency while giving useful significance bins.

        Args:
            t_abs: Absolute value of t-statistic
            df: Degrees of freedom

        Returns:
            Approximate p-value (conservative estimate)
        """
        # Check against critical values at standard alpha levels
        t_05 = _t_critical_two_tailed(df, 0.05)
        t_01 = _t_critical_two_tailed(df, 0.01)
        t_001 = _t_critical_two_tailed(df, 0.001)

        if t_abs >= t_001:
            return 0.0005  # p < 0.001
        elif t_abs >= t_01:
            return 0.005  # p < 0.01
        elif t_abs >= t_05:
            return 0.025  # p < 0.05
        else:
            # Not significant at 0.05 level — rough linear interpolation
            if t_05 > 0:
                ratio = t_abs / t_05
                return max(0.05, 1.0 - ratio * 0.95)
            return 1.0


def aggregate_replicates(
    metric_name: str,
    values: list[float],
    ci_level: float | None = None,
    policy: ReplicatePolicy | None = None,
) -> AggregateResult:
    """Aggregate seed-replicate measurements into mean + standard error (+CI).

    Recommended default for reporting ensemble metrics: with the default
    ``DEFAULT_REPLICATE_POLICY`` and no extra configuration, this yields an
    ``AggregateResult`` carrying the ensemble ``mean`` and ``standard_error``
    (SEM = std/sqrt(n)) out of the box. A single replicate still returns a
    valid result (std = SE = 0.0).

    Args:
        metric_name: Name of the metric being aggregated.
        values: Replicate measurement values (one per independent seed).
        ci_level: Confidence level override (default: policy ci_level).
        policy: ReplicatePolicy override (default: DEFAULT_REPLICATE_POLICY).

    Returns:
        AggregateResult with mean, std, standard_error, and CI.
    """
    aggregator = ReplicateAggregator(policy=policy or DEFAULT_REPLICATE_POLICY)
    return aggregator.aggregate(metric_name, values, ci_level=ci_level)
