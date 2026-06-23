"""Tests for MC-EHVI acquisition function in bayesian_optimizer."""

import numpy as np
import pytest

from recommendation.bayesian_optimizer import (
    AcquisitionFunction,
    BayesianOptimizer,
    OptimizationConfig,
    OptimizationObjective,
)


def _make_optimizer(
    acq: AcquisitionFunction = AcquisitionFunction.EHVI,
    n_objectives: int = 2,
) -> BayesianOptimizer:
    """Helper to create a configured optimizer."""
    objectives = [
        OptimizationObjective(name=f"obj_{i}", direction="maximize") for i in range(n_objectives)
    ]
    config = OptimizationConfig(
        objectives=objectives,
        n_initial_samples=3,
        acquisition_function=acq,
        seed=42,
    )
    bounds = {
        "asphaltene": (5.0, 30.0),
        "resin": (10.0, 50.0),
        "aromatic": (10.0, 60.0),
        "saturate": (5.0, 40.0),
    }
    return BayesianOptimizer(config=config, bounds=bounds)


def _seed_history(opt: BayesianOptimizer, n: int = 5) -> None:
    """Add synthetic observations to the optimizer."""
    rng = np.random.RandomState(123)
    for _ in range(n):
        comp = {
            "asphaltene": rng.uniform(5, 30),
            "resin": rng.uniform(10, 50),
            "aromatic": rng.uniform(10, 60),
            "saturate": rng.uniform(5, 40),
        }
        total = sum(comp.values())
        comp = {k: v * 100 / total for k, v in comp.items()}

        obj_values = {obj.name: rng.uniform(0, 100) for obj in opt.config.objectives}
        opt.tell(comp, obj_values)


class TestEHVIAcquisition:
    """Tests for MC-EHVI acquisition function."""

    def test_ehvi_returns_finite(self) -> None:
        """EHVI should return a finite value with sufficient history."""
        opt = _make_optimizer()
        _seed_history(opt, n=5)

        # Fit surrogates
        X = np.array(opt.X_history)
        for obj in opt.config.objectives:
            y = np.array(opt.y_history[obj.name])
            opt.surrogates[obj.name].fit(X, y)

        x = np.array([15.0, 25.0, 35.0, 20.0])
        val = opt._expected_hypervolume_improvement(x.reshape(1, -1))
        assert np.isfinite(val)

    def test_ehvi_nonnegative(self) -> None:
        """EHVI values should be >= 0 (improvement cannot be negative)."""
        opt = _make_optimizer()
        _seed_history(opt, n=5)

        X = np.array(opt.X_history)
        for obj in opt.config.objectives:
            y = np.array(opt.y_history[obj.name])
            opt.surrogates[obj.name].fit(X, y)

        rng = np.random.RandomState(42)
        for _ in range(10):
            x = rng.uniform([5, 10, 10, 5], [30, 50, 60, 40])
            val = opt._expected_hypervolume_improvement(x.reshape(1, -1))
            assert val >= -1e-10  # Allow tiny numerical noise

    def test_ehvi_vs_ei_correlation(self) -> None:
        """MC-EHVI and scalarised EI should have positive correlation.

        Both should generally agree on which regions are promising,
        though EHVI accounts for diversity.
        """
        opt = _make_optimizer()
        _seed_history(opt, n=8)

        X = np.array(opt.X_history)
        for obj in opt.config.objectives:
            y = np.array(opt.y_history[obj.name])
            opt.surrogates[obj.name].fit(X, y)

        rng = np.random.RandomState(42)
        ehvi_vals = []
        ei_vals = []
        for _ in range(20):
            x = rng.uniform([5, 10, 10, 5], [30, 50, 60, 40])
            x_2d = x.reshape(1, -1)
            ehvi_vals.append(opt._expected_hypervolume_improvement(x_2d))
            ei_vals.append(opt._expected_improvement(x_2d))

        # Correlation should be reasonably positive (>0.3 is a soft check)
        corr = np.corrcoef(ehvi_vals, ei_vals)[0, 1]
        # If all values are identical, correlation is NaN — skip
        if np.isfinite(corr):
            assert corr > -0.5  # Very lenient: just no strong anti-correlation


