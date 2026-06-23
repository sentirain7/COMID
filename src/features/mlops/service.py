"""MLOps application service for API layer."""

from api.schemas import (
    DriftCheckResponse,
    MLModelHistoryResponse,
    MLModelVersionResponse,
    RetrainRequest,
    RetrainResponse,
)
from api.utils.time_utils import to_utc_iso as _to_utc_iso
from contracts.errors import ContractError, ErrorCode
from contracts.policies.ml_policy import DEFAULT_ML_POLICY
from features.common import run_in_session


def model_version_to_response(row) -> MLModelVersionResponse:
    test_metrics = dict(row.test_metrics_json or {})
    recommendation_metrics = test_metrics.get("__recommendation__")
    if not isinstance(recommendation_metrics, dict):
        recommendation_metrics = None
    filtered_test_metrics = {
        str(name): dict(metrics)
        for name, metrics in test_metrics.items()
        if name != "__recommendation__" and isinstance(metrics, dict)
    }
    return MLModelVersionResponse(
        version_id=row.version_id,
        status=row.status,
        model_type=row.model_type,
        feature_set_version=row.feature_set_version,
        actual_feature_set=row.actual_feature_set,
        target_names=row.target_names or [],
        per_target_feature_sets=row.per_target_feature_sets_json,
        feature_schema_hash=row.feature_schema_hash,
        training_manifest_hash=row.training_manifest_hash,
        capability_manifest=row.capability_manifest_json,
        training_samples=row.training_samples,
        calibration_ece=row.calibration_ece,
        test_metrics=filtered_test_metrics or None,
        recommendation_metrics=recommendation_metrics,
        created_at=_to_utc_iso(row.created_at),
        promoted_at=_to_utc_iso(row.promoted_at),
        model_artifact_path=row.model_artifact_path,
        triggered_by=row.triggered_by,
        retraining_reason=row.triggered_by,
    )


async def get_ml_champion() -> MLModelVersionResponse:
    """Get currently promoted champion model metadata."""
    from database.repositories.model_version_repo import ModelVersionRepository

    def _query(session):
        repo = ModelVersionRepository(session)
        champion = repo.get_champion()
        if champion is None:
            raise ContractError(ErrorCode.RECORD_NOT_FOUND, "No champion model found")
        return model_version_to_response(champion)

    return run_in_session(_query)


async def get_ml_model_history(
    limit: int = 20, status: str | None = None
) -> MLModelHistoryResponse:
    """Get model version history."""
    from database.repositories.model_version_repo import ModelVersionRepository

    def _query(session):
        repo = ModelVersionRepository(session)
        rows = repo.get_history(limit=max(1, min(limit, 200)), status=status)
        return MLModelHistoryResponse(models=[model_version_to_response(r) for r in rows])

    return run_in_session(_query)


async def retrain_ml_model(request: RetrainRequest) -> RetrainResponse:
    """Manually trigger retraining pipeline.

    PR 2 (Codex Round 6): an explicit ``request.e_intra_method`` overrides
    the champion auto-inherit, enabling Method 1a bootstrap and deliberate
    cutover from the API.
    """
    from api.deps import get_model_retrainer

    def _run(session):
        retrainer = get_model_retrainer(session, e_intra_method=request.e_intra_method)
        result = retrainer.run(
            force=request.force,
            triggered_by=request.triggered_by or "api",
        )
        comparison_dict = None
        if result.comparison_result is not None:
            comparison_dict = {
                "test_type": result.comparison_result.test_type,
                "p_value": result.comparison_result.p_value,
                "improvement_pct": result.comparison_result.improvement_pct,
                "reason": result.comparison_result.reason,
            }
        return RetrainResponse(
            success=result.success,
            version_id=result.version_id,
            trigger_reason=result.trigger_reason,
            training_samples=result.training_samples,
            promoted=result.promoted,
            duration_seconds=result.duration_seconds,
            comparison=comparison_dict,
        )

    return run_in_session(_run)


