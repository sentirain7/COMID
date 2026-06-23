"""Protocol routes."""

from fastapi import APIRouter, Query

from api.schemas import DefaultStagesResponse

from . import service as protocol_service

router = APIRouter(tags=["Protocol"])


@router.get(
    "/protocol/default-stages/{tier}", response_model=DefaultStagesResponse, tags=["Protocol"]
)
async def get_default_stages(tier: str, include_optional: bool = Query(False)):
    return await protocol_service.get_default_stages(tier, include_optional=include_optional)
