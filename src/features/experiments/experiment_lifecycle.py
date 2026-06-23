"""Experiment lifecycle operations: cancel, delete, retry, batch ops.

Extracted from query.py — lifecycle management for experiments.
"""

from collections import Counter

from sqlalchemy import func, or_

from common.logging import get_logger
from contracts.errors import (
    ContractError,
    ErrorCode,
    OrchestrationError,
)
from features.common import run_in_session, run_in_session_commit

logger = get_logger("features.experiments.experiment_lifecycle")

# ---------------------------------------------------------------------------
# Status policies (SSOT)
# ---------------------------------------------------------------------------
CANCELABLE_STATUSES = {"pending", "queued", "building", "ready", "running", "analyzing"}
DELETABLE_STATUSES = {"ready", "completed", "failed", "cancelled", "timeout"}
# GPU release is safe only when no LAMMPS process is active.
_GPU_IMMEDIATE_RELEASE_STATUSES = {"pending", "queued", "building", "ready"}

# Active recommendation statuses (candidates for cancellation on experiment deletion)
_ACTIVE_RECOMMENDATION_STATUSES = {"pending", "approved", "queued", "running"}


def _raise_experiment_not_found(exp_id: str) -> None:
    from contracts.errors import DatabaseError

    raise DatabaseError(
        ErrorCode.RECORD_NOT_FOUND,
        f"Experiment {exp_id} not found",
        {"exp_id": exp_id},
    )


def _resolve_retry_e_intra_method(exp, protocol_payload: dict | None = None) -> str:
    """Resolve the preserved E_intra method for retry/recovery.

    Retry/recovery must preserve the original experiment provenance and must
    not reinterpret the method from current settings.
    """
    from contracts.schema_enums import normalize_e_intra_method

    if isinstance(protocol_payload, dict):
        payload_method = normalize_e_intra_method(protocol_payload.get("e_intra_method"))
        if payload_method:
            return payload_method

    exp_meta = getattr(exp, "metadata_json", None) or {}
    if isinstance(exp_meta, dict):
        meta_method = normalize_e_intra_method(exp_meta.get("e_intra_method"))
        if meta_method:
            return meta_method

    try:
        from features.experiments.e_intra_method import resolve_experiment_e_intra_method

        resolved_method, _origin, _resolved_from = resolve_experiment_e_intra_method(exp)
        if resolved_method:
            return resolved_method
    except Exception:
        pass

    return "single_molecule_vacuum"


# ---------------------------------------------------------------------------
# Cascade delete helper functions
# ---------------------------------------------------------------------------


def _remove_exp_id_from_json_list(value: list | None, exp_id: str) -> list:
    """Remove a specific exp_id from a JSON string list."""
    if not value:
        return []
    return [v for v in value if v != exp_id]


def _remove_exp_id_from_nested_json(value: list | None, exp_id: str) -> list:
    """Remove exp_id references from nested JSON list[dict] structure.

    Used for source_records_json and similar nested structures.
    Removes dict entries where any exp_id-related key matches the deleted exp_id.
    """
    if not value or not isinstance(value, list):
        return []

    exp_id_keys = {"exp_id", "source_exp_id", "queued_exp_id", "matched_exp_id"}
    result = []
    for item in value:
        if isinstance(item, dict):
            should_keep = True
            for key in exp_id_keys:
                if item.get(key) == exp_id:
                    should_keep = False
                    break
            if should_keep:
                result.append(item)
        elif item != exp_id:
            result.append(item)
    return result


