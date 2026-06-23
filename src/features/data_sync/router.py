"""API router for data-sync feature."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from common.logging import get_logger

from . import service

logger = get_logger("features.data_sync.router")

router = APIRouter(prefix="/data-sync", tags=["data-sync"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ScannedAssetSchema(BaseModel):
    """Single scanned asset in API response."""

    asset_id: str
    asset_type: str
    name: str = ""
    status: str = "discovered"
    already_synced: bool = False
    details: dict = Field(default_factory=dict)


class ScanRequest(BaseModel):
    """Request body for POST /data-sync/scan."""

    asset_type: str = Field(
        ...,
        description=("Asset type to scan: interface_molecule_cells, crystal_structures, all"),
    )


class ScanResponse(BaseModel):
    """Response from POST /data-sync/scan."""

    asset_type: str
    total_discovered: int
    already_synced: int
    new_items: int
    assets: list[ScannedAssetSchema]


class ImportRequest(BaseModel):
    """Request body for POST /data-sync/import."""

    asset_type: str
    asset_ids: list[str]
    force_import: bool = False


class ImportResponse(BaseModel):
    """Response from POST /data-sync/import."""

    imported: int
    failed: int
    results: list[dict]


class BackupRequest(BaseModel):
    """Request body for POST /data-sync/backup."""

    asset_types: list[str] = Field(
        default_factory=lambda: ["all"],
        description="Asset types to backup.",
    )


class BackupResponse(BaseModel):
    """Response from POST /data-sync/backup."""

    success: bool
    manifest_path: str | None = None
    items_backed_up: int = 0
    message: str = ""


class LoadRequest(BaseModel):
    """Request body for POST /data-sync/load."""

    manifest_path: str | None = None


class LoadResponse(BaseModel):
    """Response from POST /data-sync/load."""

    success: bool
    items_found: int = 0
    manifest_path: str | None = None
    message: str = ""
    assets: list[ScannedAssetSchema] = Field(default_factory=list)


class ApplyLoadRequest(BaseModel):
    """Request body for POST /data-sync/apply."""

    manifest_path: str
    targets: list[str] | None = None


class ApplyLoadResponse(BaseModel):
    """Response from POST /data-sync/apply."""

    success: bool
    items_restored: int = 0
    message: str = ""


class NasStatusResponse(BaseModel):
    """Response from GET /data-sync/nas-status."""

    configured: bool
    nas_root: str | None = None
    message: str = ""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/scan", response_model=ScanResponse)
async def scan_assets(request: ScanRequest) -> ScanResponse:
    """Scan filesystem for data assets of the given type."""
    try:
        result = service.scan_assets(request.asset_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ScanResponse(**result)


@router.post("/import", response_model=ImportResponse)
async def import_assets(request: ImportRequest) -> ImportResponse:
    """Import selected assets into the system."""
    try:
        result = service.import_assets(
            asset_type=request.asset_type,
            asset_ids=request.asset_ids,
            force_import=request.force_import,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ImportResponse(**result)


@router.post("/backup", response_model=BackupResponse)
async def backup_assets(request: BackupRequest) -> BackupResponse:
    """Backup data assets to NAS."""
    result = service.backup_to_nas(request.asset_types)
    return BackupResponse(**result)


@router.post("/load", response_model=LoadResponse)
async def load_from_nas(request: LoadRequest) -> LoadResponse:
    """Load and preview data assets from NAS (dry-run)."""
    result = service.load_from_nas(request.manifest_path)
    return LoadResponse(**result)


@router.post("/apply", response_model=ApplyLoadResponse)
async def apply_nas_load(request: ApplyLoadRequest) -> ApplyLoadResponse:
    """Apply NAS load — copy backup targets to workspace."""
    result = service.apply_nas_load(request.manifest_path, request.targets)
    return ApplyLoadResponse(**result)


@router.get("/nas-status", response_model=NasStatusResponse)
async def get_nas_status() -> NasStatusResponse:
    """Check NAS configuration status."""
    result = service.get_nas_status()
    return NasStatusResponse(**result)
