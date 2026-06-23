"""Experiment routes."""

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse, Response

from api.schemas import (
    BatchExperimentRequest,
    BatchExperimentResponse,
    DependentMoleculeExperimentRequest,
    DependentMoleculeExperimentResponse,
    ExperimentRequest,
    ExperimentResponse,
    MoleculeCompositionPreviewRequest,
    MoleculeCompositionPreviewResponse,
    MoleculeExperimentRequest,
    MoleculeExperimentResponse,
    TypingChargePrecomputeRequest,
    TypingChargePrecomputeResponse,
)
from api.schemas.experiments import (
    ExperimentDetailResponse,
    ExperimentListResponse,
    SingleMoleculeBatchRequest,
    SingleMoleculeBatchResponse,
)

from . import service as experiments_service
from .export import export_experiments_csv, export_experiments_xlsx, is_xlsx_available

router = APIRouter(tags=["Experiments"])


def _validate_e_intra_method(value: str | None) -> str | None:
    if value is None:
        return None
    from contracts.schema_enums import EIntraMethod, normalize_e_intra_method

    try:
        return normalize_e_intra_method(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown e_intra_method='{value}'. Allowed: {[m.value for m in EIntraMethod]}",
        ) from exc


@router.get("/experiments/export/formats", tags=["Experiments"])
async def get_export_formats():
    """Get available export formats.

    Returns:
        Dict with available formats and their status
    """
    return {
        "formats": {
            "csv": {"available": True},
            "xlsx": {"available": is_xlsx_available()},
        }
    }


@router.post("/experiments", response_model=ExperimentResponse, tags=["Experiments"])
async def submit_experiment(request: ExperimentRequest):
    return await experiments_service.submit_experiment(request)


@router.get("/experiments/export", tags=["Experiments"])
async def export_experiments(
    format: str = "csv",
    status: str | None = None,
    tier: str | None = None,
    study_type: str | None = None,
    additive_mol_id: str | None = None,
    e_intra_method: str | None = None,
    limit: int = 1000,
):
    """Export experiments to CSV or XLSX.

    Args:
        format: Export format ('csv' or 'xlsx')
        status: Optional status filter
        tier: Optional tier filter
        limit: Maximum number of experiments (default 1000)

    Returns:
        CSV or XLSX file download
    """
    from datetime import datetime

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if format.lower() == "xlsx":
        content = export_experiments_xlsx(
            status=status,
            tier=tier,
            study_type=study_type,
            additive_mol_id=additive_mol_id,
            e_intra_method=e_intra_method,
            limit=limit,
        )
        filename = f"experiments_{timestamp}.xlsx"
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # Default to CSV
    content = export_experiments_csv(
        status=status,
        tier=tier,
        study_type=study_type,
        additive_mol_id=additive_mol_id,
        e_intra_method=e_intra_method,
        limit=limit,
    )
    filename = f"experiments_{timestamp}.csv"
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/experiments/batch/cancel",
    response_model=BatchExperimentResponse,
    tags=["Experiments"],
)
async def batch_cancel_experiments(request: BatchExperimentRequest):
    """Cancel multiple experiments in a single request."""
    return await experiments_service.batch_cancel_experiments(request.exp_ids)


@router.post(
    "/experiments/batch/delete",
    response_model=BatchExperimentResponse,
    tags=["Experiments"],
)
async def batch_delete_experiments(request: BatchExperimentRequest):
    """Delete multiple experiments in a single request."""
    return await experiments_service.batch_delete_experiments(request.exp_ids)


@router.post(
    "/experiments/batch/retry",
    response_model=BatchExperimentResponse,
    tags=["Experiments"],
)
async def batch_retry_experiments(request: BatchExperimentRequest):
    """Retry multiple experiments in a single request."""
    return await experiments_service.batch_retry_experiments(request.exp_ids)


@router.get("/experiments/defaults", tags=["Experiments"])
async def get_experiment_defaults():
    """Return default configuration values (temperature SSOT, etc.)."""
    from contracts.policies.temperature import (
        AVAILABLE_TEMPERATURE_OPTIONS_K,
        DEFAULT_BINDER_CELL_BATCH_TEMPERATURES_K,
        DEFAULT_TEMPERATURE_PRIORITY_K,
    )

    return {
        "temperatures_k": DEFAULT_BINDER_CELL_BATCH_TEMPERATURES_K,
        "temperature_priority": DEFAULT_TEMPERATURE_PRIORITY_K,
        "available_temperature_options_k": AVAILABLE_TEMPERATURE_OPTIONS_K,
    }


@router.get("/experiments", response_model=ExperimentListResponse, tags=["Experiments"])
async def list_experiments(
    status: str | None = None,
    tier: str | None = None,
    limit: int = 100,
    exclude_layered: bool = False,
    study_type: str | None = None,
    additive_mol_id: str | None = None,
    temperature_min: float | None = None,
    temperature_max: float | None = None,
    additive_type: str | None = None,
    e_intra_method: str | None = None,
):
    return await experiments_service.list_experiments(
        status=status,
        tier=tier,
        limit=limit,
        exclude_layered=exclude_layered,
        study_type=study_type,
        additive_mol_id=additive_mol_id,
        temperature_min=temperature_min,
        temperature_max=temperature_max,
        additive_type=additive_type,
        e_intra_method=_validate_e_intra_method(e_intra_method),
    )


