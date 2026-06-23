"""
Celery-based Job Manager.

Extends the base JobManager to use Celery for distributed task execution
with Redis as the message broker.
"""

import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from celery.result import AsyncResult

from common.logging import get_logger
from contracts.policies.budget import DEFAULT_JOB_BUDGETING_POLICY, JobPriority
from contracts.policies.failure import DEFAULT_FAILURE_POLICY
from contracts.policies.tier import DEFAULT_TIER_POLICY
from contracts.schemas import BuildRequest, ProtocolRequest, RunTier
from orchestrator.job_status_sync import (
    batch_update_job_statuses,
    cleanup_old_jobs,
    schedule_cleanup,
    update_job_status,
)
from orchestrator.job_types import CeleryJob, CeleryJobStats, CeleryJobStatus  # noqa: F401
from orchestrator.job_worker_stats import compile_stats, get_worker_stats_parallel

if TYPE_CHECKING:
    from protocols.duration_adjuster import StageDurationOverride

logger = get_logger("orchestrator.celery_job_manager")


class CeleryJobManager:
    """
    Celery-based job manager.

    Uses Celery for distributed task execution with Redis broker.
    Provides job submission, status tracking, and resource management.
    """

    def __init__(
        self,
        max_concurrent: int = 4,
        max_atoms_per_gpu: int = 500000,
        gpu_tracker=None,
    ):
        """
        Initialize Celery job manager.

        Args:
            max_concurrent: Maximum concurrent jobs
            max_atoms_per_gpu: Maximum atoms per GPU
            gpu_tracker: GPUService instance (optional)
        """
        self.max_concurrent = max_concurrent
        self.max_atoms_per_gpu = max_atoms_per_gpu
        self._gpu_tracker = gpu_tracker

        self._jobs: dict[str, CeleryJob] = {}

        self.budget_policy = DEFAULT_JOB_BUDGETING_POLICY
        self.tier_policy = DEFAULT_TIER_POLICY
        self.failure_policy = DEFAULT_FAILURE_POLICY

        # Lazy import celery app
        self._celery_app = None

    @property
    def gpu_tracker(self):
        """Lazy load GPUService."""
        if self._gpu_tracker is None:
            from orchestrator.gpu_service import get_gpu_service

            self._gpu_tracker = get_gpu_service()
        return self._gpu_tracker

    @property
    def celery_app(self):
        """Lazy load Celery app."""
        if self._celery_app is None:
            from orchestrator.celery_app import celery_app

            self._celery_app = celery_app
        return self._celery_app

    def _count_db_queued_jobs(self) -> int:
        """Count experiments waiting in the queue from the DB (SSOT for depth).

        The in-memory ``self._jobs`` is per-instance and a fresh manager is
        created per request/task, so it is almost always empty — it cannot bound
        global queue depth. This counts the actual pre-running experiments
        (queued/pending/building/ready) so the queue-depth limit in
        ``can_submit_job`` is real, preventing unbounded Redis backlog under
        large staged batches. Returns 0 on any DB error (fail-open).
        """
        try:
            from database.connection import session_scope
            from database.models import ExperimentModel

            waiting = ("queued", "pending", "building", "ready")
            with session_scope() as session:
                return int(
                    session.query(ExperimentModel)
                    .filter(ExperimentModel.status.in_(waiting))
                    .count()
                )
        except Exception as e:  # noqa: BLE001 - fail open so submission isn't wedged
            logger.debug(f"DB queued-job count failed (fail-open): {e}")
            return 0

    def _get_queue_for_tier(self, tier: RunTier) -> str:
        """Get appropriate queue for run tier."""
        queue_map = {
            RunTier.SCREENING: "simulation.screening",
            RunTier.CONFIRM: "simulation.confirm",
            RunTier.VISCOSITY: "simulation.viscosity",
            RunTier.VALIDATION: "simulation",
        }
        return queue_map.get(tier, "simulation")

    def _get_task_for_tier(self, tier: RunTier):
        """Get appropriate task for run tier."""
        from orchestrator.task_registry import get_task_for_tier

        return get_task_for_tier(tier)

    def submit(
        self,
        build_request: BuildRequest,
        protocol_request: ProtocolRequest,
        material_id: str = "default_binder",
        priority: JobPriority = JobPriority.MEDIUM,
        selected_gpus: list[int] | None = None,
        stage_duration_overrides: list["StageDurationOverride"] | None = None,
        property_calculations: dict | None = None,
        exp_id: str | None = None,
        # Phase 5.1: additive metadata propagation
        additive_type: str | None = None,
        additive_wt: float = 0.0,
        additive_mol_id: str | None = None,
    ) -> str:
        """
        Submit a new job to Celery.

        Args:
            build_request: Build specification
            protocol_request: Protocol specification
            material_id: Material ID
            priority: Job priority
            selected_gpus: List of GPU IDs to use (None = all available)
            stage_duration_overrides: Optional stage duration overrides
            property_calculations: Optional property calculation settings
            exp_id: Pre-generated experiment ID (ensures API-Celery sync)
            additive_type: Additive type identifier (Phase 5.1)
            additive_wt: Additive weight percent (Phase 5.1)
            additive_mol_id: Additive molecule ID (Phase 5.1)

        Returns:
            Job ID
        """
        if exp_id:
            try:
                from database.connection import session_scope
                from database.repositories.experiment_repo import ExperimentRepository

                with session_scope() as session:
                    repo = ExperimentRepository(session)
                    exp = repo.get_by_id(exp_id)
                    if exp:
                        exp_status = str(exp.status or "").lower()
                        has_task = bool(str(exp.celery_task_id or "").strip())
                        has_attempt = bool(str(exp.active_attempt_id or "").strip())

                        # SubmissionFacade DB-first stub:
                        # queued + no task/attempt id means "not yet submitted to Celery".
                        if exp_status == "queued" and not has_task and not has_attempt:
                            logger.debug(f"Allowing DB-first stub submission: exp_id={exp_id}")
                        elif exp_status in {"queued", "building", "ready", "running", "analyzing"}:
                            if has_task or has_attempt:
                                raise ValueError(
                                    f"[E8701] Duplicate execution blocked: exp_id={exp_id} "
                                    f"is already active (status={exp_status}, "
                                    f"task_id={has_task}, attempt_id={has_attempt})"
                                )
                            logger.warning(
                                "Inconsistent active experiment state without task/attempt id: "
                                "exp_id=%s status=%s",
                                exp_id,
                                exp_status,
                            )
                            raise ValueError(
                                f"[E8701] Duplicate execution blocked: exp_id={exp_id} "
                                f"in inconsistent state (status={exp_status}, "
                                "task_id=False, attempt_id=False)"
                            )
            except ValueError:
                raise
            except Exception as e:
                logger.debug(f"Pre-submit duplicate check skipped for {exp_id}: {e}")

        # Build gpu_usage dict from tracker
        gpu_usage = {}
        for gpu in self.gpu_tracker.get_all_gpus():
            # Skip GPUs not in selected list (if specified)
            if selected_gpus is not None and gpu.gpu_id not in selected_gpus:
                continue
            # Count as 1 if busy, 0 if available
            job_count = 1 if gpu.current_job_id else 0
            gpu_usage[gpu.gpu_id] = job_count

        # Validate against budget policy
        tier = protocol_request.run_tier.value
        # Count running jobs (actually using GPU) vs queued jobs (waiting)
        running_jobs = len(
            [
                j
                for j in self._jobs.values()
                if j.status in [CeleryJobStatus.STARTED, CeleryJobStatus.RUNNING]
            ]
        )
        # Queue depth from DB (SSOT) — the in-memory _jobs is per-instance and
        # near-empty, so it cannot bound global backlog. Use the larger of the
        # two so the depth limit actually fires under large staged batches.
        queued_jobs = max(
            self._count_db_queued_jobs(),
            len(
                [
                    j
                    for j in self._jobs.values()
                    if j.status in [CeleryJobStatus.PENDING, CeleryJobStatus.QUEUED]
                ]
            ),
        )
        can_submit, reason = self.budget_policy.can_submit_job(
            tier=tier,
            atom_count=build_request.target_atoms,
            current_jobs=running_jobs,
            gpu_usage=gpu_usage,
            queued_jobs=queued_jobs,
        )

        if not can_submit:
            logger.warning(f"Job submission blocked: {reason}")
            raise ValueError(f"Cannot submit job: {reason}")

        job_id = str(uuid.uuid4())[:8]
        queue = self._get_queue_for_tier(protocol_request.run_tier)

        # Submit to Celery (import celery_app first to ensure correct broker config)
        from orchestrator.celery_app import celery_app  # noqa: F401
        from orchestrator.tasks import run_simulation

        # Serialize overrides for Celery (must be JSON-serializable)
        overrides_dict = None
        if stage_duration_overrides:
            overrides_dict = [o.model_dump() for o in stage_duration_overrides]

        task_result = run_simulation.apply_async(
            args=[
                build_request.model_dump(),
                protocol_request.model_dump(),
                material_id,
                overrides_dict,  # Pass serialized overrides
                property_calculations,
                exp_id,  # Pass pre-generated exp_id for API-Celery sync
                additive_type,
                additive_wt,
                additive_mol_id,
            ],
            queue=queue,
            priority=self._priority_to_int(priority),
        )

        job = CeleryJob(
            job_id=job_id,
            task_id=task_result.id,
            build_request=build_request,
            protocol_request=protocol_request,
            material_id=material_id,
            priority=priority,
            queue=queue,
            stage_duration_overrides=stage_duration_overrides,
        )

        self._jobs[job_id] = job

        logger.info(
            f"Job submitted: {job_id} (task_id={task_result.id}, "
            f"tier={tier}, queue={queue}, overrides={len(stage_duration_overrides) if stage_duration_overrides else 0})"
        )

        return job_id

    def submit_screening(
        self,
        composition: dict[str, float],
        temperature_K: float = 298.0,
        target_atoms: int = DEFAULT_TIER_POLICY.get_target_atoms("screening"),
        seed: int | None = None,
        material_id: str = "default_binder",
    ) -> str:
        """
        Convenience method to submit a screening simulation.

        Args:
            composition: SARA composition (wt%)
            temperature_K: Temperature in Kelvin
            target_atoms: Target atom count
            seed: Random seed
            material_id: Material identifier

        Returns:
            Job ID
        """
        from orchestrator.request_factory import create_build_request, create_protocol_request

        build_request = create_build_request(
            composition=composition,
            target_atoms=target_atoms,
            seed=seed,
            tier=RunTier.SCREENING,
        )

        protocol_request = create_protocol_request(
            tier=RunTier.SCREENING,
            temperature_K=temperature_K,
        )

        return self.submit(
            build_request=build_request,
            protocol_request=protocol_request,
            material_id=material_id,
            priority=JobPriority.HIGH,
        )

    def submit_batch(
        self,
        compositions: list[dict[str, float]],
        temperature_K: float = 298.0,
        target_atoms: int = DEFAULT_TIER_POLICY.get_target_atoms("screening"),
        tier: RunTier = RunTier.SCREENING,
    ) -> list[str]:
        """
        Submit a batch of simulations.

        Args:
            compositions: List of SARA compositions
            temperature_K: Temperature in Kelvin
            target_atoms: Target atom count
            tier: Run tier

        Returns:
            List of job IDs
        """
        from orchestrator.request_factory import create_build_request, create_protocol_request

        job_ids = []

        for i, comp in enumerate(compositions):
            build_request = create_build_request(
                composition=comp,
                target_atoms=target_atoms,
                seed=i + 1,
                tier=tier,
            )

            protocol_request = create_protocol_request(
                tier=tier,
                temperature_K=temperature_K,
            )

            try:
                job_id = self.submit(
                    build_request=build_request,
                    protocol_request=protocol_request,
                    material_id=f"batch_{i:04d}",
                )
                job_ids.append(job_id)
            except ValueError as e:
                logger.warning(f"Batch submission stopped at {i}: {e}")
                break

        logger.info(f"Batch submitted: {len(job_ids)} jobs")
        return job_ids

    def get_job(self, job_id: str) -> CeleryJob | None:
        """Get job by ID with updated status."""
        job = self._jobs.get(job_id)
        if job:
            self._update_job_status(job)
        return job

    def get_task_id(self, job_id: str) -> str | None:
        """
        Get Celery task ID for a job.

        Args:
            job_id: Job ID

        Returns:
            Celery task ID or None if job not found
        """
        job = self._jobs.get(job_id)
        if job:
            return job.task_id
        return None

    def get_task_result(self, job_id: str) -> AsyncResult | None:
        """Get Celery task result for a job."""
        job = self._jobs.get(job_id)
        if not job:
            return None
        return AsyncResult(job.task_id, app=self.celery_app)

    def _update_job_status(self, job: CeleryJob) -> None:
        """Update job status from Celery."""
        update_job_status(
            job,
            self.celery_app,
            schedule_cleanup=self._schedule_cleanup,
        )

    def _schedule_cleanup(self, job_id: str, delay_seconds: int = 60) -> None:
        """Schedule automatic cleanup of a completed job.

        Args:
            job_id: Job ID to clean up
            delay_seconds: Delay before cleanup (default 60 seconds)
        """
        schedule_cleanup(job_id, self._jobs, delay_seconds=delay_seconds)

    def _batch_update_job_statuses(self) -> int:
        """Update all job statuses using batch Redis mget.

        Returns:
            Number of jobs with status changes
        """
        return batch_update_job_statuses(
            self._jobs,
            self.celery_app,
            schedule_cleanup_fn=self._schedule_cleanup,
            update_job_status_fn=self._update_job_status,
        )

    def _cleanup_old_jobs(self) -> int:
        """Remove jobs completed more than 5 minutes ago."""
        return cleanup_old_jobs(self._jobs)

    def refresh_all_jobs(self) -> dict[str, int]:
        """
        Refresh all job statuses from Celery and clean up stale jobs.

        Uses batch Redis queries for better performance with many jobs.

        Returns:
            dict with 'refreshed' and 'removed' counts
        """
        refreshed = self._batch_update_job_statuses()
        removed = self._cleanup_old_jobs()

        logger.info(f"Job refresh: {refreshed} updated, {removed} removed")
        return {"refreshed": refreshed, "removed": removed}

    def cancel_job(self, job_id: str) -> bool:
        """
        Cancel a pending job.

        Args:
            job_id: Job ID

        Returns:
            True if cancelled
        """
        job = self._jobs.get(job_id)
        if not job:
            return False

        if job.status not in [CeleryJobStatus.PENDING, CeleryJobStatus.STARTED]:
            return False

        # Revoke the Celery task
        self.celery_app.control.revoke(job.task_id, terminate=True)
        job.status = CeleryJobStatus.REVOKED

        logger.info(f"Job cancelled: {job_id}")
        return True

    def delete_job(self, job_id: str) -> bool:
        """
        Delete a job (only SUCCESS/FAILURE/REVOKED).

        Args:
            job_id: Job ID

        Returns:
            True if deleted
        """
        job = self._jobs.get(job_id)
        if not job:
            return False

        if job.status not in [
            CeleryJobStatus.SUCCESS,
            CeleryJobStatus.FAILURE,
            CeleryJobStatus.REVOKED,
        ]:
            return False

        del self._jobs[job_id]
        logger.info(f"Job deleted: {job_id}")
        return True

    def retry_job(self, job_id: str) -> str | None:
        """
        Retry a failed job.

        Args:
            job_id: Job ID

        Returns:
            New job ID if resubmitted, None otherwise
        """
        job = self._jobs.get(job_id)
        if not job or job.status != CeleryJobStatus.FAILURE:
            return None

        max_retries = self.failure_policy.get_max_retries(job.protocol_request.ff_type.value)

        if job.retry_count >= max_retries:
            logger.warning(f"Job {job_id} exceeded max retries")
            return None

        # Resubmit with modified seed
        from orchestrator.request_factory import create_build_request

        new_build_request = create_build_request(
            composition=job.build_request.composition,
            target_atoms=job.build_request.target_atoms,
            seed=job.build_request.seed + job.retry_count + 1,
            tier=job.protocol_request.run_tier,
        )

        new_job_id = self.submit(
            build_request=new_build_request,
            protocol_request=job.protocol_request,
            material_id=job.material_id,
            priority=job.priority,
        )

        # Track retry count
        new_job = self._jobs.get(new_job_id)
        if new_job:
            new_job.retry_count = job.retry_count + 1

        logger.info(f"Job retried: {job_id} -> {new_job_id}")
        return new_job_id

    def _get_worker_stats_parallel(self) -> tuple[dict | None, dict | None, dict | None]:
        """Get worker stats using parallel inspect calls."""
        return get_worker_stats_parallel(self.celery_app)

    def get_stats(self, skip_refresh: bool = False) -> CeleryJobStats:
        """Get queue statistics.

        Args:
            skip_refresh: True to skip status refresh (use after refresh_all_jobs)
        """
        return compile_stats(
            self._jobs,
            self.celery_app,
            update_job_status_fn=self._update_job_status,
            skip_refresh=skip_refresh,
        )

    def list_jobs(
        self,
        status: CeleryJobStatus | None = None,
        tier: RunTier | None = None,
        limit: int = 100,
    ) -> list[CeleryJob]:
        """
        List jobs with optional filters.

        Args:
            status: Filter by status
            tier: Filter by run tier
            limit: Maximum results

        Returns:
            List of jobs
        """
        # Update all job statuses first
        for job in self._jobs.values():
            self._update_job_status(job)

        jobs = list(self._jobs.values())

        if status:
            jobs = [j for j in jobs if j.status == status]

        if tier:
            jobs = [j for j in jobs if j.protocol_request.run_tier == tier]

        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    def clear_completed(self, older_than_hours: int = 24) -> int:
        """
        Clear old completed jobs.

        Args:
            older_than_hours: Remove jobs older than this

        Returns:
            Number of jobs removed
        """

        cutoff = datetime.now() - timedelta(hours=older_than_hours)
        removed = 0

        to_remove = []
        for job_id, job in self._jobs.items():
            if job.status in [
                CeleryJobStatus.SUCCESS,
                CeleryJobStatus.FAILURE,
                CeleryJobStatus.REVOKED,
            ]:
                if job.completed_at and job.completed_at < cutoff:
                    to_remove.append(job_id)

        for job_id in to_remove:
            del self._jobs[job_id]
            removed += 1

        if removed > 0:
            logger.info(f"Cleared {removed} old jobs")

        return removed

    def _priority_to_int(self, priority: JobPriority) -> int:
        """Convert priority enum to integer for Celery."""
        priority_map = {
            JobPriority.HIGHEST: 0,
            JobPriority.HIGH: 3,
            JobPriority.MEDIUM: 5,
            JobPriority.LOW: 7,
            JobPriority.LOWEST: 9,
        }
        return priority_map.get(priority, 5)

    def wait_for_completion(
        self,
        job_id: str,
        timeout: float | None = None,
    ) -> dict | None:
        """
        Wait for a job to complete.

        Args:
            job_id: Job ID
            timeout: Maximum wait time in seconds

        Returns:
            Job result or None if timeout
        """
        job = self._jobs.get(job_id)
        if not job:
            return None

        result = AsyncResult(job.task_id, app=self.celery_app)

        try:
            return result.get(timeout=timeout)
        except Exception as e:
            logger.error(f"Wait for job {job_id} failed: {e}")
            return None
