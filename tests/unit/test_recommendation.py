"""
Unit tests for Recommendation Agent (4단계).
"""

import numpy as np
import pytest

from contracts.schemas import ValidityDomainTag
from recommendation.agent import (
    AgentConfig,
    Recommendation,
    RecommendationAgent,
    RecommendationBatch,
    RecommendationStatus,
    create_recommendation_agent,
)
from recommendation.bayesian_optimizer import (
    BayesianOptimizer,
    OptimizationConfig,
    OptimizationObjective,
    SurrogateModel,
    create_default_optimizer,
)
from recommendation.composition_validator import (
    CompositionValidator,
    ValidityDomainClassifier,
)
from recommendation.pareto import (
    ParetoCalculator,
    ParetoPoint,
    find_knee_point,
)


def _predictor(composition: dict[str, float]) -> dict[str, float]:
    """Deterministic test predictor for recommendation flows."""
    asphaltene = float(composition.get("asphaltene", 0.0))
    resin = float(composition.get("resin", 0.0))
    aromatic = float(composition.get("aromatic", 0.0))
    return {
        "density": 0.9 + asphaltene * 0.004,
        "cohesive_energy_density": 250.0 + asphaltene * 4.0 + resin * 1.5,
        "adhesion_energy": 20.0 + resin * 0.8 + aromatic * 0.2,
    }


class TestCompositionValidator:
    """Tests for CompositionValidator."""

    def test_valid_composition(self):
        """Test validation of a valid composition."""
        validator = CompositionValidator()
        composition = {
            "asphaltene": 20.0,
            "resin": 30.0,
            "aromatic": 35.0,
            "saturate": 15.0,
        }

        result = validator.validate(composition)

        assert result.valid
        assert len(result.errors) == 0

    def test_invalid_sum(self):
        """Test detection of invalid sum."""
        validator = CompositionValidator(auto_fix=False)
        composition = {
            "asphaltene": 20.0,
            "resin": 30.0,
            "aromatic": 30.0,
            "saturate": 10.0,  # Sum = 90, not 100
        }

        result = validator.validate(composition)

        assert not result.valid
        assert any("sum" in e.lower() for e in result.errors)

    def test_auto_fix_sum(self):
        """Test auto-fix of composition sum."""
        validator = CompositionValidator(auto_fix=True)
        composition = {
            "asphaltene": 20.0,
            "resin": 30.0,
            "aromatic": 30.0,
            "saturate": 10.0,
        }

        result = validator.validate(composition)

        assert result.valid
        assert result.corrected_composition is not None
        assert abs(sum(result.corrected_composition.values()) - 100) < 0.1

    def test_bounds_violation(self):
        """Test detection of bounds violation."""
        validator = CompositionValidator(auto_fix=False)
        composition = {
            "asphaltene": 40.0,  # Exceeds max of 30
            "resin": 20.0,
            "aromatic": 30.0,
            "saturate": 10.0,
        }

        result = validator.validate(composition)

        assert not result.valid
        assert any("asphaltene" in e.lower() for e in result.errors)

    def test_auto_fix_bounds(self):
        """Test auto-fix of bounds violation."""
        validator = CompositionValidator(auto_fix=True)
        composition = {
            "asphaltene": 40.0,
            "resin": 20.0,
            "aromatic": 30.0,
            "saturate": 10.0,
        }

        result = validator.validate(composition)

        corrected = result.corrected_composition
        assert corrected is not None
        assert corrected["asphaltene"] <= 30.0

    def test_missing_component(self):
        """Test detection of missing required component."""
        validator = CompositionValidator(auto_fix=False)
        composition = {
            "asphaltene": 30.0,
            "resin": 40.0,
            "aromatic": 30.0,
            # Missing saturate
        }

        result = validator.validate(composition)

        assert not result.valid
        assert any("saturate" in e.lower() for e in result.errors)

    def test_generate_random_composition(self):
        """Test random composition generation."""
        validator = CompositionValidator()
        composition = validator.generate_random_composition(seed=42)

        # Should be valid
        result = validator.validate(composition)
        assert result.valid

        # Should sum to 100
        assert abs(sum(composition.values()) - 100) < 0.1

    def test_generate_with_additive(self):
        """Test random composition with additive."""
        validator = CompositionValidator()
        composition = validator.generate_random_composition(
            include_additive=True,
            additive_name="SBS",
            seed=42,
        )

        assert "SBS" in composition
        result = validator.validate(composition)
        assert result.valid

    def test_generate_random_composition_always_valid(self):
        """모든 seed에서 bounds와 합=100을 동시에 만족해야 한다.

        회귀 가드: 과거 구현은 정규화 후 bounds 클리핑으로 합이 100을
        벗어난 조성(예: 100.45)을 반환할 수 있었다 — slack 비례 재분배로
        둘 다 보장한다 (v01.05.30).
        """
        validator = CompositionValidator()
        bounds = validator.constraints.bounds
        for seed in range(100):
            for include_additive in (False, True):
                comp = validator.generate_random_composition(
                    include_additive=include_additive, seed=seed
                )
                assert abs(sum(comp.values()) - 100.0) < 1e-6, f"seed={seed}"
                for component, value in comp.items():
                    low, high = bounds.get(component, bounds["additive_total"])
                    assert low - 1e-9 <= value <= high + 1e-9, f"seed={seed} {component}"


