"""Tier → Celery task mapping registry (SSOT).

Consolidates identical tier→task maps:
- orchestrator/tasks.py (batch_simulation)
- orchestrator/celery_job_manager.py (_get_task_for_tier)
- (celery_app.py routing config is NOT touched — routing is infra, not dispatch)
"""

from typing import Any

from contracts.schemas import RunTier


def get_task_for_tier(tier: str | RunTier) -> Any:
    """Return the Celery task function for the given tier.

    Args:
        tier: Run tier (str or RunTier enum)

    Returns:
        Celery task function
    """
    from orchestrator.tasks import (
        run_confirm_simulation,
        run_screening_simulation,
        run_simulation,
        run_viscosity_simulation,
    )

    tier_value = tier.value if isinstance(tier, RunTier) else tier

    task_map = {
        "screening": run_screening_simulation,
        "confirm": run_confirm_simulation,
        "viscosity": run_viscosity_simulation,
    }
    return task_map.get(tier_value, run_simulation)
