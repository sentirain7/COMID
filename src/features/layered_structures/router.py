"""Layered-structure composer routes (single job)."""

from fastapi import APIRouter, Query

from api.schemas import (
    LayeredAnalysis3DResponse,
    LayeredExperimentListResponse,
    LayeredStructurePreviewRequest,
    LayeredStructurePreviewResponse,
    LayeredStructureSubmitRequest,
    LayeredStructureSubmitResponse,
    LayerSourceListResponse,
    LibraryVisibility,
)
from contracts.schemas import LayerSourceType

from . import service

router = APIRouter(tags=["LayeredStructures"])


_VALID_STATUSES = {
    "pending",
    "queued",
    "building",
    "ready",
    "running",
    "analyzing",
    "completed",
    "failed",
    "cancelled",
    "timeout",
}


@router.get("/layered-structures", response_model=LayeredExperimentListResponse)
def list_layered_experiments_route(
    status: str | None = Query(
        None, description="Experiment status filter (optional, all if omitted)"
    ),
    limit: int = Query(200, ge=1, le=500),
):
    """List layered experiments for library."""
    if status is not None and status not in _VALID_STATUSES:
        from contracts.errors import ContractError, ErrorCode

        raise ContractError(
            ErrorCode.VALIDATION_ERROR,
            f"Invalid status '{status}'. Must be one of: {sorted(_VALID_STATUSES)}",
        )
    return service.list_layered_experiments(status=status, limit=limit)


@router.get(
    "/layered-structures/sources/{source_type}",
    response_model=LayerSourceListResponse,
)
async def list_layer_sources(
    source_type: str,
    limit: int = 100,
    visibility: LibraryVisibility = "library",
):
    from features.common.source_compat import normalize_source_type

    if source_type == "amorphous_cell":
        return await service.list_layer_sources_legacy(
            limit=limit,
            visibility=visibility,
        )
    normalized = normalize_source_type(source_type)
    try:
        st = LayerSourceType(normalized)
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=422,
            detail=f"Invalid source_type: {source_type}",
        ) from exc
    return await service.list_layer_sources(
        source_type=st,
        limit=limit,
        visibility=visibility,
    )


@router.post(
    "/layered-structures/preview",
    response_model=LayeredStructurePreviewResponse,
)
async def preview_layered_structure(request: LayeredStructurePreviewRequest):
    return await service.preview_layered_structure(request)


@router.post(
    "/layered-structures/submit",
    response_model=LayeredStructureSubmitResponse,
)
async def submit_layered_structure(request: LayeredStructureSubmitRequest):
    # 보완 #4 후속: replicate_seeds 지정 시 multi-seed replica group 자동 오케스트레이션
    # (미지정 시 단일 실험과 byte-identical).
    return await service.submit_layered_replicates(request)


@router.get(
    "/layered-structures/analysis/3d",
    response_model=LayeredAnalysis3DResponse,
)
def get_layered_analysis_3d_route(
    layer_types: list[str] | None = Query(None),
    crystal_materials: list[str] | None = Query(None),
    aging_states: list[str] | None = Query(None),
    temp_min: float | None = Query(None),
    temp_max: float | None = Query(None),
    limit: int = Query(500, ge=1, le=1000),
):
    """Aggregated layered experiment data for 3D multi-variable analysis."""
    return service.get_layered_analysis_3d(
        layer_types=layer_types,
        crystal_materials=crystal_materials,
        aging_states=aging_states,
        temp_min=temp_min,
        temp_max=temp_max,
        limit=limit,
    )