@router.get("/experiments/filter-options", tags=["Experiments"])
async def get_experiment_filter_options():
    """Return distinct values for client-side filter dropdowns."""
    return await experiments_service.get_experiment_filter_options()


@router.get("/experiments/{exp_id}", response_model=ExperimentDetailResponse, tags=["Experiments"])
async def get_experiment(exp_id: str):
    return await experiments_service.get_experiment(exp_id)


@router.post(
    "/experiments/single-molecule/batch",
    response_model=SingleMoleculeBatchResponse,
    tags=["Experiments", "Single Molecule"],
)
async def submit_single_molecule_batch(request: SingleMoleculeBatchRequest):
    """Submit single-molecule E_intra computation batch (mol × temperatures)."""
    from features.experiments.single_molecule import submit_single_molecule_batch as _submit

    return await _submit(request)


@router.delete("/experiments/{exp_id}", tags=["Experiments"])
async def delete_experiment(exp_id: str):
    return await experiments_service.delete_experiment(exp_id)


@router.post("/experiments/{exp_id}/cancel", tags=["Experiments"])
async def cancel_experiment(exp_id: str):
    return await experiments_service.cancel_experiment(exp_id)


@router.post("/experiments/{exp_id}/retry", tags=["Experiments"])
async def retry_experiment(exp_id: str):
    return await experiments_service.retry_experiment(exp_id)


@router.get("/experiments/{exp_id}/thermo", tags=["Experiments"])
async def get_experiment_thermo(exp_id: str):
    return await experiments_service.get_experiment_thermo(exp_id)


@router.post(
    "/experiments/molecule-based", response_model=MoleculeExperimentResponse, tags=["Experiments"]
)
async def submit_molecule_experiment(request: MoleculeExperimentRequest):
    return await experiments_service.submit_molecule_experiment(request)


@router.post(
    "/experiments/molecule-based/dependent",
    response_model=DependentMoleculeExperimentResponse,
    tags=["Experiments"],
)
async def submit_dependent_molecule_experiment(request: DependentMoleculeExperimentRequest):
    return await experiments_service.submit_dependent_molecule_experiment(request)


@router.post(
    "/experiments/molecule-based/preview",
    response_model=MoleculeCompositionPreviewResponse,
    tags=["Experiments"],
)
async def preview_molecule_composition(request: MoleculeCompositionPreviewRequest):
    return await experiments_service.preview_molecule_composition(request)


@router.post(
    "/experiments/molecule-based/check-typing-readiness",
    response_model=TypingChargePrecomputeResponse,
    tags=["Experiments"],
)
async def check_typing_readiness(request: TypingChargePrecomputeRequest):
    """Observe-only: artifact 준비 상태 확인 (생성/executor 호출 없음).

    - organic curated: is_artifact_ready() 만 사용
    - inorganic/ionic/water: resolve_ff_hint() / profile activation metadata만 확인
    - 생성, cache warm-up, typing assignment는 prepare endpoint 책임
    """
    return await experiments_service.check_typing_charge_readiness(request)


@router.post(
    "/experiments/molecule-based/prepare-typing-charge",
    status_code=202,
    tags=["Experiments"],
)
async def prepare_typing_charge_endpoint(
    request: TypingChargePrecomputeRequest,
    background_tasks: BackgroundTasks,
):
    """Background job: 선택된 분자의 artifact 생성 시작.

    202 Accepted 즉시 반환. /artifacts/batch-progress로 진행 상태 polling.
    batch_kind="typing_prepare"로 구분됨.
    """
    from features.molecules.artifact_service import acquire_batch_slot, get_batch_progress

    # 다른 batch 실행 중이면 409 반환
    if not acquire_batch_slot("typing_prepare", "baseline"):
        snapshot = get_batch_progress()
        raise HTTPException(
            status_code=409,
            detail={
                "message": "another batch is already running",
                "batch_kind": snapshot.get("batch_kind"),
            },
        )

    # request를 dict로 변환 (Pydantic → dict for background task)
    molecule_counts = [mc.model_dump() for mc in request.molecule_counts]
    additives = [a.model_dump() for a in request.additives] if request.additives else None

    # ⚠️ 동기 함수를 background task로 추가 (async def가 아님)
    background_tasks.add_task(
        experiments_service.prepare_typing_charge_background,
        molecule_counts,
        additives,
        request.ff_type,
        getattr(request, "aging_state", "non_aging") or "non_aging",
    )

    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "batch_kind": "typing_prepare",
            "message": "Artifact preparation started. Poll /artifacts/batch-progress.",
        },
    )


@router.post(
    "/experiments/molecule-based/precompute-typing-charge",
    response_model=TypingChargePrecomputeResponse,
    tags=["Experiments"],
    deprecated=True,
)
async def precompute_typing_charge(request: TypingChargePrecomputeRequest):
    """[DEPRECATED] Use /prepare-typing-charge for background job.

    ⚠️ submit/validate/frontend 자동 제출 경로에서 절대 호출하지 않음.
    기존 스크립트 호환성을 위해만 유지.
    """
    return await experiments_service.precompute_typing_charge(request)
