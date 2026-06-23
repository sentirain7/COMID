"""Unit tests for ReplicateAggregator (mean/std/CI/Welch's t-test)."""

import math

import pytest

from metrics.statistics import (
    _T_CRITICAL_95,
    AggregateResult,
    ReplicateAggregator,
    TTestResult,
    _lookup_t_critical,
)


@pytest.fixture
def aggregator():
    """Create a default ReplicateAggregator."""
    return ReplicateAggregator()


# ── Aggregate tests ──────────────────────────────────────────────


class TestAggregate:
    """Tests for ReplicateAggregator.aggregate()."""

    def test_single_value(self, aggregator):
        """Single value: mean=value, std=0, CI=[value, value]."""
        result = aggregator.aggregate("density", [1.05])
        assert result.n == 1
        assert result.mean == 1.05
        assert result.std == 0.0
        assert result.ci_lower == 1.05
        assert result.ci_upper == 1.05

    def test_two_values_mean(self, aggregator):
        """Two values: correct mean."""
        result = aggregator.aggregate("density", [1.00, 1.10])
        assert result.mean == pytest.approx(1.05)

    def test_two_values_std(self, aggregator):
        """Two values: sample std (ddof=1)."""
        result = aggregator.aggregate("density", [1.00, 1.10])
        expected_std = math.sqrt(((1.00 - 1.05) ** 2 + (1.10 - 1.05) ** 2) / 1)
        assert result.std == pytest.approx(expected_std)

    def test_three_values_ci(self, aggregator):
        """Three values: CI uses t-distribution (df=2, t=4.303)."""
        values = [1.00, 1.05, 1.10]
        result = aggregator.aggregate("density", values)

        mean = sum(values) / 3
        std = math.sqrt(sum((x - mean) ** 2 for x in values) / 2)
        se = std / math.sqrt(3)
        # t-critical for df=2, 95% CI (two-tailed)
        t_crit = 4.303
        margin = t_crit * se

        assert result.mean == pytest.approx(mean)
        assert result.ci_lower == pytest.approx(mean - margin, rel=0.01)
        assert result.ci_upper == pytest.approx(mean + margin, rel=0.01)

    def test_symmetric_ci(self, aggregator):
        """CI should be symmetric around the mean."""
        result = aggregator.aggregate("ced", [100.0, 110.0, 105.0, 108.0])
        ci_width_lower = result.mean - result.ci_lower
        ci_width_upper = result.ci_upper - result.mean
        assert ci_width_lower == pytest.approx(ci_width_upper)

    def test_ci_narrows_with_more_replicates(self, aggregator):
        """More replicates should narrow the CI (given same spread)."""
        # 3 values with ~same spread
        result_3 = aggregator.aggregate("density", [1.00, 1.05, 1.10])
        # 6 values with ~same spread
        result_6 = aggregator.aggregate("density", [1.00, 1.02, 1.04, 1.06, 1.08, 1.10])

        width_3 = result_3.ci_upper - result_3.ci_lower
        width_6 = result_6.ci_upper - result_6.ci_lower
        assert width_6 < width_3

    def test_identical_values(self, aggregator):
        """Identical values: std=0, CI=[mean, mean]."""
        result = aggregator.aggregate("density", [1.05, 1.05, 1.05])
        assert result.std == 0.0
        assert result.ci_lower == result.mean
        assert result.ci_upper == result.mean

    def test_empty_values_raises(self, aggregator):
        """Empty values should raise ValueError."""
        with pytest.raises(ValueError, match="No values"):
            aggregator.aggregate("density", [])

    def test_result_type(self, aggregator):
        """Result should be an AggregateResult."""
        result = aggregator.aggregate("density", [1.0, 1.1])
        assert isinstance(result, AggregateResult)

    def test_ci_level_stored(self, aggregator):
        """CI level should be stored in result."""
        result = aggregator.aggregate("density", [1.0, 1.1])
        assert result.ci_level == 0.95

    def test_values_preserved(self, aggregator):
        """Original values should be preserved in result."""
        values = [1.0, 1.1, 1.2]
        result = aggregator.aggregate("density", values)
        assert result.values == values


# ── Welch's t-test tests ─────────────────────────────────────────


