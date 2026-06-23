"""Maintenance helpers for periodic Celery/DB reconciliation tasks."""

from __future__ import annotations

import ast
from datetime import datetime, timedelta
from typing import Any

from celery.result import AsyncResult

from common.logging import get_logger
from contracts.policies.state_machine import ALLOWED_STATUS_TRANSITIONS
from database.models import ExperimentModel
from database.repositories.experiment_repo import ExperimentRepository

logger = get_logger("orchestrator.maintenance")

_TERMINAL_STATUSES = {"completed", "failed", "cancelled", "timeout"}
_ACTIVE_DB_STATUSES = {"pending", "queued", "building", "ready", "running", "analyzing"}

# Statuses eligible for *destructive* auto-cleanup (cleanup_old_jobs).
# IMPORTANT: `completed` is intentionally EXCLUDED. Completed experiments are
# finished scientific results (bulk metrics, and especially the
# `single_molecule_vacuum` E_intra reference set that CED depends on). The
# hourly cleanup previously deleted any completed experiment older than 24h,
# whose cascade (_delete_direct_outputs) also wiped the e_intra rows keyed by
# source_exp_id — repeatedly destroying the E_intra matrix. Only transient
# junk (failed/cancelled/timeout) is pruned here. `_TERMINAL_STATUSES` is kept
# unchanged for the GPU-release backstop in sync_job_status (a completed job
# must still release its GPU).
_CLEANUP_STATUSES = {"failed", "cancelled", "timeout"}


def _task_kwargs(task: dict[str, Any]) -> dict[str, Any]:
    """Best-effort parse Celery inspect task kwargs payload."""
    kwargs = task.get("kwargs")
    if isinstance(kwargs, dict):
        return kwargs
    if isinstance(kwargs, str):
        text = kwargs.strip()
        if not text:
            return {}
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


