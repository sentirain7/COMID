"""Job status synchronization helpers for CeleryJobManager.

Extracted from celery_job_manager.py — status sync, cleanup, and refresh logic.
"""

import json
import threading
from datetime import datetime
from typing import TYPE_CHECKING

from celery.result import AsyncResult

from common.logging import get_logger
from orchestrator.job_types import CeleryJob, CeleryJobStatus

if TYPE_CHECKING:
    pass

logger = get_logger("orchestrator.job_status_sync")

# Status mapping shared between single and batch update
CELERY_STATUS_MAP: dict[str, CeleryJobStatus] = {
    "PENDING": CeleryJobStatus.PENDING,
    "RECEIVED": CeleryJobStatus.QUEUED,
    "STARTED": CeleryJobStatus.RUNNING,
    "RUNNING": CeleryJobStatus.RUNNING,  # Custom state from task
    "BUILDING": CeleryJobStatus.RUNNING,  # Custom state from task
    "PROGRESS": CeleryJobStatus.RUNNING,
    "SUCCESS": CeleryJobStatus.SUCCESS,
    "FAILURE": CeleryJobStatus.FAILURE,
    "REVOKED": CeleryJobStatus.REVOKED,
    "REJECTED": CeleryJobStatus.FAILURE,
    "RETRY": CeleryJobStatus.RETRY,
}


def update_job_status(
    job: CeleryJob,
    celery_app,
    *,
    schedule_cleanup,
) -> None:
    """Update job status from Celery.

    Args:
        job: The CeleryJob to update.
        celery_app: Celery application instance.
        schedule_cleanup: Callback to schedule cleanup.
    """
    result = AsyncResult(job.task_id, app=celery_app)

    new_status = CELERY_STATUS_MAP.get(result.status, CeleryJobStatus.PENDING)

    if new_status != job.status:
        job.status = new_status

        # Set started_at when transitioning to RUNNING state
        if new_status == CeleryJobStatus.RUNNING and job.started_at is None:
            job.started_at = datetime.now()
            logger.info(f"Job {job.job_id} started (task state: {result.status})")

        elif new_status in [CeleryJobStatus.SUCCESS, CeleryJobStatus.FAILURE]:
            job.completed_at = datetime.now()
            # Ensure started_at is set if it wasn't captured
            if job.started_at is None:
                job.started_at = job.created_at
                logger.warning(f"Job {job.job_id} completed but started_at was not set")

            if result.result:
                if isinstance(result.result, dict):
                    job.result_exp_id = result.result.get("exp_id")
                    job.error_message = result.result.get("error")

            # Schedule automatic cleanup after 60 seconds
            schedule_cleanup(job.job_id, delay_seconds=60)


def schedule_cleanup(
    job_id: str,
    jobs: dict[str, CeleryJob],
    delay_seconds: int = 60,
) -> None:
    """Schedule automatic cleanup of a completed job.

    Args:
        job_id: Job ID to clean up.
        jobs: Reference to the jobs dict.
        delay_seconds: Delay before cleanup (default 60 seconds).
    """

    def cleanup() -> None:
        if job_id in jobs:
            job = jobs[job_id]
            if job.status in [
                CeleryJobStatus.SUCCESS,
                CeleryJobStatus.FAILURE,
                CeleryJobStatus.REVOKED,
            ]:
                del jobs[job_id]
                logger.debug(f"Auto-cleaned completed job: {job_id}")

    timer = threading.Timer(delay_seconds, cleanup)
    timer.daemon = True
    timer.start()


def batch_update_job_statuses(
    jobs: dict[str, CeleryJob],
    celery_app,
    *,
    schedule_cleanup_fn,
    update_job_status_fn,
) -> int:
    """Update all job statuses using batch Redis mget.

    This is much faster than individual AsyncResult queries when
    there are many jobs to check.

    Args:
        jobs: Dict of job_id -> CeleryJob.
        celery_app: Celery application instance.
        schedule_cleanup_fn: Callback to schedule cleanup.
        update_job_status_fn: Fallback single-job update function.

    Returns:
        Number of jobs with status changes.
    """
    if not jobs:
        return 0

    try:
        backend = celery_app.backend
        task_ids = [job.task_id for job in jobs.values()]
        job_list = list(jobs.values())

        # Celery task result key pattern: celery-task-meta-{task_id}
        keys = [f"celery-task-meta-{tid}" for tid in task_ids]

        # Get Redis connection and batch fetch
        redis_conn = backend.client
        results = redis_conn.mget(keys)

        updated = 0
        for job, raw_result in zip(job_list, results, strict=False):
            if raw_result is None:
                continue
            try:
                data = json.loads(raw_result)
                celery_status = data.get("status", "PENDING")
                new_status = CELERY_STATUS_MAP.get(celery_status, CeleryJobStatus.PENDING)

                if new_status != job.status:
                    job.status = new_status
                    updated += 1

                    # Handle status transitions
                    if new_status == CeleryJobStatus.RUNNING and job.started_at is None:
                        job.started_at = datetime.now()
                        logger.info(f"Job {job.job_id} started (batch update)")

                    elif new_status in [CeleryJobStatus.SUCCESS, CeleryJobStatus.FAILURE]:
                        job.completed_at = datetime.now()
                        if job.started_at is None:
                            job.started_at = job.created_at

                        result_data = data.get("result")
                        if isinstance(result_data, dict):
                            job.result_exp_id = result_data.get("exp_id")
                            job.error_message = result_data.get("error")

                        schedule_cleanup_fn(job.job_id, delay_seconds=60)
            except Exception as e:
                logger.debug(f"Failed to parse result for {job.job_id}: {e}")

        return updated

    except Exception as e:
        logger.warning(f"Batch Redis fetch failed, falling back to individual queries: {e}")
        # Fallback to individual queries
        updated = 0
        for job in jobs.values():
            old_status = job.status
            update_job_status_fn(job)
            if job.status != old_status:
                updated += 1
        return updated


def cleanup_old_jobs(jobs: dict[str, CeleryJob]) -> int:
    """Remove jobs completed more than 5 minutes ago.

    Args:
        jobs: Dict of job_id -> CeleryJob.

    Returns:
        Number of jobs removed.
    """
    removed = 0
    for job_id in list(jobs.keys()):
        job = jobs.get(job_id)
        if job and job.status in [
            CeleryJobStatus.SUCCESS,
            CeleryJobStatus.FAILURE,
            CeleryJobStatus.REVOKED,
        ]:
            if job.completed_at:
                elapsed = (datetime.now() - job.completed_at).total_seconds()
                if elapsed > 300:
                    del jobs[job_id]
                    removed += 1
                    logger.debug(f"Removed stale job: {job_id}")
    return removed
