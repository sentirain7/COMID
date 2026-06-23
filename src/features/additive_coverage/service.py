"""Additive coverage analysis service."""

from __future__ import annotations

from api.schemas import AdditiveCoverageResponse
from common.logging import get_logger
from features.common import run_in_session

logger = get_logger("features.additive_coverage")


def get_coverage_report() -> AdditiveCoverageResponse:
    """Compute additive coverage report from catalog and completed experiments."""

    def _compute(session):
        from database.repositories.additive_repo import AdditiveRepository
        from database.repositories.experiment_repo import ExperimentRepository
        from orchestrator.additive_usage_analyzer import compute_coverage_report

        additive_repo = AdditiveRepository(session)
        catalog = [
            {
                "mol_id": a.mol_id,
                "short_name": getattr(a, "short_name", a.mol_id),
                "category": getattr(a, "category", None),
                "subcategory": getattr(a, "subcategory", None),
                "functional_tags": getattr(a, "functional_tags", None),
            }
            for a in additive_repo.list_active()
        ]

        exp_repo = ExperimentRepository(session)
        completed = exp_repo.list_completed_for_additive_coverage()

        report = compute_coverage_report(
            catalog_additives=catalog,
            completed_rows=completed,
        )

        return AdditiveCoverageResponse(
            total_catalog=report.total_catalog,
            tested_count=len(report.tested_additives),
            untested_count=len(report.untested_additives),
            coverage_fraction=report.coverage_fraction,
            gaps=[
                {
                    "additive_type": g.additive_type,
                    "binder_type": g.binder_type,
                    "temperature_k": g.temperature_k,
                    "concentration": g.concentration,
                    "novelty_score": g.novelty_score,
                }
                for g in report.gaps
            ],
            ranked_gaps=[
                {
                    "additive_type": g.additive_type,
                    "binder_type": g.binder_type,
                    "temperature_k": g.temperature_k,
                    "concentration": g.concentration,
                    "novelty_score": g.novelty_score,
                }
                for g in report.ranked_gaps
            ],
        )

    return run_in_session(_compute)


def generate_exploration_wave(
    *,
    max_jobs: int = 10,
    additive_types: list[str] | None = None,
    auto_submit: bool = False,
) -> dict:
    """Generate and optionally submit an exploration wave from coverage gaps.

    Args:
        max_jobs: Maximum number of jobs in the wave.
        additive_types: Override additive types (default: from gap analysis).
        auto_submit: Whether to auto-submit the wave.

    Returns:
        Dict with wave generation results.
    """
    report = get_coverage_report()

    if not additive_types:
        # Extract from ranked gaps
        seen = set()
        additive_types = []
        for gap in report.ranked_gaps:
            at = gap.get("additive_type", "")
            if at and at not in seen:
                seen.add(at)
                additive_types.append(at)
                if len(additive_types) >= max_jobs:
                    break

    if not additive_types:
        return {
            "status": "no_gaps",
            "message": "No untested additives found in coverage analysis",
            "n_jobs": 0,
        }

    from orchestrator.temperature_scan import exploration_scan

    spec = exploration_scan(additive_types=additive_types)

    if not auto_submit:
        total = (
            len(spec.binder_types)
            * len(spec.temperatures_k)
            * len(spec.additive_types)
            * len(spec.additive_concentrations)
        )
        return {
            "status": "planned",
            "additive_types": additive_types,
            "estimated_jobs": min(total, max_jobs),
            "spec": {
                "binder_types": spec.binder_types,
                "temperatures_k": spec.temperatures_k,
                "additive_types": spec.additive_types,
                "additive_concentrations": spec.additive_concentrations,
            },
        }

    # Auto-submit via batch job
    try:
        from api.schemas import BatchJobBinderCellRequest
        from contracts.policies.budget import SimilarExistingAction
        from features.batch_job_binder_cell.service import create_batch_job_binder_cell

        batch_request = BatchJobBinderCellRequest(
            binder_types=spec.binder_types,
            temperatures_k=spec.temperatures_k,
            additive_types=spec.additive_types,
            additive_concentrations=spec.additive_concentrations,
            similar_existing_action=SimilarExistingAction.KEEP_PRIORITY,
        )
        result = create_batch_job_binder_cell(batch_request)
        return {
            "status": "submitted",
            "additive_types": additive_types,
            "n_submitted": result.submitted,
            "n_duplicates": result.duplicates,
        }
    except Exception as exc:
        logger.warning("Wave submission failed: %s", exc)
        return {
            "status": "error",
            "error": str(exc),
            "additive_types": additive_types,
        }
