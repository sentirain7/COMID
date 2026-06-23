"""Experiment, molecule composition, batch job, and protocol schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.schemas.e_intra_method import validate_submission_e_intra_method
from common.seed import generate_seed
from contracts.policies.budget import SimilarExistingAction
from contracts.policies.e_inter_compute import EInterComputeConfig
from contracts.policies.equilibration import DEFAULT_EQUILIBRATION_POLICY as _EQ_POLICY
from contracts.policies.temperature import (
    DEFAULT_BINDER_CELL_BATCH_TEMPERATURES_K as _DEFAULT_TEMPS,
)
from contracts.policies.temperature import (
    DEFAULT_TEMPERATURE_PRIORITY_K as _DEFAULT_PRIORITY,
)
from contracts.policies.tier import DEFAULT_SCREENING_TARGET_ATOMS
from contracts.schema_enums import EInterRecommendationLevel
from contracts.schemas import MoleculeCountSpec, RunTier, StudyType

# =============================================================================
# Basic Experiment Models
# =============================================================================


class CompositionRequest(BaseModel):
    """Composition specification."""

    model_config = ConfigDict(title="CompositionRequest")

    asphaltene_wt: float = Field(0.2, ge=0, le=1, description="Asphaltene weight fraction")
    resin_wt: float = Field(0.3, ge=0, le=1, description="Resin weight fraction")
    aromatic_wt: float = Field(0.35, ge=0, le=1, description="Aromatic weight fraction")
    saturate_wt: float = Field(0.15, ge=0, le=1, description="Saturate weight fraction")


class ExperimentRequest(BaseModel):
    """Experiment submission request."""

    model_config = ConfigDict(title="ExperimentRequest")

    composition: CompositionRequest
    target_atoms: int = Field(DEFAULT_SCREENING_TARGET_ATOMS, ge=1000, le=1000000)
    temperature_K: float = Field(298.0, ge=200, le=500)
    pressure_atm: float = Field(1.0, ge=0.1, le=100)
    run_tier: str = Field("screening", description="Run tier")
    ff_type: str = Field("bulk_ff_gaff2", description="Force field type")
    seed: int | None = Field(None, description="Random seed")
    e_intra_method: str | None = Field(
        None,
        description="Optional submission-time E_intra method override for new jobs",
    )

    @field_validator("e_intra_method")
    @classmethod
    def validate_experiment_e_intra_method(cls, v: str | None) -> str | None:
        return validate_submission_e_intra_method(v)


class ExperimentResponse(BaseModel):
    """Experiment submission response."""

    model_config = ConfigDict(title="ExperimentResponse")

    exp_id: str
    job_id: str
    status: str


class ExperimentStatusResponse(BaseModel):
    """Experiment status response."""

    model_config = ConfigDict(title="ExperimentStatusResponse")

    exp_id: str
    status: str
    run_tier: str
    ff_type: str
    created_at: str | None = None
    completed_at: str | None = None
    error_message: str | None = None
    metrics: dict | None = None


class ExperimentCompositionResponse(BaseModel):
    """Experiment composition payload for detail views."""

    model_config = ConfigDict(title="ExperimentCompositionResponse")

    asphaltene: float | None = None
    resin: float | None = None
    aromatic: float | None = None
    saturate: float | None = None


class ExperimentMoleculeDetailResponse(BaseModel):
    """Per-molecule detail entry in experiment detail payloads."""

    model_config = ConfigDict(title="ExperimentMoleculeDetailResponse")

    count: int | None = None
    molecular_weight: float | None = None
    weight: float | None = None
    sara_type: str | None = None
    short_name: str | None = None


class ExperimentListItemResponse(BaseModel):
    """Experiment list row returned by GET /experiments."""

    model_config = ConfigDict(title="ExperimentListItemResponse")

    exp_id: str
    status: str | None = None
    run_tier: str | None = None
    ff_type: str | None = None
    study_type: str | None = None
    additive_mol_id: str | None = None
    e_intra_method: str | None = None
    e_intra_method_origin: str | None = None
    e_intra_method_resolved_from: str | None = None
    e_intra_method_source: str | None = None
    temperature_k: float | None = None
    target_atoms: int | None = None
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    wall_time_seconds: float | None = None
    pipeline_elapsed_seconds: float | None = None
    error_message: str | None = None
    metrics: dict[str, float | None] | None = None
    data_age: str | None = None
    gpu_id_allocated: int | None = None
    box_lx: float | None = None
    box_ly: float | None = None
    box_lz: float | None = None
    binder_code: str | None = None
    binder_type: str | None = None
    aging_code: str | None = None
    aging_state: str | None = None
    structure_size: str | None = None
    additive_label: str | None = None


class ExperimentListResponse(BaseModel):
    """Experiment list response."""

    model_config = ConfigDict(title="ExperimentListResponse")

    experiments: list[ExperimentListItemResponse]
    total: int
    filtered_total_count: int
    total_count: int
    limit: int


class ExperimentDetailResponse(BaseModel):
    """Experiment detail response."""

    model_config = ConfigDict(title="ExperimentDetailResponse")

    exp_id: str
    status: str | None = None
    run_tier: str | None = None
    ff_type: str | None = None
    force_field_type: str | None = None
    study_type: str | None = None
    additive_mol_id: str | None = None
    e_intra_method: str | None = None
    e_intra_method_origin: str | None = None
    e_intra_method_resolved_from: str | None = None
    e_intra_method_source: str | None = None
    temperature_k: float | None = None
    pressure_atm: float | None = None
    target_atoms: int | None = None
    actual_atoms: int | None = None
    seed: int | None = None
    composition: ExperimentCompositionResponse | None = None
    mol_counts: dict[str, int] | None = None
    mol_details: dict[str, ExperimentMoleculeDetailResponse] | None = None
    total_mass: float | None = None
    data_file_path: str | None = None
    log_file_path: str | None = None
    dump_files: list[str] | None = None
    error_code: str | None = None
    error_message: str | None = None
    metrics: dict[str, float | None] | None = None
    wall_time_seconds: float | None = None
    box_lx: float | None = None
    box_ly: float | None = None
    box_lz: float | None = None
    binder_code: str | None = None
    binder_type: str | None = None
    aging_code: str | None = None
    aging_state: str | None = None
    structure_size: str | None = None
    additive_label: str | None = None
    created_at: str | None = None
    completed_at: str | None = None


class JobStatusResponse(BaseModel):
    """Job status response."""

    model_config = ConfigDict(title="JobStatusResponse")

    job_id: str
    status: str
    priority: str
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    error_message: str | None = None
    result_exp_id: str | None = None


class QueueStatsResponse(BaseModel):
    """Queue statistics response."""

    model_config = ConfigDict(title="QueueStatsResponse")

    total_pending: int
    total_queued: int
    building: int = 0  # Jobs in structure building phase
    ready: int = 0  # Build-complete, waiting for GPU scheduling
    total_running: int
    analyzing: int = 0  # Jobs in post-processing/analysis phase
    total_completed: int
    total_failed: int
    total_cancelled: int = 0  # User cancelled
    total_timeout: int = 0  # GPU wait timeout (distinct from simulation failure)
    atoms_in_progress: int
    jobs_by_tier: dict
    # Time-based completion stats
    completed_today: int = 0
    completed_this_week: int = 0


class HealthResponse(BaseModel):
    """Health check response."""

    model_config = ConfigDict(title="HealthResponse")

    status: str
    version: str
    database: str
    lammps: str


class DetailedHealthResponse(BaseModel):
    """Detailed health check response - backwards compatible with HealthResponse.

    Extends HealthResponse with infrastructure component details while
    maintaining all existing fields for UI compatibility.
    """

    model_config = ConfigDict(title="DetailedHealthResponse")

    # Existing fields (UI compatibility - MUST keep)
    status: str  # "ready", "limited", "down"
    severity: str = Field(default="ok", description="Operational severity: ok|warn|critical")
    version: str
    database: str  # "connected" or "disconnected"
    lammps: str  # "available" or "not_checked"

    # Extended fields
    components: dict[str, dict] | None = None
    can_submit_jobs: bool = True
    llm_status: str = Field(
        default="mock",
        description="LLM provider status: ok | degraded | mock",
    )


# =============================================================================
# Molecule-Based Composition Models
# =============================================================================


class BinderTypeInfo(BaseModel):
    """Binder type information."""

    model_config = ConfigDict(title="BinderTypeInfo")

    name: str
    description: str
    sara_fractions: dict[str, float]


class MoleculeCountItem(BaseModel):
    """Molecule count item for response."""

    model_config = ConfigDict(title="MoleculeCountItem")

    mol_id: str
    count: int
    sara_type: str
    atom_count: int = 50  # From YAML SSOT


class BinderCompositionDetailResponse(BaseModel):
    """Detailed binder composition response."""

    model_config = ConfigDict(title="BinderCompositionDetailResponse")

    binder_type: str
    description: str
    structure_size: str
    aging_state: str
    molecules: list[MoleculeCountItem]
    total_molecules: int
    sara_fractions: dict[str, float]
    sara_counts: dict[str, int]  # Molecule counts aggregated by SARA category
    estimated_atoms: int


class AdditiveInfo(BaseModel):
    """Additive information."""

    model_config = ConfigDict(title="AdditiveInfo")

    mol_id: str
    name: str
    short_name: str | None = None  # Short display name from YAML SSOT
    atom_count: int = 50  # From YAML SSOT
    molecular_weight: float
    category: str
    default_counts: dict[str, int]
    structure_file: str | None = None  # Path relative to data/molecules/
    # Wave 0: surface ff_assignment SSOT fields so the frontend can render
    # route/status badges and disable blocked additives without an extra
    # round-trip to resolve_ff_hint per additive.
    route: str | None = None
    status: str | None = None
    is_submittable: bool = True
    blocked_reason: str | None = None
    # v00.99.30: runtime readiness signal. Non-null only when the organic
    # curated artifact is missing/incomplete — submit is still permitted
    # because the build pipeline auto-generates the artifact. Separate from
    # blocked_reason so the frontend can distinguish warnings from blocks.
    artifact_warning: str | None = None


class PropertyCalculationRequest(BaseModel):
    """Optional property calculation settings."""

    model_config = ConfigDict(title="PropertyCalculationRequest")

    viscosity_enabled: bool = False
    viscosity_temperatures: list[float] = Field(default_factory=lambda: [298.0])
    tensile_enabled: bool = False
    tensile_temperatures: list[float] = Field(default_factory=lambda: [298.0])


class StageDurationOverrideRequest(BaseModel):
    """User-specified duration override for a protocol stage."""

    model_config = ConfigDict(title="StageDurationOverrideRequest")

    stage_name: str = Field(..., description="Stage name (e.g., 'nvt_equilibration')")
    duration_ps: float | None = Field(None, ge=0, description="Duration in picoseconds")
    duration_steps: int | None = Field(None, ge=0, description="Duration in steps (for minimize)")


class StageRequest(BaseModel):
    """Canonical stage request payload for optional stage control and overrides."""

    model_config = ConfigDict(title="StageRequest")

    stage_key: str = Field(..., description="Canonical stage key")
    enabled: bool = Field(True, description="Whether this stage should be active")
    duration_ps: float | None = Field(None, ge=0, description="Optional duration override (ps)")
    duration_steps: int | None = Field(
        None, ge=0, description="Optional duration override (steps for minimize)"
    )
    params_override: dict[str, float | int | str | bool] | None = Field(
        None,
        description="Per-stage parameter overrides such as temperature_K or pressure_atm",
    )


class EquilibrationSettingsRequest(BaseModel):
    """High-temperature/high-pressure equilibration settings for kinetic trapping mitigation.

    When enabled, inserts additional equilibration stages before the standard NVT:
    minimize -> [high_temp_nvt @ high_T] -> [high_pressure_npt @ high_T, high_P] -> nvt @ target_T -> npt @ target_T, 1atm

    Literature references:
    - Scientific Reports 2021: NPT @ 100 atm (200 ps) -> NPT @ 1 atm (1000 ps)
    - ACS Omega 2022: NVT @ 800K (100 ps) -> NPT @ 200 atm, 800K (500 ps) -> gradual cooling

    Note: Default values and bounds are sourced from contracts.policies.equilibration (SSOT).
    """

    model_config = ConfigDict(title="EquilibrationSettingsRequest")

    enabled: bool = Field(
        False, description="Enable enhanced equilibration for low-temperature simulations"
    )
    high_temp_nvt_temperature_K: float = Field(
        _EQ_POLICY.high_temp_nvt_temperature_K,
        ge=_EQ_POLICY.temperature_min_K,
        le=_EQ_POLICY.temperature_max_K,
        description="High-temperature NVT stage temperature (K)",
    )
    high_temp_nvt_duration_ps: float = Field(
        _EQ_POLICY.high_temp_nvt_duration_ps,
        ge=_EQ_POLICY.duration_min_ps,
        le=_EQ_POLICY.duration_max_ps,
        description="High-temperature NVT stage duration (ps)",
    )
    high_pressure_npt_temperature_K: float = Field(
        _EQ_POLICY.high_pressure_npt_temperature_K,
        ge=_EQ_POLICY.temperature_min_K,
        le=_EQ_POLICY.temperature_max_K,
        description="High-pressure NPT stage temperature (K)",
    )
    high_pressure_npt_pressure_atm: float = Field(
        _EQ_POLICY.high_pressure_npt_pressure_atm,
        ge=_EQ_POLICY.pressure_min_atm,
        le=_EQ_POLICY.pressure_max_atm,
        description="High-pressure NPT stage pressure (atm)",
    )
    high_pressure_npt_duration_ps: float = Field(
        _EQ_POLICY.high_pressure_npt_duration_ps,
        ge=_EQ_POLICY.duration_min_ps,
        le=_EQ_POLICY.duration_max_ps,
        description="High-pressure NPT stage duration (ps)",
    )


class MoleculeExperimentRequest(BaseModel):
    """Molecule-based experiment submission request."""

    model_config = ConfigDict(title="MoleculeExperimentRequest")

    binder_type: str = "AAA1"
    structure_size: str = "X1"
    aging_state: str = "non_aging"
    molecule_counts: list[MoleculeCountSpec]
    additives: list[MoleculeCountSpec] | None = None
    temperature_K: float = 298.0
    run_tier: str = "screening"
    ff_type: str = "bulk_ff_gaff2"
    box_dimensions: tuple[float, float, float] | None = Field(
        None,
        description="Optional explicit orthorhombic box dimensions (lx, ly, lz) in Angstrom",
    )
    study_type: StudyType | None = Field(
        None,
        description="Optional study type override (bulk/layer) for boundary control",
    )
    initial_density: float | None = Field(
        None,
        gt=0,
        description="Optional initial packing density (g/cm3) for Packmol. Defaults to 0.5 if not specified.",
    )
    property_calculations: PropertyCalculationRequest | None = None
    seed: int | None = None
    e_intra_method: str | None = Field(
        None,
        description="Optional submission-time E_intra method override for new jobs",
    )
    stage_requests: list[StageRequest] | None = Field(
        None,
        description="Canonical stage request list. Preferred over legacy stage_durations/equilibration_settings.",
    )
    # Protocol stage duration overrides (optional)
    stage_durations: list[StageDurationOverrideRequest] | None = Field(
        None,
        description="Optional stage duration overrides. Only stages with different "
        "durations from defaults need to be specified.",
    )
    # High-temperature/high-pressure equilibration settings (optional)
    equilibration_settings: EquilibrationSettingsRequest | None = Field(
        None,
        description="Optional high-temperature/high-pressure equilibration settings "
        "for low-temperature simulations with kinetic trapping issues.",
    )

    @field_validator("box_dimensions")
    @classmethod
    def validate_box_dimensions(
        cls, value: tuple[float, float, float] | None
    ) -> tuple[float, float, float] | None:
        if value is None:
            return None
        if any(float(v) <= 0 for v in value):
            raise ValueError("box_dimensions values must be positive")
        return value

    @field_validator("e_intra_method")
    @classmethod
    def validate_molecule_e_intra_method(cls, v: str | None) -> str | None:
        return validate_submission_e_intra_method(v)


class DependentMoleculeExperimentRequest(MoleculeExperimentRequest):
    """Molecule experiment request that depends on upstream parent experiment."""

    parent_exp_id: str = Field(..., description="Upstream parent experiment ID")


class TypingChargePrecomputeRequest(BaseModel):
    """Precompute request for typing/charge cache warm-up."""

    model_config = ConfigDict(title="TypingChargePrecomputeRequest")

    binder_type: str = "AAA1"
    structure_size: str = "X1"
    aging_state: str = "non_aging"
    molecule_counts: list[MoleculeCountSpec]
    additives: list[MoleculeCountSpec] | None = None
    ff_type: str = "bulk_ff_gaff2"


class TypingChargePrecomputeItem(BaseModel):
    """Per-molecule typing/charge precompute status item."""

    model_config = ConfigDict(title="TypingChargePrecomputeItem")

    mol_id: str
    status: str
    atom_count: int | None = None
    charge_model: str | None = None
    message: str | None = None


class TypingChargePrecomputeResponse(BaseModel):
    """Typing/charge precompute summary response."""

    model_config = ConfigDict(title="TypingChargePrecomputeResponse")

    ff_type: str
    total_molecules: int
    unique_molecules: int
    cached: int
    computed: int
    failed: int
    details: list[TypingChargePrecomputeItem] = Field(default_factory=list)


class MoleculeCompositionPreviewRequest(BaseModel):
    """Molecule-based composition preview request."""

    model_config = ConfigDict(title="MoleculeCompositionPreviewRequest")

    binder_type: str = "AAA1"
    structure_size: str = "X1"
    aging_state: str = "non_aging"
    molecule_counts: list[MoleculeCountSpec]
    additives: list[MoleculeCountSpec] | None = None
    temperature_K: float = 298.0


class FFEligibilityItem(BaseModel):
    """One FF eligibility issue (blocked or warning)."""

    item_id: str
    item_kind: str = "molecule"  # molecule | additive
    route: str | None = None
    status: str = "blocked"  # blocked | warn
    message: str = ""


class EInterRecommendationResponse(BaseModel):
    """E_inter precision analysis recommendation (v01.02.17).

    Returned in validate/preview responses to help UI render
    the precision analysis panel with correct state.
    """

    model_config = ConfigDict(title="EInterRecommendationResponse")

    level: EInterRecommendationLevel = Field(
        EInterRecommendationLevel.NONE,
        description="Recommendation level: none, optional, recommended, required",
    )
    score: float = Field(0.0, description="Recommendation score (0.0-1.0)")
    reason_codes: list[str] = Field(
        default_factory=list, description="Reason codes for recommendation"
    )
    affected_metrics: list[str] = Field(
        default_factory=list, description="Metrics affected by E_inter precision"
    )
    estimated_cpu_cost_minutes: float = Field(0.0, description="Estimated CPU cost in minutes")
    default_enabled: bool = Field(False, description="Whether enabled by default")


class MoleculeCompositionPreviewResponse(BaseModel):
    """Molecule-based composition preview response."""

    model_config = ConfigDict(title="MoleculeCompositionPreviewResponse")

    sara_fractions: dict[str, float]
    estimated_atoms: int
    total_molecules: int
    ff_blocked_items: list[FFEligibilityItem] = []
    ff_warning_items: list[FFEligibilityItem] = []


class MoleculeExperimentResponse(BaseModel):
    """Molecule-based experiment submission response."""

    model_config = ConfigDict(title="MoleculeExperimentResponse")

    exp_id: str
    job_id: str
    status: str
    binder_type: str
    structure_size: str
    total_molecules: int
    estimated_atoms: int


class DependentMoleculeExperimentResponse(MoleculeExperimentResponse):
    """Response for deferred dependent molecule experiment submission."""

    parent_exp_id: str
    dependency_status: str = "blocked"


# =============================================================================
# Protocol Configuration Models
# =============================================================================


class StageCondition(BaseModel):
    """Structured metadata describing a stage's temperature/pressure conditions."""

    model_config = ConfigDict(title="StageCondition")

    temperature_mode: str = Field(
        ...,
        description=(
            "'none' (minimize), 'fixed' (policy-defined temperature), "
            "'target' (user-set temperature), 'ramp' (target↔fixed cycling), "
            "'ramp_from' (start→end temperature ramp)"
        ),
    )
    fixed_temperature_K: float | None = Field(
        None, description="Policy-fixed temperature (e.g. high_temp_nvt, annealing high)"
    )
    temp_start_K: float | None = Field(
        None, description="Starting temperature for ramp (e.g., 10K for layered high_temp_nvt)"
    )
    uses_target_temperature: bool = Field(
        False, description="Whether the stage uses user-set target temperature"
    )
    uses_target_pressure: bool = Field(
        False, description="Whether the stage uses user-set target pressure (NPT)"
    )
    n_cycles: int | None = Field(None, description="Number of annealing cycles")