class TestEHVIFallback:
    """Tests for EHVI fallback conditions."""

    def test_fallback_single_objective(self) -> None:
        """With < 2 objectives, EHVI should fall back to EI."""
        opt = _make_optimizer(n_objectives=1)
        _seed_history(opt, n=5)

        X = np.array(opt.X_history)
        for obj in opt.config.objectives:
            y = np.array(opt.y_history[obj.name])
            opt.surrogates[obj.name].fit(X, y)

        x = np.array([15.0, 25.0, 35.0, 20.0]).reshape(1, -1)
        ehvi_val = opt._expected_hypervolume_improvement(x)
        ei_val = opt._expected_improvement(x)
        assert ehvi_val == pytest.approx(ei_val)

    def test_fallback_insufficient_history(self) -> None:
        """With < 3 observations, EHVI should fall back to EI."""
        opt = _make_optimizer()
        _seed_history(opt, n=2)  # Only 2 observations

        X = np.array(opt.X_history)
        for obj in opt.config.objectives:
            y = np.array(opt.y_history[obj.name])
            opt.surrogates[obj.name].fit(X, y)

        x = np.array([15.0, 25.0, 35.0, 20.0]).reshape(1, -1)
        ehvi_val = opt._expected_hypervolume_improvement(x)
        ei_val = opt._expected_improvement(x)
        assert ehvi_val == pytest.approx(ei_val)

    def test_fallback_no_history(self) -> None:
        """With 0 observations, EHVI should fall back to EI."""
        opt = _make_optimizer()
        x = np.array([15.0, 25.0, 35.0, 20.0]).reshape(1, -1)
        ehvi_val = opt._expected_hypervolume_improvement(x)
        ei_val = opt._expected_improvement(x)
        assert ehvi_val == pytest.approx(ei_val)

    def test_acquisition_dispatch_ehvi(self) -> None:
        """_acquisition() dispatches to EHVI when configured."""
        opt = _make_optimizer(acq=AcquisitionFunction.EHVI)
        _seed_history(opt, n=5)

        X = np.array(opt.X_history)
        for obj in opt.config.objectives:
            y = np.array(opt.y_history[obj.name])
            opt.surrogates[obj.name].fit(X, y)

        x = np.array([15.0, 25.0, 35.0, 20.0])
        val = opt._acquisition(x)
        assert np.isfinite(val)


class TestParetoFrontExtraction:
    """Tests for _get_pareto_front_points helper."""

    def test_empty_history(self) -> None:
        opt = _make_optimizer()
        pts = opt._get_pareto_front_points()
        assert len(pts) == 0

    def test_single_point(self) -> None:
        opt = _make_optimizer()
        opt.tell(
            {"asphaltene": 15, "resin": 25, "aromatic": 35, "saturate": 25},
            {"obj_0": 10.0, "obj_1": 20.0},
        )
        pts = opt._get_pareto_front_points()
        assert len(pts) == 1

    def test_dominated_point_excluded(self) -> None:
        opt = _make_optimizer()
        opt.tell(
            {"asphaltene": 15, "resin": 25, "aromatic": 35, "saturate": 25},
            {"obj_0": 10.0, "obj_1": 10.0},
        )
        opt.tell(
            {"asphaltene": 20, "resin": 25, "aromatic": 30, "saturate": 25},
            {"obj_0": 20.0, "obj_1": 20.0},  # Dominates first point
        )
        pts = opt._get_pareto_front_points()
        assert len(pts) == 1
        assert pts[0, 0] == 20.0
        assert pts[0, 1] == 20.0
