"""Job and queue management operations."""

from api.schemas import JobStatusResponse, QueueStatsResponse
from api.utils.time_utils import to_utc_iso
from common.logging import get_logger
from contracts.errors import ContractError, ErrorCode, OrchestrationError

logger = get_logger("features.jobs.management")


async def list_jobs(status: str | None = None, limit: int = 100) -> dict:
    from api.deps import get_job_manager

    try:
        job_manager = get_job_manager()
    except RuntimeError as exc:
        logger.warning(f"Job manager unavailable: {exc}")
        raise OrchestrationError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "Infrastructure degraded. Queue data unavailable.",
            {"reason": str(exc)},
        ) from exc

    jobs = job_manager.list_jobs(limit=limit)
    if status:
        jobs = [j for j in jobs if j.status.value == status]

    return {
        "jobs": [
            {
                "job_id": j.job_id,
                "status": j.status.value,
                "priority": j.priority.name.lower()
                if hasattr(j.priority, "name")
                else str(j.priority),
                "tier": j.protocol_request.run_tier.value,
                "material_id": j.material_id,
                "target_atoms": j.build_request.target_atoms,
                "temperature_k": j.protocol_request.temperature_K,
                "created_at": to_utc_iso(j.created_at),
                "started_at": to_utc_iso(j.started_at),
                "completed_at": to_utc_iso(j.completed_at),
                "error_message": j.error_message,
            }
            for j in jobs
        ],
        "total": len(jobs),
    }


async def get_job(job_id: str) -> JobStatusResponse:
    from datetime import datetime

    from api.deps import get_job_manager

    try:
        job_manager = get_job_manager()
    except RuntimeError as exc:
        logger.warning(f"Job manager unavailable: {exc}")
        raise OrchestrationError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "Infrastructure degraded. Job status unavailable.",
            {"reason": str(exc)},
        ) from exc

    job = job_manager.get_job(job_id)
    if job:
        return JobStatusResponse(
            job_id=job.job_id,
            status=job.status.value,
            priority=job.priority.name.lower()
            if hasattr(job.priority, "name")
            else str(job.priority),
            created_at=to_utc_iso(job.created_at) or to_utc_iso(datetime.now()),
            started_at=to_utc_iso(job.started_at),
            completed_at=to_utc_iso(job.completed_at),
            error_message=job.error_message,
            result_exp_id=job.result_exp_id,
        )

    return JobStatusResponse(
        job_id=job_id, status="pending", priority="normal", created_at=to_utc_iso(datetime.now())
    )