class StageConfigResponse(BaseModel):
    """Response model for protocol stage configuration."""

    model_config = ConfigDict(title="StageConfigResponse")

    name: str = Field(..., description="Stage name")
    type: str = Field(..., description="Stage type (minimize, nvt, npt, nemd)")
    duration_ps: float | None = Field(None, description="Duration in picoseconds")
    duration_steps: int | None = Field(None, description="Duration in steps")
    editable: bool = Field(True, description="Whether duration is user-editable")
    condition: StageCondition | None = Field(None, description="Stage condition metadata")
    display_name: str | None = Field(None, description="Human-readable stage label")
    compact_display_name: str | None = Field(
        None, description="Compact label for dense stage cards"
    )
    short_name: str | None = Field(None, description="Compact label for timeline display")
    color: str | None = Field(None, description="Preferred UI color")
    optional: bool = Field(False, description="Whether the stage is optional")
    editable_fields: list[str] = Field(
        default_factory=lambda: ["duration"], description="Editable stage field names"
    )
    bounds: dict = Field(default_factory=dict, description="Validation bounds for editable fields")
    ui_metadata: dict = Field(default_factory=dict, description="Extra UI metadata")
    order_index: int = Field(0, description="Suggested stage render order")


class DefaultStagesResponse(BaseModel):
    """Response model for default protocol stages."""

    model_config = ConfigDict(title="DefaultStagesResponse")

    tier: str = Field(..., description="Run tier name")
    stages: list[StageConfigResponse] = Field(..., description="Stage configurations")
    total_duration_ps: float = Field(..., description="Total simulation duration in ps")


