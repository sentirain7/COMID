"""API router for scan-database feature."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from common.logging import get_logger

from . import service

logger = get_logger("features.scan_database.router")

router = APIRouter(prefix="/scan-database", tags=["scan-database"])


# ---------------------------------------------------------------------------
# Response / request schemas
# ---------------------------------------------------------------------------


class ScannedExperimentSchema(BaseModel):
    """Single scanned experiment in API response."""

    exp_id: str
    directory: str
    has_in_lammps: bool
    has_log_lammps: bool
    has_data_lammps: bool
    tier: str | None
    ff_type: str | None
    temperature_k: float | None
    total_atoms: int | None
    protocol_hash_found: str | None
    protocol_hash_current: str | None
    compatibility: str
    compatibility_reason: str
    lammps_completed: bool
    already_in_db: bool
    seed: int | None
    box_dims: list[float] | None
    study_type: str | None = None
    additive_mol_id: str | None = None


class ScanResponse(BaseModel):
    """Response from POST /scan-database/scan."""

    total_discovered: int
    compatible: int
    incompatible: int
    already_imported: int
    experiments: list[ScannedExperimentSchema]


class ImportRequest(BaseModel):
    """Request body for POST /scan-database/import."""

    exp_ids: list[str]
    force_import: bool = False


class ImportResponse(BaseModel):
    """Response from POST /scan-database/import."""

    imported: int
    failed: int
    results: list[dict]


class DeleteRequest(BaseModel):
    """Request body for POST /scan-database/delete."""

    exp_ids: list[str]


class DeleteResponse(BaseModel):
    """Response from POST /scan-database/delete."""

    deleted: int
    failed: int
    results: list[dict]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/scan", response_model=ScanResponse)
async def scan_database() -> ScanResponse:
    """Scan filesystem for experiment directories and check compatibility."""
    experiments = service.scan()

    compatible = sum(
        1 for e in experiments if e.compatibility in ("compatible", "compatible_incomplete")
    )
    already = sum(1 for e in experiments if e.already_in_db)

    schemas = [
        ScannedExperimentSchema(
            exp_id=e.exp_id,
            directory=e.directory,
            has_in_lammps=e.has_in_lammps,
            has_log_lammps=e.has_log_lammps,
            has_data_lammps=e.has_data_lammps,
            tier=e.tier,
            ff_type=e.ff_type,
            temperature_k=e.temperature_k,
            total_atoms=e.total_atoms,
            protocol_hash_found=e.protocol_hash_found,
            protocol_hash_current=e.protocol_hash_current,
            compatibility=e.compatibility,
            compatibility_reason=e.compatibility_reason,
            lammps_completed=e.lammps_completed,
            already_in_db=e.already_in_db,
            seed=e.seed,
            box_dims=e.box_dims,
            study_type=e.study_type,
            additive_mol_id=e.additive_mol_id,
        )
        for e in experiments
    ]

    return ScanResponse(
        total_discovered=len(experiments),
        compatible=compatible,
        incompatible=len(experiments) - compatible,
        already_imported=already,
        experiments=schemas,
    )


@router.post("/import", response_model=ImportResponse)
async def import_experiments(request: ImportRequest) -> ImportResponse:
    """Import selected experiments into the database."""
    result = service.import_experiments(
        exp_ids=request.exp_ids,
        force_import=request.force_import,
    )
    return ImportResponse(**result)


@router.post("/delete", response_model=DeleteResponse)
async def delete_experiments(request: DeleteRequest) -> DeleteResponse:
    """Delete experiment directories from the filesystem."""
    result = service.delete_experiment_dirs(exp_ids=request.exp_ids)
    return DeleteResponse(**result)