class TestValidityDomainClassifier:
    """Tests for ValidityDomainClassifier."""

    def test_standard_composition(self):
        """Test classification of standard composition."""
        classifier = ValidityDomainClassifier()
        composition = {
            "asphaltene": 20.0,
            "resin": 30.0,
            "aromatic": 35.0,
            "saturate": 15.0,
        }

        tags = classifier.classify(composition)

        assert ValidityDomainTag.BULK_GAFF2_OK in tags
        assert ValidityDomainTag.HIGH_ASPHALTENE_SENSITIVE not in tags

    def test_high_asphaltene(self):
        """Test classification of high asphaltene composition."""
        classifier = ValidityDomainClassifier()
        composition = {
            "asphaltene": 28.0,
            "resin": 25.0,
            "aromatic": 30.0,
            "saturate": 17.0,
        }

        tags = classifier.classify(composition)

        assert ValidityDomainTag.HIGH_ASPHALTENE_SENSITIVE in tags

    def test_low_temperature(self):
        """Test classification with low temperature."""
        classifier = ValidityDomainClassifier()
        composition = {
            "asphaltene": 20.0,
            "resin": 30.0,
            "aromatic": 35.0,
            "saturate": 15.0,
        }

        tags = classifier.classify(composition, temperature_k=250.0)

        assert ValidityDomainTag.LOW_TEMPERATURE_CAUTION in tags

    def test_high_additive(self):
        """Test classification with high additive content."""
        classifier = ValidityDomainClassifier()
        composition = {
            "asphaltene": 18.0,
            "resin": 28.0,
            "aromatic": 30.0,
            "saturate": 12.0,
            "SBS": 12.0,  # High additive
        }

        tags = classifier.classify(composition)

        assert ValidityDomainTag.HIGH_ADDITIVE_UNCERTAIN in tags


class TestParetoCalculator:
    """Tests for ParetoCalculator."""

    def test_dominates(self):
        """Test dominance checking."""
        calc = ParetoCalculator(
            objectives=["obj1", "obj2"],
            directions=["maximize", "maximize"],
        )

        a = np.array([5.0, 5.0])
        b = np.array([3.0, 4.0])

        assert calc.dominates(a, b)
        assert not calc.dominates(b, a)

    def test_no_dominance(self):
        """Test non-dominated points."""
        calc = ParetoCalculator(
            objectives=["obj1", "obj2"],
            directions=["maximize", "maximize"],
        )

        a = np.array([5.0, 3.0])
        b = np.array([3.0, 5.0])

        assert not calc.dominates(a, b)
        assert not calc.dominates(b, a)

    def test_calculate_pareto_front(self):
        """Test Pareto front calculation."""
        calc = ParetoCalculator(
            objectives=["obj1", "obj2"],
            directions=["maximize", "maximize"],
        )

        points = [
            ParetoPoint(
                objectives=np.array([5.0, 3.0]),
                composition={"a": 1},
                predicted_properties={"obj1": 5.0, "obj2": 3.0},
            ),
            ParetoPoint(
                objectives=np.array([3.0, 5.0]),
                composition={"a": 2},
                predicted_properties={"obj1": 3.0, "obj2": 5.0},
            ),
            ParetoPoint(
                objectives=np.array([2.0, 2.0]),
                composition={"a": 3},
                predicted_properties={"obj1": 2.0, "obj2": 2.0},
            ),
        ]

        front = calc.calculate_pareto_front(points)

        pareto_points = front.get_pareto_points()
        assert len(pareto_points) == 2  # First two are Pareto optimal

    def test_minimize_direction(self):
        """Test Pareto with minimize direction."""
        calc = ParetoCalculator(
            objectives=["cost", "quality"],
            directions=["minimize", "maximize"],
        )

        points = [
            ParetoPoint(
                objectives=np.array([10.0, 5.0]),  # High cost, medium quality
                composition={"a": 1},
                predicted_properties={"cost": 10.0, "quality": 5.0},
            ),
            ParetoPoint(
                objectives=np.array([5.0, 4.0]),  # Low cost, low quality
                composition={"a": 2},
                predicted_properties={"cost": 5.0, "quality": 4.0},
            ),
            ParetoPoint(
                objectives=np.array([7.0, 8.0]),  # Medium cost, high quality
                composition={"a": 3},
                predicted_properties={"cost": 7.0, "quality": 8.0},
            ),
        ]

        front = calc.calculate_pareto_front(points)

        pareto_points = front.get_pareto_points()
        # Point 2 (low cost) and Point 3 (high quality) should be Pareto optimal
        assert len(pareto_points) >= 2

    def test_crowding_distance(self):
        """Test crowding distance calculation."""
        calc = ParetoCalculator(
            objectives=["obj1", "obj2"],
            directions=["maximize", "maximize"],
        )

        points = [
            ParetoPoint(
                objectives=np.array([1.0, 5.0]),
                composition={},
                predicted_properties={},
            ),
            ParetoPoint(
                objectives=np.array([3.0, 4.0]),
                composition={},
                predicted_properties={},
            ),
            ParetoPoint(
                objectives=np.array([5.0, 1.0]),
                composition={},
                predicted_properties={},
            ),
        ]

        front = calc.calculate_pareto_front(points)
        pareto_points = front.get_pareto_points()

        # Boundary points should have infinite crowding distance
        crowding_distances = [p.crowding_distance for p in pareto_points]
        assert max(crowding_distances) == float("inf")


