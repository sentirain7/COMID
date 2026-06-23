"""Active-learning recommendation service."""

from __future__ import annotations

from typing import TypedDict

from api.schemas import (
    ActiveLearningSummaryResponse,
    ApproveRecommendationRequest,
    ApproveRejectResponse,
    FeedResultRequest,
    RecommendationBatchResponse,
    RecommendationItem,
    RejectRecommendationRequest,
    StopRecommendationRequest,
)
from common.logging import get_logger
from common.seed import generate_seed
from contracts.errors import ContractError, ErrorCode, OrchestrationError
from contracts.policies.ml_policy import DEFAULT_ML_POLICY
from contracts.policies.recommendation_policy import DEFAULT_RECOMMENDATION_POLICY
from contracts.schemas import FFType, RunTier

logger = get_logger("features.recommendations")

_al_workflow = None
_REQUIRED_COMPOSITION_KEYS = ("asphaltene", "resin", "aromatic", "saturate")


class PostRetrainBatchResult(TypedDict, total=False):
    """Typed payload returned by post-retrain auto batch generation."""

    ok: bool
    batch_id: str
    generated: int
    persisted: int
    queued: int
    failed: int


def _normalize_feedback_composition(composition: dict[str, float]) -> dict[str, float]:
    """Normalize completion feedback compositions into a stable SARA payload."""
    if not isinstance(composition, dict):
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            "Completed experiment composition must be a mapping",
        )

    normalized: dict[str, float] = {}
    present_base_keys = 0
    for key in _REQUIRED_COMPOSITION_KEYS:
        raw = composition.get(key)
        if raw is not None:
            present_base_keys += 1
        normalized[key] = float(raw or 0.0)

    if present_base_keys == 0:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            "Completed experiment composition must include at least one SARA component",
            {"required_keys": list(_REQUIRED_COMPOSITION_KEYS)},
        )

    if composition.get("additive") is not None:
        normalized["additive"] = float(composition["additive"])

    return normalized


def _queue_active_learning_experiment(
    *,
    composition: dict[str, float],
    temperature_k: float,
    run_tier: str,
    metadata_json: dict[str, object] | None = None,
) -> str:
    """Queue an active-learning recommendation as a real Celery simulation.

    Uses SubmissionFacade for consistent DB-first lifecycle and error handling.
    """
    from api.deps import get_job_manager
    from common.pathing import generate_exp_id
    from config.dashboard_settings import load_dashboard_settings
    from orchestrator.request_factory import create_build_request, create_protocol_request
    from orchestrator.submission_facade import SubmissionFacade

    try:
        tier = RunTier(run_tier)
    except ValueError as e:
        raise RuntimeError(f"Invalid run tier for active learning queue: {run_tier}") from e

    ff_type = FFType.BULK_FF_GAFF2
    seed = generate_seed(None)

    build_request = create_build_request(
        composition=composition,
        seed=seed,
        tier=tier,
    )
    protocol_request = create_protocol_request(
        tier=tier,
        ff_type=ff_type,
        temperature_K=temperature_k,
        pressure_atm=1.0,
    )

    exp_id = generate_exp_id(
        binder_type="custom",
        structure_size="X1",
        temperature_k=temperature_k,
        ff_type=ff_type.value,
        aging_state="non_aging",
        atom_count=build_request.target_atoms,
        seed=seed,
    )

    job_manager = get_job_manager()

    dashboard_settings = load_dashboard_settings()
    selected_gpus = dashboard_settings.get("selected_gpus", [])
    if not selected_gpus:
        selected_gpus = None

    try:
        job_id, celery_task_id = SubmissionFacade.submit_experiment(
            job_manager=job_manager,
            exp_id=exp_id,
            run_tier=tier.value,
            ff_type=ff_type.value,
            target_atoms=build_request.target_atoms,
            temperature_k=temperature_k,
            pressure_atm=1.0,
            seed=seed,
            comp_asphaltene_wt=float(composition.get("asphaltene", 0.0)),
            comp_resin_wt=float(composition.get("resin", 0.0)),
            comp_aromatic_wt=float(composition.get("aromatic", 0.0)),
            comp_saturate_wt=float(composition.get("saturate", 0.0)),
            build_request=build_request,
            protocol_request=protocol_request,
            material_id="custom_X1_non_aging",
            selected_gpus=selected_gpus,
            metadata_json={
                "source": "active_learning",
                "reason_code": "al_recommendation",
                **dict(metadata_json or {}),
            },
        )
    except ContractError as e:
        raise RuntimeError(f"Failed to submit active learning job: {e.message}") from e

    logger.info(f"Active learning recommendation queued: exp_id={exp_id}, job_id={job_id}")
    return exp_id


