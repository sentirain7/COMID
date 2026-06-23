"""
Task maintenance helpers: status management, lifecycle, feedback, locks, scheduling.

Extracted from tasks.py — NO functional changes, only code organization.
"""

from __future__ import annotations

import time

from common.logging import get_logger
from orchestrator.task_common import (
    run_in_task_session,
    run_in_task_session_commit,
)

logger = get_logger("orchestrator.tasks")


def _update_experiment_status_by_task_id(
    task_id: str,
    status: str,
    error_code: str | None = None,
    error_message: str | None = None,
) -> bool:
    """
    Update experiment status in DB by Celery task ID.

    IMPORTANT: Also releases GPU allocation when status is 'completed' or 'failed'.

    Args:
        task_id: Celery task ID
        status: New status
        error_code: Error code if failed
        error_message: Error message if failed

    Returns:
        True if updated, False if experiment not found
    """
    try:
        from database.repositories.experiment_repo import ExperimentRepository

        def _op(session) -> tuple[bool, str | None]:
            repo = ExperimentRepository(session)
            experiment = repo.get_by_celery_task_id(task_id)
            if experiment:
                # GPU release is handled exclusively by GPUService.release()
                # in the finally block of _run_tier_simulation().
                # Direct DB UPDATE here caused GPUService cache staleness (v00.75.01 fix).
                repo.update_status(
                    experiment.exp_id,
                    status,
                    error_code=error_code,
                    error_message=error_message,
                    attempt_id=task_id,
                )
                logger.info(f"Updated experiment status via task_id {task_id}: {status}")
                return (True, experiment.exp_id)
            logger.warning(f"No experiment found for task_id {task_id}")
            return (False, None)

        updated, exp_id = run_in_task_session_commit(_op)
        if updated and exp_id:
            _reconcile_dependency_after_status_update(exp_id=exp_id, status=status)
            # P1-1: replica ensemble은 마지막 sibling이 failed/cancelled/timeout으로
            # 종료돼도 집계돼야 하므로 모든 terminal 상태에서 시도(group 아니면 no-op).
            if str(status or "").lower() in {"failed", "cancelled", "timeout"}:
                _try_auto_replicate_ensemble(exp_id)
            if str(status or "").lower() == "completed":
                _handle_completed_experiment_feedback(exp_id)
        return bool(updated)
    except Exception as e:
        logger.warning(f"Failed to update experiment status: {e}")
        return False


def _load_completed_experiment_payload(exp_id: str) -> dict[str, object] | None:
    """Load experiment feedback payload for recommendation lineage and AL ingestion."""
    try:
        from database.repositories.experiment_repo import ExperimentRepository
        from database.repositories.metric_repo import MetricRepository

        def _op(session):
            exp_repo = ExperimentRepository(session)
            metric_repo = MetricRepository(session)
            exp = exp_repo.get_by_id(exp_id)
            if exp is None:
                return None

            metrics = {}
            for metric in metric_repo.get_by_exp(exp_id):
                if metric.value is None:
                    continue
                metrics[metric.metric_name] = float(metric.value)

            composition = {
                "asphaltene": float(exp.comp_asphaltene_wt or 0.0),
                "resin": float(exp.comp_resin_wt or 0.0),
                "aromatic": float(exp.comp_aromatic_wt or 0.0),
                "saturate": float(exp.comp_saturate_wt or 0.0),
            }
            if float(exp.additive_wt or 0.0) > 0.0:
                composition["additive"] = float(exp.additive_wt or 0.0)
            if exp.additive_type:
                composition["additive_type"] = str(exp.additive_type)

            return {
                "metadata": dict(exp.metadata_json or {}),
                "temperature_k": float(exp.temperature_K or 298.0),
                "composition": composition,
                "observed_properties": metrics,
            }

        return run_in_task_session(_op)
    except Exception as exc:
        logger.warning("Failed to load completion payload for %s: %s", exp_id, exc)
        return None


def _mark_feedback_processed(exp_id: str) -> None:
    """Mark experiment feedback as processed."""
    from database.repositories.experiment_repo import ExperimentRepository

    def _op(session):
        ExperimentRepository(session).set_feedback_processed(exp_id)

    run_in_task_session_commit(_op)


