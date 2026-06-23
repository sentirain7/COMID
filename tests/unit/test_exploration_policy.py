"""Tests for exploration policy SSOT."""

import sys

sys.path.insert(0, "src")

from contracts.policies.exploration_policy import (
    DEFAULT_EXPLORATION_POLICY,
    CoverageThresholds,
    ExplorationBudget,
    ExplorationPolicy,
)


def test_default_policy_has_expected_budget():
    pol = DEFAULT_EXPLORATION_POLICY
    assert pol.budget.exploration_fraction == 0.30
    assert pol.budget.min_exploration_jobs == 2
    assert pol.budget.max_exploration_jobs == 20


def test_default_policy_has_coverage_thresholds():
    pol = DEFAULT_EXPLORATION_POLICY
    assert pol.coverage.min_completed_per_cell == 1
    assert pol.coverage.min_concentrations_tested == 2
    assert "AAA1" in pol.coverage.required_binder_types
    assert 293.0 in pol.coverage.required_temperatures_k


def test_novelty_weights_sum_to_one():
    n = DEFAULT_EXPLORATION_POLICY.novelty
    total = (
        n.category_diversity_weight
        + n.functional_tag_gap_weight
        + n.descriptor_distance_weight
        + n.literature_prior_weight
    )
    assert abs(total - 1.0) < 1e-6


def test_default_concentrations():
    assert DEFAULT_EXPLORATION_POLICY.default_exploration_concentrations == [5.0]


def test_custom_policy_overrides():
    pol = ExplorationPolicy(
        budget=ExplorationBudget(exploration_fraction=0.5, max_exploration_jobs=50),
        coverage=CoverageThresholds(required_binder_types=["AAA1", "AAK1"]),
    )
    assert pol.budget.exploration_fraction == 0.5
    assert pol.budget.max_exploration_jobs == 50
    assert len(pol.coverage.required_binder_types) == 2
