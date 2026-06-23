"""Batch Job Binder Cell API routes."""

from fastapi import APIRouter

from api.schemas import BatchJobBinderCellRequest, BatchJobBinderCellResponse

from . import service as batch_job_binder_cell_service

router = APIRouter(tags=["Batch Job Binder Cell"])


@router.post("/batch-job/binder-cell/validate", response_model=BatchJobBinderCellResponse)
def validate_batch_job_binder_cell(request: BatchJobBinderCellRequest):
    """Dry-run: generate batch Binder Cell jobs and check for duplicates."""
    return batch_job_binder_cell_service.validate_batch_job_binder_cell(request)


@router.post("/batch-job/binder-cell", response_model=BatchJobBinderCellResponse)
def create_batch_job_binder_cell(request: BatchJobBinderCellRequest):
    """Create and submit a batch Binder Cell job."""
    return batch_job_binder_cell_service.create_batch_job_binder_cell(request)
