"""
Exploration policy — SSOT for exploration budget, coverage, and novelty scoring.

Governs how much exploration vs exploitation the planning orchestrator performs.
"""

from pydantic import BaseModel, Field


class ExplorationBudget(BaseModel):
    """Budget allocation for exploration jobs."""

    exploration_fraction: float = Field(
        0.30, description="Fraction of total GPU budget for exploration"
    )
    min_exploration_jobs: int = Field(2, description="Minimum exploration jobs per wave")
    max_exploration_jobs: int = Field(20, description="Maximum exploration jobs per wave")


class CoverageThresholds(BaseModel):
    """Thresholds for determining adequate coverage."""

    min_completed_per_cell: int = Field(
        1, description="Minimum completed experiments per (additive, binder, temp, conc) cell"
    )
    min_concentrations_tested: int = Field(
        2, description="Minimum concentrations tested per additive"
    )
    required_binder_types: list[str] = Field(
        default=["AAA1"], description="Binder types required for coverage"
    )
    required_temperatures_k: list[float] = Field(
        default=[293.0, 313.0], description="Temperatures required for coverage (K)"
    )


class NoveltyScoring(BaseModel):
    """Weights for novelty-based gap ranking."""

    category_diversity_weight: float = Field(
        0.30, description="Weight for additive category diversity"
    )
    functional_tag_gap_weight: float = Field(
        0.25, description="Weight for functional tag gap coverage"
    )
    descriptor_distance_weight: float = Field(
        0.25, description="Weight for descriptor-space distance (0 if lookup unavailable)"
    )
    literature_prior_weight: float = Field(0.20, description="Weight for literature evidence prior")


class ExplorationPolicy(BaseModel):
    """
    Exploration policy — SSOT for planning orchestrator exploration decisions.

    Controls exploration budget, coverage requirements, and novelty scoring.
    """

    budget: ExplorationBudget = Field(default_factory=ExplorationBudget)
    coverage: CoverageThresholds = Field(default_factory=CoverageThresholds)
    novelty: NoveltyScoring = Field(default_factory=NoveltyScoring)
    default_exploration_concentrations: list[float] = Field(
        default=[5.0], description="Default additive concentrations for exploration (wt%)"
    )


DEFAULT_EXPLORATION_POLICY = ExplorationPolicy()