def _refresh_workflow_predictor():
    """Attach a real ML predictor to the workflow when available."""
    from api.deps import get_ml_predictor_fn

    wf = _get_al_workflow()
    predictor = get_ml_predictor_fn()
    if predictor is not None:
        wf.agent.predictor = predictor
    return wf, predictor


def _get_current_model_lineage() -> tuple[str | None, str | None]:
    """Return champion version id and feature set when available."""
    from database.repositories.model_version_repo import ModelVersionRepository
    from features.common import run_in_session

    def _load(session):
        champion = ModelVersionRepository(session).get_champion()
        if champion is None:
            return None, None
        return champion.version_id, champion.feature_set_version

    return run_in_session(_load)


def run_post_retrain_auto_batch(
    *,
    n_candidates: int | None = None,
    source: str | None = None,
) -> PostRetrainBatchResult:
    """Generate, persist, and optionally auto-execute post-retrain recommendations."""
    from features.recommendations import pending_service

    wf, predictor = _refresh_workflow_predictor()
    if predictor is None:
        logger.warning("Auto re-recommend skipped: ML predictor not available after retraining")
        return {"ok": False, "generated": 0, "persisted": 0, "queued": 0, "failed": 0}

    policy = DEFAULT_RECOMMENDATION_POLICY.post_retrain_automation
    if not policy.enabled:
        return {"ok": False, "generated": 0, "persisted": 0, "queued": 0, "failed": 0}

    resolved_candidates = int(n_candidates or policy.n_candidates)
    source_label = str(source or policy.source_label)
    try:
        batch = wf.suggest_next(n_candidates=resolved_candidates)
    except Exception as exc:
        logger.warning("Auto re-recommend skipped: %s", exc)
        return {"ok": False, "generated": 0, "persisted": 0, "queued": 0, "failed": 0}

    if not batch.recommendations:
        return {"ok": True, "generated": 0, "persisted": 0, "queued": 0, "failed": 0}

    model_version_id, feature_set_version = _get_current_model_lineage()
    persisted = pending_service.add_candidates_to_pending(
        candidates=[
            {
                "origin": "optimizer",
                "score": 1.0 / float(index + 1),
                "composition": recommendation.composition,
                "predicted_properties": recommendation.predicted_properties,
                "uncertainty": recommendation.uncertainty,
                "rationale": "Auto-generated after successful retraining",
                "model_version_id": model_version_id,
                "feature_set_version": feature_set_version,
            }
            for index, recommendation in enumerate(batch.recommendations)
        ],
        source=source_label,
        session_id=batch.batch_id,
        model_version_id=model_version_id,
        feature_set_version=feature_set_version,
    )

    queued = 0
    failed = 0
    if policy.auto_approve_and_execute:
        for memory_rec, persisted_rec in zip(batch.recommendations, persisted, strict=False):
            try:
                approved = wf.approve(
                    memory_rec.id,
                    notes=f"Auto-approved after retraining ({source_label})",
                )
                if approved is None or not approved.queued_exp_id:
                    raise RuntimeError("workflow approval did not queue an experiment")
                pending_service.mark_auto_approved_and_queued(
                    persisted_rec.id,
                    exp_id=approved.queued_exp_id,
                    notes=f"Auto-approved after retraining ({source_label})",
                )
                queued += 1
            except Exception as exc:
                failed += 1
                try:
                    pending_service.mark_pending_failed(
                        persisted_rec.id,
                        reason=f"Auto execution failed: {exc}",
                    )
                except Exception:
                    pass
                logger.warning("Auto execution failed for %s: %s", persisted_rec.id, exc)

    logger.info(
        "Prepared post-retrain recommendation batch %s with %d recommendations (%d queued, %d failed)",
        batch.batch_id,
        len(batch.recommendations),
        queued,
        failed,
    )
    return {
        "ok": True,
        "batch_id": batch.batch_id,
        "generated": len(batch.recommendations),
        "persisted": len(persisted),
        "queued": queued,
        "failed": failed,
    }