def _try_auto_cpu_rerun(exp_id: str) -> None:
    """Auto-trigger CPU rerun if metadata has auto_cpu_rerun=True."""
    try:
        from database.repositories.experiment_repo import ExperimentRepository

        def _check(session):
            repo = ExperimentRepository(session)
            exp = repo.get_by_exp_id(exp_id)
            if not exp:
                return None
            metadata = exp.metadata_json or {}
            interaction_analysis = metadata.get("interaction_analysis", {})
            if interaction_analysis.get("enabled") and interaction_analysis.get(
                "auto_trigger_rerun", True
            ):
                # Codex #2: normalize empty metrics to default
                raw_metrics = interaction_analysis.get("metrics")
                return raw_metrics if raw_metrics else ["e_inter_total"]
            return None

        metrics = run_in_task_session(_check)
        # Codex #2: ensure metrics is non-empty list before triggering
        if metrics and len(metrics) > 0:
            from features.e_inter_compute.service import DEFAULT_E_INTER_COMPUTE_SERVICE

            DEFAULT_E_INTER_COMPUTE_SERVICE.create_cpu_rerun_job(
                exp_id=exp_id,
                metrics=metrics,
                trigger="auto_after_gpu",
            )
            logger.info(f"Auto-triggered CPU rerun for {exp_id}")
    except Exception as exc:
        logger.warning(f"Auto CPU rerun skipped for {exp_id}: {exc}")


def _try_auto_replicate_ensemble(exp_id: str) -> None:
    """replica group 멤버가 종료되면 계면 지표 mean±SE ensemble 자동 집계/보존.

    실패 격리: ensemble 집계 실패는 부모 실험 상태에 영향을 주지 않는다.
    """
    try:
        from features.layered_structures.replicate_orchestration import (
            persist_replicate_ensemble,
        )

        persist_replicate_ensemble(exp_id)
    except Exception as exc:
        logger.warning(f"Auto replicate ensemble skipped for {exp_id}: {exc}")


def _try_structural_retrain() -> None:
    """P6: opt-in V7 structural 재학습 트리거 (기본 OFF).

    정책이 비활성이면 즉시 no-op(외부 호출조차 없음). 실패 격리: 재학습
    실패는 부모 실험 완료 처리에 영향을 주지 않는다.
    """
    try:
        from contracts.policies.structural_ml import DEFAULT_STRUCTURAL_ML_POLICY

        if not DEFAULT_STRUCTURAL_ML_POLICY.enabled:
            return
        from database.connection import session_scope
        from ml.structural_challenger import maybe_retrain_structural

        with session_scope() as session:
            result = maybe_retrain_structural(session)
        if result.get("triggered"):
            logger.info("Structural V7 retrain triggered: %s", result.get("targets"))
    except Exception as exc:
        logger.warning(f"Structural retrain trigger skipped: {exc}")


def _try_write_result_sidecar(exp_id: str) -> None:
    """Best-effort write-through of the experiment result sidecar (opt-in)."""
    try:
        from contracts.policies.result_export import DEFAULT_RESULT_EXPORT_POLICY

        if not DEFAULT_RESULT_EXPORT_POLICY.enabled:
            return
        from database.connection import session_scope
        from features.common.result_sidecar import write_experiment_sidecar

        with session_scope() as session:
            write_experiment_sidecar(session, exp_id)
    except Exception as exc:  # noqa: BLE001 - must never break completion handling
        logger.warning("Result sidecar write-through skipped for %s: %s", exp_id, exc)


