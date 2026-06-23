"""Scheduler for deferred GPU execution (ready -> running).

When LammpsCaps probe indicates a non-GPU acceleration mode (e.g. kokkos_cpu,
mpi_only, serial), the scheduler dispatches without allocating a GPU slot so
that CPU-only jobs are not blocked by GPU availability.
"""

from __future__ import annotations

import os
import tempfile
import uuid

from common.logging import get_logger
from database.connection import session_scope
from database.repositories.experiment_repo import ExperimentRepository

try:
    import fcntl
except Exception:  # pragma: no cover - non-POSIX fallback
    fcntl = None  # type: ignore[assignment]

logger = get_logger("orchestrator.run_scheduler")

# Cross-process single-flight lock for the ready->running dispatcher.
# The dispatcher (schedule_ready_experiments) is fired both by celery beat
# (control@) and by every fire-and-forget _trigger_ready_scheduler fan-out.
# Without serialization, two overlapping invocations each read the SAME ready
# experiment with gpu_id_allocated=None in their own SQLite-WAL read snapshot
# (the run_scheduler `gpu_id_allocated is not None` skip cannot serialize across
# concurrent snapshots), then both allocate a GPU and publish a run task for one
# experiment -> mis-dispatch + GPU churn (and, combined with the historical
# active_attempt_id poisoning, duplicate lmp). A non-blocking POSIX file lock
# lets exactly ONE dispatcher run at a time across all worker pools/processes;
# losers no-op this tick (the next beat/trigger re-runs immediately).
_DISPATCH_LOCK_PATH = os.path.join(tempfile.gettempdir(), "asphalt_ready_dispatch.lock")

# Sentinel returned when POSIX locking is unavailable -> fail OPEN (run without
# single-flight) so behavior is unchanged on platforms lacking fcntl.
_NO_LOCK_SENTINEL = object()


def _acquire_dispatch_lock() -> object | None:
    """Acquire the single-flight dispatcher lock (non-blocking).

    Returns an open file handle holding the exclusive lock, ``_NO_LOCK_SENTINEL``
    when POSIX locking is unavailable (fail-open), or ``None`` when another
    dispatcher instance already holds the lock (this tick must no-op).
    """
    if fcntl is None:
        return _NO_LOCK_SENTINEL
    try:
        handle = open(_DISPATCH_LOCK_PATH, "a+", encoding="utf-8")
    except Exception:
        return _NO_LOCK_SENTINEL
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle
    except BlockingIOError:
        try:
            handle.close()
        except Exception:
            pass
        return None
    except Exception:
        try:
            handle.close()
        except Exception:
            pass
        return _NO_LOCK_SENTINEL


def _release_dispatch_lock(handle: object | None) -> None:
    """Release the single-flight dispatcher lock."""
    if handle is None or handle is _NO_LOCK_SENTINEL:
        return
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)  # type: ignore[arg-type]
    except Exception:
        pass
    try:
        handle.close()  # type: ignore[attr-defined]
    except Exception:
        pass


def _caps_needs_gpu() -> bool:
    """Check if the probed LAMMPS acceleration mode requires a GPU.

    Returns True (conservative default) if caps are unavailable OR degraded.

    Only a NON-degraded probe is trusted to say "no GPU needed". A degraded cache
    (empty ``installed_packages`` == ``lmp -h`` read nothing, i.e. the probe timed
    out under load) reports a bogus ``mpi_only``/``serial`` mode; trusting it would
    make the scheduler dispatch GPU jobs with ``gpu_id=-1`` (CPU), and a KOKKOS
    input then fails with "Package kokkos command without KOKKOS package enabled".
    Conservative True is safe (at worst it holds a slot for a genuine CPU build);
    the reverse silently loses the job. Pairs with the caps cache hardening
    (start_all warm + get_lammps_caps Defense B) on the worker/execution side.
    """
    try:
        from orchestrator.lammps_probe import _cached_caps

        if _cached_caps is not None and _cached_caps.installed_packages:
            return _cached_caps.accel_mode.value == "kokkos_gpu"
    except Exception:
        pass
    # Conservative: unavailable or degraded caps -> assume GPU needed.
    return True


class RunScheduler:
    """Submit GPU execution tasks for experiments in ready state."""

    def __init__(self, *, gpu_service, celery_app):
        self.gpu_service = gpu_service
        self.celery_app = celery_app

    def schedule_ready_experiments(self, max_submissions: int = 10) -> dict[str, int]:
        # Single-flight: only one dispatcher instance runs at a time across all
        # worker pools/processes. If another instance holds the lock, no-op this
        # tick (the next beat/trigger re-runs). This closes the concurrent-tick
        # mis-dispatch / GPU-churn race at its source.
        lock = _acquire_dispatch_lock()
        if lock is None:
            logger.debug("Ready dispatcher already running in another process; skipping this tick.")
            return {
                "submitted": 0,
                "skipped_no_gpu": 0,
                "errors": 0,
                "skipped_locked": 1,
            }
        try:
            return self._schedule_ready_experiments_locked(max_submissions)
        finally:
            _release_dispatch_lock(lock)

    def _schedule_ready_experiments_locked(self, max_submissions: int = 10) -> dict[str, int]:
        submitted = 0
        skipped_no_gpu = 0
        errors = 0

        # Ensure GPUService is initialized before allocation attempts.
        init = getattr(self.gpu_service, "initialize", None)
        if callable(init):
            init()

        with session_scope() as session:
            repo = ExperimentRepository(session)
            ready_experiments = repo.list_by_status("ready", limit=max_submissions)

            needs_gpu = _caps_needs_gpu()

            for exp in ready_experiments:
                if exp.gpu_id_allocated is not None:
                    # Already assigned by a previous scheduler pass.
                    continue

                gpu_id: int | None = None
                if needs_gpu:
                    lock_owner = str(exp.exp_id)
                    gpu_id = self.gpu_service.allocate_gpu(job_id=lock_owner, exp_id=exp.exp_id)
                    if gpu_id is None:
                        skipped_no_gpu += 1
                        continue

                try:
                    dispatch_attempt_id = uuid.uuid4().hex
                    repo.set_dispatch_attempt_id(exp.exp_id, dispatch_attempt_id)
                    # Commit token + GPU allocation before task publish to avoid
                    # worker observing stale ownership state.
                    session.commit()

                    task = self.celery_app.send_task(
                        "orchestrator.tasks.run_prepared_simulation",
                        kwargs={
                            "exp_id": exp.exp_id,
                            "gpu_id": int(gpu_id) if gpu_id is not None else -1,
                            "dispatch_attempt_id": dispatch_attempt_id,
                        },
                        queue="simulation.gpu",
                    )
                    repo.update_celery_task_id(exp.exp_id, task.id)
                    session.commit()
                    submitted += 1
                except Exception as exc:
                    errors += 1
                    logger.error("Failed to schedule run task for %s: %s", exp.exp_id, exc)
                    # Roll back allocation for this experiment only.
                    if gpu_id is not None:
                        self.gpu_service.release(int(gpu_id), exp_id=exp.exp_id)
                    repo.clear_dispatch_attempt_id(exp.exp_id)
                    session.commit()

            # Per-item commits above are intentional for publish/DB ordering.

        return {
            "submitted": submitted,
            "skipped_no_gpu": skipped_no_gpu,
            "errors": errors,
            "skipped_locked": 0,
        }
