"""Interface molecule cell library routes."""

import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse

from api.schemas.interface_molecules import (
    InterfaceMoleculeBatchGenerateRequest,
    InterfaceMoleculeBatchGenerateResponse,
    InterfaceMoleculeCellCreateRequest,
    InterfaceMoleculeCellListResponse,
    InterfaceMoleculeCellPreviewResponse,
    InterfaceMoleculeCellResponse,
    InterfaceMoleculeListResponse,
    InterfaceMoleculePreviewResponse,
)
from api.schemas.structures import LibraryVisibility

from . import service as interface_service
from .batch_progress import (
    acquire_batch_slot,
    get_batch_progress,
    get_running_batch_id,
    init_batch_progress_queued,
)

router = APIRouter(tags=["InterfaceMolecules"])


# =============================================================================
# Molecule Catalog Endpoints
# =============================================================================


@router.get("/interface-molecules", response_model=InterfaceMoleculeListResponse)
def list_interface_molecules():
    """List available interface molecules with category info."""
    return interface_service.list_interface_molecules()


@router.get(
    "/interface-molecules/{mol_id}/preview",
    response_model=InterfaceMoleculePreviewResponse,
)
async def get_molecule_preview(mol_id: str):
    """Get single molecule preview for 3D viewer."""
    return await interface_service.get_molecule_preview(mol_id)


# =============================================================================
# Cell Library Endpoints
# =============================================================================


@router.get("/interface-molecule-cells", response_model=InterfaceMoleculeCellListResponse)
async def list_interface_molecule_cells(
    status: str | None = None,
    limit: int = 100,
    visibility: LibraryVisibility = "library",
):
    """List interface molecule cells from library."""
    return await interface_service.list_interface_molecule_cells(
        status=status,
        limit=limit,
        visibility=visibility,
    )


@router.get(
    "/interface-molecule-cells/{cell_id}",
    response_model=InterfaceMoleculeCellResponse,
)
async def get_interface_molecule_cell(cell_id: str):
    """Get interface molecule cell detail."""
    return await interface_service.get_interface_molecule_cell(cell_id)


@router.get(
    "/interface-molecule-cells/{cell_id}/preview",
    response_model=InterfaceMoleculeCellPreviewResponse,
)
async def get_interface_molecule_cell_preview(cell_id: str):
    """Get interface molecule cell preview for 3D viewer."""
    return await interface_service.get_interface_molecule_cell_preview(cell_id)


@router.post("/interface-molecule-cells", response_model=InterfaceMoleculeCellResponse)
async def create_interface_molecule_cell(request: InterfaceMoleculeCellCreateRequest):
    """Create interface molecule cell (structure only, no MD simulation)."""
    return await interface_service.create_interface_molecule_cell(request)


@router.post(
    "/interface-molecule-cells/batch-generate",
    response_model=InterfaceMoleculeBatchGenerateResponse,
    deprecated=True,
)
async def batch_generate_interface_molecule_cells(
    request: InterfaceMoleculeBatchGenerateRequest,
):
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
        return await interface_service.batch_generate_interface_molecule_cells(request)
    finally:
        release_batch_slot(sync_batch_id)


@router.post("/interface-molecule-cells/batch-generate-async", status_code=202)
async def batch_generate_interface_molecule_cells_async(
    request: InterfaceMoleculeBatchGenerateRequest,
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
    # Items not known at router time — will be set by worker
    init_batch_progress_queued(batch_id, [])

    background_tasks.add_task(
        interface_service.batch_generate_interface_molecule_cells_background,
        batch_id,
        request,
    )

    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "batch_id": batch_id,
            "poll_url": f"/interface-molecule-cells/batch-progress/{batch_id}",
        },
    )


@router.get("/interface-molecule-cells/batch-progress/{batch_id}")
async def get_interface_batch_progress_endpoint(batch_id: str):
    """Get progress status for an async batch generation."""
    return get_batch_progress(batch_id)


@router.delete("/interface-molecule-cells/{cell_id}")
async def delete_interface_molecule_cell(cell_id: str):
    """Delete interface molecule cell from library."""
    return await interface_service.delete_interface_molecule_cell(cell_id)