# ── Batch Job Binder Cell Schemas ──────────────────────────────────


class BatchJobBinderCellRequest(BaseModel):
    """Request to create a batch Binder Cell job."""

    model_config = ConfigDict(title="BatchJobBinderCellRequest")

    binder_types: list[str]
    structure_sizes: list[str] = ["X1"]
    temperatures_k: list[float] = Field(default_factory=lambda: list(_DEFAULT_TEMPS))
    aging_states: list[str] = ["non_aging"]
    tier: RunTier = RunTier.SCREENING
    ff_type: str = "bulk_ff_gaff2"
    e_intra_method: str | None = Field(
        None,
        description="Optional E_intra method override for new jobs. Defaults to settings.json.",
    )
    seed: int = Field(default_factory=generate_seed)
    temperature_priority: list[float] = Field(default_factory=lambda: list(_DEFAULT_PRIORITY))
    # Phase 5.1: additive DOE axes (empty = existing behavior)
    additive_types: list[str] = []
    additive_concentrations: list[float] = []
    initial_density: float | None = Field(
        None,
        gt=0,
        description="Optional initial packing density (g/cm3) for Packmol. Defaults to 0.5 if not specified.",
    )
    stage_requests: list[StageRequest] | None = Field(
        None,
        description="Canonical stage request list. Preferred over legacy stage_durations/equilibration_settings.",
    )
    stage_durations: list[StageDurationOverrideRequest] | None = Field(
        None,
        description="Optional stage duration overrides. Only stages with different "
        "durations from defaults need to be specified.",
    )
    property_calculations: PropertyCalculationRequest | None = None
    # High-temperature/high-pressure equilibration settings (optional)
    equilibration_settings: EquilibrationSettingsRequest | None = Field(
        None,
        description="Optional high-temperature/high-pressure equilibration settings "
        "for low-temperature simulations with kinetic trapping issues.",
    )
    # Similar experiment handling action (v00.95.02)
    similar_existing_action: SimilarExistingAction = Field(
        SimilarExistingAction.UNSPECIFIED,
        description="유사 실험 존재 시 처리 방식. 'unspecified'면 similar job 있을 때 submit 거부.",
    )
    # User-excluded exp_ids (v00.95.27)
    excluded_exp_ids: list[str] = Field(
        default_factory=list,
        description="사용자가 제출에서 제외할 exp_id 목록 (duplicate이 아닌 잡만)",
    )
    # E_inter 정밀 분석 설정 (v01.02.17)
    interaction_analysis: EInterComputeConfig | None = Field(
        None,
        description="E_inter 정밀 분석 설정. GPU 완료 후 CPU rerun으로 장거리 Coulomb 포함 E_inter 계산.",
    )

    @field_validator("e_intra_method")
    @classmethod
    def validate_e_intra_method(cls, v: str | None) -> str | None:
        return validate_submission_e_intra_method(v)