def _get_al_workflow():
    """Get or create the ActiveLearningWorkflow singleton."""
    global _al_workflow
    if _al_workflow is None:
        from api.deps import get_ml_predictor_fn
        from features.mlops import service as mlops_service
        from recommendation.active_learning import ActiveLearningWorkflow
        from recommendation.agent import AgentConfig, RecommendationAgent

        predictor_fn = get_ml_predictor_fn()
        agent = RecommendationAgent(
            config=AgentConfig(auto_run=False),
            predictor=predictor_fn,
        )

        def _retrain_and_prepare(training_data):
            did_retrain = mlops_service.trigger_retraining_if_needed(
                triggered_by="active_learning",
                new_samples=DEFAULT_ML_POLICY.retraining.min_new_samples,
                completed_exp_ids=sorted(
                    {str(d.exp_id) for d in training_data if getattr(d, "exp_id", None)}
                ),
            )
            if did_retrain:
                try:
                    run_post_retrain_auto_batch(source="active_learning_auto")
                except Exception as exc:
                    logger.warning("Auto post-retrain execution skipped: %s", exc)
            return did_retrain

        _al_workflow = ActiveLearningWorkflow(
            agent=agent,
            queue_fn=_queue_active_learning_experiment,
            retrain_fn=_retrain_and_prepare,
            min_retrain_samples=DEFAULT_ML_POLICY.retraining.min_new_samples,
        )
    return _al_workflow


def ingest_completed_experiment(
    *,
    exp_id: str,
    composition: dict[str, float],
    observed_properties: dict[str, float],
    temperature_k: float = 298.0,
) -> bool:
    """Feed a completed experiment into the active-learning loop once."""
    wf = _get_al_workflow()
    if any(d.exp_id == exp_id for d in wf.state.training_data):
        return False
    normalized_composition = _normalize_feedback_composition(composition)
    wf.feed_result(
        exp_id=exp_id,
        composition=normalized_composition,
        observed_properties=observed_properties,
        temperature_k=temperature_k,
    )
    return True


async def suggest_recommendations(n_candidates: int = 20) -> RecommendationBatchResponse:
    """Generate a batch of composition recommendations."""
    wf, predictor = _refresh_workflow_predictor()
    if predictor is None:
        raise ContractError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "ML predictor not available for active-learning recommendations",
        )
    batch = wf.suggest_next(n_candidates=n_candidates)

    return RecommendationBatchResponse(
        batch_id=batch.batch_id,
        n_recommendations=len(batch.recommendations),
        optimization_iteration=batch.optimization_iteration,
        recommendations=[
            RecommendationItem(
                id=r.id,
                composition=r.composition,
                predicted_properties=r.predicted_properties,
                uncertainty=r.uncertainty,
                validity_tags=r.validity_tags,
                pareto_rank=r.pareto_rank,
                crowding_distance=r.crowding_distance,
                status=r.status.value,
            )
            for r in batch.recommendations
        ],
    )


async def approve_recommendation(request: ApproveRecommendationRequest) -> ApproveRejectResponse:
    """Approve a recommendation for MD simulation.

    Routes to:
    - pending_service for DB-persisted recommendations (prec-* prefix)
    - in-memory workflow for transient recommendations
    """
    recommendation_id = request.recommendation_id

    # Persistent recommendations (from inverse design, context pipeline, etc.)
    if recommendation_id.startswith("prec-"):
        from features.recommendations import pending_service

        try:
            result = pending_service.approve_pending(
                recommendation_id,
                notes=request.notes,
            )
            return ApproveRejectResponse(
                recommendation_id=result.id,
                status=result.status,
                exp_id=result.queued_exp_id,
                message=f"Recommendation approved{': ' + request.notes if request.notes else ''}",
            )
        except ContractError:
            raise
        except Exception as e:
            raise OrchestrationError(
                ErrorCode.SERVICE_UNAVAILABLE,
                str(e),
                {"recommendation_id": recommendation_id},
            ) from e

    # In-memory workflow recommendations
    wf = _get_al_workflow()
    try:
        rec = wf.approve(recommendation_id, notes=request.notes)
    except RuntimeError as e:
        raise OrchestrationError(
            ErrorCode.SERVICE_UNAVAILABLE,
            str(e),
            {"recommendation_id": recommendation_id},
        ) from e

    if rec is None:
        raise ContractError(
            ErrorCode.RECORD_NOT_FOUND,
            f"Recommendation {recommendation_id} not found or already processed",
            {"recommendation_id": recommendation_id},
        )

    return ApproveRejectResponse(
        recommendation_id=rec.id,
        status=rec.status.value,
        exp_id=rec.queued_exp_id,
        message=f"Recommendation approved{': ' + rec.notes if rec.notes else ''}",
    )


