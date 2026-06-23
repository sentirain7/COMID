"""Jobs and queue routes."""

from fastapi import APIRouter

from api.schemas import JobStatusResponse, QueueStatsResponse

from . import service as jobs_service

router = APIRouter(tags=["Jobs"])


@router.get("/jobs", tags=["Jobs"])
async def list_jobs(status: str | None = None, limit: int = 100):
    return await jobs_service.list_jobs(status=status, limit=limit)


@router.get("/jobs/running", tags=["Jobs"])
async def get_running_jobs_endpoint():
    return await jobs_service.get_running_jobs()


@router.get("/jobs/{job_id}", response_model=JobStatusResponse, tags=["Jobs"])
async def get_job(job_id: str):
    return await jobs_service.get_job(job_id)


@router.get("/queue/stats", response_model=QueueStatsResponse, tags=["Queue"])
async def get_queue_stats():
    return await jobs_service.get_queue_stats()


@router.post("/queue/refresh", tags=["Queue"])
async def refresh_queue_status():
    return await jobs_service.refresh_queue_status()


@router.delete("/jobs/{job_id}", tags=["Jobs"])
async def delete_or_cancel_job(job_id: str, action: str = "cancel"):
    return await jobs_service.delete_or_cancel_job(job_id, action=action)


@router.post("/jobs/{job_id}/retry", tags=["Jobs"])
async def retry_job(job_id: str):
    return await jobs_service.retry_job(job_id)


@router.post("/jobs/cleanup", tags=["Jobs"])
async def cleanup_jobs(older_than_hours: int = 24):
    return await jobs_service.cleanup_jobs(older_than_hours=older_than_hours)


@router.delete("/jobs/completed", tags=["Jobs"])
async def delete_all_completed_jobs():
    return await jobs_service.delete_all_completed_jobs()


@router.get("/queue/dependencies", tags=["Queue"])
async def list_job_dependencies(status: str | None = None, limit: int = 200):
    return await jobs_service.list_job_dependencies(status=status, limit=limit)


@router.post("/queue/dependencies/reconcile", tags=["Queue"])
async def reconcile_job_dependencies(max_submissions: int = 10):
    return await jobs_service.trigger_dependency_reconcile(max_submissions=max_submissions)


@router.post("/queue/dependencies/link", tags=["Queue"])
async def create_job_dependency(parent_exp_id: str, child_exp_id: str):
    return await jobs_service.create_job_dependency(
        parent_exp_id=parent_exp_id,
        child_exp_id=child_exp_id,
    )
