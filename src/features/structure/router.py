"""Structure routes."""

from fastapi import APIRouter

from . import service as structure_service

router = APIRouter(tags=["Structure"])


@router.get("/experiments/{exp_id}/structure/{stage}", tags=["Structure"])
async def get_structure_xyz(exp_id: str, stage: str):
    return await structure_service.get_structure_xyz(exp_id=exp_id, stage=stage)


@router.get("/experiments/{exp_id}/available-stages", tags=["Structure"])
async def get_available_stages_endpoint(exp_id: str):
    return await structure_service.get_available_stages(exp_id)
