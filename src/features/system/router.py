"""System/settings/resources routes."""

from fastapi import APIRouter

from api.schemas import GPUStatsResponse, SettingsResponse, SettingsUpdateRequest

from . import service as system_service

router = APIRouter(tags=["System"])


@router.get("/system/stats", tags=["System"])
async def get_system_stats():
    return await system_service.get_system_stats()


@router.get("/settings", response_model=SettingsResponse, tags=["Settings"])
async def get_settings():
    return await system_service.get_settings()


@router.put("/settings", tags=["Settings"])
async def update_settings(data: SettingsUpdateRequest):
    return await system_service.update_settings(data.model_dump(exclude_none=True))


@router.get("/resources/gpus", response_model=GPUStatsResponse, tags=["Resources"])
async def get_gpu_stats():
    return await system_service.get_gpu_stats()


@router.get("/system/lammps-caps", tags=["System"])
async def get_lammps_caps():
    """Get detailed LAMMPS binary capability information."""
    return await system_service.get_lammps_caps()