class BatchJobBinderCellJobResponse(BaseModel):
    """Status of a single batch Binder Cell job."""

    model_config = ConfigDict(title="BatchJobBinderCellJobResponse")

    exp_id: str
    binder_type: str
    structure_size: str
    temperature_k: float
    aging_state: str
    tier: str
    status: str
    error: str | None = None
    # Phase 5.1: additive DOE metadata
    additive_type: str | None = None
    additive_concentration: float = 0.0
    # v00.95.02: priority and similarity tracking
    priority: str = Field("medium", description="작업 우선순위")
    similar_existing: bool = Field(False, description="유사 실험 존재 여부")
    similar_experiment_ids: list[str] = Field(default_factory=list, description="유사 실험 ID 목록")


class BatchJobBinderCellResponse(BaseModel):
    """Response for batch Binder Cell creation/validation."""

    model_config = ConfigDict(title="BatchJobBinderCellResponse")

    batch_job_id: str
    total: int
    new: int
    duplicates: int
    submitted: int
    errors: int
    jobs: list[BatchJobBinderCellJobResponse]
    # v00.95.02: queue limits and similarity decision
    blocked: int = Field(0, description="큐 한계로 제출 대기 중인 작업 수")
    requires_similarity_decision: bool = Field(
        False, description="유사 실험 존재로 사용자 결정이 필요한지 여부"
    )
    similar_job_count: int = Field(0, description="유사 실험이 있는 작업 수")
    # v00.95.27: user-excluded jobs
    excluded: int = Field(0, description="사용자가 제외한 작업 수")
    # v00.99.22: FF eligibility
    ff_blocked_items: list[FFEligibilityItem] = Field(
        default_factory=list, description="FF-blocked additive/molecule items"
    )
    # v01.02.17: E_inter precision analysis recommendation
    e_inter_recommendation: EInterRecommendationResponse | None = Field(
        None, description="E_inter precision analysis recommendation for UI"
    )


