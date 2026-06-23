"""E_inter 정밀 분석 API 라우터."""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .service import DEFAULT_E_INTER_COMPUTE_SERVICE

router = APIRouter(prefix="/e-inter", tags=["E_inter Analysis"])


class RecommendationRequest(BaseModel):
    """Recommendation request body."""

    workflow: str
    tier: str = "screening"
    layer_count: int = 1
    has_additive: bool = False
    has_water_ion: bool = False
    estimated_atoms: int = 0
    selected_metrics: list[str] = Field(default_factory=list)


class CreateJobRequest(BaseModel):
    """Create CPU rerun job request body."""

    metrics: list[str] | None = None


@router.post("/recommendation")
def get_recommendation(request: RecommendationRequest) -> dict[str, Any]:
    """Get E_inter precision analysis recommendation."""
    return DEFAULT_E_INTER_COMPUTE_SERVICE.get_recommendation(
        workflow=request.workflow,
        tier=request.tier,
        layer_count=request.layer_count,
        has_additive=request.has_additive,
        has_water_ion=request.has_water_ion,
        estimated_atoms=request.estimated_atoms,
        selected_metrics=tuple(request.selected_metrics),
    )


@router.post("/jobs/{exp_id}", status_code=202)
def create_cpu_rerun_job(exp_id: str, request: CreateJobRequest | None = None) -> dict[str, Any]:
    """Create CPU rerun job for completed experiment."""
    from contracts.errors import ContractError, ErrorCode

    try:
        metrics = request.metrics if request else None
        return DEFAULT_E_INTER_COMPUTE_SERVICE.create_cpu_rerun_job(
            exp_id=exp_id,
            metrics=metrics,
            trigger="manual",
        )
    except ContractError as e:
        if e.code == ErrorCode.DUPLICATE_RECORD:
            raise HTTPException(status_code=409, detail="Active analysis job already exists") from e
        if e.code == ErrorCode.RECORD_NOT_FOUND:
            raise HTTPException(status_code=404, detail=str(e)) from e
        if e.code == ErrorCode.VALIDATION_ERROR:
            raise HTTPException(status_code=400, detail=str(e)) from e
        raise
    except Exception:
        raise


@router.get("/jobs/{exp_id}")
def get_job_status(exp_id: str) -> dict[str, Any]:
    """Get analysis job status for experiment."""
    return DEFAULT_E_INTER_COMPUTE_SERVICE.get_job_status(exp_id)
