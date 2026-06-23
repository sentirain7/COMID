"""Campaign API routes."""

from typing import Annotated

from fastapi import APIRouter, Query

from api.schemas import (
    CampaignCreateRequest,
    CampaignDetailResponse,
    CampaignListResponse,
    CampaignProgressResponse,
    CampaignWaveStatusResponse,
    CampaignWaveSubmitRequest,
)
from contracts.schema_enums import CampaignStatus

from . import service

router = APIRouter(tags=["Campaigns"])


@router.post("/campaigns", response_model=CampaignDetailResponse)
async def create_campaign(request: CampaignCreateRequest):
    """Create a campaign explicitly."""
    return service.create_campaign(request)


@router.get("/campaigns", response_model=CampaignListResponse)
async def list_campaigns(
    status: CampaignStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """List campaigns."""
    return service.list_campaigns(status=status, limit=limit, offset=offset)


@router.get("/campaigns/progress", response_model=CampaignProgressResponse)
async def get_campaign_progress(campaign_id: str | None = None):
    """Get campaign progress for a specific or latest campaign."""
    return service.get_progress(campaign_id=campaign_id)


@router.get("/campaigns/{campaign_id}", response_model=CampaignDetailResponse)
async def get_campaign_detail(campaign_id: str):
    """Get detailed campaign information."""
    return service.get_campaign_detail(campaign_id)


@router.post("/campaigns/waves/submit", response_model=CampaignWaveStatusResponse)
async def submit_campaign_wave(request: CampaignWaveSubmitRequest):
    """Submit a predefined data-collection wave."""
    return service.submit_wave(request)
