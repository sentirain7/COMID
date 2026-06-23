"""
Recommendation Agent for Asphalt Binder optimization.

Orchestrates the recommendation workflow:
1. Generate candidate compositions
2. Validate constraints
3. Predict properties using ML
4. Calculate Pareto front
5. Present recommendations for user approval
6. Queue approved simulations
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np

from common.logging import get_logger
from contracts.schema_enums import RecommendationStatus

from .bayesian_optimizer import (
    AcquisitionFunction,
    BayesianOptimizer,
    CandidateSolution,
    OptimizationConfig,
    OptimizationObjective,
)
from .composition_validator import (
    CompositionValidator,
    ValidityDomainClassifier,
)
from .pareto import (
    ParetoCalculator,
    ParetoFront,
    ParetoPoint,
)

logger = get_logger("recommendation.agent")


@dataclass
class Recommendation:
    """A single recommendation for user approval."""

    id: str
    composition: dict[str, float]
    predicted_properties: dict[str, float]
    uncertainty: dict[str, float]
    validity_tags: list[str]
    pareto_rank: int
    crowding_distance: float
    status: RecommendationStatus = RecommendationStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    approved_at: datetime | None = None
    queued_exp_id: str | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "composition": self.composition,
            "predicted_properties": self.predicted_properties,
            "uncertainty": self.uncertainty,
            "validity_tags": self.validity_tags,
            "pareto_rank": self.pareto_rank,
            "crowding_distance": self.crowding_distance,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "queued_exp_id": self.queued_exp_id,
            "notes": self.notes,
        }


@dataclass
class RecommendationBatch:
    """A batch of recommendations."""

    batch_id: str
    recommendations: list[Recommendation]
    pareto_front: ParetoFront
    optimization_iteration: int
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "batch_id": self.batch_id,
            "recommendations": [r.to_dict() for r in self.recommendations],
            "pareto_front": self.pareto_front.to_dict(),
            "optimization_iteration": self.optimization_iteration,
            "created_at": self.created_at.isoformat(),
            "n_recommendations": len(self.recommendations),
            "n_approved": sum(
                1 for r in self.recommendations if r.status == RecommendationStatus.APPROVED
            ),
        }


@dataclass
class AgentConfig:
    """Configuration for the recommendation agent."""

    objectives: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {"name": "cohesive_energy_density", "direction": "maximize", "weight": 1.0},
            {"name": "work_of_separation", "direction": "maximize", "weight": 1.0},
        ]
    )
    n_recommendations_per_batch: int = 5
    auto_run: bool = False  # Must be False per spec
    require_approval: bool = True
    include_additive: bool = True
    additive_name: str = "additive"
    bounds_overrides: dict[str, tuple[float, float]] = field(default_factory=dict)
    temperature_k: float = 298.0
    run_tier: str = "screening"


class RecommendationAgent:
    """
    Agent for recommending optimal asphalt binder compositions.

    Workflow:
    1. Generate candidate compositions (LLM or Bayesian optimization)
    2. Validate composition constraints
    3. Predict properties using ML model
    4. Calculate Pareto front for multi-objective optimization
    5. Present top recommendations for user approval
    6. Queue approved experiments
    """

    def __init__(
        self,
        config: AgentConfig | None = None,
        predictor: Callable | None = None,
        queue_fn: Callable | None = None,
    ):
        """
        Initialize recommendation agent.

        Args:
            config: Agent configuration
            predictor: Function to predict properties from composition
            queue_fn: Function to queue experiments
        """
        self.config = config or AgentConfig()

        # Ensure auto_run is disabled per spec
        if self.config.auto_run:
            logger.warning("auto_run disabled per specification")
            self.config.auto_run = False

        # Setup components
        self.validator = CompositionValidator(auto_fix=True)
        self.domain_classifier = ValidityDomainClassifier()

        # Setup optimizer
        self._setup_optimizer()

        # Setup Pareto calculator
        objective_names = [obj["name"] for obj in self.config.objectives]
        directions = [obj.get("direction", "maximize") for obj in self.config.objectives]
        self.pareto_calculator = ParetoCalculator(
            objectives=objective_names,
            directions=directions,
        )

        # External dependencies
        self.predictor = predictor
        self.queue_fn = queue_fn

        # State
        self.batches: list[RecommendationBatch] = []
        self.iteration = 0

    def _setup_optimizer(self) -> None:
        """Setup the Bayesian optimizer."""
        objectives = [
            OptimizationObjective(
                name=obj["name"],
                direction=obj.get("direction", "maximize"),
                weight=obj.get("weight", 1.0),
            )
            for obj in self.config.objectives
        ]

        opt_config = OptimizationConfig(
            objectives=objectives,
            n_initial_samples=10,
            n_iterations=50,
            acquisition_function=AcquisitionFunction.EI,
        )

        bounds = {
            "asphaltene": (5.0, 30.0),
            "resin": (10.0, 50.0),
            "aromatic": (10.0, 60.0),
            "saturate": (5.0, 40.0),
        }

        if self.config.include_additive:
            bounds[self.config.additive_name] = (0.0, 10.0)

        for name, override in self.config.bounds_overrides.items():
            if len(override) != 2:
                continue
            lo, hi = float(override[0]), float(override[1])
            if lo > hi:
                lo, hi = hi, lo
            bounds[name] = (lo, hi)

        self.optimizer = BayesianOptimizer(
            config=opt_config,
            bounds=bounds,
        )

    def generate_recommendations(
        self,
        n_candidates: int = 20,
    ) -> RecommendationBatch:
        """
        Generate a batch of recommendations.

        Args:
            n_candidates: Number of candidate compositions to generate

        Returns:
            RecommendationBatch with top recommendations
        """
        logger.info(f"Generating {n_candidates} candidate compositions")

        # Step 1: Generate candidates
        candidates = self._generate_candidates(n_candidates)

        # Step 2: Validate and correct
        validated_candidates = []
        for comp in candidates:
            result = self.validator.validate(comp)
            if result.valid:
                final_comp = result.corrected_composition or comp
                validated_candidates.append(final_comp)
            elif result.corrected_composition:
                validated_candidates.append(result.corrected_composition)

        logger.info(f"Validated {len(validated_candidates)} candidates")

        # Step 3: Predict properties
        pareto_points = []
        for i, comp in enumerate(validated_candidates):
            properties = self._predict_properties(comp)
            if properties:
                # Create objective vector
                objectives = np.array(
                    [properties.get(obj["name"], 0.0) for obj in self.config.objectives]
                )

                pareto_points.append(
                    ParetoPoint(
                        objectives=objectives,
                        composition=comp,
                        predicted_properties=properties,
                        index=i,
                    )
                )

        # Step 4: Calculate Pareto front
        pareto_front = self.pareto_calculator.calculate_pareto_front(pareto_points)
        logger.info(f"Pareto front has {len(pareto_front.get_pareto_points())} points")

        # Step 5: Select top recommendations
        top_points = pareto_front.get_top_k(self.config.n_recommendations_per_batch)

        # Create recommendations
        recommendations = []
        for rank, point in enumerate(top_points):
            # Get validity domain tags
            validity_tags = self.domain_classifier.classify(
                point.composition,
                self.config.temperature_k,
            )

            # Estimate uncertainty
            uncertainty = self._estimate_uncertainty(point.composition)

            rec = Recommendation(
                id=f"rec_{self.iteration}_{rank}",
                composition=point.composition,
                predicted_properties=point.predicted_properties,
                uncertainty=uncertainty,
                validity_tags=validity_tags,
                pareto_rank=rank + 1,
                crowding_distance=point.crowding_distance,
            )
            recommendations.append(rec)

        # Create batch
        batch = RecommendationBatch(
            batch_id=f"batch_{self.iteration}",
            recommendations=recommendations,
            pareto_front=pareto_front,
            optimization_iteration=self.iteration,
        )

        self.batches.append(batch)
        self.iteration += 1

        return batch

    def _generate_candidates(self, n: int) -> list[dict[str, float]]:
        """Generate candidate compositions."""
        # Use Bayesian optimization suggestions
        return self.optimizer.suggest(n)

    def _predict_properties(
        self,
        composition: dict[str, float],
    ) -> dict[str, float]:
        """Predict properties for a composition."""
        if self.predictor is None:
            raise RuntimeError("ML predictor is required for recommendation generation")
        try:
            predictions = self.predictor(composition)
        except Exception as e:
            logger.warning(f"Prediction failed: {e}")
            raise RuntimeError("ML predictor failed during recommendation generation") from e

        if not isinstance(predictions, dict) or not predictions:
            raise RuntimeError("ML predictor returned no predictions")
        return predictions

    def _estimate_uncertainty(
        self,
        composition: dict[str, float],
    ) -> dict[str, float]:
        """Estimate prediction uncertainty."""
        # Simple heuristic: higher uncertainty for extreme compositions
        uncertainty = {}

        asphaltene = composition.get("asphaltene", 20)
        additive = sum(
            v
            for k, v in composition.items()
            if k not in ["asphaltene", "resin", "aromatic", "saturate"]
        )

        base_uncertainty = 0.05

        # Higher uncertainty for high asphaltene
        if asphaltene > 25:
            base_uncertainty += 0.03

        # Higher uncertainty for high additive
        if additive > 5:
            base_uncertainty += 0.02

        for obj in self.config.objectives:
            uncertainty[obj["name"]] = base_uncertainty

        return uncertainty

    def approve_recommendation(
        self,
        recommendation_id: str,
        notes: str = "",
    ) -> Recommendation | None:
        """
        Approve a recommendation for simulation.

        Args:
            recommendation_id: ID of the recommendation to approve
            notes: Optional notes

        Returns:
            The approved Recommendation, or None if not found
        """
        for batch in self.batches:
            for rec in batch.recommendations:
                if rec.id == recommendation_id:
                    if rec.status != RecommendationStatus.PENDING:
                        logger.warning(f"Recommendation {recommendation_id} is not pending")
                        return None

                    rec.status = RecommendationStatus.APPROVED
                    rec.approved_at = datetime.now()
                    rec.notes = notes

                    logger.info(f"Approved recommendation {recommendation_id}")

                    # Queue if queue function available
                    if self.queue_fn is not None:
                        self._queue_experiment(rec)

                    return rec

        logger.warning(f"Recommendation {recommendation_id} not found")
        return None

    def reject_recommendation(
        self,
        recommendation_id: str,
        reason: str = "",
    ) -> Recommendation | None:
        """
        Reject a recommendation.

        Args:
            recommendation_id: ID of the recommendation to reject
            reason: Reason for rejection

        Returns:
            The rejected Recommendation, or None if not found
        """
        for batch in self.batches:
            for rec in batch.recommendations:
                if rec.id == recommendation_id:
                    rec.status = RecommendationStatus.REJECTED
                    rec.notes = reason
                    logger.info(f"Rejected recommendation {recommendation_id}: {reason}")
                    return rec

        return None

    def _queue_experiment(self, recommendation: Recommendation) -> None:
        """Queue an approved recommendation for simulation."""
        if self.queue_fn is None:
            logger.warning("No queue function configured")
            return

        try:
            exp_id = self.queue_fn(
                composition=recommendation.composition,
                temperature_k=self.config.temperature_k,
                run_tier=self.config.run_tier,
            )
            recommendation.queued_exp_id = exp_id
            recommendation.status = RecommendationStatus.QUEUED
            logger.info(f"Queued experiment {exp_id} for recommendation {recommendation.id}")
        except Exception as e:
            logger.error(f"Failed to queue experiment: {e}")
            recommendation.status = RecommendationStatus.FAILED
            recommendation.notes += f" Queue error: {str(e)}"

    def update_with_results(
        self,
        composition: dict[str, float],
        observed_properties: dict[str, float],
    ) -> None:
        """
        Update the optimizer with observed results.

        Args:
            composition: The evaluated composition
            observed_properties: Observed property values
        """
        self.optimizer.tell(composition, observed_properties)
        logger.info("Updated optimizer with results for composition")

    def get_best_compositions(self, n: int = 5) -> list[CandidateSolution]:
        """
        Get the best compositions found so far.

        Args:
            n: Number of best compositions to return

        Returns:
            List of best CandidateSolution objects
        """
        return self.optimizer.get_best(n)

    def get_pending_recommendations(self) -> list[Recommendation]:
        """Get all pending recommendations."""
        pending = []
        for batch in self.batches:
            for rec in batch.recommendations:
                if rec.status == RecommendationStatus.PENDING:
                    pending.append(rec)
        return pending

    def get_recommendation_summary(self) -> dict[str, Any]:
        """Get summary of all recommendations."""
        total = 0
        by_status = {status.value: 0 for status in RecommendationStatus}

        for batch in self.batches:
            for rec in batch.recommendations:
                total += 1
                by_status[rec.status.value] += 1

        return {
            "total_batches": len(self.batches),
            "total_recommendations": total,
            "by_status": by_status,
            "current_iteration": self.iteration,
        }


def create_recommendation_agent(
    predictor_fn: Callable | None = None,
    queue_fn: Callable | None = None,
    objectives: list[dict[str, Any]] | None = None,
    *,
    include_additive: bool = True,
    bounds_overrides: dict[str, tuple[float, float]] | None = None,
) -> RecommendationAgent:
    """
    Create a configured recommendation agent.

    Args:
        predictor_fn: Function to predict properties
        queue_fn: Function to queue experiments
        objectives: Optimization objectives

    Returns:
        Configured RecommendationAgent
    """
    config = AgentConfig(
        objectives=objectives
        or [
            {"name": "cohesive_energy_density", "direction": "maximize", "weight": 1.0},
            {"name": "work_of_separation", "direction": "maximize", "weight": 1.0},
        ],
        auto_run=False,
        require_approval=True,
        include_additive=include_additive,
        bounds_overrides=bounds_overrides or {},
    )

    return RecommendationAgent(
        config=config,
        predictor=predictor_fn,
        queue_fn=queue_fn,
    )