async def get_queue_stats() -> QueueStatsResponse:
    from api.deps import get_job_manager
    from database.repositories.experiment_repo import ExperimentRepository
    from features.common import run_in_session

    total_pending = 0
    total_queued = 0
    total_building = 0
    total_ready = 0
    total_running = 0
    total_completed = 0
    total_failed = 0
    total_cancelled = 0
    total_timeout = 0
    atoms_in_progress = 0
    jobs_by_tier = {}

    try:
        job_manager = get_job_manager()
        job_manager.refresh_all_jobs()
        stats = job_manager.get_stats(skip_refresh=True)
        total_pending = stats.total_pending
        total_running = stats.total_running
        jobs_by_tier = stats.jobs_by_tier

        for job in job_manager.list_jobs():
            if job.status.value in ["pending", "running", "queued"]:
                atoms_in_progress += job.build_request.target_atoms
    except RuntimeError as exc:
        logger.warning(f"Job manager unavailable: {exc}")
        raise OrchestrationError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "Infrastructure degraded. Queue stats unavailable.",
            {"reason": str(exc)},
        ) from exc
    except Exception as exc:
        logger.warning(f"Failed to get job manager stats: {exc}")

    completed_today = 0
    completed_this_week = 0
    try:

        def _load_db_stats(
            session,
        ) -> tuple[int, int, int, int, int, int, int, int, int, int, int, int, dict]:
            repo = ExperimentRepository(session)
            db_counts = repo.count_by_status()
            # Get ALL status counts from database (SSOT)
            pending = db_counts.get("pending", 0)
            queued = db_counts.get("queued", 0)
            building = db_counts.get("building", 0)
            ready = db_counts.get("ready", 0)
            running = db_counts.get("running", 0)
            completed = db_counts.get("completed", 0)
            failed = db_counts.get("failed", 0)
            cancelled = db_counts.get("cancelled", 0)
            timeout = db_counts.get("timeout", 0)
            today = repo.count_completed_today()
            week = repo.count_completed_this_week()
            inferred_by_tier = {}
            if not jobs_by_tier:
                experiments = repo.list_all(limit=1000)
                for exp in experiments:
                    tier = exp.run_tier
                    inferred_by_tier[tier] = inferred_by_tier.get(tier, 0) + 1
            return (
                pending,
                queued,
                building,
                ready,
                running,
                completed,
                failed,
                cancelled,
                timeout,
                today,
                week,
                inferred_by_tier,
            )

        (
            db_pending,
            db_queued,
            total_building,
            total_ready,
            db_running,
            total_completed,
            total_failed,
            total_cancelled,
            total_timeout,
            completed_today,
            completed_this_week,
            inferred_by_tier,
        ) = run_in_session(_load_db_stats)
        # Use database counts as SSOT (override job_manager stats)
        total_pending = db_pending
        total_queued = db_queued
        total_running = db_running
        if not jobs_by_tier and inferred_by_tier:
            jobs_by_tier = inferred_by_tier
    except Exception as exc:
        logger.warning(f"Failed to get DB experiment stats: {exc}")

    return QueueStatsResponse(
        total_pending=total_pending,
        total_queued=total_queued,
        building=total_building,
        ready=total_ready,
        total_running=total_running,
        analyzing=0,
        total_completed=total_completed,
        total_failed=total_failed,
        total_cancelled=total_cancelled,
        total_timeout=total_timeout,
        atoms_in_progress=atoms_in_progress,
        jobs_by_tier=jobs_by_tier,
        completed_today=completed_today,
        completed_this_week=completed_this_week,
    )


async def refresh_queue_status() -> dict[str, object]:
    from api.deps import get_job_manager

    try:
        job_manager = get_job_manager()
    except RuntimeError as exc:
        logger.warning(f"Job manager unavailable: {exc}")
        raise OrchestrationError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "Infrastructure degraded. Queue refresh unavailable.",
            {"reason": str(exc)},
        ) from exc

    result = job_manager.refresh_all_jobs()
    return {"status": "ok", "refreshed": result["refreshed"], "removed": result["removed"]}


async def delete_or_cancel_job(job_id: str, action: str = "cancel") -> dict[str, object]:
    from api.deps import get_job_manager

    try:
        job_manager = get_job_manager()
    except RuntimeError as exc:
        logger.warning(f"Job manager unavailable: {exc}")
        raise OrchestrationError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "Infrastructure degraded. Job cancel/delete unavailable.",
            {"reason": str(exc)},
        ) from exc

    job = job_manager.get_job(job_id)
    if not job:
        if action == "delete":
            return {"job_id": job_id, "deleted": True}
        return {"job_id": job_id, "cancelled": True}

    if action == "delete":
        success = job_manager.delete_job(job_id)
        if not success:
            raise ContractError(
                ErrorCode.INVALID_REQUEST,
                "Can only delete completed/failed/cancelled jobs",
                {"job_id": job_id, "action": action},
            )
        return {"job_id": job_id, "deleted": True}

    success = job_manager.cancel_job(job_id)
    if not success:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            "Can only cancel pending/queued jobs",
            {"job_id": job_id, "action": action},
        )
    return {"job_id": job_id, "cancelled": True}


async def retry_job(job_id: str) -> dict[str, object]:
    return {"job_id": job_id, "requeued": True}