def _iter_inspect_tasks(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Flatten inspect() payloads to task dictionaries."""
    tasks: list[dict[str, Any]] = []
    if not payload:
        return tasks
    for worker_tasks in payload.values():
        if not isinstance(worker_tasks, list):
            continue
        for task in worker_tasks:
            if not isinstance(task, dict):
                continue
            # scheduled() wraps entries under {"request": {...}}
            if isinstance(task.get("request"), dict):
                req = dict(task["request"])
                req.setdefault("eta", task.get("eta"))
                tasks.append(req)
            else:
                tasks.append(task)
    return tasks


class MaintenanceService:
    """Periodic job maintenance service."""

    def __init__(self, session):
        self._session = session
        self._repo = ExperimentRepository(session)

    def cleanup_old_jobs(self, older_than_hours: int = 24) -> dict[str, int]:
        """Delete old *non-completed* terminal experiments and associated rows.

        Only prunes transient junk (``failed``/``cancelled``/``timeout``) older
        than ``older_than_hours`` — see ``_CLEANUP_STATUSES``. ``completed``
        experiments are NEVER auto-deleted, because they are finished scientific
        results and the ``single_molecule_vacuum`` E_intra reference set that CED
        depends on; auto-deleting them previously wiped the e_intra table on a
        recurring basis.

        Uses experiment_lifecycle._delete_one() for full cascade handling,
        ensuring all related data (metrics with artifact ref_count, e_intra,
        campaign_experiments, JSON arrays, etc.) are properly cleaned up.
        """
        from features.experiments.experiment_lifecycle import _delete_deferred_files, _delete_one

        cutoff = datetime.utcnow() - timedelta(hours=max(0, int(older_than_hours)))
        deleted = 0
        skipped = 0
        deferred_file_deletions: list[str] = []

        stale = (
            self._session.query(ExperimentModel)
            .filter(ExperimentModel.status.in_(list(_CLEANUP_STATUSES)))
            .filter(ExperimentModel.updated_at < cutoff)
            .all()
        )

        for exp in stale:
            exp_id = exp.exp_id
            try:
                # Use lifecycle cascade delete inside a savepoint so one failure
                # cannot leak partial cleanup into the outer commit.
                with self._session.begin_nested():
                    result = _delete_one(self._session, exp_id)
                if result.get("success"):
                    deleted += 1
                    deferred_file_deletions.extend(result.get("deferred_files", []))
                else:
                    skipped += 1
                    logger.debug(
                        "cleanup_old_jobs: skipped %s: %s",
                        exp_id,
                        result.get("reason", "unknown"),
                    )
            except Exception as exc:
                logger.warning("cleanup_old_jobs: failed to delete %s: %s", exp_id, exc)
                skipped += 1

        self._session.commit()
        _delete_deferred_files(deferred_file_deletions)
        return {"deleted": deleted, "skipped": skipped}

    def check_stalled_jobs(
        self,
        *,
        stall_timeout_minutes: int = 60,
        celery_app=None,
    ) -> dict[str, int]:
        """Handle stale active jobs.

        Policy:
        - **running** stale: timeout → GPU release + failed.
        - **queued/building** stale: if the Celery task is missing from
          broker/worker state (inspect snapshot) **and** age exceeds
          timeout, mark failed with a distinct message.  If the task is
          still visible in the broker, leave the experiment alone
          (it may just be waiting for a worker slot).
        """
        now = datetime.utcnow()
        timeout = timedelta(minutes=max(1, int(stall_timeout_minutes)))
        scanned = 0
        marked_failed = 0

        # Build a set of task IDs visible in the broker/worker for fast lookup.
        broker_task_ids: set[str] = set()
        if celery_app is not None:
            try:
                insp = celery_app.control.inspect()
                for payload in [insp.active(), insp.reserved(), insp.scheduled()]:
                    for task in _iter_inspect_tasks(payload):
                        tid = str(task.get("id") or "").strip()
                        if tid:
                            broker_task_ids.add(tid)
            except Exception as exc:
                logger.warning("Failed to inspect broker for stall check: %s", exc)

        active_experiments = (
            self._session.query(ExperimentModel)
            .filter(ExperimentModel.status.in_(["queued", "building", "running"]))
            .all()
        )
        for exp in active_experiments:
            scanned += 1
            age_ref = exp.last_heartbeat_at or exp.updated_at or exp.created_at
            if not age_ref or (now - age_ref) <= timeout:
                continue

            status = str(exp.status or "").lower()

            if status == "running":
                # Running stale — release GPU and fail.
                if exp.gpu_id_allocated is not None:
                    try:
                        from orchestrator.gpu_service import get_gpu_service

                        get_gpu_service().release(
                            int(exp.gpu_id_allocated),
                            task_id=str(exp.active_attempt_id or exp.celery_task_id or "") or None,
                            exp_id=exp.exp_id,
                        )
                    except Exception as exc:
                        logger.warning("Failed to release stale GPU for %s: %s", exp.exp_id, exc)

                self._repo.update_status(
                    exp.exp_id,
                    "failed",
                    error_code="E4001",
                    error_message="Stalled job timed out",
                )
                marked_failed += 1

            elif status in ("queued", "building"):
                # Queued/building stale handling.
                #
                # CRITICAL (v01.06.09): with worker_prefetch_multiplier=1 +
                # task_acks_late=True, tasks waiting in the broker QUEUE for a
                # free worker slot are NOT visible in the inspect snapshot
                # (active/reserved/scheduled only). A large batch (e.g. 300+
                # jobs over 15 slots) therefore has most of its *queued*
                # backlog legitimately absent from broker_task_ids. Treating
                # that absence as "task vanished" mass-fails healthy queued
                # jobs the moment they age past the timeout (observed: a single
                # sweep marked 112 queued jobs failed). acks_late guarantees
                # redelivery if a worker dies, so a queued job that still holds
                # a celery_task_id is never truly lost — only waiting for a slot.
                #
                # Therefore: only snapshot-absence-fail 'building' jobs (which
                # are actively executing run_simulation on a worker and MUST
                # appear in the active snapshot). Never snapshot-fail a 'queued'
                # job that has a task_id. Both states still fail if no task_id
                # was ever recorded (genuinely stuck without a task).
                task_id = str(exp.celery_task_id or "").strip()
                if not task_id:
                    # No celery_task_id at all — stuck without a task.
                    self._repo.update_status(
                        exp.exp_id,
                        "failed",
                        error_code="E4001",
                        error_message="No Celery task assigned; stalled in queue",
                    )
                    marked_failed += 1
                elif status == "building" and task_id not in broker_task_ids:
                    # A 'building' job is mid-execution on a worker, so genuine
                    # absence from the active snapshot means the task vanished.
                    self._repo.update_status(
                        exp.exp_id,
                        "failed",
                        error_code="E4001",
                        error_message="Celery task missing from broker/worker state",
                    )
                    marked_failed += 1
                # else: queued with a task_id (waiting for a worker slot in the
                # broker queue, invisible to inspect under prefetch=1) -> leave
                # alone. Redelivery via acks_late covers genuine worker death.

        self._session.commit()
        return {
            "scanned": scanned,
            "marked_failed": marked_failed,
        }

    # Task names that represent experiment simulation runs.
    # Only these are eligible for orphan revoke; maintenance/system tasks are never touched.
    _SIMULATION_TASK_NAMES: frozenset[str] = frozenset(
        {
            "orchestrator.tasks.run_simulation",
            "orchestrator.tasks.run_prepared_simulation",
            "orchestrator.tasks.run_viscosity_simulation",
            "orchestrator.tasks.run_layer_simulation",
            "orchestrator.tasks.run_restart_simulation",
        }
    )

    def cleanup_orphaned_tasks(self, celery_app) -> dict[str, int]:
        """Revoke simulation tasks whose experiment has been deleted from DB.

        Checks reserved, scheduled, **and active** worker tasks.
        Only experiment-execution tasks (name whitelist) with an ``exp_id``
        are eligible; maintenance/system tasks are never revoked.

        Active orphans are terminated immediately (``terminate=True``)
        to free worker slots.  Reserved/scheduled orphans use graceful
        revoke (``terminate=False``).
        """
        insp = celery_app.control.inspect()
        reserved = _iter_inspect_tasks(insp.reserved())
        scheduled = _iter_inspect_tasks(insp.scheduled())
        active = _iter_inspect_tasks(insp.active())

        revoked = 0
        scanned = 0

        # Tag each task with whether it is currently active (needs terminate).
        tagged: list[tuple[dict, bool]] = [
            *((t, False) for t in reserved),
            *((t, False) for t in scheduled),
            *((t, True) for t in active),
        ]

        for task, is_active in tagged:
            scanned += 1
            task_id = str(task.get("id") or "").strip()
            task_name = str(task.get("name") or task.get("type") or "").strip()
            if not task_id:
                continue

            # Only target known simulation tasks.
            if task_name not in self._SIMULATION_TASK_NAMES:
                continue

            # Extract exp_id from task args (positional arg index 5) or kwargs.
            kwargs = _task_kwargs(task)
            exp_id = str(kwargs.get("exp_id") or "").strip()
            if not exp_id:
                args = task.get("args") or []
                if isinstance(args, list | tuple) and len(args) > 5:
                    exp_id = str(args[5] or "").strip()
            if not exp_id:
                continue  # Cannot determine experiment — leave alone.

            # If experiment still exists in DB, not an orphan.
            if self._repo.get_by_id(exp_id) is not None:
                continue

            # Revoke: active tasks need immediate termination to free worker slot.
            celery_app.control.revoke(
                task_id,
                terminate=is_active,
                signal="SIGTERM" if is_active else None,
            )
            revoked += 1
            logger.info(
                "Revoked orphaned task %s (exp_id=%s, active=%s)",
                task_id[:12],
                exp_id,
                is_active,
            )

            # Best-effort exp_lock cleanup.
            try:
                from orchestrator.exp_lock_manager import clear_lock_for_experiment

                clear_lock_for_experiment(exp_id, force=True)
            except Exception:
                pass

        return {"scanned": scanned, "revoked": revoked}

    def sync_job_status(self, celery_app) -> dict[str, int]:
        """
        Sync DB status with Celery task state for active experiments.

        The method preserves status SSOT by only mutating active records and
        never reviving terminal states.
        """
        checked = 0
        updated = 0

        active_experiments = (
            self._session.query(ExperimentModel)
            .filter(ExperimentModel.status.in_(list(_ACTIVE_DB_STATUSES)))
            .filter(ExperimentModel.celery_task_id.isnot(None))
            .all()
        )
        for exp in active_experiments:
            checked += 1
            task_id = str(exp.celery_task_id or "").strip()
            if not task_id:
                continue
            state = str(AsyncResult(task_id, app=celery_app).state or "").upper()
            current = str(exp.status or "").lower()

            # Map Celery state → desired DB status
            desired: str | None = None
            error_code: str | None = None
            error_message: str | None = None

            if state in {"STARTED"} and current != "running":
                desired = "running"
            elif state in {"SUCCESS"} and current in _ACTIVE_DB_STATUSES:
                desired = "completed"
            elif state in {"FAILURE"} and current in _ACTIVE_DB_STATUSES:
                desired = "failed"
                error_code = "E4001"
                error_message = "Celery task failed"
            elif state in {"REVOKED"} and current in _ACTIVE_DB_STATUSES:
                desired = "cancelled"

            if desired is not None:
                allowed = ALLOWED_STATUS_TRANSITIONS.get(current, set())
                if desired not in allowed:
                    logger.debug(
                        "sync_job_status: skipping %s → %s for %s (not in allowed: %s)",
                        current,
                        desired,
                        exp.exp_id,
                        sorted(allowed),
                    )
                    continue
                status_changed = False
                try:
                    self._repo.update_status(
                        exp.exp_id,
                        desired,
                        error_code=error_code,
                        error_message=error_message,
                        attempt_id=task_id,
                    )
                    updated += 1
                    status_changed = True
                except Exception as exc:
                    logger.warning(
                        "sync_job_status: failed to transition %s from %s to %s: %s",
                        exp.exp_id,
                        current,
                        desired,
                        exc,
                    )
                if status_changed and desired in {"running", "cancelled", "failed"}:
                    try:
                        from features.recommendations import pending_service

                        if desired == "running":
                            pending_service.mark_running_by_exp_id(exp.exp_id)
                        elif desired == "cancelled":
                            pending_service.mark_cancelled_by_exp_id(
                                exp.exp_id,
                                reason="Linked experiment cancelled",
                            )
                        elif desired == "failed":
                            pending_service.mark_failed_by_exp_id(
                                exp.exp_id,
                                reason=error_message or "Linked experiment failed",
                            )
                    except Exception:
                        pass
                # Terminal transition observed from Celery state: release any GPU
                # slot the now-closed task still holds. The normal path releases in
                # the worker `finally`; this is the backstop for when the worker
                # died after Celery recorded the terminal state but before `finally`
                # ran — otherwise gpu_id_allocated leaks until the next API restart.
                # release() is idempotent (no-op if already released), so safe even
                # when `finally` did run.
                if (
                    status_changed
                    and desired in _TERMINAL_STATUSES
                    and exp.gpu_id_allocated is not None
                ):
                    try:
                        from orchestrator.gpu_service import get_gpu_service

                        get_gpu_service().release(
                            int(exp.gpu_id_allocated),
                            task_id=str(exp.active_attempt_id or task_id) or None,
                            exp_id=exp.exp_id,
                        )
                    except Exception:
                        pass
                continue

            # Guard against stale running rows with no active task process.
            if current == "running" and state == "PENDING" and not exp.last_heartbeat_at:
                if exp.gpu_id_allocated is not None:
                    try:
                        from orchestrator.gpu_service import get_gpu_service

                        get_gpu_service().release(
                            int(exp.gpu_id_allocated),
                            task_id=str(exp.active_attempt_id or task_id) or None,
                            exp_id=exp.exp_id,
                        )
                    except Exception:
                        pass
                self._repo.update_status(
                    exp.exp_id,
                    "failed",
                    error_code="E4001",
                    error_message="Stale running task without heartbeat",
                    attempt_id=task_id,
                )
                updated += 1

        self._session.commit()
        return {"checked": checked, "updated": updated}

    def reconcile_unprocessed_completions(self, *, limit: int = 20) -> list[str]:
        """Return completed experiment ids whose feedback has not been processed yet."""
        rows = self._repo.list_completed_feedback_candidates(limit=limit)
        return [str(row.exp_id) for row in rows if getattr(row, "exp_id", None)]