def _delete_metrics_with_artifacts(session, exp_id: str, experiment_id: int | None) -> list[str]:
    """Delete metrics and properly manage array artifact ref_counts.

    Aggregates artifact references first to avoid duplicate ref_count decrements
    when multiple metrics share the same artifact.
    Returns workspace-relative file paths that should be unlinked only after
    the surrounding DB transaction commits successfully.
    """
    from database.models import MetricModel
    from database.models.metric import MetricArrayArtifactModel

    # Build filter conditions
    conditions = [MetricModel.exp_id == exp_id]
    if experiment_id is not None:
        conditions.append(MetricModel.experiment_id == experiment_id)

    metric_rows = session.query(MetricModel).filter(or_(*conditions)).all()

    # Aggregate artifact references to avoid duplicate decrements
    artifact_ref_counts: Counter[int] = Counter()
    legacy_file_paths: set[str] = set()
    deferred_file_deletions: set[str] = set()

    for m in metric_rows:
        if m.array_artifact_id:
            artifact_ref_counts[m.array_artifact_id] += 1
        elif m.array_file_path:
            legacy_file_paths.add(m.array_file_path)

    # Decrement ref_counts (aggregated, not per-metric)
    for artifact_id, count in artifact_ref_counts.items():
        artifact = session.get(MetricArrayArtifactModel, artifact_id)
        if artifact:
            artifact.ref_count = max(0, (artifact.ref_count or 1) - count)
            if artifact.ref_count == 0:
                if artifact.storage_path:
                    deferred_file_deletions.add(str(artifact.storage_path))
                session.delete(artifact)

    # Delete legacy array files after commit only (unique paths only)
    for file_path in legacy_file_paths:
        deferred_file_deletions.add(str(file_path))

    # Delete metric rows
    session.query(MetricModel).filter(or_(*conditions)).delete(synchronize_session=False)
    return sorted(deferred_file_deletions)


def _delete_deferred_files(file_paths: list[str] | tuple[str, ...] | set[str] | None) -> None:
    """Best-effort unlink of files after DB commit has succeeded."""
    if not file_paths:
        return

    from features.common.workspace import resolve_workspace_path

    for file_path in sorted({str(path) for path in file_paths if path}):
        try:
            safe_path = resolve_workspace_path(file_path)
            safe_path.unlink(missing_ok=True)
        except Exception as e:
            logger.warning("Failed to delete deferred experiment file %s: %s", file_path, e)


def _delete_direct_outputs(session, exp_id: str) -> None:
    """Delete direct outputs of an experiment (not workflow references)."""
    from database.models.campaign import CampaignExperimentModel
    from database.models.metric import EIntraModel
    from database.models.recommendation import DesignSimulationRecord

    # Delete E_intra cache entries
    session.query(EIntraModel).filter(EIntraModel.source_exp_id == exp_id).delete(
        synchronize_session=False
    )

    # Delete campaign experiment linkages
    session.query(CampaignExperimentModel).filter(CampaignExperimentModel.exp_id == exp_id).delete(
        synchronize_session=False
    )

    # Design simulation records: SET NULL + status='cancelled'
    session.query(DesignSimulationRecord).filter(DesignSimulationRecord.exp_id == exp_id).update(
        {"exp_id": None, "status": "cancelled"}, synchronize_session=False
    )


