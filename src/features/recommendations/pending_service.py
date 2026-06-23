"""Persistent pending recommendation service for Binder Design workflows."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from api.schemas import RecommendationDetailResponse, UnifiedRecommendation
from contracts.errors import ContractError, ErrorCode
from contracts.schema_enums import RecommendationMode, RecommendationStatus, SimulationPriority
from database.repositories.recommendation_repo import PendingRecommendationRepository
from features.common import run_in_session, run_in_session_commit

_REQUIRED_COMPOSITION_KEYS = ("asphaltene", "resin", "aromatic", "saturate")


def _now_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_composition(raw: dict[str, object] | None) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, float] = {}
    for key, value in raw.items():
        if value is None:
            continue
        normalized[str(key)] = _safe_float(value)
    return normalized


def _extract_additive_wt(candidate: dict[str, object]) -> float | None:
    if "additive_wt_pct" in candidate:
        return _safe_float(candidate.get("additive_wt_pct"))
    min_wt = candidate.get("recommended_wt_pct_min")
    max_wt = candidate.get("recommended_wt_pct_max")
    if min_wt is None and max_wt is None:
        return None
    return (_safe_float(min_wt) + _safe_float(max_wt)) / 2.0


def _normalize_candidate(candidate: dict[str, object]) -> dict[str, object]:
    return {
        "origin": str(candidate.get("origin") or "optimizer"),
        "mode": str(candidate.get("mode") or RecommendationMode.KNOWN),
        "model_version_id": candidate.get("model_version_id"),
        "feature_set_version": candidate.get("feature_set_version"),
        "simulation_priority": candidate.get("simulation_priority"),
        "additive_type": candidate.get("additive_type"),
        "additive_wt_pct": _extract_additive_wt(candidate),
        "score": _safe_float(candidate.get("score"), 0.0),
        "composition_json": _normalize_composition(candidate.get("composition")),  # type: ignore[arg-type]
        "predicted_properties_json": dict(candidate.get("predicted_properties") or {}),
        "uncertainty_json": dict(candidate.get("uncertainty") or {}),
        "rationale": candidate.get("rationale"),
    }


def _to_unified(row) -> UnifiedRecommendation:
    return UnifiedRecommendation(
        id=row.id,
        session_id=row.session_id,
        source=row.source,
        status=row.status,
        version=row.version,
        score=_safe_float(row.score),
        origin=row.origin,
        mode=row.mode or RecommendationMode.KNOWN,
        model_version_id=row.model_version_id,
        feature_set_version=row.feature_set_version,
        simulation_priority=row.simulation_priority,
        additive_type=row.additive_type,
        additive_wt_pct=row.additive_wt_pct,
        composition=dict(row.composition_json or {}),
        predicted_properties=dict(row.predicted_properties_json or {}),
        uncertainty=dict(row.uncertainty_json or {}),
        result_metrics=dict(row.result_metrics_json or {}),
        prediction_error=dict(row.prediction_error_json or {}),
        used_in_retraining=bool(row.used_in_retraining),
        rationale=row.rationale,
        queued_exp_id=row.queued_exp_id,
        notes=row.notes,
        created_at=_now_iso(row.created_at),
        approved_at=_now_iso(row.approved_at),
    )


def _to_detail(row) -> RecommendationDetailResponse:
    return RecommendationDetailResponse(
        **_to_unified(row).model_dump(),
        pg_decision=dict(row.pg_decision_json or {}),
        decision_trace=list(row.decision_trace_json or []),
        source_records=list(row.source_records_json or []),
        literature_refs=list(row.literature_refs_json or []),
    )


def _pick_queue_params_from_row(row) -> tuple[float, str]:
    """Resolve queue params from stored metadata with sensible defaults."""
    temperature_k = 298.0
    run_tier = "screening"

    pg_decision = row.pg_decision_json if isinstance(row.pg_decision_json, dict) else {}
    if "temperature_k" in pg_decision:
        temperature_k = _safe_float(pg_decision.get("temperature_k"), 298.0)
    if "run_tier" in pg_decision and pg_decision.get("run_tier"):
        run_tier = str(pg_decision.get("run_tier"))

    trace = row.decision_trace_json
    if isinstance(trace, list):
        for event in reversed(trace):
            if not isinstance(event, dict):
                continue
            if "temperature_k" in event:
                temperature_k = _safe_float(event.get("temperature_k"), temperature_k)
            if "run_tier" in event and event.get("run_tier"):
                run_tier = str(event.get("run_tier"))
            if "queue_params" in event and isinstance(event["queue_params"], dict):
                qp = event["queue_params"]
                if "temperature_k" in qp:
                    temperature_k = _safe_float(qp.get("temperature_k"), temperature_k)
                if "run_tier" in qp and qp.get("run_tier"):
                    run_tier = str(qp.get("run_tier"))
                break

    return temperature_k, run_tier


def _prediction_error_from_row(row, result_metrics: dict[str, object]) -> dict[str, float]:
    predicted = dict(row.predicted_properties_json or {})
    errors: dict[str, float] = {}
    for name, observed in result_metrics.items():
        if name not in predicted:
            continue
        try:
            errors[str(name)] = float(observed) - float(predicted[name])
        except (TypeError, ValueError):
            continue
    return errors


def add_candidates_to_pending(
    *,
    candidates: list[dict[str, object]],
    source: str,
    session_id: str | None = None,
    pg_decision: dict[str, object] | None = None,
    decision_trace: list[dict[str, object]] | None = None,
    source_records: list[dict[str, object]] | None = None,
    literature_refs: list[dict[str, object]] | None = None,
    mode: RecommendationMode | str = RecommendationMode.KNOWN,
    model_version_id: str | None = None,
    feature_set_version: str | None = None,
    simulation_priority: SimulationPriority | str | None = None,
) -> list[UnifiedRecommendation]:
    """Persist a candidate list into pending recommendations."""

    if not candidates:
        return []

    def _save(session):
        repo = PendingRecommendationRepository(session)
        rows = []
        for candidate in candidates:
            payload = _normalize_candidate(candidate)
            row = repo.create(
                id=f"prec-{uuid4().hex[:16]}",
                session_id=session_id,
                source=source,
                status="pending",
                composition_json=payload["composition_json"],
                additive_type=payload["additive_type"],
                additive_wt_pct=payload["additive_wt_pct"],
                predicted_properties_json=payload["predicted_properties_json"],
                uncertainty_json=payload["uncertainty_json"],
                score=payload["score"],
                origin=payload["origin"],
                mode=str(payload.get("mode") or mode),
                model_version_id=payload.get("model_version_id") or model_version_id,
                feature_set_version=payload.get("feature_set_version") or feature_set_version,
                simulation_priority=str(
                    payload.get("simulation_priority") or simulation_priority or ""
                )
                or None,
                pg_decision_json=pg_decision,
                rationale=payload["rationale"],
                decision_trace_json=decision_trace,
                source_records_json=source_records,
                literature_refs_json=literature_refs,
            )
            rows.append(row)
        return [_to_unified(row) for row in rows]

    return run_in_session_commit(_save)


def list_pending(limit: int = 100) -> list[UnifiedRecommendation]:
    def _load(session):
        repo = PendingRecommendationRepository(session)
        return [_to_unified(row) for row in repo.list_by_status("pending", limit=limit)]

    return run_in_session(_load)


def list_recent(limit: int = 200) -> list[UnifiedRecommendation]:
    def _load(session):
        repo = PendingRecommendationRepository(session)
        return [_to_unified(row) for row in repo.list_recent(limit=limit)]

    return run_in_session(_load)


def get_detail(recommendation_id: str) -> RecommendationDetailResponse:
    def _load(session):
        repo = PendingRecommendationRepository(session)
        row = repo.get_by_id(recommendation_id)
        if row is None:
            raise ContractError(
                ErrorCode.RECORD_NOT_FOUND,
                f"Pending recommendation not found: {recommendation_id}",
                {"recommendation_id": recommendation_id},
            )
        return _to_detail(row)

    return run_in_session(_load)


def _validate_queueable_composition(composition: dict[str, float]) -> None:
    missing = [key for key in _REQUIRED_COMPOSITION_KEYS if key not in composition]
    if missing:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            "Recommendation lacks required base composition for simulation queue",
            {"missing_keys": missing},
        )


def approve_pending(
    recommendation_id: str,
    *,
    notes: str = "",
    expected_version: int | None = None,
) -> UnifiedRecommendation:
    """Approve and queue a pending recommendation with guarded transitions."""

    from .active_learning import _queue_active_learning_experiment

    def _approve_and_queue(session):
        repo = PendingRecommendationRepository(session)
        approved = repo.transition(
            recommendation_id,
            to_status="approved",
            expected_version=expected_version,
            notes=notes,
        )
        if approved is None:
            raise ContractError(
                ErrorCode.RECORD_NOT_FOUND,
                f"Pending recommendation not found: {recommendation_id}",
                {"recommendation_id": recommendation_id},
            )

        composition = dict(approved.composition_json or {})
        _validate_queueable_composition(composition)
        temperature_k, run_tier = _pick_queue_params_from_row(approved)
        exp_id = _queue_active_learning_experiment(
            composition=composition,
            temperature_k=temperature_k,
            run_tier=run_tier,
            metadata_json={
                "source": "pending_recommendation",
                "recommendation_id": approved.id,
                "recommendation_source": approved.source,
                "recommendation_mode": approved.mode,
            },
        )

        queued = repo.transition(
            recommendation_id,
            to_status="queued",
            notes=notes,
            queued_exp_id=exp_id,
        )
        if queued is None:
            raise ContractError(
                ErrorCode.ORCHESTRATION_ERROR,
                "Failed to update recommendation state after queueing",
                {"recommendation_id": recommendation_id, "exp_id": exp_id},
            )
        return _to_unified(queued)

    try:
        return run_in_session_commit(_approve_and_queue)
    except ValueError as exc:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            str(exc),
            {"recommendation_id": recommendation_id},
        ) from exc


def mark_auto_approved_and_queued(
    recommendation_id: str,
    *,
    exp_id: str,
    notes: str = "",
) -> UnifiedRecommendation:
    """Persist auto-approved recommendation execution using an existing queued exp_id."""

    def _mark(session):
        repo = PendingRecommendationRepository(session)
        approved = repo.transition(
            recommendation_id,
            to_status=RecommendationStatus.APPROVED,
            notes=notes,
        )
        if approved is None:
            raise ContractError(
                ErrorCode.RECORD_NOT_FOUND,
                f"Pending recommendation not found: {recommendation_id}",
                {"recommendation_id": recommendation_id},
            )
        queued = repo.transition(
            recommendation_id,
            to_status=RecommendationStatus.QUEUED,
            notes=notes,
            queued_exp_id=exp_id,
        )
        if queued is None:
            raise ContractError(
                ErrorCode.ORCHESTRATION_ERROR,
                "Failed to persist queued recommendation state",
                {"recommendation_id": recommendation_id, "exp_id": exp_id},
            )
        return _to_unified(queued)

    try:
        return run_in_session_commit(_mark)
    except ValueError as exc:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            str(exc),
            {"recommendation_id": recommendation_id, "exp_id": exp_id},
        ) from exc


def mark_pending_failed(
    recommendation_id: str,
    *,
    reason: str = "",
) -> UnifiedRecommendation:
    """Mark a persisted recommendation as failed."""

    def _mark(session):
        repo = PendingRecommendationRepository(session)
        failed = repo.transition(
            recommendation_id,
            to_status=RecommendationStatus.FAILED,
            notes=reason,
        )
        if failed is None:
            raise ContractError(
                ErrorCode.RECORD_NOT_FOUND,
                f"Pending recommendation not found: {recommendation_id}",
                {"recommendation_id": recommendation_id},
            )
        return _to_unified(failed)

    try:
        return run_in_session_commit(_mark)
    except ValueError as exc:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            str(exc),
            {"recommendation_id": recommendation_id},
        ) from exc


def mark_cancelled(
    recommendation_id: str,
    *,
    reason: str = "",
) -> UnifiedRecommendation:
    """Mark a queued/running recommendation as cancelled after execution stop."""

    def _cancel(session):
        repo = PendingRecommendationRepository(session)
        cancelled = repo.transition(
            recommendation_id,
            to_status="cancelled",
            notes=reason or "Execution cancelled",
        )
        if cancelled is None:
            raise ContractError(
                ErrorCode.RECORD_NOT_FOUND,
                f"Pending recommendation not found: {recommendation_id}",
                {"recommendation_id": recommendation_id},
            )
        return _to_unified(cancelled)

    try:
        return run_in_session_commit(_cancel)
    except ValueError as exc:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            str(exc),
            {"recommendation_id": recommendation_id},
        ) from exc


def mark_running_by_exp_id(exp_id: str) -> UnifiedRecommendation | None:
    """Mirror experiment running state onto a linked recommendation."""

    def _mark(session):
        repo = PendingRecommendationRepository(session)
        row = repo.get_by_queued_exp_id(exp_id)
        if row is None:
            return None
        current_status = str(row.status or "")
        if current_status == RecommendationStatus.RUNNING.value:
            return _to_unified(row)
        if current_status != RecommendationStatus.QUEUED.value:
            return None
        updated = repo.transition(row.id, to_status=RecommendationStatus.RUNNING)
        return _to_unified(updated) if updated is not None else None

    try:
        return run_in_session_commit(_mark)
    except ValueError as exc:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            str(exc),
            {"exp_id": exp_id},
        ) from exc


def mark_cancelled_by_exp_id(exp_id: str, *, reason: str = "") -> UnifiedRecommendation | None:
    """Mirror experiment cancellation onto the linked recommendation."""

    def _mark(session):
        repo = PendingRecommendationRepository(session)
        row = repo.get_by_queued_exp_id(exp_id)
        if row is None:
            return None
        current_status = str(row.status or "")
        if current_status == RecommendationStatus.CANCELLED.value:
            return _to_unified(row)
        if current_status not in {
            RecommendationStatus.QUEUED.value,
            RecommendationStatus.RUNNING.value,
        }:
            return None
        updated = repo.transition(
            row.id,
            to_status=RecommendationStatus.CANCELLED,
            notes=reason or "Execution cancelled",
        )
        return _to_unified(updated) if updated is not None else None

    try:
        return run_in_session_commit(_mark)
    except ValueError as exc:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            str(exc),
            {"exp_id": exp_id},
        ) from exc


def mark_failed_by_exp_id(exp_id: str, *, reason: str = "") -> UnifiedRecommendation | None:
    """Mirror experiment failure onto the linked recommendation."""

    def _mark(session):
        repo = PendingRecommendationRepository(session)
        row = repo.get_by_queued_exp_id(exp_id)
        if row is None:
            return None
        current_status = str(row.status or "")
        if current_status == RecommendationStatus.FAILED.value:
            return _to_unified(row)
        if current_status not in {
            RecommendationStatus.APPROVED.value,
            RecommendationStatus.QUEUED.value,
            RecommendationStatus.RUNNING.value,
        }:
            return None
        updated = repo.transition(
            row.id,
            to_status=RecommendationStatus.FAILED,
            notes=reason or "Execution failed",
        )
        return _to_unified(updated) if updated is not None else None

    try:
        return run_in_session_commit(_mark)
    except ValueError as exc:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            str(exc),
            {"exp_id": exp_id},
        ) from exc


def stop_pending_execution(
    recommendation_id: str,
    *,
    reason: str = "",
) -> UnifiedRecommendation:
    """Cancel the linked experiment and mark the recommendation cancelled."""

    def _stop(session):
        from database.repositories.experiment_repo import ExperimentRepository

        repo = PendingRecommendationRepository(session)
        row = repo.get_by_id(recommendation_id)
        if row is None:
            raise ContractError(
                ErrorCode.RECORD_NOT_FOUND,
                f"Pending recommendation not found: {recommendation_id}",
                {"recommendation_id": recommendation_id},
            )
        exp_id = str(row.queued_exp_id or "").strip()
        if not exp_id:
            raise ContractError(
                ErrorCode.INVALID_REQUEST,
                "Recommendation has no linked experiment to stop",
                {"recommendation_id": recommendation_id},
            )

        exp_repo = ExperimentRepository(session)
        exp = exp_repo.get_by_id(exp_id)
        if exp is None:
            raise ContractError(
                ErrorCode.RECORD_NOT_FOUND,
                f"Linked experiment not found: {exp_id}",
                {"recommendation_id": recommendation_id, "exp_id": exp_id},
            )
        if exp.celery_task_id:
            try:
                from orchestrator.celery_app import celery_app

                celery_app.control.revoke(exp.celery_task_id, terminate=True, signal="SIGTERM")
            except Exception:
                pass

        exp_repo.update_status(
            exp_id,
            "cancelled",
            error_message=reason or "Execution cancelled",
        )
        cancelled = repo.transition(
            recommendation_id,
            to_status=RecommendationStatus.CANCELLED,
            notes=reason or "Execution cancelled",
        )
        if cancelled is None:
            raise ContractError(
                ErrorCode.ORCHESTRATION_ERROR,
                "Failed to mark recommendation as cancelled",
                {"recommendation_id": recommendation_id, "exp_id": exp_id},
            )
        return _to_unified(cancelled)

    try:
        return run_in_session_commit(_stop)
    except ValueError as exc:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            str(exc),
            {"recommendation_id": recommendation_id},
        ) from exc


def reject_pending(
    recommendation_id: str,
    *,
    reason: str = "",
    expected_version: int | None = None,
) -> UnifiedRecommendation:
    """Reject a pending recommendation with optimistic-state guard."""

    def _reject(session):
        repo = PendingRecommendationRepository(session)
        rejected = repo.transition(
            recommendation_id,
            to_status=RecommendationStatus.REJECTED,
            expected_version=expected_version,
            notes=reason,
        )
        if rejected is None:
            raise ContractError(
                ErrorCode.RECORD_NOT_FOUND,
                f"Pending recommendation not found: {recommendation_id}",
                {"recommendation_id": recommendation_id},
            )
        return _to_unified(rejected)

    try:
        return run_in_session_commit(_reject)
    except ValueError as exc:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            str(exc),
            {"recommendation_id": recommendation_id},
        ) from exc


def update_recommendation_result(
    recommendation_id: str,
    *,
    result_metrics: dict[str, object],
    prediction_error: dict[str, object] | None = None,
) -> UnifiedRecommendation:
    """Persist observed metrics and prediction error for a completed recommendation."""

    def _update(session):
        repo = PendingRecommendationRepository(session)
        updated = repo.update_result(
            recommendation_id,
            result_metrics=result_metrics,
            prediction_error=prediction_error,
        )
        if updated is None:
            raise ContractError(
                ErrorCode.RECORD_NOT_FOUND,
                f"Pending recommendation not found: {recommendation_id}",
                {"recommendation_id": recommendation_id},
            )
        return _to_unified(updated)

    try:
        return run_in_session_commit(_update)
    except ValueError as exc:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            str(exc),
            {"recommendation_id": recommendation_id},
        ) from exc


def backfill_from_experiment(
    exp_id: str,
    *,
    result_metrics: dict[str, object],
) -> UnifiedRecommendation | None:
    """Backfill lineage for a recommendation linked to exp_id."""

    def _backfill(session):
        repo = PendingRecommendationRepository(session)
        row = repo.get_by_queued_exp_id(exp_id)
        if row is None:
            return None
        if row.status in {"queued", "running"}:
            row = repo.transition(row.id, to_status="completed")
        prediction_error = _prediction_error_from_row(row, result_metrics)
        row = repo.update_result(
            row.id,
            result_metrics=result_metrics,
            prediction_error=prediction_error or None,
        )
        return _to_unified(row) if row is not None else None

    try:
        return run_in_session_commit(_backfill)
    except ValueError as exc:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            str(exc),
            {"exp_id": exp_id},
        ) from exc


def mark_recommendation_fed_back(recommendation_id: str) -> UnifiedRecommendation:
    """Mark a recommendation as incorporated into retraining."""

    def _mark(session):
        repo = PendingRecommendationRepository(session)
        updated = repo.mark_fed_back(recommendation_id)
        if updated is None:
            raise ContractError(
                ErrorCode.RECORD_NOT_FOUND,
                f"Pending recommendation not found: {recommendation_id}",
                {"recommendation_id": recommendation_id},
            )
        return _to_unified(updated)

    return run_in_session_commit(_mark)


def mark_recommendations_fed_back_for_experiments(
    exp_ids: list[str],
) -> list[UnifiedRecommendation]:
    """Mark completed recommendations as fed_back when used in retraining."""

    normalized_exp_ids = [str(exp_id) for exp_id in exp_ids if exp_id]
    if not normalized_exp_ids:
        return []

    def _mark(session):
        repo = PendingRecommendationRepository(session)
        rows = repo.get_by_queued_exp_ids(normalized_exp_ids)
        updated = []
        for row in rows:
            marked = repo.mark_fed_back(row.id)
            if marked is not None:
                updated.append(_to_unified(marked))
        return updated

    try:
        return run_in_session_commit(_mark)
    except ValueError as exc:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            str(exc),
            {"exp_ids": normalized_exp_ids},
        ) from exc


def sync_session_pending_candidates(
    *,
    session_id: str,
    candidates: list[dict[str, object]],
) -> int:
    """Update pending records for a session with post-simulation candidate metrics."""

    if not session_id or not candidates:
        return 0

    def _comp_key(comp: dict[str, object] | None, additive_type: object) -> str:
        safe_comp = _normalize_composition(comp)
        parts = [f"{k}:{safe_comp[k]:.6f}" for k in sorted(safe_comp)]
        return f"{str(additive_type or '')}|{'|'.join(parts)}"

    def _sync(session):
        repo = PendingRecommendationRepository(session)
        rows = [
            row
            for row in repo.list_recent(limit=500)
            if row.session_id == session_id
            and row.source == "ai_advisor"
            and row.status == "pending"
        ]
        if not rows:
            return 0

        row_by_key: dict[str, object] = {}
        for row in rows:
            key = _comp_key(dict(row.composition_json or {}), row.additive_type)
            row_by_key[key] = row

        updated = 0
        for candidate in candidates:
            key = _comp_key(candidate.get("composition"), candidate.get("additive_type"))
            row = row_by_key.get(key)
            if row is None:
                continue
            row.predicted_properties_json = dict(candidate.get("predicted_properties") or {})
            row.score = _safe_float(candidate.get("score"), row.score)
            if candidate.get("rationale"):
                row.rationale = str(candidate.get("rationale"))
            row.version = int(row.version) + 1
            updated += 1
        return updated

    return run_in_session_commit(_sync)
