from datetime import datetime, timedelta
from unittest.mock import patch

from database.models import ExperimentModel
from orchestrator.tasks import recover_orphan_ready_allocations


def _add_ready_exp(
    db_session,
    *,
    exp_id: str,
    gpu_id: int,
    task_id: str | None,
    age_seconds: int = 300,
) -> None:
    # age_seconds older than the recovery grace window (default 90s) so the row
    # is eligible for reclamation; pass a small value to exercise the grace guard.
    db_session.add(
        ExperimentModel(
            exp_id=exp_id,
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            status="ready",
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
            celery_task_id=task_id,
            gpu_id_allocated=gpu_id,
            lammps_pid=None,
            updated_at=datetime.utcnow() - timedelta(seconds=age_seconds),
        )
    )
    db_session.commit()


def _stub_celery_with_alive(*alive_task_ids: str):
    class _StubInspect:
        def active(self):
            return {
                "worker@host": [
                    {"id": tid, "name": "orchestrator.tasks.run_prepared_simulation"}
                    for tid in alive_task_ids
                ]
            }

        def reserved(self):
            return {"worker@host": []}

        def scheduled(self):
            return {"worker@host": []}

    class _StubCelery:
        class _Control:
            @staticmethod
            def inspect(timeout=1.0):
                return _StubInspect()

        control = _Control()

    return _StubCelery()


def test_recover_orphan_ready_allocations_releases_only_orphans(db_session):
    # Both rows are OLD (past the grace window). Only the one with no live task
    # is reclaimed.
    _add_ready_exp(db_session, exp_id="ready_orphan", gpu_id=1, task_id="task-orphan")
    _add_ready_exp(db_session, exp_id="ready_alive", gpu_id=2, task_id="task-alive")

    released = []

    class _StubGpuService:
        @staticmethod
        def release(gpu_id, task_id=None, exp_id=None):
            released.append((gpu_id, task_id, exp_id))
            return True

    with (
        patch("orchestrator.celery_app.celery_app", _stub_celery_with_alive("task-alive")),
        patch("orchestrator.gpu_service.get_gpu_service", return_value=_StubGpuService()),
        patch("orchestrator.tasks._trigger_ready_scheduler"),
    ):
        result = recover_orphan_ready_allocations(limit=100)

    assert result["status"] == "ok"
    assert result["released"] == 1
    assert released == [(1, "task-orphan", "ready_orphan")]


def test_recover_orphan_ready_allocations_grace_protects_fresh_rows(db_session):
    """A freshly-dispatched-but-not-yet-active row must NOT be reclaimed.

    Regression guard (v01.06.22): a just-dispatched run task can be invisible in
    the celery inspect() snapshot under load; releasing its GPU prematurely
    re-triggers the dispatcher and causes re-dispatch churn. The grace window
    keeps young ready+allocated rows out of recovery.
    """
    # No live task in the inspect snapshot, but the row is YOUNG (within grace).
    _add_ready_exp(db_session, exp_id="ready_fresh", gpu_id=3, task_id="task-fresh", age_seconds=5)

    released = []

    class _StubGpuService:
        @staticmethod
        def release(gpu_id, task_id=None, exp_id=None):
            released.append((gpu_id, task_id, exp_id))
            return True

    with (
        patch("orchestrator.celery_app.celery_app", _stub_celery_with_alive()),
        patch("orchestrator.gpu_service.get_gpu_service", return_value=_StubGpuService()),
        patch("orchestrator.tasks._trigger_ready_scheduler"),
    ):
        result = recover_orphan_ready_allocations(limit=100)

    assert result["status"] == "ok"
    assert result["released"] == 0
    assert released == []