def _handle_completed_experiment_feedback(exp_id: str) -> bool:
    """Backfill recommendation lineage and feed completed runs into active learning.

    CPU rerun is triggered early (before metric checks) since it's independent
    of active learning feedback. Failure isolation: rerun failure doesn't affect
    parent experiment status.
    """
    # Auto-trigger CPU rerun first (independent of AL feedback)
    _try_auto_cpu_rerun(exp_id)

    # 보완 #4 후속: replica group이면 완료시 계면 지표 ensemble 자동 집계/보존.
    _try_auto_replicate_ensemble(exp_id)

    # P6: opt-in V7 structural 재학습 트리거 (기본 OFF → no-op, byte-identical).
    _try_structural_retrain()

    # Result sidecar write-through: persist this experiment's shareable result
    # (metadata + scalar metrics + array-curve refs) to a git-tracked JSON so a
    # ``git pull`` + import lights up the graphs on another machine. The large
    # LAMMPS raw outputs stay local (database/). Best-effort, opt-in via policy.
    _try_write_result_sidecar(exp_id)

    payload = _load_completed_experiment_payload(exp_id)
    if not payload:
        return False

    observed_properties = dict(payload.get("observed_properties") or {})
    if not observed_properties:
        return False

    recommendation = None
    try:
        from features.recommendations import pending_service

        recommendation = pending_service.backfill_from_experiment(
            exp_id,
            result_metrics=observed_properties,
        )
    except Exception as exc:
        logger.warning("Recommendation lineage backfill skipped for %s: %s", exp_id, exc)

    metadata = dict(payload.get("metadata") or {})
    should_ingest = (
        recommendation is not None or str(metadata.get("source") or "") == "active_learning"
    )
    if not should_ingest:
        _mark_feedback_processed(exp_id)
        return True

    try:
        from features.recommendations import active_learning as active_learning_service

        active_learning_service.ingest_completed_experiment(
            exp_id=exp_id,
            composition=dict(payload.get("composition") or {}),
            observed_properties=observed_properties,
            temperature_k=float(payload.get("temperature_k") or 298.0),
        )
        _mark_feedback_processed(exp_id)
        return True
    except Exception as exc:
        logger.warning("Active learning feedback skipped for %s: %s", exp_id, exc)
        return False


def _reconcile_dependency_after_status_update(*, exp_id: str, status: str) -> None:
    """Trigger dependency reconciliation on terminal upstream state changes."""
    terminal_statuses = {"completed", "failed", "cancelled", "timeout"}
    if str(status or "").lower() not in terminal_statuses:
        return
    try:
        from orchestrator.celery_job_manager import CeleryJobManager
        from orchestrator.dependency_scheduler import DependencyScheduler
        from orchestrator.gpu_service import get_gpu_service

        scheduler = DependencyScheduler(CeleryJobManager(gpu_tracker=get_gpu_service()))
        scheduler.reconcile_parent(exp_id)
    except Exception as exc:
        logger.warning("Dependency reconcile skipped for exp_id=%s: %s", exp_id, exc)


def _get_experiment_state_by_task_id(task_id: str) -> tuple[str | None, str | None]:
    """Return (exp_id, status) for task_id, or (None, None) if not found."""
    try:
        from database.repositories.experiment_repo import ExperimentRepository

        def _op(session):
            repo = ExperimentRepository(session)
            exp = repo.get_by_celery_task_id(task_id)
            if exp is None:
                return (None, None)
            return (exp.exp_id, str(exp.status or "").lower())

        return run_in_task_session(_op)
    except Exception as e:
        logger.debug(f"Failed to query experiment state for task {task_id}: {e}")
        return (None, None)


def _get_experiment_lifecycle_by_task_id(task_id: str) -> tuple[str | None, str | None, bool]:
    """Return (exp_id, status, completed_at_exists) for task_id."""
    try:
        from database.repositories.experiment_repo import ExperimentRepository

        def _op(session):
            repo = ExperimentRepository(session)
            exp = repo.get_by_celery_task_id(task_id)
            if exp is None:
                return (None, None, False)
            return (exp.exp_id, str(exp.status or "").lower(), exp.completed_at is not None)

        return run_in_task_session(_op)
    except Exception as e:
        logger.debug(f"Failed to query lifecycle for task {task_id}: {e}")
        return (None, None, False)


