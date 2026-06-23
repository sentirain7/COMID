"""Analysis Explorer REST endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from api.schemas.analysis_explorer import (
    ExplorerAggregateRequest,
    ExplorerAggregateResponse,
    ExplorerDataRequest,
    ExplorerDataResponse,
)
from features.analysis_explorer import service

router = APIRouter(tags=["Analysis Explorer"])


@router.get("/analysis/explorer/catalog")
async def get_explorer_catalog():
    """Return dataset catalog with dimensions, metrics, and defaults per mode."""
    catalog = service.get_catalog()
    return [c.model_dump() for c in catalog]


@router.post(
    "/analysis/explorer/data",
    response_model=ExplorerDataResponse,
)
async def post_explorer_data(request: ExplorerDataRequest):
    """Query raw rows from a dataset with filters, sort, and pagination."""
    return await service.query_data(request)


@router.post(
    "/analysis/explorer/aggregate",
    response_model=ExplorerAggregateResponse,
)
async def post_explorer_aggregate(request: ExplorerAggregateRequest):
    """Compute aggregated values for charting."""
    return await service.query_aggregate(request)