# =============================================================================
# Batch Cancel / Delete
# =============================================================================


class BatchExperimentRequest(BaseModel):
    """Batch cancel or delete request."""

    exp_ids: list[str] = Field(..., min_length=1, description="Experiment IDs to process")


class BatchExperimentDetailItem(BaseModel):
    """Per-experiment result in a batch operation."""

    exp_id: str
    success: bool
    reason: str | None = None


class BatchExperimentResponse(BaseModel):
    """Batch cancel or delete response."""

    total: int = Field(description="Total experiments requested")
    succeeded: int = Field(default=0)
    skipped: int = Field(default=0)
    failed: int = Field(default=0)
    details: list[BatchExperimentDetailItem] = Field(default_factory=list)


# =============================================================================
# Single Molecule E_intra Batch Submission
# =============================================================================


class SingleMoleculeBatchRequest(BaseModel):
    """Request to submit single-molecule E_intra calculation batch."""

    model_config = ConfigDict(title="SingleMoleculeBatchRequest")

    selected_mol_id: str = Field(
        ...,
        min_length=1,
        description="Molecule ID from Database Molecules",
    )
    temperatures_k: list[float] = Field(
        default_factory=lambda: list(_DEFAULT_TEMPS),
        description="Temperatures to compute E_intra at",
    )
    ff_type: str = Field(
        "bulk_ff_gaff2",
        description="Deprecated — server resolves FF from molecule metadata. Kept for backward compat.",
    )
    e_intra_method: str | None = Field(
        None,
        description="Optional E_intra method override for new jobs. Defaults to settings.json.",
    )
    seed: int = Field(default_factory=generate_seed)
    force_recompute: bool = Field(False, description="Force recompute even if E_intra exists")

    @field_validator("e_intra_method")
    @classmethod
    def validate_single_molecule_e_intra_method(cls, v: str | None) -> str | None:
        return validate_submission_e_intra_method(v)


class SingleMoleculeBatchResponseItem(BaseModel):
    """Status of a single temperature submission."""

    temperature_K: float
    status: str  # "submitted", "skipped_existing", "failed"
    exp_id: str | None = None
    error: str | None = None
    error_type: str | None = None  # Exception class name on failure (debug aid)


class SingleMoleculeBatchResponse(BaseModel):
    """Response from single-molecule batch submission."""

    mol_id: str
    total: int
    submitted: int = 0
    skipped_existing: int = 0
    failed: int = 0
    items: list[SingleMoleculeBatchResponseItem] = Field(default_factory=list)
    resolved_ff_hint: str = Field(
        "gaff2", description="Resolved FF hint from server (gaff2 or interface_profile)"
    )
    resolved_ff_display_label: str = Field("GAFF2", description="Human-readable FF label")
