"""Distributed experiment lock maintenance for Redis exp_lock:* keys."""

from __future__ import annotations

from common.logging import get_logger
from config.settings import get_settings

logger = get_logger("orchestrator.exp_lock_manager")

_ACTIVE_STATUSES = {"pending", "queued", "building", "ready", "running", "analyzing"}
_TERMINAL_STATUSES = {"completed", "failed", "cancelled", "timeout"}


def _redis_client():
    import redis

    return redis.Redis.from_url(get_settings().celery.broker_url)


def clear_lock_for_experiment(exp_id: str, *, force: bool = False) -> bool:
    """Clear Redis exp_lock for an experiment."""
    key = f"exp_lock:{exp_id}"
    try:
        client = _redis_client()
        owner = client.get(key)
        if owner is None:
            return False
        if force:
            return bool(client.delete(key))

        owner_id = owner.decode(errors="ignore")
        from database.connection import session_scope
        from database.repositories.experiment_repo import ExperimentRepository

        with session_scope() as session:
            exp = ExperimentRepository(session).get_by_id(exp_id)
            if exp is None:
                return bool(client.delete(key))

            status = str(getattr(exp, "status", "") or "").lower()
            task_ids = {
                str(getattr(exp, "active_attempt_id", "") or "").strip(),
                str(getattr(exp, "celery_task_id", "") or "").strip(),
            }
            task_ids.discard("")

            # Keep lock when it matches current owner of an active experiment.
            if status in _ACTIVE_STATUSES and owner_id in task_ids:
                return False
            return bool(client.delete(key))
    except Exception as exc:
        logger.debug("Failed to clear exp lock for %s: %s", exp_id, exc)
        return False


def cleanup_stale_exp_locks(*, max_keys: int = 500) -> dict[str, int]:
    """
    Cleanup stale exp_lock:* keys.

    Policy:
    - no matching experiment row -> remove lock
    - terminal experiment status -> remove lock
    - active experiment with owner mismatch -> keep (conservative)
    - active experiment with owner match -> keep
    """
    removed = 0
    kept = 0
    scanned = 0

    try:
        client = _redis_client()
        from database.connection import session_scope
        from database.repositories.experiment_repo import ExperimentRepository

        with session_scope() as session:
            repo = ExperimentRepository(session)
            for raw_key in client.scan_iter(match="exp_lock:*", count=200):
                if scanned >= max_keys:
                    break
                scanned += 1
                key = raw_key.decode(errors="ignore")
                exp_id = key.split("exp_lock:", 1)[-1]

                owner_raw = client.get(raw_key)
                owner = owner_raw.decode(errors="ignore") if owner_raw else ""
                exp = repo.get_by_id(exp_id)
                if exp is None:
                    removed += int(bool(client.delete(raw_key)))
                    continue

                status = str(getattr(exp, "status", "") or "").lower()
                if status in _TERMINAL_STATUSES:
                    removed += int(bool(client.delete(raw_key)))
                    continue

                task_ids = {
                    str(getattr(exp, "active_attempt_id", "") or "").strip(),
                    str(getattr(exp, "celery_task_id", "") or "").strip(),
                }
                task_ids.discard("")

                if status in _ACTIVE_STATUSES and owner in task_ids:
                    kept += 1
                else:
                    # Conservative keep for ambiguous active state; handled by owner checks in runtime.
                    kept += 1

    except Exception as exc:
        logger.warning("Failed stale exp_lock cleanup: %s", exc)

    return {"scanned": scanned, "removed": removed, "kept": kept}
