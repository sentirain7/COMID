"""Worker stats gathering for CeleryJobManager.

Extracted from celery_job_manager.py — parallel worker inspection and stats compilation.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

from common.logging import get_logger
from orchestrator.job_types import CeleryJob, CeleryJobStats, CeleryJobStatus

logger = get_logger("orchestrator.job_worker_stats")


def get_worker_stats_parallel(celery_app) -> tuple[dict | None, dict | None, dict | None]:
    """Get worker stats using parallel inspect calls.

    Runs active(), reserved(), and scheduled() concurrently
    to reduce total latency.

    Args:
        celery_app: Celery application instance.

    Returns:
        Tuple of (active, reserved, scheduled) dicts.
    """
    inspect = celery_app.control.inspect()

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(inspect.active): "active",
            executor.submit(inspect.reserved): "reserved",
            executor.submit(inspect.scheduled): "scheduled",
        }

        results: dict[str, dict | None] = {
            "active": None,
            "reserved": None,
            "scheduled": None,
        }

        for future in as_completed(futures, timeout=5):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception as e:
                logger.debug(f"Failed to get {key} stats: {e}")

    return results["active"], results["reserved"], results["scheduled"]


def compile_stats(
    jobs: dict[str, CeleryJob],
    celery_app,
    *,
    update_job_status_fn,
    skip_refresh: bool = False,
) -> CeleryJobStats:
    """Compile queue statistics from jobs and Celery workers.

    Args:
        jobs: Dict of job_id -> CeleryJob.
        celery_app: Celery application instance.
        update_job_status_fn: Callback to update single job status.
        skip_refresh: True to skip status refresh (use after refresh_all_jobs).

    Returns:
        CeleryJobStats with compiled statistics.
    """
    stats = CeleryJobStats()

    # Update all job statuses (skip if caller already refreshed)
    if not skip_refresh:
        for job in jobs.values():
            update_job_status_fn(job)

    for job in jobs.values():
        if job.status in [CeleryJobStatus.PENDING]:
            stats.total_pending += 1
        elif job.status in [CeleryJobStatus.STARTED, CeleryJobStatus.RUNNING]:
            stats.total_running += 1
        elif job.status == CeleryJobStatus.SUCCESS:
            stats.total_completed += 1
        elif job.status in [CeleryJobStatus.FAILURE, CeleryJobStatus.REVOKED]:
            stats.total_failed += 1

        tier = job.protocol_request.run_tier.value
        stats.jobs_by_tier[tier] = stats.jobs_by_tier.get(tier, 0) + 1

        stats.jobs_by_queue[job.queue] = stats.jobs_by_queue.get(job.queue, 0) + 1

    # Get worker stats from Celery (parallel inspect calls)
    try:
        active, reserved, scheduled = get_worker_stats_parallel(celery_app)

        if active:
            stats.active_workers = len(active)
            for tasks in active.values():
                stats.total_running = max(stats.total_running, len(tasks))

        if reserved:
            for tasks in reserved.values():
                stats.reserved_tasks += len(tasks)

        if scheduled:
            for tasks in scheduled.values():
                stats.scheduled_tasks += len(tasks)

    except Exception as e:
        logger.warning(f"Failed to get worker stats: {e}")

    return stats
