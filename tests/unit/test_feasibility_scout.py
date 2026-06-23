"""Tests for recommendation.feasibility_scout.FeasibilityScout."""

from __future__ import annotations

import pytest

from recommendation.feasibility_scout import (
    DIFFICULT,
    FEASIBLE,
    INFEASIBLE,
    UNKNOWN,
    FeasibilityScout,
)
from recommendation.property_targets import PropertyTarget, PropertyTargetSet


def _target_set() -> PropertyTargetSet:
    return PropertyTargetSet(
        name="t",
        description="t",
        targets=[
            PropertyTarget(metric_name="density", target_min=0.9, target_max=1.1, direction="target"),
        ],
    )


class TestClassification:
    def test_always_satisfied_is_feasible(self):
        scout = FeasibilityScout(lambda c: {"density": 1.0}, _target_set(), n_samples=50)
        report = scout.scout()
        assert report.status == FEASIBLE
        assert report.all_targets_satisfied_pct == pytest.approx(100.0)
        assert report.n_evaluated == 50

    def test_never_satisfied_is_infeasible(self):
        scout = FeasibilityScout(lambda c: {"density": 5.0}, _target_set(), n_samples=50)
        report = scout.scout()
        assert report.status == INFEASIBLE
        assert report.all_targets_satisfied_pct == pytest.approx(0.0)

    def test_partial_satisfaction_is_difficult(self):
        """~10% satisfaction (between 5% and 20% thresholds) → difficult."""
        calls = {"n": 0}

        def _predict(_c):
            calls["n"] += 1
            # 1 in 10 satisfies the [0.9, 1.1] band
            return {"density": 1.0 if calls["n"] % 10 == 0 else 5.0}

        scout = FeasibilityScout(_predict, _target_set(), n_samples=100)
        report = scout.scout()
        assert report.status == DIFFICULT
        assert 5.0 <= report.all_targets_satisfied_pct < 20.0

    def test_threshold_overrides(self):
        """Explicit thresholds override policy defaults."""
        scout = FeasibilityScout(
            lambda c: {"density": 5.0},
            _target_set(),
            n_samples=20,
            infeasible_pct=0.0,  # nothing is ever infeasible
            difficult_pct=0.0,  # nothing is ever difficult
        )
        report = scout.scout()
        assert report.status == FEASIBLE  # 0% >= 0% thresholds


class TestPredictorFormats:
    def test_uncertainty_format_handled(self):
        """Predictor returning {'predictions': {...}} is unwrapped."""
        scout = FeasibilityScout(
            lambda c: {"predictions": {"density": 1.0}, "uncertainties": {"density": 0.1}},
            _target_set(),
            n_samples=20,
        )
        report = scout.scout()
        assert report.status == FEASIBLE

    def test_prediction_failures_are_skipped(self):
        """Predictor exceptions are skipped; only successful samples count."""
        calls = {"n": 0}

        def _flaky(_c):
            calls["n"] += 1
            if calls["n"] % 2 == 0:
                raise RuntimeError("boom")
            return {"density": 1.0}

        scout = FeasibilityScout(_flaky, _target_set(), n_samples=40)
        report = scout.scout()
        assert report.status == FEASIBLE
        assert report.n_evaluated == 20  # half skipped

    def test_no_predictions_is_unknown(self):
        """All predictions failing → unknown verdict (does not block)."""

        def _always_fail(_c):
            raise RuntimeError("boom")

        scout = FeasibilityScout(_always_fail, _target_set(), n_samples=10)
        report = scout.scout()
        assert report.status == UNKNOWN
        assert report.n_evaluated == 0


class TestReport:
    def test_per_target_breakdown(self):
        ts = PropertyTargetSet(
            name="multi",
            description="multi",
            targets=[
                PropertyTarget(metric_name="density", target_min=0.9, target_max=1.1, direction="target"),
                PropertyTarget(metric_name="viscosity", target_max=3000.0, direction="minimize"),
            ],
        )
        # density always satisfied, viscosity never satisfied
        scout = FeasibilityScout(
            lambda c: {"density": 1.0, "viscosity": 9999.0}, ts, n_samples=30
        )
        report = scout.scout()
        d = report.to_dict()
        assert d["per_target"]["density"]["satisfied_pct"] == pytest.approx(100.0)
        assert d["per_target"]["viscosity"]["satisfied_pct"] == pytest.approx(0.0)
        assert d["per_target"]["density"]["achievable"] is True
        assert d["per_target"]["viscosity"]["achievable"] is False
        # all-targets gated by the never-satisfied viscosity
        assert report.status == INFEASIBLE
