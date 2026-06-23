"""Tests for recommendation.inverse_designer module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from recommendation.inverse_designer import InverseDesigner, InverseDesignResult
from recommendation.property_targets import PropertyTarget, PropertyTargetSet

# A representative bulk target set (formerly the PG_64_22 preset) used for the
# end-to-end roundtrip test.
_BULK_TARGET_SET = PropertyTargetSet(
    name="bulk_target",
    description="Representative bulk property targets",
    targets=[
        PropertyTarget(metric_name="viscosity", target_max=3000.0, direction="minimize"),
        PropertyTarget(
            metric_name="cohesive_energy_density",
            target_min=300.0,
            target_max=500.0,
            direction="target",
        ),
        PropertyTarget(metric_name="elastic_modulus", target_min=0.5, direction="maximize"),
    ],
)

# Reduce policy defaults for test speed
_FAST_POLICY = {
    "max_iterations": 100,
    "convergence_threshold": 0.01,
    "convergence_window": 5,
    "n_candidates_per_iteration": 5,
    "feasibility_check_enabled": True,
    "require_pareto_improvement": True,
}


@pytest.fixture(autouse=True)
def _fast_policy():
    """Reduce candidates per iteration for test speed."""
    from contracts.policies.recommendation_policy import DEFAULT_RECOMMENDATION_POLICY

    original = DEFAULT_RECOMMENDATION_POLICY.inverse_design.n_candidates_per_iteration
    DEFAULT_RECOMMENDATION_POLICY.inverse_design.n_candidates_per_iteration = 5
    yield
    DEFAULT_RECOMMENDATION_POLICY.inverse_design.n_candidates_per_iteration = original


def _dummy_predictor(composition: dict[str, float]) -> dict[str, float]:
    """Deterministic dummy predictor based on composition."""
    asp = composition.get("asphaltene", 20.0)
    res = composition.get("resin", 30.0)
    return {
        "viscosity": 2000 + asp * 10,
        "cohesive_energy_density": 300 + res * 3,
        "elastic_modulus": 0.5 + asp * 0.04,
        "tensile_strength": 3.0 + asp * 0.15,
    }


def _feasible_predictor(composition: dict[str, float]) -> dict[str, float]:
    """Predictor that always returns values within the bulk target set."""
    return {
        "viscosity": 1500.0,
        "cohesive_energy_density": 400.0,
        "elastic_modulus": 1.0,
    }


class TestInverseDesigner:
    """Tests for InverseDesigner orchestrator."""

    def test_basic_run(self) -> None:
        """Should complete without error and return results."""
        ts = PropertyTargetSet(
            name="test",
            description="test",
            targets=[
                PropertyTarget(metric_name="viscosity", target_max=3000.0, direction="minimize"),
                PropertyTarget(
                    metric_name="cohesive_energy_density",
                    target_min=300.0,
                    target_max=500.0,
                    direction="target",
                ),
            ],
        )
        designer = InverseDesigner(
            predictor_fn=_dummy_predictor,
            target_set=ts,
        )
        # n_initial=1000 ensures random sampling (fast) for entire run
        result = designer.run(max_iterations=3, n_initial=1000, n_top=3)

        assert isinstance(result, InverseDesignResult)
        assert result.n_iterations > 0
        assert len(result.best_compositions) <= 3
        assert result.feasibility_rate > 0

    def test_feasible_convergence(self) -> None:
        """With a predictor that always satisfies targets, should converge or complete."""
        ts = PropertyTargetSet(
            name="easy",
            description="easy",
            targets=[
                PropertyTarget(metric_name="viscosity", target_max=3000.0, direction="minimize"),
                PropertyTarget(
                    metric_name="cohesive_energy_density",
                    target_min=300.0,
                    target_max=500.0,
                    direction="target",
                ),
                PropertyTarget(
                    metric_name="elastic_modulus",
                    target_min=0.5,
                    target_max=2.0,
                    direction="target",
                ),
            ],
        )
        designer = InverseDesigner(
            predictor_fn=_feasible_predictor,
            target_set=ts,
        )
        result = designer.run(max_iterations=3, n_initial=1000, n_top=3)

        # At least some results should satisfy targets
        satisfied = [
            c for c in result.best_compositions if ts.are_all_satisfied(c.predicted_objectives)
        ]
        assert len(satisfied) > 0

    def test_additive_type_fixed(self) -> None:
        """additive_type should be injected into predictor calls."""
        received_inputs: list[dict] = []

        def _spy_predictor(comp: dict[str, float]) -> dict[str, float]:
            received_inputs.append(dict(comp))
            return {"viscosity": 1500.0, "cohesive_energy_density": 400.0}

        ts = PropertyTargetSet(
            name="test",
            description="test",
            targets=[
                PropertyTarget(metric_name="viscosity", target_max=3000.0, direction="minimize"),
            ],
        )
        designer = InverseDesigner(
            predictor_fn=_spy_predictor,
            target_set=ts,
            additive_type="SBS",
        )
        designer.run(max_iterations=2, n_initial=1000, n_top=1)

        # Check that additive_type was injected
        assert len(received_inputs) > 0
        for inp in received_inputs:
            assert inp.get("additive_type") == "SBS"

    def test_additive_type_none_no_additive_dim(self) -> None:
        """Without additive_type, no additive dimension in optimizer."""
        ts = PropertyTargetSet(
            name="test",
            description="test",
            targets=[
                PropertyTarget(metric_name="viscosity", target_max=3000.0, direction="minimize"),
            ],
        )
        designer = InverseDesigner(
            predictor_fn=lambda c: {"viscosity": 1500.0},
            target_set=ts,
            additive_type=None,
        )
        result = designer.run(max_iterations=2, n_initial=1000, n_top=1)

        # Compositions should only have SARA keys
        for c in result.best_compositions:
            keys = set(c.composition.keys())
            assert "additive" not in keys

    def test_bounds_overrides_applied(self) -> None:
        """Custom SARA bounds should be applied to the optimizer."""
        ts = PropertyTargetSet(
            name="test",
            description="test",
            targets=[
                PropertyTarget(metric_name="viscosity", target_max=3000.0, direction="minimize"),
            ],
        )
        designer = InverseDesigner(
            predictor_fn=lambda c: {"viscosity": 1500.0},
            target_set=ts,
            bounds_overrides={
                "resin": (22.0, 28.0),
                "aromatic": (44.0, 36.0),
            },
        )

        from recommendation.bayesian_optimizer import AcquisitionFunction

        optimizer = designer._create_optimizer(
            designer._build_objectives(), 10, AcquisitionFunction.EI
        )

        assert optimizer.bounds["resin"] == (22.0, 28.0)
        assert optimizer.bounds["aromatic"] == (36.0, 44.0)

    def test_ood_flagging(self) -> None:
        """OOD detector results should be counted."""
        from dataclasses import dataclass

        @dataclass
        class FakeOODResult:
            is_ood: bool = True
            distance: float = 5.0
            threshold: float = 3.0

        mock_detector = MagicMock()
        mock_detector.detect.return_value = [FakeOODResult(is_ood=True)]

        ts = PropertyTargetSet(
            name="test",
            description="test",
            targets=[
                PropertyTarget(metric_name="viscosity", target_max=3000.0, direction="minimize"),
            ],
        )
        designer = InverseDesigner(
            predictor_fn=lambda c: {"viscosity": 1500.0},
            target_set=ts,
            ood_detector=mock_detector,
        )
        result = designer.run(max_iterations=2, n_initial=1000, n_top=1)

        assert result.ood_flagged_count > 0

    def test_composition_validator_applied(self) -> None:
        """Compositions in results should be valid (sum ~ 100%)."""
        ts = PropertyTargetSet(
            name="test",
            description="test",
            targets=[
                PropertyTarget(metric_name="viscosity", target_max=3000.0, direction="minimize"),
            ],
        )
        designer = InverseDesigner(
            predictor_fn=lambda c: {"viscosity": 1500.0},
            target_set=ts,
        )
        result = designer.run(max_iterations=3, n_initial=1000, n_top=3)

        for c in result.best_compositions:
            total = sum(c.composition.values())
            # After validation/correction, sum should be near 100
            assert 90.0 <= total <= 110.0

    def test_history_recorded(self) -> None:
        """Each iteration should be recorded in history."""
        ts = PropertyTargetSet(
            name="test",
            description="test",
            targets=[
                PropertyTarget(metric_name="viscosity", target_max=3000.0, direction="minimize"),
            ],
        )
        designer = InverseDesigner(
            predictor_fn=lambda c: {"viscosity": 1500.0},
            target_set=ts,
        )
        result = designer.run(max_iterations=3, n_initial=1000, n_top=1)

        assert len(result.history) == result.n_iterations
        for h in result.history:
            assert "iteration" in h
            assert "hypervolume" in h
            assert "n_candidates" in h

    def test_bulk_target_roundtrip(self) -> None:
        """Full roundtrip with a representative bulk target set."""
        designer = InverseDesigner(
            predictor_fn=_feasible_predictor,
            target_set=_BULK_TARGET_SET,
        )
        result = designer.run(max_iterations=3, n_initial=1000, n_top=3)

        assert result.target_set.name == "bulk_target"
        assert len(result.best_compositions) > 0
        assert result.n_iterations > 0

    def test_prediction_failure_handled(self) -> None:
        """Predictor failures should be gracefully skipped."""
        call_count = 0

        def _flaky_predictor(comp: dict[str, float]) -> dict[str, float]:
            nonlocal call_count
            call_count += 1
            if call_count % 3 == 0:
                raise RuntimeError("Simulated failure")
            return {"viscosity": 1500.0}

        ts = PropertyTargetSet(
            name="test",
            description="test",
            targets=[
                PropertyTarget(metric_name="viscosity", target_max=3000.0, direction="minimize"),
            ],
        )
        designer = InverseDesigner(
            predictor_fn=_flaky_predictor,
            target_set=ts,
        )
        result = designer.run(max_iterations=2, n_initial=1000, n_top=2)
        # Should complete despite some failures
        assert result.n_iterations > 0

    def test_optimize_temperature_adds_temperature_dimension(self) -> None:
        """Temperature optimization should add temperature_k to predictor inputs."""
        seen: list[dict[str, float]] = []

        def _predictor(comp: dict[str, float]) -> dict[str, float]:
            seen.append(dict(comp))
            return {"density": 1.0}

        ts = PropertyTargetSet(
            name="temp",
            description="temp",
            targets=[PropertyTarget(metric_name="density", direction="maximize")],
        )
        designer = InverseDesigner(
            predictor_fn=_predictor,
            target_set=ts,
            optimize_temperature=True,
            temperature_range_k=(273.0, 333.0),
        )
        designer.run(max_iterations=2, n_initial=1000, n_top=1)

        assert seen
        assert any("temperature_k" in comp for comp in seen)

    def test_hard_extrapolation_blocked_by_default(self) -> None:
        """Hard extrapolation should be skipped when allow_extrapolation is false."""
        ts = PropertyTargetSet(
            name="temp",
            description="temp",
            targets=[PropertyTarget(metric_name="density", direction="maximize")],
        )
        designer = InverseDesigner(
            predictor_fn=lambda comp: {"density": 1.0},
            target_set=ts,
            temperature_k_fixed=400.0,
            capability_manifest={
                "supported_temperature_range_k": [273.0, 333.0],
            },
            allow_extrapolation=False,
        )
        result = designer.run(max_iterations=2, n_initial=1000, n_top=1)
        assert result.best_compositions == []


class TestAcquisitionSelection:
    """Policy-driven acquisition function selection (#1+#3)."""

    def _designer(self):
        ts = PropertyTargetSet(
            name="t",
            description="t",
            targets=[
                PropertyTarget(metric_name="density", direction="maximize"),
                PropertyTarget(metric_name="viscosity", target_max=3000.0, direction="minimize"),
            ],
        )
        return InverseDesigner(predictor_fn=lambda c: {"density": 1.0}, target_set=ts)

    def test_auto_multi_objective_long_run_picks_ehvi(self):
        from recommendation.bayesian_optimizer import AcquisitionFunction

        acq, rationale = self._designer()._select_acquisition(n_objectives=2, max_iter=50)
        assert acq == AcquisitionFunction.EHVI
        assert "auto:" in rationale

    def test_auto_single_objective_picks_ei(self):
        from recommendation.bayesian_optimizer import AcquisitionFunction

        acq, _ = self._designer()._select_acquisition(n_objectives=1, max_iter=50)
        assert acq == AcquisitionFunction.EI

    def test_auto_short_run_picks_ei(self):
        from recommendation.bayesian_optimizer import AcquisitionFunction

        acq, _ = self._designer()._select_acquisition(n_objectives=2, max_iter=3)
        assert acq == AcquisitionFunction.EI

    def test_explicit_ucb_strategy(self, monkeypatch):
        from contracts.policies.recommendation_policy import DEFAULT_RECOMMENDATION_POLICY
        from recommendation.bayesian_optimizer import AcquisitionFunction

        monkeypatch.setattr(
            DEFAULT_RECOMMENDATION_POLICY.inverse_design, "acquisition_strategy", "ucb"
        )
        acq, rationale = self._designer()._select_acquisition(n_objectives=2, max_iter=50)
        assert acq == AcquisitionFunction.UCB
        assert "policy:" in rationale

    def test_result_records_acquisition(self):
        """A completed run records the chosen acquisition function for audit."""
        ts = PropertyTargetSet(
            name="t",
            description="t",
            targets=[PropertyTarget(metric_name="density", direction="maximize")],
        )
        designer = InverseDesigner(predictor_fn=lambda c: {"density": 1.0}, target_set=ts)
        result = designer.run(max_iterations=2, n_initial=5, n_top=1)
        assert result.acquisition_function == "expected_improvement"
        assert result.acquisition_rationale
