"""GPU, recovery, settings, MLOps, benchmark, and additive-coverage schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.schemas.e_intra_method import validate_submission_e_intra_method

# =============================================================================
# GPU Resource Models
# =============================================================================


class GPUInfoResponse(BaseModel):
    """GPU information.

    Multi-job-per-GPU (N=6/MPS, v01.05.54) adds ``jobs``/``slots_used``/
    ``slots_total``. These are kept here with defaults so that if
    ``GPUStatsResponse.gpus`` is ever typed as ``list[GPUInfoResponse]`` the
    fields survive serialization rather than being silently stripped (which
    would hide the multi-job display). ``job`` remains for backward-compat.
    """

    model_config = ConfigDict(title="GPUInfoResponse")

    id: int
    name: str
    utilization: float
    memory: float
    status: str
    job: str | None = None
    jobs: list[str] = Field(default_factory=list)
    slots_used: int = 0
    slots_total: int = 1
    # Hardware identity + eligibility (additive). ``eligible=False`` marks a
    # sub-threshold GPU (e.g. RTX 3050) that is shown/selectable but capped at 1
    # job. ``uuid`` is the routing identity. Defaults keep older clients working.
    uuid: str | None = None
    eligible: bool = True
    kind: str = "whole_gpu"


class GPUStatsResponse(BaseModel):
    """GPU statistics response.

    ``gpus`` is intentionally an untyped ``list`` of GPU dicts (built by
    ``gpu_stats_service``) so additive fields pass through without a schema
    edit. ``GPUInfoResponse`` documents the per-GPU shape and is the safe target
    if the list is ever typed.
    """

    model_config = ConfigDict(title="GPUStatsResponse")

    gpus: list
    total: int
    available: int
    busy: int


# =============================================================================
# Recovery Models
# =============================================================================


class RecoveryCheckResponse(BaseModel):
    """Quick recovery check response."""

    model_config = ConfigDict(title="RecoveryCheckResponse")

    needs_recovery: bool
    candidate_count: int
    message: str


class ExecuteRecoveryRequest(BaseModel):
    """Request to execute a recovery action."""

    model_config = ConfigDict(title="ExecuteRecoveryRequest")

    exp_id: str
    action: str


# =============================================================================
# MLOps Schemas (Phase 8)
# =============================================================================


class MLModelVersionResponse(BaseModel):
    """Single model version summary."""

    version_id: str
    status: str
    model_type: str
    feature_set_version: str
    actual_feature_set: str | None = None
    target_names: list[str]
    per_target_feature_sets: dict[str, str] | None = None
    feature_schema_hash: str | None = None
    training_manifest_hash: str | None = None
    capability_manifest: dict[str, Any] | None = None
    training_samples: int
    calibration_ece: float | None = None
    test_metrics: dict[str, dict[str, float]] | None = None
    recommendation_metrics: dict[str, float] | None = None
    created_at: str | None = None
    promoted_at: str | None = None
    model_artifact_path: str
    triggered_by: str | None = None
    retraining_reason: str | None = None


class MLModelHistoryResponse(BaseModel):
    """Model registry history response."""

    models: list[MLModelVersionResponse]


class DriftCheckResponse(BaseModel):
    """Drift check response payload."""

    drift_type: str
    feature_drift_fraction: float
    rmse_drift_pct: float
    page_hinkley_detected: bool
    should_retrain: bool
    checked_at: str | None = None
    new_samples: int | None = None
    drifted_targets: list[str] = []


class RetrainRequest(BaseModel):
    """Manual retraining request.

    PR 2 (Codex Round 6): ``e_intra_method`` overrides the CED label method
    for this retraining run.  ``None`` (default) falls back to the current
    champion's method via ``training_config_json["e_intra_method"]``.  Set
    explicitly to bootstrap the first Method 1a challenger or to perform a
    deliberate cutover.
    """

    force: bool = False
    triggered_by: str = Field(default="api")
    e_intra_method: str | None = None


class RetrainResponse(BaseModel):
    """Manual retraining response."""

    success: bool
    version_id: str | None = None
    trigger_reason: str
    training_samples: int
    promoted: bool
    duration_seconds: float
    comparison: dict | None = None


# =============================================================================
# Benchmark Models
# =============================================================================


class BenchmarkValidationItem(BaseModel):
    """Single metric validation result."""

    exp_id: str
    binder_type: str
    temperature_k: float
    metric_name: str
    simulated_value: float | None = None
    reference_value: float | None = None
    relative_error: float | None = None
    tolerance: float
    passed: bool | None = None


class BenchmarkReportResponse(BaseModel):
    """Aggregate benchmark validation report."""

    total_checks: int
    passed: int
    failed: int
    missing_data: int
    pass_rate: float
    all_gates_passed: bool
    per_binder: dict = Field(default_factory=dict)
    per_metric: dict = Field(default_factory=dict)
    validations: list[BenchmarkValidationItem] = Field(default_factory=list)


class BenchmarkExpIdsResponse(BaseModel):
    """Expected experiment IDs for benchmark."""

    n_ids: int
    exp_ids: list[str]


# =============================================================================
# Settings Models
# =============================================================================


class SettingsUpdateRequest(BaseModel):
    """Validated settings update request."""

    model_config = ConfigDict(title="SettingsUpdateRequest")

    llm_provider: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    gpu_enabled: bool | None = None
    selected_gpus: list[int] | None = None
    max_concurrent_jobs: int | None = None
    default_tier: str | None = None
    default_e_intra_method: str | None = None
    auto_retry_on_failure: bool | None = None
    refresh_interval_queue_ms: int | None = None
    refresh_interval_gpu_ms: int | None = None
    refresh_interval_system_ms: int | None = None

    @field_validator("llm_provider")
    @classmethod
    def validate_llm_provider(cls, v: str | None) -> str | None:
        if v is not None and v not in ("mock", "openai", "anthropic"):
            raise ValueError(f"Invalid llm_provider: {v}")
        return v

    @field_validator("default_e_intra_method")
    @classmethod
    def validate_default_e_intra_method(cls, v: str | None) -> str | None:
        return validate_submission_e_intra_method(v)


class SettingsResponse(BaseModel):
    """GET /settings response shape."""

    model_config = ConfigDict(title="SettingsResponse")

    llm_provider: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    gpu_enabled: bool | None = None
    selected_gpus: list[int] | None = None
    max_concurrent_jobs: int | None = None
    default_tier: str | None = None
    default_e_intra_method: str | None = None
    auto_retry_on_failure: bool | None = None
    refresh_interval_queue_ms: int | None = None
    refresh_interval_gpu_ms: int | None = None
    refresh_interval_system_ms: int | None = None


# ---------------------------------------------------------------------------
# Additive Coverage
# ---------------------------------------------------------------------------


class AdditiveCoverageResponse(BaseModel):
    """Additive coverage analysis report."""

    model_config = ConfigDict(title="AdditiveCoverageResponse")

    total_catalog: int = 0
    tested_count: int = 0
    untested_count: int = 0
    coverage_fraction: float = 0.0
    gaps: list[dict[str, Any]] = Field(default_factory=list)
    ranked_gaps: list[dict[str, Any]] = Field(default_factory=list)


class GenerateWaveRequest(BaseModel):
    """Request to generate an exploration wave from coverage gaps."""

    model_config = ConfigDict(title="GenerateWaveRequest")

    max_jobs: int = 10
    additive_types: list[str] | None = None
    auto_submit: bool = False