class TestFindKneePoint:
    """Tests for knee point finding."""

    def test_find_knee(self):
        """Test finding knee point."""
        calc = ParetoCalculator(
            objectives=["obj1", "obj2"],
            directions=["maximize", "maximize"],
        )

        points = [
            ParetoPoint(objectives=np.array([1.0, 9.0]), composition={}, predicted_properties={}),
            ParetoPoint(objectives=np.array([3.0, 7.0]), composition={}, predicted_properties={}),
            ParetoPoint(
                objectives=np.array([5.0, 5.0]), composition={}, predicted_properties={}
            ),  # Knee
            ParetoPoint(objectives=np.array([7.0, 3.0]), composition={}, predicted_properties={}),
            ParetoPoint(objectives=np.array([9.0, 1.0]), composition={}, predicted_properties={}),
        ]

        front = calc.calculate_pareto_front(points)
        knee = find_knee_point(front)

        assert knee is not None


class TestSurrogateModel:
    """Tests for SurrogateModel."""

    def test_fit_predict(self):
        """Test fitting and prediction."""
        model = SurrogateModel(length_scale=1.0)

        X = np.array([[1.0], [2.0], [3.0]])
        y = np.array([1.0, 4.0, 9.0])

        model.fit(X, y)

        X_test = np.array([[1.5], [2.5]])
        mean, std = model.predict(X_test)

        assert len(mean) == 2
        assert len(std) == 2
        assert all(s > 0 for s in std)

    def test_unfitted_prediction(self):
        """Test prediction on unfitted model returns prior."""
        model = SurrogateModel()

        X_test = np.array([[1.0], [2.0]])
        mean, std = model.predict(X_test)

        # Should return prior (zeros mean, ones std)
        assert np.allclose(mean, 0)
        assert np.allclose(std, 1)


class TestSurrogateModelGP:
    """Tests for GP-backed SurrogateModel."""

    def test_gp_predictions_close_to_training(self):
        """Test GP predictions near training points are accurate."""
        model = SurrogateModel(length_scale=1.0, noise=0.01)

        # Linear function — GP with RBF kernel should fit well
        X = np.linspace(0, 5, 15).reshape(-1, 1)
        y = 2.0 * X.ravel() + 1.0

        model.fit(X, y)

        # Predict at interior training points (excluding boundary)
        X_interior = X[2:-2]
        y_interior = y[2:-2]
        mean, std = model.predict(X_interior)
        np.testing.assert_allclose(mean, y_interior, atol=1.0)

    def test_gp_uncertainty_increases_with_distance(self):
        """Test uncertainty grows away from training data."""
        model = SurrogateModel(length_scale=1.0)

        X = np.array([[0.0], [1.0]])
        y = np.array([0.0, 1.0])

        model.fit(X, y)

        near = np.array([[0.5]])
        far = np.array([[5.0]])

        _, std_near = model.predict(near)
        _, std_far = model.predict(far)

        assert std_far[0] > std_near[0]

    def test_gp_multivariate(self):
        """Test GP with multi-dimensional input."""
        model = SurrogateModel(length_scale=1.0)

        rng = np.random.RandomState(42)
        X = rng.uniform(0, 10, size=(20, 4))
        y = X[:, 0] + 0.5 * X[:, 1]  # linear target

        model.fit(X, y)

        X_test = rng.uniform(0, 10, size=(5, 4))
        mean, std = model.predict(X_test)

        assert len(mean) == 5
        assert len(std) == 5
        assert all(s >= 0 for s in std)