def _detach_workflow_references(session, exp_id: str) -> None:
    """Remove exp_id references from workflow/audit records (preserving rows)."""
    from database.models.binder_analysis import BinderAnalysisRunModel
    from database.models.llm import AuditLogModel, LLMTurnsTrainModel
    from database.models.recommendation import (
        PendingRecommendationModel,
    )
    from database.models.structure import AmorphousCellModel

    # AmorphousCells: SET NULL
    session.query(AmorphousCellModel).filter(
        AmorphousCellModel.stabilization_exp_id == exp_id
    ).update({"stabilization_exp_id": None}, synchronize_session=False)

    # BinderAnalysisRuns: SET NULL for both exp_id and matched_exp_id
    session.query(BinderAnalysisRunModel).filter(BinderAnalysisRunModel.exp_id == exp_id).update(
        {"exp_id": None}, synchronize_session=False
    )

    session.query(BinderAnalysisRunModel).filter(
        BinderAnalysisRunModel.matched_exp_id == exp_id
    ).update({"matched_exp_id": None}, synchronize_session=False)

    # AuditLog: SET NULL
    session.query(AuditLogModel).filter(AuditLogModel.exp_id == exp_id).update(
        {"exp_id": None}, synchronize_session=False
    )

    # LLMTurnsTrain: SET NULL
    session.query(LLMTurnsTrainModel).filter(LLMTurnsTrainModel.exp_id == exp_id).update(
        {"exp_id": None}, synchronize_session=False
    )

    # PendingRecommendations: Active status → cancelled, terminal status → preserve
    session.query(PendingRecommendationModel).filter(
        PendingRecommendationModel.queued_exp_id == exp_id,
        PendingRecommendationModel.status.in_(_ACTIVE_RECOMMENDATION_STATUSES),
    ).update(
        {
            "queued_exp_id": None,
            "status": "cancelled",
            "notes": func.coalesce(PendingRecommendationModel.notes, "")
            + " [linked experiment deleted]",
        },
        synchronize_session=False,
    )

    # PendingRecommendations: Terminal status — only clear exp_id
    session.query(PendingRecommendationModel).filter(
        PendingRecommendationModel.queued_exp_id == exp_id,
        ~PendingRecommendationModel.status.in_(_ACTIVE_RECOMMENDATION_STATUSES),
    ).update({"queued_exp_id": None}, synchronize_session=False)

    # JSON array fields cleanup
    _remove_exp_from_json_fields(session, exp_id)


def _remove_exp_from_json_fields(session, exp_id: str) -> None:
    """Remove deleted exp_id from JSON array fields."""
    from database.models.campaign import MLModelVersionModel
    from database.models.orchestration import ScenarioModel
    from database.models.recommendation import (
        PendingRecommendationModel,
        PropertyDesignSessionModel,
    )

    # PropertyDesignSession.simulation_exp_ids_json (string list)
    for row in (
        session.query(PropertyDesignSessionModel)
        .filter(PropertyDesignSessionModel.simulation_exp_ids_json.isnot(None))
        .all()
    ):
        if exp_id in (row.simulation_exp_ids_json or []):
            row.simulation_exp_ids_json = _remove_exp_id_from_json_list(
                row.simulation_exp_ids_json, exp_id
            )

    # ScenarioModel.result_exp_ids (string list)
    for row in session.query(ScenarioModel).filter(ScenarioModel.result_exp_ids.isnot(None)).all():
        if exp_id in (row.result_exp_ids or []):
            row.result_exp_ids = _remove_exp_id_from_json_list(row.result_exp_ids, exp_id)

    # MLModelVersionModel.holdout_exp_ids (string list)
    for row in (
        session.query(MLModelVersionModel)
        .filter(MLModelVersionModel.holdout_exp_ids.isnot(None))
        .all()
    ):
        if exp_id in (row.holdout_exp_ids or []):
            row.holdout_exp_ids = _remove_exp_id_from_json_list(row.holdout_exp_ids, exp_id)

    # PendingRecommendationModel.source_records_json (list[dict])
    for row in (
        session.query(PendingRecommendationModel)
        .filter(PendingRecommendationModel.source_records_json.isnot(None))
        .all()
    ):
        original = row.source_records_json or []
        cleaned = _remove_exp_id_from_nested_json(original, exp_id)
        if len(cleaned) != len(original):
            row.source_records_json = cleaned


# ---------------------------------------------------------------------------
# Shared single-experiment helpers (used by both single and batch paths)
# ---------------------------------------------------------------------------