def _mark_experiment_ready_with_artifact(
    task_id: str,
    exp_id: str,
    prepared_payload: dict,
    property_calculations: dict | None = None,
    additive_type: str | None = None,
    additive_wt: float = 0.0,
    additive_mol_id: str | None = None,
) -> bool:
    """Persist build artifacts and move experiment to ready state."""
    try:
        from database.repositories.experiment_repo import ExperimentRepository

        def _op(session) -> bool:
            repo = ExperimentRepository(session)
            exp = repo.get_by_id(exp_id)
            if exp is None:
                return False
            payload = dict(prepared_payload or {})
            payload["property_calculations"] = property_calculations or {}
            payload["additive"] = {
                "type": additive_type,
                "wt": additive_wt,
                "mol_id": additive_mol_id,
            }
            repo.set_prepared_artifact(exp_id, payload)
            exp.gpu_id_allocated = None
            # Sync ready ownership so update_status won't reject as stale
            # (critical for restart paths where task_id differs from original celery id).
            exp.active_attempt_id = task_id
            repo.update_status(exp_id, "ready", attempt_id=task_id)
            return True

        return bool(run_in_task_session_commit(_op))
    except Exception as e:
        logger.warning("Failed to mark experiment ready for %s: %s", exp_id, e)
        return False


def _is_duplicate_active_execution(exp_id: str, task_id: str) -> bool:
    """
    Detect whether another active task already owns this experiment.
    """
    try:
        from database.repositories.experiment_repo import ExperimentRepository

        def _op(session):
            repo = ExperimentRepository(session)
            exp = repo.get_by_id(exp_id)
            if exp is None:
                return False
            other_task = (exp.active_attempt_id or exp.celery_task_id or "").strip()
            status = str(exp.status or "").lower()
            if not other_task or other_task == task_id:
                return False
            return status in {"queued", "building", "ready", "running", "analyzing"}

        return bool(run_in_task_session(_op))
    except Exception as e:
        logger.debug(f"Failed duplicate-execution check for {exp_id}: {e}")
        return False


def _acquire_exp_lock(exp_id: str, task_id: str, ttl_seconds: int = 172800) -> bool:
    """
    Acquire a distributed lock for exp_id.

    Returns True when lock is acquired by this task, else False.
    Redis errors are treated as lock-acquisition failure (safe-fail).
    """
    lock_key = f"exp_lock:{exp_id}"
    try:
        import redis

        from config.settings import get_settings

        client = redis.Redis.from_url(get_settings().celery.broker_url)
        for attempt in range(3):
            acquired = bool(client.set(lock_key, task_id, nx=True, ex=ttl_seconds))
            if acquired:
                return True

            current_owner = client.get(lock_key)
            if current_owner and current_owner.decode(errors="ignore") == task_id:
                client.expire(lock_key, ttl_seconds)
                return True

            if attempt < 2:
                time.sleep(0.1)
        return False
    except Exception as e:
        logger.error(f"Redis lock acquisition failed for {exp_id}: {e}")
        return False


def _release_exp_lock(exp_id: str, task_id: str) -> None:
    """Release exp_id lock only when owned by this task."""
    lock_key = f"exp_lock:{exp_id}"
    try:
        import redis

        from config.settings import get_settings

        client = redis.Redis.from_url(get_settings().celery.broker_url)
        current_owner = client.get(lock_key)
        if current_owner and current_owner.decode(errors="ignore") == task_id:
            client.delete(lock_key)
    except Exception:
        # Best-effort: lock layer must not break task completion path.
        pass


def _trigger_ready_scheduler(max_submissions: int = 10) -> None:
    """
    Fire-and-forget trigger for ready scheduler.

    Keeps ready->running progression moving even when beat is temporarily down.
    """
    try:
        from orchestrator.celery_app import celery_app

        # Route to the control queue (consumed only by the control@ pool), the
        # SAME queue the routing table pins schedule_ready_experiments to
        # (celery_app.py task_routes). Publishing to "default" sent the
        # dispatcher to the build@/cpu@ pool as well, so it ran concurrently
        # across two pools with no cross-pool mutual exclusion -> overlapping
        # ticks dispatching the same ready experiment. The single-flight lock
        # (run_scheduler) is the primary guard; keeping the queue consistent
        # avoids fanning the dispatcher out across pools in the first place.
        celery_app.send_task(
            "orchestrator.tasks.schedule_ready_experiments",
            kwargs={"max_submissions": int(max_submissions)},
            queue="control",
        )
    except Exception as exc:
        logger.debug("Ready scheduler trigger skipped: %s", exc)