class TestBayesianOptimizer:
    """Tests for BayesianOptimizer."""

    def test_suggest_initial(self):
        """Test initial suggestions are random."""
        optimizer = create_default_optimizer()

        suggestions = optimizer.suggest(5)

        assert len(suggestions) == 5
        for comp in suggestions:
            assert "asphaltene" in comp
            assert "resin" in comp
            assert abs(sum(comp.values()) - 100) < 1.0

    def test_tell_and_suggest(self):
        """Test optimization loop."""
        objectives = [
            OptimizationObjective(name="density", direction="maximize"),
        ]
        config = OptimizationConfig(
            objectives=objectives,
            n_initial_samples=3,
        )
        bounds = {
            "asphaltene": (5.0, 30.0),
            "resin": (10.0, 50.0),
            "aromatic": (10.0, 60.0),
            "saturate": (5.0, 40.0),
        }
        optimizer = BayesianOptimizer(config=config, bounds=bounds)

        # Initial samples
        for _ in range(5):
            comps = optimizer.suggest(1)
            comp = comps[0]
            # Fake observation
            density = 1.0 + comp.get("asphaltene", 0) * 0.01
            optimizer.tell(comp, {"density": density})

        # Should now use surrogate model
        suggestions = optimizer.suggest(2)
        assert len(suggestions) == 2

    def test_get_best(self):
        """Test getting best solutions."""
        optimizer = create_default_optimizer()

        # Add some observations
        compositions = [
            {"asphaltene": 20, "resin": 30, "aromatic": 35, "saturate": 15},
            {"asphaltene": 25, "resin": 25, "aromatic": 35, "saturate": 15},
            {"asphaltene": 15, "resin": 35, "aromatic": 35, "saturate": 15},
        ]

        for i, comp in enumerate(compositions):
            # Normalize
            total = sum(comp.values())
            comp = {k: v * 100 / total for k, v in comp.items()}

            optimizer.tell(
                comp,
                {
                    "density": 1.0 + i * 0.01,
                    "cohesive_energy_density": 300 + i * 10,
                },
            )

        best = optimizer.get_best(2)
        assert len(best) == 2


