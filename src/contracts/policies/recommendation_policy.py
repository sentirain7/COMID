"""
Recommendation and Inverse Design policy definitions.

Configures EHVI acquisition function parameters and inverse design
optimization settings.
"""

from pydantic import BaseModel, Field, field_validator


class EHVIConfig(BaseModel):
    """Configuration for MC-EHVI acquisition function."""

    reference_point_offset: float = Field(
        default=1.0,
        description="Offset below nadir for reference point",
    )
    n_mc_samples: int = Field(
        default=1000,
        ge=100,
        le=100000,
        description="Number of Monte Carlo samples for EHVI estimation",
    )
    n_restarts: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Number of random restarts for acquisition optimization",
    )


class InverseDesignConfig(BaseModel):
    """Configuration for inverse design optimization loop."""

    max_iterations: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Maximum optimization iterations",
    )
    convergence_threshold: float = Field(
        default=0.01,
        gt=0,
        description="Minimum HV improvement to continue",
    )
    convergence_window: int = Field(
        default=5,
        ge=2,
        le=50,
        description="Number of iterations to check for convergence",
    )
    n_candidates_per_iteration: int = Field(
        default=20,
        ge=1,
        le=200,
        description="Candidates generated per iteration",
    )
    feasibility_check_enabled: bool = Field(
        default=True,
        description="Whether to enforce composition constraints",
    )
    require_pareto_improvement: bool = Field(
        default=True,
        description="Require Pareto improvement for convergence check",
    )
    uncertainty_penalty_lambda: float = Field(
        default=0.0,
        ge=0.0,
        description="Soft ranking penalty multiplier for relative predictive uncertainty.",
    )
    ood_penalty: float = Field(
        default=0.0,
        ge=0.0,
        description="Soft ranking penalty applied to OOD-flagged candidates.",
    )
    extrapolation_penalty: float = Field(
        default=0.0,
        ge=0.0,
        description="Soft ranking penalty applied to combinatorial generalization candidates.",
    )
    high_uncertainty_ratio_threshold: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Relative uncertainty threshold above which a candidate is marked high-uncertainty. "
            "Set to 0 to disable."
        ),
    )
    feasibility_scout_enabled: bool = Field(
        default=False,
        description=(
            "Opt-in: pre-screen target feasibility by random composition sampling before "
            "running the (expensive) optimization loop. Default OFF keeps existing behavior "
            "byte-identical; enable after benchmarking thresholds against the active champion."
        ),
    )
    feasibility_n_samples: int = Field(
        default=200,
        ge=10,
        le=5000,
        description="Random valid compositions sampled for feasibility pre-screening.",
    )
    feasibility_infeasible_pct: float = Field(
        default=5.0,
        ge=0.0,
        le=100.0,
        description=(
            "If the percentage of random samples satisfying ALL targets is below this, "
            "the request is classified 'infeasible' (blocked unless explicitly allowed)."
        ),
    )
    feasibility_difficult_pct: float = Field(
        default=20.0,
        ge=0.0,
        le=100.0,
        description=(
            "If the all-targets satisfaction percentage is below this (but at/above the "
            "infeasible threshold), the request is classified 'difficult' (warned, not blocked)."
        ),
    )
    feasibility_seed: int = Field(
        default=20260611,
        description=(
            "Base RNG seed for FeasibilityScout sampling — deterministic so a "
            "threshold-adjacent feasible/infeasible verdict is reproducible/auditable."
        ),
    )
    acquisition_strategy: str = Field(
        default="auto",
        description=(
            "Acquisition function selection: 'auto' (EHVI for >=2 objectives & long runs, "
            "else EI — legacy behavior), or an explicit 'ei' | 'ucb' | 'ehvi' | 'pi'."
        ),
    )
    exploration_weight: float = Field(
        default=0.1,
        ge=0.0,
        description="Exploration weight (beta) for the UCB acquisition function.",
    )
    pareto_front_max_points: int = Field(
        default=20,
        ge=1,
        le=500,
        description="Max Pareto-optimal points exposed in the inverse-design response.",
    )

    @field_validator("acquisition_strategy")
    @classmethod
    def _validate_acquisition_strategy(cls, v: str) -> str:
        allowed = {"auto", "ei", "ucb", "ehvi", "pi"}
        if v not in allowed:
            raise ValueError(f"acquisition_strategy must be one of {sorted(allowed)}, got {v!r}")
        return v


class AdditiveScoreWeights(BaseModel):
    """Weights for additive-specific 4D scoring."""

    effectiveness: float = Field(default=0.30, ge=0, le=1)
    cost_benefit: float = Field(default=0.20, ge=0, le=1)
    compatibility: float = Field(default=0.25, ge=0, le=1)
    scalability: float = Field(default=0.25, ge=0, le=1)


class DebateConfig(BaseModel):
    """Configuration for additive debate workflow."""

    max_rounds: int = Field(default=5, ge=1, le=20)
    delta_threshold: float = Field(default=0.02, gt=0)
    convergence_rounds: int = Field(default=2, ge=1, le=10)
    additive_score_weights: AdditiveScoreWeights = Field(default_factory=AdditiveScoreWeights)
    merge_bo_weight: float = Field(default=0.6, ge=0, le=1)
    max_candidate_additives: int = Field(default=5, ge=1, le=20)
    evidence_k_similar: int = Field(default=10, ge=1, le=50)


class PostRetrainAutomationConfig(BaseModel):
    """Configuration for post-retrain recommendation automation."""

    enabled: bool = Field(
        default=True,
        description="Whether to prepare recommendations after a successful retrain/promotion.",
    )
    n_candidates: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Number of recommendations to generate after retraining.",
    )
    auto_approve_and_execute: bool = Field(
        default=True,
        description="Automatically approve and queue post-retrain recommendations.",
    )
    source_label: str = Field(
        default="post_retrain_auto",
        description="Source label recorded for persisted auto-generated recommendations.",
    )


class RecommendationPolicy(BaseModel):
    """Top-level recommendation/inverse design policy."""

    ehvi: EHVIConfig = Field(default_factory=EHVIConfig)
    inverse_design: InverseDesignConfig = Field(default_factory=InverseDesignConfig)
    debate: DebateConfig = Field(default_factory=DebateConfig)
    post_retrain_automation: PostRetrainAutomationConfig = Field(
        default_factory=PostRetrainAutomationConfig
    )


DEFAULT_RECOMMENDATION_POLICY = RecommendationPolicy()
