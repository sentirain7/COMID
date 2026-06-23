"""Amorphous cell library routes."""

from fastapi import APIRouter

from api.schemas import (
    AmorphousCellCreateRequest,
    AmorphousCellListResponse,
    AmorphousCellPreviewResponse,
    AmorphousCellResponse,
    BoxPresetResponse,
    LibraryVisibility,
)

from . import service as amorphous_service

router = APIRouter(tags=["AmorphousCells"])


@router.get("/amorphous-cells", response_model=AmorphousCellListResponse)
async def list_amorphous_cells(
    status: str | None = None,
    limit: int = 100,
    visibility: LibraryVisibility = "library",
):
    return await amorphous_service.list_amorphous_cells(
        status=status,
        limit=limit,
        visibility=visibility,
    )


@router.get("/amorphous-cells/box-presets", response_model=list[BoxPresetResponse])
def get_box_presets() -> list[BoxPresetResponse]:
    """Return box size presets derived from completed binder experiments."""
    return amorphous_service.get_box_presets_from_db()


@router.get("/amorphous-cells/{amorphous_id}", response_model=AmorphousCellResponse)
async def get_amorphous_cell(amorphous_id: str):
    return await amorphous_service.get_amorphous_cell(amorphous_id)


@router.get(
    "/amorphous-cells/{amorphous_id}/preview",
    response_model=AmorphousCellPreviewResponse,
)
async def get_amorphous_cell_preview(amorphous_id: str):
    return await amorphous_service.get_amorphous_cell_preview(amorphous_id)


@router.post("/amorphous-cells", response_model=AmorphousCellResponse)
async def create_amorphous_cell(request: AmorphousCellCreateRequest):
    return await amorphous_service.create_amorphous_cell(request)


@router.delete("/amorphous-cells/{amorphous_id}")
async def delete_amorphous_cell(amorphous_id: str):
    return await amorphous_service.delete_amorphous_cell(amorphous_id)
