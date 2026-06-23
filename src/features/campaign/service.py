"""Campaign service for staged MD data collection waves."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from api.deps import get_aging_config
from api.schemas import (
    CampaignCreateRequest,
    CampaignDetailResponse,
    CampaignListResponse,
    CampaignProgressResponse,
    CampaignSummary,
    CampaignWaveStatusResponse,
    CampaignWaveSubmitRequest,
)
from api.utils.time_utils import iso_or_none as _iso
from contracts.errors import ContractError, ErrorCode
from contracts.schema_enums import CampaignStatus, ExperimentStatus, WaveStatus
from database.models import CampaignModel, CampaignWaveModel
from database.repositories.campaign_repo import CampaignRepository
from features.common import run_in_session, run_in_session_commit
from features.experiments.validation import validate_additive_mol_ids, validate_binder_types
from orchestrator.batch_job_binder_cell import (
    BatchJobBinderCellResult,
)
from orchestrator.temperature_scan import (
    PRIORITY_TEMPERATURES,
    STANDARD_TEMPERATURES,
    additive_doe_scan,
    full_screening_scan,
)

_DEFAULT_CAMPAIGN_NAME = "pilot_closed_loop"
_ACTIVE_EXPERIMENT_STATUSES = {
    ExperimentStatus.QUEUED.value,
    ExperimentStatus.BUILDING.value,
    ExperimentStatus.READY.value,
    ExperimentStatus.RUNNING.value,
    ExperimentStatus.ANALYZING.value,
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _normalize_counts(raw: dict[str, int] | None) -> dict[str, int]:
    normalized: dict[str, int] = {}
    for key, value in (raw or {}).items():
        normalized[str(key)] = int(value or 0)
    return normalized


def _default_wave_spec(request: CampaignWaveSubmitRequest):
    wave_no = request.wave_no
    if wave_no == 1:
        return full_screening_scan(binder_types=request.binder_types or None)
    if wave_no == 2:
        return additive_doe_scan(
            additive_types=request.additive_types or None,
            additive_concentrations=request.additive_concentrations or None,
        )
    if wave_no == 3:
        if not request.additive_types:
            raise ContractError(
                ErrorCode.INVALID_REQUEST,
                "Wave 3 requires additive_types (top-performing additives from Wave 2)",
            )
        from orchestrator.batch_job_binder_cell import BatchJobBinderCellSpec

        return BatchJobBinderCellSpec(
            binder_types=request.binder_types or ["AAK1", "AAM1"],
            structure_sizes=["X1"],
            temperatures_k=STANDARD_TEMPERATURES,
            aging_states=["non_aging"],
            tier="screening",
            temperature_priority=PRIORITY_TEMPERATURES,
            additive_types=request.additive_types,
            additive_concentrations=request.additive_concentrations or [5.0],
        )
    if wave_no == 4:
        if not request.additive_types:
            raise ContractError(
                ErrorCode.INVALID_REQUEST,
                "Wave 4 requires additive_types (remaining catalog additives to cover)",
            )
        from orchestrator.batch_job_binder_cell import BatchJobBinderCellSpec

        return BatchJobBinderCellSpec(
            binder_types=request.binder_types or ["AAA1"],
            structure_sizes=["X1"],
            temperatures_k=PRIORITY_TEMPERATURES,
            aging_states=["non_aging", "short_aging"],
            tier="screening",
            temperature_priority=PRIORITY_TEMPERATURES,
            additive_types=request.additive_types,
            additive_concentrations=request.additive_concentrations or [5.0],
        )
    raise ContractError(ErrorCode.INVALID_REQUEST, f"Unsupported wave: {wave_no}")


def _spec_to_payload(spec) -> dict[str, object]:
    if hasattr(spec, "__dict__"):
        return {
            "binder_types": list(spec.binder_types),
            "structure_sizes": list(spec.structure_sizes),
            "temperatures_k": list(spec.temperatures_k),
            "aging_states": list(spec.aging_states),
            "tier": spec.tier,
            "ff_type": spec.ff_type,
            "temperature_priority": list(spec.temperature_priority),
            "additive_types": list(spec.additive_types),
            "additive_concentrations": list(spec.additive_concentrations),
        }
    return {}


def _submit_wave_spec(session, spec) -> BatchJobBinderCellResult:
    from api.deps import get_job_manager
    from database.repositories.experiment_repo import ExperimentRepository
    from orchestrator.batch_job_binder_cell import select_batch_runner_cls

    repo = ExperimentRepository(session)
    runner = select_batch_runner_cls(spec)(experiment_repo=repo, job_manager=get_job_manager())
    return runner.submit(spec)


def _derive_wave_status(wave: CampaignWaveModel, experiment_counts: dict[str, int]) -> WaveStatus:
    if int(wave.error_jobs or 0) > 0 and int(wave.submitted_jobs or 0) == 0:
        return WaveStatus.ERROR
    if any(experiment_counts.get(key, 0) > 0 for key in _ACTIVE_EXPERIMENT_STATUSES):
        return WaveStatus.RUNNING
    if int(wave.total_jobs or 0) > 0 and experiment_counts.get("completed", 0) >= int(
        wave.total_jobs or 0
    ) - int(wave.error_jobs or 0):
        return WaveStatus.COMPLETED
    if int(wave.submitted_jobs or 0) > 0 or int(wave.duplicate_jobs or 0) > 0:
        return WaveStatus.SUBMITTED
    try:
        return WaveStatus(str(wave.status or WaveStatus.DRAFT.value))
    except ValueError:
        return WaveStatus.DRAFT


def _derive_campaign_status(
    campaign: CampaignModel,
    wave_responses: list[CampaignWaveStatusResponse],
) -> CampaignStatus:
    if wave_responses and all(w.status == WaveStatus.COMPLETED for w in wave_responses):
        return CampaignStatus.COMPLETED
    if any(w.status == WaveStatus.RUNNING for w in wave_responses):
        return CampaignStatus.RUNNING
    if wave_responses:
        return CampaignStatus.ACTIVE

    raw = str(campaign.status or CampaignStatus.DRAFT.value)
    try:
        return CampaignStatus(raw)
    except ValueError:
        return CampaignStatus.DRAFT


def _wave_to_response(
    campaign_id: str,
    wave: CampaignWaveModel,
    counts_by_wave_id: dict[int, dict[str, int]],
) -> CampaignWaveStatusResponse:
    experiment_counts = _normalize_counts(counts_by_wave_id.get(int(wave.id), {}))
    return CampaignWaveStatusResponse(
        campaign_id=campaign_id,
        wave_id=int(wave.id),
        wave_no=int(wave.wave_no),
        status=_derive_wave_status(wave, experiment_counts),
        total_jobs=int(wave.total_jobs or 0),
        new_jobs=int(wave.new_jobs or 0),
        duplicate_jobs=int(wave.duplicate_jobs or 0),
        submitted_jobs=int(wave.submitted_jobs or 0),
        error_jobs=int(wave.error_jobs or 0),
        experiment_counts=experiment_counts,
        spec=dict(wave.spec_json or {}),
        submitted_at=_iso(wave.submitted_at),
    )


def _campaign_summary_from_waves(
    campaign: CampaignModel,
    wave_responses: list[CampaignWaveStatusResponse],
) -> CampaignSummary:
    return CampaignSummary(
        campaign_id=str(campaign.id),
        name=str(campaign.name),
        status=_derive_campaign_status(campaign, wave_responses),
        wave_count=len(wave_responses),
        total_experiments=sum(w.total_jobs for w in wave_responses),
        completed_experiments=sum(
            w.experiment_counts.get(ExperimentStatus.COMPLETED.value, 0) for w in wave_responses
        ),
    )


def _campaign_detail_response(
    campaign: CampaignModel,
    wave_responses: list[CampaignWaveStatusResponse],
) -> CampaignDetailResponse:
    summary = _campaign_summary_from_waves(campaign, wave_responses)
    return CampaignDetailResponse(
        **summary.model_dump(),
        waves=wave_responses,
        created_at=_iso(campaign.created_at),
    )


def _validate_wave_inputs(request: CampaignWaveSubmitRequest, session) -> None:
    validate_binder_types(request.binder_types, config=get_aging_config())
    validate_additive_mol_ids(request.additive_types, session=session)


def _load_wave_responses(
    repo: CampaignRepository,
    campaign_id: str,
    waves: list[CampaignWaveModel],
) -> list[CampaignWaveStatusResponse]:
    counts_by_wave_id = repo.get_status_counts_by_wave_ids([int(wave.id) for wave in waves])
    return [_wave_to_response(campaign_id, wave, counts_by_wave_id) for wave in waves]


def _matches_campaign_status_filter(
    summary: CampaignSummary,
    status: CampaignStatus | None,
) -> bool:
    if status is None:
        return True
    return summary.status == status


def create_campaign(request: CampaignCreateRequest) -> CampaignDetailResponse:
    """Create a campaign explicitly."""

    def _create(session):
        repo = CampaignRepository(session)
        campaign_id = request.campaign_id or f"camp-{uuid4().hex[:12]}"
        if repo.get_campaign(campaign_id) is not None:
            raise ContractError(
                ErrorCode.DUPLICATE_RECORD,
                f"Campaign already exists: {campaign_id}",
                {"campaign_id": campaign_id},
            )
        metadata: dict[str, object] = {"source": "campaign_service"}
        if request.description:
            metadata["description"] = request.description
        campaign = repo.create_campaign(
            campaign_id=campaign_id,
            name=request.name,
            metadata_json=metadata,
            status=CampaignStatus.DRAFT,
        )
        return _campaign_detail_response(campaign, [])

    return run_in_session_commit(_create)


def list_campaigns(
    *,
    status: CampaignStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> CampaignListResponse:
    """List campaigns with aggregate progress."""

    def _list(session):
        repo = CampaignRepository(session)
        campaigns = repo.list_campaigns()
        waves_by_campaign = repo.list_waves_for_campaign_ids([str(c.id) for c in campaigns])
        all_wave_ids = [int(wave.id) for waves in waves_by_campaign.values() for wave in waves]
        counts_by_wave_id = repo.get_status_counts_by_wave_ids(all_wave_ids)

        summaries: list[CampaignSummary] = []
        for campaign in campaigns:
            waves = waves_by_campaign.get(str(campaign.id), [])
            wave_responses = [
                _wave_to_response(str(campaign.id), wave, counts_by_wave_id) for wave in waves
            ]
            summary = _campaign_summary_from_waves(campaign, wave_responses)
            if _matches_campaign_status_filter(summary, status):
                summaries.append(summary)
        total = len(summaries)
        paged_summaries = summaries[offset : offset + limit]
        return CampaignListResponse(
            campaigns=paged_summaries,
            total=total,
            limit=limit,
            offset=offset,
            status_filter=status,
        )

    return run_in_session(_list)


def get_campaign_detail(campaign_id: str) -> CampaignDetailResponse:
    """Return detailed campaign information."""

    def _load(session):
        repo = CampaignRepository(session)
        campaign = repo.get_campaign(campaign_id)
        if campaign is None:
            raise ContractError(ErrorCode.RECORD_NOT_FOUND, "Campaign not found")
        waves = repo.list_waves(campaign_id)
        wave_responses = _load_wave_responses(repo, campaign_id, waves)
        return _campaign_detail_response(campaign, wave_responses)

    return run_in_session(_load)


def submit_wave(request: CampaignWaveSubmitRequest) -> CampaignWaveStatusResponse:
    """Create or submit a campaign wave using existing batch runners."""

    def _submit(session):
        repo = CampaignRepository(session)
        _validate_wave_inputs(request, session)
        spec = _default_wave_spec(request)
        campaign_id = request.campaign_id or f"camp-{uuid4().hex[:12]}"
        campaign = repo.get_campaign(campaign_id)
        if campaign is None:
            campaign = repo.create_campaign(
                campaign_id=campaign_id,
                name=request.campaign_name or _DEFAULT_CAMPAIGN_NAME,
                metadata_json={"source": "campaign_service"},
                status=CampaignStatus.DRAFT,
            )

        existing_wave = repo.get_wave_by_campaign_and_no(str(campaign.id), request.wave_no)
        if existing_wave is not None:
            raise ContractError(
                ErrorCode.DUPLICATE_RECORD,
                f"Wave {request.wave_no} already exists for campaign {campaign.id}",
                {"campaign_id": campaign.id, "wave_no": request.wave_no},
            )

        wave = repo.create_wave(
            campaign_id=str(campaign.id),
            wave_no=request.wave_no,
            spec_json=_spec_to_payload(spec),
            status=WaveStatus.DRAFT,
        )
        result = _submit_wave_spec(session, spec)
        repo.update_wave_submission(
            int(wave.id),
            status=WaveStatus.SUBMITTED,
            total_jobs=result.total,
            new_jobs=result.new,
            duplicate_jobs=result.duplicates,
            submitted_jobs=result.submitted,
            error_jobs=result.errors,
            submitted_at=_utc_now(),
            updated_at=_utc_now(),
        )

        for job in result.jobs:
            repo.create_experiment_link(
                wave_id=int(wave.id),
                exp_id=job.exp_id,
                submission_status=job.status,
                error_message=job.error,
            )

        campaign.status = CampaignStatus.ACTIVE.value  # type: ignore[assignment]
        campaign.updated_at = _utc_now()  # type: ignore[assignment]
        session.flush()

        refreshed_wave = repo.get_wave(int(wave.id)) or wave
        counts_by_wave_id = repo.get_status_counts_by_wave_ids([int(refreshed_wave.id)])
        return _wave_to_response(str(campaign.id), refreshed_wave, counts_by_wave_id)

    return run_in_session_commit(_submit)


def get_progress(campaign_id: str | None = None) -> CampaignProgressResponse:
    """Return campaign progress summary."""

    def _load(session):
        repo = CampaignRepository(session)
        campaign = repo.get_campaign(campaign_id) if campaign_id else repo.get_latest_campaign()
        if campaign is None:
            raise ContractError(ErrorCode.RECORD_NOT_FOUND, "Campaign not found")

        waves = repo.list_waves(str(campaign.id))
        wave_responses = _load_wave_responses(repo, str(campaign.id), waves)
        summary = _campaign_summary_from_waves(campaign, wave_responses)
        return CampaignProgressResponse(
            campaign_id=summary.campaign_id,
            name=summary.name,
            status=summary.status,
            total_waves=summary.wave_count,
            total_experiments=summary.total_experiments,
            completed_experiments=summary.completed_experiments,
            waves=wave_responses,
        )

    return run_in_session(_load)