class TestWelchTTest:
    """Tests for ReplicateAggregator.welch_ttest()."""

    def test_identical_groups_not_significant(self, aggregator):
        """Identical groups should not be significant."""
        a = [1.05, 1.06, 1.04]
        b = [1.05, 1.06, 1.04]
        result = aggregator.welch_ttest("density", a, b)

        assert result.delta_mean == pytest.approx(0.0)
        assert result.significant is False
        assert result.significance_stars == ""

    def test_clearly_different_groups(self, aggregator):
        """Well-separated groups should be significant."""
        a = [2.00, 2.01, 2.02, 2.03]
        b = [1.00, 1.01, 1.02, 1.03]
        result = aggregator.welch_ttest("density", a, b)

        assert result.delta_mean == pytest.approx(1.0, rel=0.01)
        assert result.significant is True
        assert result.p_value < 0.001
        assert "***" in result.significance_stars

    def test_delta_mean_is_a_minus_b(self, aggregator):
        """Delta mean should be mean(A) - mean(B)."""
        a = [10.0, 11.0, 12.0]
        b = [5.0, 6.0, 7.0]
        result = aggregator.welch_ttest("ced", a, b)

        expected_delta = 11.0 - 6.0
        assert result.delta_mean == pytest.approx(expected_delta)

    def test_negative_delta(self, aggregator):
        """If A < B, delta should be negative."""
        a = [1.0, 1.1, 1.2]
        b = [5.0, 5.1, 5.2]
        result = aggregator.welch_ttest("density", a, b)

        assert result.delta_mean < 0

    def test_insufficient_values_raises(self, aggregator):
        """Less than 2 values per group should raise ValueError."""
        with pytest.raises(ValueError, match="at least 2 values"):
            aggregator.welch_ttest("density", [1.0], [2.0, 2.1])

        with pytest.raises(ValueError, match="at least 2 values"):
            aggregator.welch_ttest("density", [1.0, 1.1], [2.0])

    def test_result_type(self, aggregator):
        """Result should be a TTestResult."""
        result = aggregator.welch_ttest("density", [1.0, 1.1, 1.2], [1.0, 1.1, 1.2])
        assert isinstance(result, TTestResult)

    def test_result_contains_aggregates(self, aggregator):
        """Result should contain both group aggregates."""
        a = [1.0, 1.1, 1.2]
        b = [2.0, 2.1, 2.2]
        result = aggregator.welch_ttest("density", a, b)

        assert isinstance(result.group_a, AggregateResult)
        assert isinstance(result.group_b, AggregateResult)
        assert result.group_a.n == 3
        assert result.group_b.n == 3

    def test_delta_ci_contains_delta_mean(self, aggregator):
        """Delta CI should contain the delta mean."""
        a = [1.0, 1.1, 1.2, 1.3]
        b = [2.0, 2.1, 2.2, 2.3]
        result = aggregator.welch_ttest("density", a, b)

        assert result.delta_ci_lower <= result.delta_mean <= result.delta_ci_upper

    def test_significance_stars_levels(self, aggregator):
        """Stars should reflect p-value levels."""
        # Very different groups
        a = [100.0, 100.1, 100.2, 100.3, 100.4]
        b = [1.0, 1.1, 1.2, 1.3, 1.4]
        result = aggregator.welch_ttest("ced", a, b)
        assert "***" in result.significance_stars

    def test_df_is_positive(self, aggregator):
        """Degrees of freedom should be positive."""
        result = aggregator.welch_ttest("density", [1.0, 1.1, 1.2], [2.0, 2.1, 2.2])
        assert result.df > 0

    def test_unequal_group_sizes(self, aggregator):
        """Should handle unequal group sizes."""
        a = [1.0, 1.1]
        b = [5.0, 5.1, 5.2, 5.3, 5.4]
        result = aggregator.welch_ttest("density", a, b)

        assert result.group_a.n == 2
        assert result.group_b.n == 5
        assert result.significant is True


class TestTCriticalLookup:
    """Tests for t-critical lookup and interpolation behavior."""

    def test_exact_integer_df_returns_tabulated_value(self):
        value = _lookup_t_critical(10.0, _T_CRITICAL_95)
        assert value == pytest.approx(2.228)

    def test_fractional_df_interpolates_between_neighbors(self):
        # Between df=2 (4.303) and df=3 (3.182): midpoint at 2.5
        value = _lookup_t_critical(2.5, _T_CRITICAL_95)
        expected = 4.303 + 0.5 * (3.182 - 4.303)
        assert value == pytest.approx(expected)

    def test_missing_integer_df_interpolates_between_neighbors(self):
        # df=11 sits between df=10 and df=12 in the table.
        value = _lookup_t_critical(11.0, _T_CRITICAL_95)
        expected = 2.228 + 0.5 * (2.179 - 2.228)
        assert value == pytest.approx(expected)

    def test_lookup_clamps_outside_table_range(self):
        low = _lookup_t_critical(0.1, _T_CRITICAL_95)
        high = _lookup_t_critical(9999.0, _T_CRITICAL_95)
        assert low == pytest.approx(_T_CRITICAL_95[1])
        assert high == pytest.approx(_T_CRITICAL_95[120])


# ── Standard error (Principle 9 — recommended default) ───────────


class TestStandardError:
    """Ensemble mean + standard error reported by default."""

    def test_single_value_se_zero(self, aggregator):
        result = aggregator.aggregate("density", [1.05])
        assert result.standard_error == 0.0

    def test_se_equals_std_over_sqrt_n(self, aggregator):
        values = [1.00, 1.05, 1.10]
        result = aggregator.aggregate("density", values)
        assert result.standard_error == pytest.approx(result.std / math.sqrt(3))

    def test_se_decreases_with_more_replicates(self, aggregator):
        """SEM shrinks as 1/sqrt(n) for the same spread."""
        few = aggregator.aggregate("density", [1.0, 1.1])
        many = aggregator.aggregate("density", [1.0, 1.1, 1.0, 1.1, 1.0, 1.1, 1.0, 1.1])
        assert many.standard_error < few.standard_error

    def test_convenience_yields_mean_and_se_by_default(self):
        """aggregate_replicates produces mean + standard error with defaults."""
        from metrics.statistics import aggregate_replicates

        result = aggregate_replicates("density", [1.00, 1.05, 1.10])
        assert result.mean == pytest.approx(1.05)
        assert result.standard_error == pytest.approx(result.std / math.sqrt(3))
        assert result.n == 3

    def test_policy_recommends_standard_error_by_default(self):
        from contracts.policies.replicate import DEFAULT_REPLICATE_POLICY

        assert DEFAULT_REPLICATE_POLICY.report_standard_error is True
