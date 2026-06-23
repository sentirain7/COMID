"""Recommendation and inverse design schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from contracts.schema_enums import (
    CampaignStatus,
    RecommendationMode,
    RecommendationStatus,
    SimulationPriority,
    WaveStatus,
)

# =============================================================================
# Active Learning / Recommendation Schemas
# =============================================================================


class RecommendationItem(BaseModel):
    """A single recommendation."""

    id: str
    composition: dict[str, float]
    predicted_properties: dict[str, float]
    uncertainty: dict[str, float]
    validity_tags: list[str]
    pareto_rank: int
    crowding_distance: float
    status: RecommendationStatus


class RecommendationBatchResponse(BaseModel):
    """Response for recommendation batch."""

    model_config = ConfigDict(title="RecommendationBatchResponse")

    batch_id: str
    n_recommendations: int
    optimization_iteration: int
    recommendations: list[RecommendationItem]


class ApproveRecommendationRequest(BaseModel):
    """Request to approve a recommendation."""

    recommendation_id: str
    notes: str = ""


class RejectRecommendationRequest(BaseModel):
    """Request to reject a recommendation."""

    recommendation_id: str
    reason: str = ""


class StopRecommendationRequest(BaseModel):
    """Request to stop execution for a queued/running recommendation."""

    recommendation_id: str
    reason: str = ""


class ApproveRejectResponse(BaseModel):
    """Response for approve/reject actions."""

    recommendation_id: str
    status: RecommendationStatus
    exp_id: str | None = None
    message: str = ""


class UnifiedRecommendation(BaseModel):
    """Unified recommendation schema for pending service and active learning."""

    model_config = ConfigDict(title="UnifiedRecommendation")

    id: str
    session_id: str | None = None
    source: str
    status: RecommendationStatus
    version: int = 1
    score: float = 0.0
    origin: str = "optimizer"
    mode: RecommendationMode = RecommendationMode.KNOWN
    model_version_id: str | None = None
    feature_set_version: str | None = None
    simulation_priority: SimulationPriority | None = None
    additive_type: str | None = None
    additive_wt_pct: float | None = None
    composition: dict[str, float] = Field(default_factory=dict)
    predicted_properties: dict[str, float] = Field(default_factory=dict)
    uncertainty: dict[str, float] = Field(default_factory=dict)
    result_metrics: dict[str, object] = Field(default_factory=dict)
    prediction_error: dict[str, object] = Field(default_factory=dict)
    used_in_retraining: bool = False
    rationale: str | None = None
    queued_exp_id: str | None = None
    notes: str | None = None
    created_at: str | None = None
    approved_at: str | None = None


class RecommendationDetailResponse(UnifiedRecommendation):
    """Detailed recommendation response with full decision context."""

    model_config = ConfigDict(title="RecommendationDetailResponse")

    pg_decision: dict[str, object] = Field(default_factory=dict)
    decision_trace: list[dict[str, object]] = Field(default_factory=list)
    source_records: list[dict[str, object]] = Field(default_factory=list)
    literature_refs: list[dict[str, object]] = Field(default_factory=list)


class FeedResultRequest(BaseModel):
    """Request to feed MD results back."""

    exp_id: str
    composition: dict[str, float]
    observed_properties: dict[str, float]
    temperature_k: float = 298.0


class ActiveLearningSummaryResponse(BaseModel):
    """Summary of active learning state."""

    iteration: int
    n_observations: int
    n_pending: int
    n_auto_running: int = 0
    agent_summary: dict


class CampaignWaveSubmitRequest(BaseModel):
    """Submit or create a campaign wave."""

    campaign_id: str | None = None
    campaign_name: str = "pilot_closed_loop"
    wave_no: int = Field(..., ge=1, le=4)
    binder_types: list[str] | None = None
    additive_types: list[str] = Field(default_factory=list)
    additive_concentrations: list[float] = Field(default_factory=list)


class CampaignWaveStatusResponse(BaseModel):
    """Wave submission and progress summary."""

    campaign_id: str
    wave_id: int
    wave_no: int
    status: WaveStatus
    total_jobs: int
    new_jobs: int
    duplicate_jobs: int
    submitted_jobs: int
    error_jobs: int
    experiment_counts: dict[str, int] = Field(default_factory=dict)
    spec: dict[str, object] = Field(default_factory=dict)
    submitted_at: str | None = None


class CampaignProgressResponse(BaseModel):
    """Campaign-level progress summary."""

    campaign_id: str
    name: str
    status: CampaignStatus
    total_waves: int
    total_experiments: int
    completed_experiments: int
    waves: list[CampaignWaveStatusResponse] = Field(default_factory=list)


class CampaignCreateRequest(BaseModel):
    """Create a campaign explicitly."""

    campaign_id: str | None = None
    name: str
    description: str | None = None


class CampaignSummary(BaseModel):
    """Campaign summary without wave details."""

    campaign_id: str
    name: str
    status: CampaignStatus
    wave_count: int
    total_experiments: int
    completed_experiments: int


class CampaignListResponse(BaseModel):
    """List of campaigns."""

    campaigns: list[CampaignSummary] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0
    status_filter: CampaignStatus | None = None


class CampaignDetailResponse(CampaignSummary):
    """Campaign detail with wave breakdown."""

    waves: list[CampaignWaveStatusResponse] = Field(default_factory=list)
    created_at: str | None = None


# =============================================================================
# Inverse Design Schemas (Phase 6)
# =============================================================================


class PropertyTargetItem(BaseModel):
    """A single property target specification."""

    metric_name: str
    target_min: float | None = None
    target_max: float | None = None
    direction: str = "maximize"
    weight: float = 1.0


class CompositionConstraintRequest(BaseModel):
    """Optional composition bound overrides for recommendation optimization."""

    min_asphaltene: float | None = None
    max_asphaltene: float | None = None
    min_resin: float | None = None
    max_resin: float | None = None
    min_aromatic: float | None = None
    max_aromatic: float | None = None
    min_saturate: float | None = None
    max_saturate: float | None = None


class AggregateSpecRequest(BaseModel):
    """Aggregate (crystal) specification for layered structure optimization."""

    material: str = Field(..., description="Crystal material (e.g. 'SiO2', 'CaCO3')")
    surface: str = Field("001", description="Miller index (e.g. '001', '110')")


class TemperatureRangeRequest(BaseModel):
    """Temperature optimization bounds."""

    min_k: float = Field(..., ge=233.0, le=473.0)
    max_k: float = Field(..., ge=233.0, le=473.0)


class InverseDesignRequest(BaseModel):
    """Request for inverse design optimization."""

    model_config = ConfigDict(title="InverseDesignRequest")

    custom_targets: list[PropertyTargetItem] = Field(
        ...,
        min_length=1,
        description="Property targets to design for (e.g. viscosity, density, work_of_separation)",
    )
    include_additive: bool = Field(
        False,
        description="Whether additive optimization is enabled for inverse design",
    )
    additive_type: str | None = Field(None, description="Fixed additive type for optimization")
    binder_types: list[str] | None = Field(
        None,
        description="Candidate binder types restricted to YAML-defined binders "
        "(e.g. ['AAA1']). None = pipeline policy pool (AAA1/AAK1/AAM1).",
    )
    structure_size: str = Field(
        "X1",
        pattern="^X[123]$",
        description="Binder cell structure size (X1/X2/X3) — molecule-count scale. "
        "Default X1; larger sizes scale cell per YAML composition.",
    )
    constraints: CompositionConstraintRequest | None = Field(
        None,
        description="Optional SARA composition bound overrides",
    )
    max_iterations: int = Field(50, ge=1, le=500)
    n_results: int = Field(5, ge=1, le=20)

    # Aggregate-aware design (optional, backward compatible)
    aggregate_specs: list[AggregateSpecRequest] | None = Field(
        None, description="Aggregate materials for layered structure optimization"
    )
    explore_all_additives: bool = Field(
        False, description="Explore all active additives in catalog"
    )
    binder_source_exp_id: str | None = Field(
        None,
        description="Source experiment ID for binder molecule composition (enables V3 features)",
    )
    optimize_temperature: bool = Field(
        False,
        description="Whether to optimize temperature as an additional design variable.",
    )
    temperature_k_fixed: float | None = Field(
        None,
        description="Fixed temperature for prediction/design when optimization is disabled.",
    )
    temperature_range_k: TemperatureRangeRequest | None = Field(
        None,
        description="Temperature optimization bounds in Kelvin.",
    )
    pressure_atm_fixed: float | None = Field(
        None,
        description="Fixed pressure carried into feature construction.",
    )
    allow_extrapolation: bool = Field(
        False,
        description="Allow hard extrapolation candidates for exploratory-only analysis.",
    )
    allow_infeasible_exploration: bool = Field(
        False,
        description=(
            "Proceed with optimization even when feasibility pre-screening classifies the "
            "targets as 'infeasible'. Default False fails fast on infeasible targets."
        ),
    )
    prediction_contract: str | None = Field(
        None,
        description="Optional requested ML feature contract/version (e.g. 'v3', 'v5', 'v6').",
    )


class InverseDesignResultItem(BaseModel):
    """A single result from inverse design optimization."""

    composition: dict[str, float]
    predicted_properties: dict[str, float]
    uncertainty: dict[str, float]
    targets_satisfied: bool
    target_distances: dict[str, float]
    is_ood: bool = False
    rationale: str | None = None
    extrapolation_status: str = "in_domain"
    high_uncertainty: bool = False
    capability_notes: list[str] = Field(default_factory=list)


class InverseDesignResponse(BaseModel):
    """Response from inverse design optimization."""

    model_config = ConfigDict(title="InverseDesignResponse")

    target_set_name: str
    n_iterations: int
    converged: bool
    feasibility_rate: float
    ood_flagged_count: int
    results: list[InverseDesignResultItem]
    hypervolume_history: list[float]
    prediction_contract: str | None = None
    feasibility: dict[str, Any] | None = Field(
        default=None,
        description="Target feasibility pre-screening report (status, per-target satisfaction).",
    )
    pareto_front: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Pareto-optimal candidates for manual trade-off exploration "
            "(composition, predicted_properties, crowding_distance)."
        ),
    )
    audit_log: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Decision trace: acquisition function + rationale, ranking formula/parameters, "
            "and per-iteration optimization summaries."
        ),
    )
