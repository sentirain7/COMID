"""
Recommendation Module for Asphalt Binder Optimization.

This module implements the recommendation agent (4단계) from INTEGRATED_PLAN.md:
- Multi-objective Bayesian optimization
- Pareto front calculation
- Composition constraint validation
- User approval workflow
"""

from contracts.policies.composition import CompositionConstraints
from contracts.schemas import ValidityDomainTag

from .agent import (
    AgentConfig,
    Recommendation,
    RecommendationAgent,
    RecommendationBatch,
    RecommendationStatus,
    create_recommendation_agent,
)
from .bayesian_optimizer import (
    AcquisitionFunction,
    BayesianOptimizer,
    CandidateSolution,
    OptimizationConfig,
    OptimizationObjective,
    SurrogateModel,
    create_default_optimizer,
)
from .composition_validator import (
    CompositionValidator,
    ValidationResult,
    ValidityDomainClassifier,
)
from .inverse_designer import InverseDesigner, InverseDesignResult
from .pareto import (
    ParetoCalculator,
    ParetoFront,
    ParetoPoint,
    find_knee_point,
)
from .property_targets import (
    PropertyTarget,
    PropertyTargetSet,
)

__all__ = [
    # Composition Validator
    "CompositionValidator",
    "CompositionConstraints",
    "ValidationResult",
    "ValidityDomainTag",
    "ValidityDomainClassifier",
    # Pareto
    "ParetoCalculator",
    "ParetoPoint",
    "ParetoFront",
    "find_knee_point",
    # Bayesian Optimizer
    "BayesianOptimizer",
    "OptimizationConfig",
    "OptimizationObjective",
    "AcquisitionFunction",
    "CandidateSolution",
    "SurrogateModel",
    "create_default_optimizer",
    # Agent
    "RecommendationAgent",
    "RecommendationStatus",
    "Recommendation",
    "RecommendationBatch",
    "AgentConfig",
    "create_recommendation_agent",
    # Inverse Design
    "InverseDesigner",
    "InverseDesignResult",
    # Property Targets
    "PropertyTarget",
    "PropertyTargetSet",
]
