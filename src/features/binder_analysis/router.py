"""Binder Analysis admin routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from database.connection import session_scope
from database.models.metric import MetricModel
from database.repositories.binder_analysis_repo import BinderAnalysisRepository

router = APIRouter(prefix="/analysis", tags=["binder-analysis-admin"])


@router.get("/binder-studies")
async def list_studies(state: str | None = None) -> list[dict]:
    """List binder-analysis studies, optionally filtered by state."""
    with session_scope() as db:
        repo = BinderAnalysisRepository(db)
        studies = repo.list_studies(state=state)
        return [
            {
                "study_id": s.id,
                "state": s.state,
                "problem_text": s.problem_text,
                "agent_session_id": s.agent_session_id,
                "plan_summary": s.plan_summary_json,
                "created_at": str(s.created_at) if s.created_at else None,
                "updated_at": str(s.updated_at) if s.updated_at else None,
            }
            for s in studies
        ]


@router.get("/binder-studies/{study_id}")
async def get_study(study_id: str) -> dict:
    """Get a single binder-analysis study with run snapshot (read-only)."""
    with session_scope() as db:
        repo = BinderAnalysisRepository(db)
        study = repo.get_study(study_id)
        if study is None:
            raise HTTPException(status_code=404, detail=f"Study {study_id} not found")

        runs = repo.get_runs(study_id)

        # Build run_summary from DB snapshot — no writes, no status sync
        status_counts: dict[str, int] = {}
        for r in runs:
            st = str(r.status)
            status_counts[st] = status_counts.get(st, 0) + 1

        return {
            "study_id": study.id,
            "state": study.state,
            "problem_text": study.problem_text,
            "agent_session_id": study.agent_session_id,
            "normalized_intent": study.normalized_intent_json,
            "plan_summary": study.plan_summary_json,
            "run_summary": status_counts,
            "total_runs": len(runs),
            "runs": [
                {
                    "run_key": r.run_key,
                    "intent_kind": r.intent_kind,
                    "structure_mode": r.structure_mode,
                    "status": r.status,
                    "route": r.route,
                    "exp_id": r.exp_id,
                    "matched_exp_id": r.matched_exp_id,
                    "temperature_K": (r.parameters_json or {}).get("temperature_K"),
                    "crystal_material": (r.parameters_json or {}).get("crystal_material"),
                }
                for r in runs
            ],
            "created_at": str(study.created_at) if study.created_at else None,
            "updated_at": str(study.updated_at) if study.updated_at else None,
        }


@router.get("/binder-studies/{study_id}/results")
async def get_results(study_id: str) -> dict:
    """Get metric results for completed/matched runs (read-only)."""
    with session_scope() as db:
        repo = BinderAnalysisRepository(db)
        study = repo.get_study(study_id)
        if study is None:
            raise HTTPException(status_code=404, detail=f"Study {study_id} not found")

        runs = repo.get_runs(study_id)
        results: list[dict] = []

        for run in runs:
            if str(run.status) not in ("completed", "matched"):
                continue
            exp_id = run.matched_exp_id or run.exp_id
            if not exp_id:
                continue

            target_metrics = run.target_metrics_json or []
            metrics = (
                db.query(MetricModel.metric_name, MetricModel.value, MetricModel.unit)
                .filter(MetricModel.exp_id == exp_id)
                .all()
            )
            metric_dict = {}
            for mname, mval, munit in metrics:
                if not target_metrics or mname in target_metrics:
                    metric_dict[mname] = {"value": mval, "unit": munit}

            params = run.parameters_json or {}
            results.append(
                {
                    "run_key": run.run_key,
                    "exp_id": exp_id,
                    "intent_kind": run.intent_kind,
                    "temperature_K": params.get("temperature_K"),
                    "crystal_material": params.get("crystal_material"),
                    "aging_state": params.get("aging_state"),
                    "metrics": metric_dict,
                }
            )

        return {"study_id": study_id, "state": study.state, "results": results}


@router.delete("/binder-studies/{study_id}")
async def delete_study(study_id: str) -> dict:
    """Delete a binder-analysis study and all its runs."""
    with session_scope() as db:
        repo = BinderAnalysisRepository(db)
        deleted = repo.delete_study(study_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Study {study_id} not found")
        return {"deleted": True, "study_id": study_id}
