"""Additive coverage analysis API router."""

from fastapi import APIRouter

from api.schemas import AdditiveCoverageResponse, GenerateWaveRequest
from features.additive_coverage import service

router = APIRouter(prefix="/additive-coverage", tags=["additive-coverage"])


@router.get("", response_model=AdditiveCoverageResponse)
async def get_coverage() -> AdditiveCoverageResponse:
    """Get additive coverage analysis report."""
    return service.get_coverage_report()


@router.post("/generate-wave")
async def generate_wave(request: GenerateWaveRequest) -> dict:
    """Generate and optionally submit an exploration wave from coverage gaps."""
    return service.generate_exploration_wave(
        max_jobs=request.max_jobs,
        additive_types=request.additive_types,
        auto_submit=request.auto_submit,
    )