async def reject_recommendation(request: RejectRecommendationRequest) -> ApproveRejectResponse:
    """Reject a recommendation.

    Routes to:
    - pending_service for DB-persisted recommendations (prec-* prefix)
    - in-memory workflow for transient recommendations
    """
    recommendation_id = request.recommendation_id

    # Persistent recommendations
    if recommendation_id.startswith("prec-"):
        from features.recommendations import pending_service

        try:
            result = pending_service.reject_pending(
                recommendation_id,
                reason=request.reason,
            )
            return ApproveRejectResponse(
                recommendation_id=result.id,
                status=result.status,
                message=f"Recommendation rejected{': ' + request.reason if request.reason else ''}",
            )
        except ContractError:
            raise
        except Exception as e:
            raise OrchestrationError(
                ErrorCode.SERVICE_UNAVAILABLE,
                str(e),
                {"recommendation_id": recommendation_id},
            ) from e

    # In-memory workflow
    wf = _get_al_workflow()
    rec = wf.reject(recommendation_id, reason=request.reason)

    if rec is None:
        raise ContractError(
            ErrorCode.RECORD_NOT_FOUND,
            f"Recommendation {recommendation_id} not found",
            {"recommendation_id": recommendation_id},
        )

    return ApproveRejectResponse(
        recommendation_id=rec.id,
        status=rec.status.value,
        message=f"Recommendation rejected{': ' + rec.notes if rec.notes else ''}",
    )


async def stop_recommendation_execution(
    request: StopRecommendationRequest,
) -> ApproveRejectResponse:
    """Stop a queued or running recommendation-linked execution."""
    recommendation_id = request.recommendation_id
    if not recommendation_id.startswith("prec-"):
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            "Only persisted recommendations support stop execution",
            {"recommendation_id": recommendation_id},
        )

    from features.recommendations import pending_service

    try:
        result = pending_service.stop_pending_execution(
            recommendation_id,
            reason=request.reason or "Stopped by user",
        )
        return ApproveRejectResponse(
            recommendation_id=result.id,
            status=result.status,
            exp_id=result.queued_exp_id,
            message=request.reason or "Execution stopped",
        )
    except ContractError:
        raise
    except Exception as e:
        raise OrchestrationError(
            ErrorCode.SERVICE_UNAVAILABLE,
            str(e),
            {"recommendation_id": recommendation_id},
        ) from e


async def feed_recommendation_result(request: FeedResultRequest) -> dict[str, object]:
    """Feed MD simulation results back to active learning loop."""
    wf = _get_al_workflow()
    wf.feed_result(
        exp_id=request.exp_id,
        composition=request.composition,
        observed_properties=request.observed_properties,
        temperature_k=request.temperature_k,
    )
    return {"status": "ok", "n_observations": wf.state.n_observations}


async def get_pending_recommendations() -> list[RecommendationItem]:
    """Get all pending (unapproved) recommendations.

    Merges both:
    1. Persistent pending from database (via pending_service)
    2. In-memory pending from active learning workflow
    """
    from features.recommendations import pending_service

    # Get persistent pending from DB
    persistent_pending = pending_service.list_pending(limit=200)
    persistent_items = [
        RecommendationItem(
            id=r.id,
            composition=r.composition,
            predicted_properties=r.predicted_properties,
            uncertainty=r.uncertainty,
            validity_tags=[],
            pareto_rank=0,
            crowding_distance=0.0,
            status=r.status,
        )
        for r in persistent_pending
    ]

    # Get in-memory pending from workflow
    wf = _get_al_workflow()
    memory_pending = wf.get_pending()
    memory_items = [
        RecommendationItem(
            id=r.id,
            composition=r.composition,
            predicted_properties=r.predicted_properties,
            uncertainty=r.uncertainty,
            validity_tags=r.validity_tags,
            pareto_rank=r.pareto_rank,
            crowding_distance=r.crowding_distance,
            status=r.status.value,
        )
        for r in memory_pending
    ]

    # Merge: persistent first, then memory (exclude duplicates by id)
    seen_ids = {item.id for item in persistent_items}
    merged = persistent_items + [item for item in memory_items if item.id not in seen_ids]

    return merged


async def get_active_learning_summary() -> ActiveLearningSummaryResponse:
    """Get a summary of the active learning state."""
    from features.recommendations import pending_service

    wf = _get_al_workflow()
    summary = wf.get_state_summary()
    auto_sources = {
        DEFAULT_RECOMMENDATION_POLICY.post_retrain_automation.source_label,
        "active_learning_auto",
        "continuous_loop_auto",
    }
    recent = pending_service.list_recent(limit=200)
    n_auto_running = sum(
        1 for item in recent if item.source in auto_sources and item.status in {"queued", "running"}
    )
    return ActiveLearningSummaryResponse(
        iteration=summary["iteration"],
        n_observations=summary["n_observations"],
        n_pending=summary["n_pending"],
        n_auto_running=n_auto_running,
        agent_summary=summary["agent_summary"],
    )