class TestRecommendationAgent:
    """Tests for RecommendationAgent."""

    def test_create_agent(self):
        """Test agent creation."""
        agent = create_recommendation_agent()

        assert agent is not None
        assert agent.config.auto_run is False
        assert agent.config.require_approval is True

    def test_auto_run_disabled(self):
        """Test that auto_run is always disabled."""
        config = AgentConfig(auto_run=True)  # Try to enable
        agent = RecommendationAgent(config=config)

        # Should be forced to False
        assert agent.config.auto_run is False

    def test_generate_recommendations(self):
        """Test generating recommendations."""
        agent = create_recommendation_agent(predictor_fn=_predictor)

        batch = agent.generate_recommendations(n_candidates=10)

        assert batch is not None
        assert len(batch.recommendations) > 0
        assert all(r.status == RecommendationStatus.PENDING for r in batch.recommendations)

    def test_approve_recommendation(self):
        """Test approving a recommendation."""
        agent = create_recommendation_agent(predictor_fn=_predictor)

        batch = agent.generate_recommendations(n_candidates=5)
        rec_id = batch.recommendations[0].id

        approved = agent.approve_recommendation(rec_id, notes="Test approval")

        assert approved is not None
        assert approved.status == RecommendationStatus.APPROVED
        assert approved.approved_at is not None

    def test_reject_recommendation(self):
        """Test rejecting a recommendation."""
        agent = create_recommendation_agent(predictor_fn=_predictor)

        batch = agent.generate_recommendations(n_candidates=5)
        rec_id = batch.recommendations[0].id

        rejected = agent.reject_recommendation(rec_id, reason="Not suitable")

        assert rejected is not None
        assert rejected.status == RecommendationStatus.REJECTED

    def test_get_pending_recommendations(self):
        """Test getting pending recommendations."""
        agent = create_recommendation_agent(predictor_fn=_predictor)

        batch = agent.generate_recommendations(n_candidates=5)

        # Approve one
        agent.approve_recommendation(batch.recommendations[0].id)

        pending = agent.get_pending_recommendations()

        assert len(pending) == len(batch.recommendations) - 1

    def test_recommendation_summary(self):
        """Test recommendation summary."""
        agent = create_recommendation_agent(predictor_fn=_predictor)

        agent.generate_recommendations(n_candidates=5)
        agent.generate_recommendations(n_candidates=5)

        summary = agent.get_recommendation_summary()

        assert summary["total_batches"] == 2
        assert summary["total_recommendations"] > 0

    def test_with_custom_predictor(self):
        """Test agent with custom predictor function."""

        def predictor(composition):
            return {
                "cohesive_energy_density": 300 + composition.get("asphaltene", 0) * 5,
                "adhesion_energy": 50 + composition.get("resin", 0),
            }

        agent = create_recommendation_agent(predictor_fn=predictor)
        batch = agent.generate_recommendations(n_candidates=10)

        # Check predictions use our function
        for rec in batch.recommendations:
            assert "cohesive_energy_density" in rec.predicted_properties
            assert "adhesion_energy" in rec.predicted_properties

    def test_update_with_results(self):
        """Test updating optimizer with results."""
        agent = create_recommendation_agent(predictor_fn=_predictor)

        # Generate initial batch
        batch = agent.generate_recommendations(n_candidates=5)

        # Simulate getting results
        composition = batch.recommendations[0].composition
        observed = {
            "cohesive_energy_density": 350,
            "adhesion_energy": 55,
        }

        # Should not raise
        agent.update_with_results(composition, observed)

    def test_generate_recommendations_requires_predictor(self):
        """Recommendation generation must fail without an ML predictor."""
        agent = create_recommendation_agent()

        with pytest.raises(RuntimeError, match="ML predictor is required"):
            agent.generate_recommendations(n_candidates=5)


class TestRecommendation:
    """Tests for Recommendation dataclass."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        rec = Recommendation(
            id="rec_0_0",
            composition={"asphaltene": 20, "resin": 30, "aromatic": 35, "saturate": 15},
            predicted_properties={"density": 1.0},
            uncertainty={"density": 0.05},
            validity_tags=["bulk_gaff2_ok"],
            pareto_rank=1,
            crowding_distance=1.5,
        )

        d = rec.to_dict()

        assert d["id"] == "rec_0_0"
        assert d["pareto_rank"] == 1
        assert d["status"] == "pending"


class TestRecommendationBatch:
    """Tests for RecommendationBatch."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        calc = ParetoCalculator(objectives=["obj1"], directions=["maximize"])
        front = calc.calculate_pareto_front([])

        batch = RecommendationBatch(
            batch_id="batch_0",
            recommendations=[],
            pareto_front=front,
            optimization_iteration=0,
        )

        d = batch.to_dict()

        assert d["batch_id"] == "batch_0"
        assert d["n_recommendations"] == 0


class TestIntegration:
    """Integration tests for the recommendation system."""

    def test_full_workflow(self):
        """Test the complete recommendation workflow."""
        # Create agent
        agent = create_recommendation_agent(predictor_fn=_predictor)

        # Generate recommendations
        batch1 = agent.generate_recommendations(n_candidates=15)
        assert len(batch1.recommendations) > 0

        # Approve top recommendation
        top_rec = batch1.recommendations[0]
        approved = agent.approve_recommendation(top_rec.id)
        assert approved.status == RecommendationStatus.APPROVED

        # Simulate getting results
        agent.update_with_results(
            approved.composition,
            {
                "cohesive_energy_density": 340,
                "adhesion_energy": 52,
            },
        )

        # Generate more recommendations (should use updated model)
        batch2 = agent.generate_recommendations(n_candidates=15)
        assert len(batch2.recommendations) > 0

        # Check summary
        summary = agent.get_recommendation_summary()
        assert summary["total_batches"] == 2
        assert summary["by_status"]["approved"] >= 1

    def test_pareto_ranking(self):
        """Test that recommendations are properly Pareto-ranked."""
        agent = create_recommendation_agent(predictor_fn=_predictor)

        batch = agent.generate_recommendations(n_candidates=20)

        # Check that Pareto ranks are assigned
        ranks = [rec.pareto_rank for rec in batch.recommendations]
        assert all(r > 0 for r in ranks)

        # Ranks should be ordered
        assert ranks == sorted(ranks)