def _cancel_one(session, exp_id: str) -> dict[str, object]:
    """Cancel a single experiment within an existing session.

    Returns a result dict.  Does NOT commit — caller manages the transaction.
    """
    from database.repositories.experiment_repo import ExperimentRepository

    repo = ExperimentRepository(session)
    exp = repo.get_by_id(exp_id)
    if not exp:
        return {"exp_id": exp_id, "success": False, "reason": "not_found"}

    if exp.status not in CANCELABLE_STATUSES:
        return {"exp_id": exp_id, "success": False, "reason": f"status:{exp.status}"}

    # Revoke Celery task
    if exp.celery_task_id:
        try:
            from orchestrator.celery_app import celery_app

            celery_app.control.revoke(exp.celery_task_id, terminate=True, signal="SIGTERM")
        except Exception as exc:
            logger.warning(f"Failed to revoke Celery task for {exp_id}: {exc}")

    # GPU: immediate release only for non-running states (running/analyzing
    # delegates to the worker finally block to prevent duplicate allocation).
    if exp.status in _GPU_IMMEDIATE_RELEASE_STATUSES and exp.gpu_id_allocated is not None:
        try:
            from orchestrator.gpu_service import get_gpu_service

            get_gpu_service().release(int(exp.gpu_id_allocated), exp_id=exp_id)
        except Exception as exc:
            logger.warning(f"Failed to release GPU for {exp_id}: {exc}")

    repo.update_status(exp_id, "cancelled", error_message="Cancelled by user")

    try:
        from orchestrator.exp_lock_manager import clear_lock_for_experiment

        clear_lock_for_experiment(exp_id, force=True)
    except Exception as exc:
        logger.warning("Failed to clear exp lock on cancel for %s: %s", exp_id, exc)

    return {"exp_id": exp_id, "success": True, "reason": None}


def _delete_one(session, exp_id: str) -> dict[str, object]:
    """Delete a single experiment within an existing session.

    Full cascade:
    1. Direct outputs: metrics, e_intra, campaign_experiments, design_simulation_records
    2. Workflow references: SET NULL (amorphous_cells, binder_analysis_runs, audit_log, etc.)
    3. JSON array cleanup: simulation_exp_ids_json, result_exp_ids, etc.
    4. Dependencies/process info/layered sources
    5. Experiment row (includes experiment_molecules, experiment_conditions via repo)

    Does NOT commit — caller manages the transaction.
    """
    from database.repositories.experiment_repo import ExperimentRepository

    repo = ExperimentRepository(session)
    experiment = repo.get_by_id(exp_id)
    if not experiment:
        return {"exp_id": exp_id, "success": False, "reason": "not_found"}

    if experiment.status not in DELETABLE_STATUSES:
        return {"exp_id": exp_id, "success": False, "reason": f"status:{experiment.status}"}

    experiment_id = experiment.id  # DB primary key for metric lookup

    # Revoke Celery task
    if experiment.celery_task_id:
        try:
            from orchestrator.celery_app import celery_app

            celery_app.control.revoke(experiment.celery_task_id, terminate=True, signal="SIGTERM")
        except Exception as exc:
            logger.warning(f"Failed to revoke Celery task for {exp_id}: {exc}")

    # GPU immediate release (non-running states only)
    if (
        experiment.status in _GPU_IMMEDIATE_RELEASE_STATUSES
        and experiment.gpu_id_allocated is not None
    ):
        try:
            from orchestrator.gpu_service import get_gpu_service

            get_gpu_service().release(int(experiment.gpu_id_allocated), exp_id=exp_id)
        except Exception as exc:
            logger.warning(f"Failed to release GPU for {exp_id}: {exc}")

    # ========== DB CASCADE DELETE (exceptions propagate for rollback) ==========
    # DB 정합성 작업 — 실패 시 예외 전파하여 전체 트랜잭션 rollback
    # 파일 삭제 실패는 각 함수 내부에서 warning 처리되므로 안전

    # 1. Delete metrics + array artifacts (with aggregated ref_count handling)
    deferred_file_deletions = _delete_metrics_with_artifacts(session, exp_id, experiment_id)

    # 2. Delete direct outputs (e_intra, campaign_experiments, etc.)
    _delete_direct_outputs(session, exp_id)

    # 3. Detach workflow references (SET NULL, JSON cleanup)
    _detach_workflow_references(session, exp_id)

    # 4. Delete dependency / process / layered source rows
    from database.models import JobDependencyModel, ProcessInfoModel

    session.query(JobDependencyModel).filter(
        (JobDependencyModel.parent_exp_id == exp_id) | (JobDependencyModel.child_exp_id == exp_id)
    ).delete(synchronize_session=False)
    session.query(ProcessInfoModel).filter(ProcessInfoModel.exp_id == exp_id).delete(
        synchronize_session=False
    )

    # 5. Delete layered experiment source rows (FK: exp_id)
    from database.models import LayeredExperimentSourceModel

    session.query(LayeredExperimentSourceModel).filter(
        LayeredExperimentSourceModel.exp_id == exp_id
    ).delete(synchronize_session=False)

    # ========== EXTERNAL SYSTEM CLEANUP (exceptions swallowed) ==========
    # 외부 시스템 실패는 experiment 삭제를 막지 않음

    # 6. Delete experiment (includes experiment_molecules via repo)
    repo.delete(exp_id)

    # 7. Clear lock (external system)
    try:
        from orchestrator.exp_lock_manager import clear_lock_for_experiment

        clear_lock_for_experiment(exp_id, force=True)
    except Exception as exc:
        logger.warning("Failed to clear exp lock on delete for %s: %s", exp_id, exc)

    return {
        "exp_id": exp_id,
        "success": True,
        "reason": None,
        "deferred_files": deferred_file_deletions,
    }