async def promote_ml_model(version_id: str) -> MLModelVersionResponse:
    """Promote challenger model to champion."""
    from api.deps import get_model_registry
    from contracts.errors import MLOpsError

    try:

        def _promote(session):
            registry = get_model_registry(session)
            row = registry.promote(version_id)
            return model_version_to_response(row)

        return run_in_session(_promote)
    except MLOpsError as e:
        raise ContractError(
            ErrorCode.RECORD_NOT_FOUND,
            e.message,
            {"version_id": version_id},
        ) from e


async def rollback_ml_model() -> MLModelVersionResponse:
    """Rollback champion to previous promoted model."""
    from api.deps import get_model_registry
    from contracts.errors import MLOpsError

    try:

        def _rollback(session):
            registry = get_model_registry(session)
            row = registry.rollback()
            return model_version_to_response(row)

        return run_in_session(_rollback)
    except MLOpsError as e:
        raise ContractError(ErrorCode.INVALID_REQUEST, e.message) from e


async def check_ml_drift() -> DriftCheckResponse:
    """Run on-demand drift check against current champion and recent data.

    PR 2 (Codex Round 5): the loop inherits the champion's CED label method
    so any retraining triggered by drift detection stays on the same
    e_intra_method contract.
    """
    from api.deps import _resolve_champion_e_intra_method
    from orchestrator.continuous_loop import ContinuousLearningLoop

    def _check(session):
        # Critical path: drift judgement must not silently drift to baseline
        # (Codex Round 7).
        method = _resolve_champion_e_intra_method(session, strict=True)
        loop = ContinuousLearningLoop(session, e_intra_method=method)
        outcome = loop.drift_check_only()
        drift = outcome.get("drift") or {
            "drift_type": "none",
            "feature_drift_fraction": 0.0,
            "rmse_drift_pct": 0.0,
            "page_hinkley_detected": False,
            "should_retrain": False,
        }
        drift["checked_at"] = outcome.get("checked_at")
        drift["new_samples"] = outcome.get("new_samples")
        drift.setdefault("drifted_targets", [])
        return DriftCheckResponse(**drift)

    return run_in_session(_check)


def trigger_retraining_if_needed(
    *,
    triggered_by: str = "active_learning",
    new_samples: int | None = None,
    force: bool = False,
    completed_exp_ids: list[str] | None = None,
) -> bool:
    """Synchronous contract for recommendation workflows to trigger retraining."""
    from api.deps import get_model_retrainer

    effective_new_samples = (
        DEFAULT_ML_POLICY.retraining.min_new_samples if new_samples is None else int(new_samples)
    )
    normalized_exp_ids = sorted({str(exp_id) for exp_id in (completed_exp_ids or []) if exp_id})

    def _run(session):
        from database.repositories.recommendation_repo import PendingRecommendationRepository

        retrainer = get_model_retrainer(session)
        linked_rows = []
        lineage_snapshot: dict[str, object] | None = None
        if normalized_exp_ids:
            repo = PendingRecommendationRepository(session)
            linked_rows = repo.get_by_queued_exp_ids(normalized_exp_ids)
            linked_recommendation_ids = sorted({row.id for row in linked_rows if row.id})
            lineage_snapshot = {
                "active_learning_exp_ids": normalized_exp_ids,
                "linked_recommendation_ids": linked_recommendation_ids,
            }
        result = retrainer.run(
            force=force,
            triggered_by=triggered_by,
            new_samples=effective_new_samples,
            training_snapshot_extra=lineage_snapshot,
        )
        did_retrain = bool(result.version_id or result.promoted)
        if did_retrain and linked_rows:
            repo = PendingRecommendationRepository(session)
            for row in linked_rows:
                repo.mark_fed_back(row.id)
        return did_retrain

    return run_in_session(_run)
