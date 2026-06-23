"""Crystal structure library routes."""

import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse

from api.schemas import (
    CrystalBatchGenerateRequest,
    CrystalBatchGenerateResponse,
    CrystalStructureCreateRequest,
    CrystalStructureListResponse,
    CrystalStructurePreviewResponse,
    CrystalStructureResponse,
    LibraryVisibility,
)

from . import service as crystal_service
from .batch_progress import (
    acquire_batch_slot,
    get_batch_progress,
    get_running_batch_id,
    init_batch_progress_queued,
)

router = APIRouter(tags=["CrystalStructures"])


@router.get("/crystal-structures", response_model=CrystalStructureListResponse)
async def list_crystal_structures(
    status: str | None = None,
    limit: int = 100,
    visibility: LibraryVisibility = "library",
):
    return await crystal_service.list_crystal_structures(
        status=status,
        limit=limit,
        visibility=visibility,
    )


@router.get("/crystal-structures/{crystal_id}", response_model=CrystalStructureResponse)
async def get_crystal_structure(crystal_id: str):
    return await crystal_service.get_crystal_structure(crystal_id)


@router.get(
    "/crystal-structures/{crystal_id}/preview",
    response_model=CrystalStructurePreviewResponse,
)
async def get_crystal_structure_preview(crystal_id: str):
    return await crystal_service.get_crystal_structure_preview(crystal_id)


@router.post("/crystal-structures", response_model=CrystalStructureResponse)
async def create_crystal_structure(request: CrystalStructureCreateRequest):
    return await crystal_service.create_crystal_structure(request)


@router.post(
    "/crystal-structures/batch-generate",
    response_model=CrystalBatchGenerateResponse,
    deprecated=True,
)
async def batch_generate_crystal_sizes(request: CrystalBatchGenerateRequest):
    """[DEPRECATED] Synchronous batch generation. Use /batch-generate-async instead.

    Codex fix: Apply same slot guard as async route to prevent concurrent execution.
    """
    from .batch_progress import acquire_batch_slot, get_running_batch_id, release_batch_slot

    # Use "sync" as batch_id for slot tracking
    sync_batch_id = "sync-batch"
    if not acquire_batch_slot(sync_batch_id):
        running_id = get_running_batch_id()
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Another batch is already running",
                "running_batch_id": running_id,
            },
        )
    try:
        return await crystal_service.batch_generate_crystal_sizes(request)
    finally:
        release_batch_slot(sync_batch_id)


@router.post("/crystal-structures/batch-generate-async", status_code=202)
async def batch_generate_crystal_sizes_async(
    request: CrystalBatchGenerateRequest,
    background_tasks: BackgroundTasks,
):
    """P2: Non-blocking batch generation with 202 Accepted.

    Returns immediately with batch_id. Poll /batch-progress/{batch_id} for status.
    Codex fix: concurrent execution guard + queued progress init.
    """
    batch_id = str(uuid.uuid4())

    # Codex fix: Acquire slot to prevent concurrent batch execution
    if not acquire_batch_slot(batch_id):
        running_id = get_running_batch_id()
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Another batch is already running",
                "running_batch_id": running_id,
            },
        )

    # Codex fix: Init progress as 'queued' BEFORE returning 202
    # This ensures immediate polling sees queued status, not not_found
    sizes = request.sizes if hasattr(request, "sizes") else []
    init_batch_progress_queued(batch_id, sizes)

    background_tasks.add_task(
        crystal_service.batch_generate_crystal_sizes_background,
        batch_id,
        request,
    )

    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "batch_id": batch_id,
            "poll_url": f"/crystal-structures/batch-progress/{batch_id}",
        },
    )


@router.get("/crystal-structures/batch-progress/{batch_id}")
async def get_crystal_batch_progress_endpoint(batch_id: str):
    """Get progress status for an async batch generation."""
    return get_batch_progress(batch_id)


@router.delete("/crystal-structures/{crystal_id}")
async def delete_crystal_structure(crystal_id: str):
    return await crystal_service.delete_crystal_structure(crystal_id)