# ---------------------------------------------------------------------------
# Public API: single experiment cancel / delete (backward compatible)
# ---------------------------------------------------------------------------


async def delete_experiment(exp_id: str) -> dict[str, object]:
    """Delete an experiment and associated data."""
    try:

        def _do(session):
            result = _delete_one(session, exp_id)
            if not result.get("success"):
                reason = result.get("reason", "unknown")
                if reason == "not_found":
                    _raise_experiment_not_found(exp_id)
                raise OrchestrationError(
                    code=ErrorCode.JOB_LIMIT_EXCEEDED,
                    message=f"Cannot delete experiment {exp_id}: {reason}",
                )
            session.commit()
            _delete_deferred_files(result.get("deferred_files", []))
            return {"exp_id": exp_id, "deleted": True}

        return run_in_session(_do)
    except ImportError:
        return {"exp_id": exp_id, "deleted": True}


async def cancel_experiment(exp_id: str) -> dict[str, object]:
    """Cancel pending or running experiment."""
    try:

        def _do(session):
            result = _cancel_one(session, exp_id)
            if not result.get("success"):
                reason = result.get("reason", "unknown")
                if reason == "not_found":
                    _raise_experiment_not_found(exp_id)
                raise OrchestrationError(
                    code=ErrorCode.JOB_LIMIT_EXCEEDED,
                    message=f"Cannot cancel experiment {exp_id}: {reason}",
                )
            session.commit()
            return {"exp_id": exp_id, "cancelled": True}

        return run_in_session(_do)
    except ImportError:
        return {"exp_id": exp_id, "cancelled": True}


# ---------------------------------------------------------------------------
# Public API: batch cancel / delete
# ---------------------------------------------------------------------------


async def batch_cancel_experiments(exp_ids: list[str]) -> dict[str, object]:
    """Cancel multiple experiments. Per-item commit for partial success."""
    results = {"total": len(exp_ids), "succeeded": 0, "skipped": 0, "failed": 0, "details": []}

    def _do(session):
        for eid in exp_ids:
            try:
                r = _cancel_one(session, eid)
                session.commit()
                if r.get("success"):
                    results["succeeded"] += 1
                else:
                    results["skipped"] += 1
                results["details"].append(r)
            except Exception as exc:
                session.rollback()
                results["failed"] += 1
                results["details"].append({"exp_id": eid, "success": False, "reason": str(exc)})

    try:
        run_in_session(_do)
    except ImportError:
        pass
    return results


async def batch_delete_experiments(exp_ids: list[str]) -> dict[str, object]:
    """Delete multiple experiments. Per-item commit for partial success."""
    results = {"total": len(exp_ids), "succeeded": 0, "skipped": 0, "failed": 0, "details": []}

    def _do(session):
        for eid in exp_ids:
            try:
                r = _delete_one(session, eid)
                session.commit()
                if r.get("success"):
                    _delete_deferred_files(r.get("deferred_files", []))
                    results["succeeded"] += 1
                else:
                    results["skipped"] += 1
                results["details"].append(r)
            except Exception as exc:
                session.rollback()
                results["failed"] += 1
                results["details"].append({"exp_id": eid, "success": False, "reason": str(exc)})

    try:
        run_in_session(_do)
    except ImportError:
        pass
    return results