async def cleanup_jobs(older_than_hours: int = 24) -> dict[str, object]:
    from api.deps import get_job_manager

    try:
        job_manager = get_job_manager()
    except RuntimeError as exc:
        logger.warning(f"Job manager unavailable: {exc}")
        raise OrchestrationError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "Infrastructure degraded. Job cleanup unavailable.",
            {"reason": str(exc)},
        ) from exc

    removed = job_manager.clear_completed(older_than_hours=older_than_hours)
    return {"removed": removed, "older_than_hours": older_than_hours}


async def delete_all_completed_jobs() -> dict[str, int]:
    from api.deps import get_job_manager

    try:
        job_manager = get_job_manager()
    except RuntimeError as exc:
        logger.warning(f"Job manager unavailable: {exc}")
        raise OrchestrationError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "Infrastructure degraded. Job deletion unavailable.",
            {"reason": str(exc)},
        ) from exc

    jobs = job_manager.list_jobs()
    deleted = 0
    for job in jobs:
        if hasattr(job, "status"):
            status_val = job.status.value if hasattr(job.status, "value") else str(job.status)
            if status_val in ["completed", "SUCCESS", "success"] and job_manager.delete_job(
                job.job_id
            ):
                deleted += 1

    return {"deleted": deleted}


async def list_job_dependencies(status: str | None = None, limit: int = 200) -> dict[str, object]:
    from features.common import run_in_session

    def _load(session):
        from database.models import JobDependencyModel

        query = session.query(JobDependencyModel).order_by(JobDependencyModel.created_at.desc())
        if status:
            query = query.filter(JobDependencyModel.status == status)
        rows = query.limit(limit).all()
        return [
            {
                "parent_exp_id": row.parent_exp_id,
                "child_exp_id": row.child_exp_id,
                "status": row.status,
                "reason": row.reason,
                "created_at": to_utc_iso(row.created_at),
                "updated_at": to_utc_iso(row.updated_at),
            }
            for row in rows
        ]

    items = run_in_session(_load)
    return {"items": items, "count": len(items)}


async def trigger_dependency_reconcile(max_submissions: int = 10) -> dict[str, object]:
    from orchestrator.tasks import reconcile_dependency_chains

    # Execute asynchronously via Celery for consistent runtime context.
    task = reconcile_dependency_chains.delay(max_submissions=max_submissions)
    return {"status": "queued", "task_id": task.id, "max_submissions": max_submissions}


async def create_job_dependency(parent_exp_id: str, child_exp_id: str) -> dict[str, object]:
    from contracts.errors import ContractError, ErrorCode
    from features.common import run_in_session_commit

    if parent_exp_id == child_exp_id:
        raise ContractError(
            ErrorCode.DEPENDENCY_CYCLE,
            "Parent and child cannot be the same experiment",
            {"parent_exp_id": parent_exp_id, "child_exp_id": child_exp_id},
        )

    def _create(session):
        from database.repositories.experiment_repo import ExperimentRepository
        from database.repositories.job_dependency_repo import JobDependencyRepository

        exp_repo = ExperimentRepository(session)
        dep_repo = JobDependencyRepository(session)

        if exp_repo.get_by_id(parent_exp_id) is None:
            raise ContractError(
                ErrorCode.RECORD_NOT_FOUND,
                f"Parent experiment not found: {parent_exp_id}",
                {"parent_exp_id": parent_exp_id},
            )
        if exp_repo.get_by_id(child_exp_id) is None:
            raise ContractError(
                ErrorCode.RECORD_NOT_FOUND,
                f"Child experiment not found: {child_exp_id}",
                {"child_exp_id": child_exp_id},
            )

        edge = dep_repo.create_dependency(parent_exp_id, child_exp_id)
        return edge

    edge_id = run_in_session_commit(_create)
    return {
        "edge_id": edge_id,
        "parent_exp_id": parent_exp_id,
        "child_exp_id": child_exp_id,
        "status": "blocked",
    }