async def batch_retry_experiments(exp_ids: list[str]) -> dict[str, object]:
    """Retry multiple experiments. Per-item for partial success."""
    results = {"total": len(exp_ids), "succeeded": 0, "skipped": 0, "failed": 0, "details": []}

    for eid in exp_ids:
        try:
            await retry_experiment(eid)
            results["succeeded"] += 1
            results["details"].append({"exp_id": eid, "success": True, "reason": None})
        except ContractError as exc:
            # Status not retryable (e.g., still running)
            results["skipped"] += 1
            results["details"].append({"exp_id": eid, "success": False, "reason": str(exc)})
        except Exception as exc:
            results["failed"] += 1
            results["details"].append({"exp_id": eid, "success": False, "reason": str(exc)})

    return results


async def retry_experiment(exp_id: str) -> dict[str, object]:
    """Retry a previously finished experiment by resubmitting with incremented seed."""
    from api.deps import get_job_manager
    from config.dashboard_settings import load_dashboard_settings
    from contracts.policies.tier import DEFAULT_TIER_POLICY
    from orchestrator.request_factory import create_build_request, create_protocol_request

    try:
        job_manager = get_job_manager()
    except RuntimeError as exc:
        logger.warning(f"Job manager unavailable: {exc}")
        raise OrchestrationError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "Infrastructure degraded. Retry unavailable.",
            {"reason": str(exc)},
        ) from exc

    dashboard_settings = load_dashboard_settings()
    selected_gpus = dashboard_settings.get("selected_gpus", []) or None

    def _retry(session):
        from database.repositories.experiment_repo import ExperimentRepository
        from protocols.duration_adjuster import StageDurationOverride

        repo = ExperimentRepository(session)
        exp = repo.get_by_id(exp_id)
        if not exp:
            _raise_experiment_not_found(exp_id)

        if exp.status in {"pending", "queued", "building", "ready", "running", "analyzing"}:
            raise ContractError(
                ErrorCode.INVALID_REQUEST,
                f"Cannot retry active experiment with status: {exp.status}",
                {"exp_id": exp_id, "status": exp.status},
            )

        # --- Checkpoint-first restart (v1) ---
        # If a stage-boundary restart file exists, resume from there
        # instead of re-running from scratch.  exp_id and seed are
        # preserved for checkpoint restarts.
        if exp.prepared_artifact_json and exp.metadata_json:
            from orchestrator.task_runners import prepare_restart_artifact
            from protocols.restart_discovery import discover_restart_point

            compiled_plan = exp.metadata_json.get("compiled_execution_plan")
            if compiled_plan:
                from pathlib import Path

                from orchestrator.task_common import get_experiment_work_dir

                base_dir = get_experiment_work_dir(exp_id)
                candidate_dirs: list[Path] = sorted(
                    base_dir.glob("attempt_*"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                # Also check compositions path where LAMMPS writes restart files.
                from common.pathing import get_experiment_path

                compositions_input = get_experiment_path(exp_id, "input")
                if compositions_input.is_dir() and compositions_input not in candidate_dirs:
                    candidate_dirs.append(compositions_input)

                restart_point = discover_restart_point(exp_id, compiled_plan, candidate_dirs)
                if restart_point is not None:
                    exp.completed_at = None  # type: ignore[assignment]
                    exp.error_code = None  # type: ignore[assignment]
                    exp.error_message = None  # type: ignore[assignment]
                    session.commit()
                    ok = prepare_restart_artifact(exp_id, restart_point)
                    if ok:
                        return {
                            "exp_id": exp_id,
                            "job_id": "checkpoint_restart",
                            "status": "ready",
                            "retry_count": exp.retry_count or 0,
                            "checkpoint_resume": True,
                        }

        # --- Fallback: fresh rerun with seed+1 ---
        next_seed = (exp.seed or 0) + 1

        # Priority-based request restoration for fresh rerun
        from pydantic import ValidationError

        from contracts.schemas import BuildRequest, ProtocolRequest

        build_request = None
        protocol_request = None
        stage_duration_overrides = None

        # Priority 1: Restore from prepared_artifact_json
        artifact = exp.prepared_artifact_json or {}
        if artifact.get("build_request") and artifact.get("protocol_request"):
            try:
                restored_method = _resolve_retry_e_intra_method(exp, artifact["protocol_request"])
                build_request = BuildRequest.model_validate(
                    {
                        **artifact["build_request"],
                        "seed": next_seed,
                    }
                )
                protocol_request = ProtocolRequest.model_validate(
                    {
                        **artifact["protocol_request"],
                        "e_intra_method": restored_method,
                        "data_file_path": artifact["protocol_request"].get("data_file_path", ""),
                    }
                )
                if artifact.get("stage_duration_overrides"):
                    stage_duration_overrides = [
                        StageDurationOverride(**o) for o in artifact["stage_duration_overrides"]
                    ]
                logger.info(f"Retry {exp_id}: restored from prepared_artifact_json")
            except ValidationError as e:
                raise ContractError(
                    ErrorCode.INVALID_REQUEST,
                    f"Cannot retry {exp_id}: corrupted prepared_artifact_json",
                    {"exp_id": exp_id, "error": str(e)},
                ) from e

        # Priority 2: Restore from metadata_json.deferred_submission
        if build_request is None:
            deferred = (exp.metadata_json or {}).get("deferred_submission", {})
            if deferred.get("build_request") and deferred.get("protocol_request"):
                try:
                    restored_method = _resolve_retry_e_intra_method(
                        exp, deferred["protocol_request"]
                    )
                    build_request = BuildRequest.model_validate(
                        {
                            **deferred["build_request"],
                            "seed": next_seed,
                        }
                    )
                    protocol_request = ProtocolRequest.model_validate(
                        {
                            **deferred["protocol_request"],
                            "e_intra_method": restored_method,
                            "data_file_path": deferred["protocol_request"].get(
                                "data_file_path", ""
                            ),
                        }
                    )
                    if deferred.get("stage_duration_overrides"):
                        stage_duration_overrides = [
                            StageDurationOverride(**o) for o in deferred["stage_duration_overrides"]
                        ]
                    logger.info(f"Retry {exp_id}: restored from deferred_submission")
                except ValidationError as e:
                    raise ContractError(
                        ErrorCode.INVALID_REQUEST,
                        f"Cannot retry {exp_id}: corrupted deferred_submission",
                        {"exp_id": exp_id, "error": str(e)},
                    ) from e

        # Priority 3: DB-based restoration for single_molecule_vacuum
        if build_request is None and exp.study_type == "single_molecule_vacuum":
            exp_mols = repo.get_experiment_molecules(exp_id)
            if exp_mols:
                mol_counts = {mol.mol_id: exp_mol.count for exp_mol, mol in exp_mols}
                build_request = BuildRequest(
                    composition=mol_counts,
                    composition_mode="mol_count",
                    target_atoms=exp.target_atoms or 100,
                    initial_density=0.01,
                    seed=next_seed,
                )
                protocol_request = create_protocol_request(
                    tier=exp.run_tier or "screening",
                    ff_type=exp.ff_type or "bulk_ff_gaff2",
                    temperature_K=exp.temperature_K or 298.0,
                    pressure_atm=exp.pressure_atm or 1.0,
                    study_type="single_molecule_vacuum",
                    e_intra_method=_resolve_retry_e_intra_method(exp),
                    skip_stage_keys=["npt_production"],
                )
                logger.info(f"Retry {exp_id}: restored from experiment_molecules DB")
            else:
                raise ContractError(
                    ErrorCode.INVALID_REQUEST,
                    f"Cannot retry single-molecule experiment {exp_id}: "
                    "original build configuration could not be reconstructed; resubmit required",
                    {"exp_id": exp_id, "study_type": exp.study_type},
                )

        # Priority 4: SARA fallback for bulk/layer experiments only
        if build_request is None:
            if exp.study_type == "single_molecule_vacuum":
                # Should not reach here, but safety check
                raise ContractError(
                    ErrorCode.INVALID_REQUEST,
                    f"Cannot retry single-molecule experiment {exp_id}: "
                    "original build configuration could not be reconstructed; resubmit required",
                    {"exp_id": exp_id},
                )

            target_atoms = exp.target_atoms or DEFAULT_TIER_POLICY.get_target_atoms(exp.run_tier)
            build_request = create_build_request(
                composition={
                    "asphaltene": exp.comp_asphaltene_wt,
                    "resin": exp.comp_resin_wt,
                    "aromatic": exp.comp_aromatic_wt,
                    "saturate": exp.comp_saturate_wt,
                },
                target_atoms=target_atoms,
                seed=next_seed,
                tier=exp.run_tier,
            )
            protocol_request = create_protocol_request(
                tier=exp.run_tier,
                ff_type=exp.ff_type,
                temperature_K=exp.temperature_K or 298.0,
                pressure_atm=exp.pressure_atm or 1.0,
                e_intra_method=_resolve_retry_e_intra_method(exp),
            )
            logger.info(f"Retry {exp_id}: created from SARA composition (bulk/layer)")

        # stage_duration_overrides from exp if not restored above
        if stage_duration_overrides is None and exp.stage_duration_overrides:
            try:
                stage_duration_overrides = [
                    StageDurationOverride(**o) for o in exp.stage_duration_overrides
                ]
            except (ValidationError, TypeError, KeyError) as e:
                raise ContractError(
                    ErrorCode.INVALID_REQUEST,
                    f"Cannot retry {exp_id}: corrupted stage_duration_overrides",
                    {"exp_id": exp_id, "error": str(e)},
                ) from e

        try:
            job_id = job_manager.submit(
                build_request=build_request,
                protocol_request=protocol_request,
                material_id="retry_experiment",
                selected_gpus=selected_gpus,
                stage_duration_overrides=stage_duration_overrides,
                exp_id=exp.exp_id,
                additive_type=exp.additive_type,
                additive_wt=exp.additive_wt or 0.0,
                additive_mol_id=exp.additive_mol_id,
            )
        except ValueError as e:
            raise ContractError(
                ErrorCode.INVALID_REQUEST,
                f"Cannot retry {exp_id}: {e}",
                {"exp_id": exp_id, "reason": str(e)},
            ) from e

        celery_task_id = job_manager.get_task_id(job_id)
        if celery_task_id:
            repo.update_celery_task_id(exp_id, celery_task_id)
        repo.update_status(exp_id, "queued")
        exp.seed = next_seed  # type: ignore[assignment]
        exp.completed_at = None  # type: ignore[assignment]
        exp.error_code = None  # type: ignore[assignment]
        exp.error_message = None  # type: ignore[assignment]
        # Clear prior-attempt dashboard timing metadata so elapsed does
        # not surface the stale freeze value while queued; pipeline's
        # composition_validation entry will rewrite these keys.
        if exp.metadata_json:
            meta = dict(exp.metadata_json)
            stale_keys_removed = False
            for key in (
                "dashboard_build_started_at",
                "dashboard_build_completed_at",
                "build_progress_percent",
            ):
                if key in meta:
                    meta.pop(key, None)
                    stale_keys_removed = True
            if stale_keys_removed:
                exp.metadata_json = meta  # type: ignore[assignment]
        retry_count = repo.increment_retry(exp_id)

        return {
            "exp_id": exp_id,
            "job_id": job_id,
            "status": "queued",
            "retry_count": retry_count,
        }

    return run_in_session_commit(_retry)
