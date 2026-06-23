from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from database.models import ExperimentModel
from orchestrator.maintenance import MaintenanceService


def _mk_exp(
    db_session,
    *,
    exp_id: str,
    status: str,
    task_id: str | None = None,
    prepared: bool = False,
    gpu_id: int | None = None,
    heartbeat: datetime | None = None,
):
    exp = ExperimentModel(
        exp_id=exp_id,
        run_tier="screening",
        ff_type="bulk_ff_gaff2",
        status=status,
        comp_asphaltene_wt=20.0,
        comp_resin_wt=30.0,
        comp_aromatic_wt=35.0,
        comp_saturate_wt=15.0,
        celery_task_id=task_id,
        active_attempt_id=task_id,
        prepared_artifact_json={"build_request": {}, "protocol_request": {}} if prepared else None,
        gpu_id_allocated=gpu_id,
        last_heartbeat_at=heartbeat,
    )
    db_session.add(exp)
    db_session.commit()
    return exp


def test_sync_job_status_sets_running_from_started(db_session):
    exp = _mk_exp(
        db_session,
        exp_id="exp_sync_started",
        status="ready",
        task_id="task_sync_started",
        prepared=True,
    )
    svc = MaintenanceService(db_session)

    with patch("orchestrator.maintenance.AsyncResult") as async_result:
        async_result.return_value = SimpleNamespace(state="STARTED")
        res = svc.sync_job_status(celery_app=SimpleNamespace())

    db_session.refresh(exp)
    assert res["checked"] >= 1
    assert exp.status == "running"


def test_sync_job_status_marks_stale_running_failed(db_session):
    exp = _mk_exp(
        db_session,
        exp_id="exp_sync_stale",
        status="running",
        task_id="task_sync_stale",
        prepared=True,
        gpu_id=0,
        heartbeat=None,
    )
    svc = MaintenanceService(db_session)

    class _StubGpu:
        def release(self, gpu_id, task_id=None, exp_id=None):
            return True

    with patch("orchestrator.maintenance.AsyncResult") as async_result:
        async_result.return_value = SimpleNamespace(state="PENDING")
        with patch("orchestrator.gpu_service.get_gpu_service", return_value=_StubGpu()):
            res = svc.sync_job_status(celery_app=SimpleNamespace())

    db_session.refresh(exp)
    assert res["updated"] >= 1
    assert exp.status == "failed"


def test_cleanup_orphaned_tasks_revokes_unknown_exp(db_session):
    _mk_exp(
        db_session,
        exp_id="exp_known",
        status="queued",
        task_id="task_known",
    )
    svc = MaintenanceService(db_session)

    reserved = {
        "worker@host": [
            {
                "id": "task_orphan",
                "name": "orchestrator.tasks.run_prepared_simulation",
                "kwargs": {"exp_id": "exp_missing"},
            }
        ]
    }
    revoked: list[str] = []

    class _Ctl:
        def inspect(self):
            return SimpleNamespace(
                reserved=lambda: reserved,
                scheduled=lambda: {},
                active=lambda: {},
            )

        def revoke(self, task_id, terminate=False, signal=None):
            del terminate, signal
            revoked.append(task_id)

    celery_app = SimpleNamespace(control=_Ctl())
    res = svc.cleanup_orphaned_tasks(celery_app=celery_app)
    assert res["revoked"] == 1
    assert revoked == ["task_orphan"]


def test_cleanup_old_jobs_rolls_back_partial_delete_failure(db_session, monkeypatch):
    """A failed per-experiment cleanup must not commit partial DB mutations."""
    # Use a prunable status (failed). `completed` is intentionally excluded from
    # auto-cleanup, so it would no longer be a deletion candidate at all.
    exp = _mk_exp(db_session, exp_id="exp_cleanup_partial", status="failed")
    exp.updated_at = datetime.utcnow() - timedelta(hours=48)
    db_session.commit()

    import features.experiments.experiment_lifecycle as lifecycle_module

    def partial_delete_then_raise(session, exp_id):
        row = session.query(ExperimentModel).filter(ExperimentModel.exp_id == exp_id).first()
        session.delete(row)
        raise RuntimeError("simulated cleanup failure")

    monkeypatch.setattr(lifecycle_module, "_delete_one", partial_delete_then_raise)

    result = MaintenanceService(db_session).cleanup_old_jobs(older_than_hours=24)

    assert result == {"deleted": 0, "skipped": 1}
    assert (
        db_session.query(ExperimentModel)
        .filter(ExperimentModel.exp_id == "exp_cleanup_partial")
        .first()
        is not None
    )


def test_cleanup_old_jobs_never_deletes_completed(db_session, monkeypatch):
    """Completed experiments (scientific results + E_intra refs) are protected.

    Regression guard: the hourly cleanup previously deleted any completed
    experiment older than 24h, whose cascade wiped the e_intra table. Completed
    rows must never be selected for auto-deletion, regardless of age.
    """
    old = datetime.utcnow() - timedelta(hours=72)
    # An old completed single-molecule E_intra reference + an old failed junk row.
    done = _mk_exp(db_session, exp_id="exp_done_ref", status="completed")
    done.updated_at = old
    junk = _mk_exp(db_session, exp_id="exp_junk", status="failed")
    junk.updated_at = old
    db_session.commit()

    import features.experiments.experiment_lifecycle as lifecycle_module

    deleted_ids: list[str] = []

    def _record_delete(session, exp_id):
        deleted_ids.append(exp_id)
        row = session.query(ExperimentModel).filter(ExperimentModel.exp_id == exp_id).first()
        if row is not None:
            session.delete(row)
        return {"success": True, "deferred_files": []}

    monkeypatch.setattr(lifecycle_module, "_delete_one", _record_delete)

    result = MaintenanceService(db_session).cleanup_old_jobs(older_than_hours=24)

    # Only the failed junk row is pruned; the completed reference survives.
    assert deleted_ids == ["exp_junk"]
    assert result["deleted"] == 1
    assert (
        db_session.query(ExperimentModel).filter(ExperimentModel.exp_id == "exp_done_ref").first()
        is not None
    )


def test_check_stalled_jobs_marks_prepared_running_failed(db_session):
    stale_time = datetime.utcnow() - timedelta(minutes=120)
    exp = _mk_exp(
        db_session,
        exp_id="exp_stalled",
        status="running",
        task_id="task_stalled",
        prepared=True,
        gpu_id=1,
        heartbeat=stale_time,
    )
    exp.updated_at = stale_time
    db_session.commit()

    class _StubGpu:
        def release(self, gpu_id, task_id=None, exp_id=None):
            return True

    svc = MaintenanceService(db_session)
    with patch("orchestrator.gpu_service.get_gpu_service", return_value=_StubGpu()):
        res = svc.check_stalled_jobs(stall_timeout_minutes=30)

    db_session.refresh(exp)
    assert res["marked_failed"] == 1
    assert exp.status == "failed"


# ---------------------------------------------------------------------------
# Active orphan cleanup tests
# ---------------------------------------------------------------------------


def test_cleanup_active_orphan_terminates(db_session):
    """Active task for deleted experiment should be revoked with terminate=True."""
    svc = MaintenanceService(db_session)

    active_tasks = {
        "worker@host": [
            {
                "id": "task_active_orphan",
                "name": "orchestrator.tasks.run_simulation",
                "args": [{}, {}, "mat", None, None, "exp_deleted", None, 0.0, None],
            }
        ]
    }
    revoked: list[tuple[str, bool]] = []

    class _Ctl:
        def inspect(self):
            return SimpleNamespace(
                reserved=lambda: {},
                scheduled=lambda: {},
                active=lambda: active_tasks,
            )

        def revoke(self, task_id, terminate=False, signal=None):
            revoked.append((task_id, terminate))

    res = svc.cleanup_orphaned_tasks(celery_app=SimpleNamespace(control=_Ctl()))
    assert res["revoked"] == 1
    assert revoked[0] == ("task_active_orphan", True)


def test_cleanup_skips_non_simulation_tasks(db_session):
    """Non-simulation tasks (e.g., maintenance) should never be revoked."""
    svc = MaintenanceService(db_session)

    active_tasks = {
        "worker@host": [
            {
                "id": "task_maintenance",
                "name": "orchestrator.tasks.check_stalled_jobs",
                "kwargs": {},
            }
        ]
    }
    revoked: list[str] = []

    class _Ctl:
        def inspect(self):
            return SimpleNamespace(
                reserved=lambda: {},
                scheduled=lambda: {},
                active=lambda: active_tasks,
            )

        def revoke(self, task_id, terminate=False, signal=None):
            revoked.append(task_id)

    res = svc.cleanup_orphaned_tasks(celery_app=SimpleNamespace(control=_Ctl()))
    assert res["revoked"] == 0
    assert revoked == []


def test_cleanup_skips_known_experiment(db_session):
    """Tasks for existing experiments should not be revoked."""
    _mk_exp(db_session, exp_id="exp_alive", status="running", task_id="task_alive")
    svc = MaintenanceService(db_session)

    active_tasks = {
        "worker@host": [
            {
                "id": "task_alive",
                "name": "orchestrator.tasks.run_simulation",
                "args": [{}, {}, "mat", None, None, "exp_alive", None, 0.0, None],
            }
        ]
    }
    revoked: list[str] = []

    class _Ctl:
        def inspect(self):
            return SimpleNamespace(
                reserved=lambda: {},
                scheduled=lambda: {},
                active=lambda: active_tasks,
            )

        def revoke(self, task_id, terminate=False, signal=None):
            revoked.append(task_id)

    res = svc.cleanup_orphaned_tasks(celery_app=SimpleNamespace(control=_Ctl()))
    assert res["revoked"] == 0


# ---------------------------------------------------------------------------
# Stalled queued/building with lost Celery task
# ---------------------------------------------------------------------------


def test_stalled_queued_with_task_id_survives_invisible_queue(db_session):
    """Queued experiment with a task_id is NOT failed even when absent from the
    broker inspect snapshot (v01.06.09 fix).

    With worker_prefetch_multiplier=1 + task_acks_late=True, tasks waiting in
    the broker queue for a free worker slot are invisible to inspect
    (active/reserved/scheduled). Failing them mass-kills the healthy queued
    backlog of a large batch. acks_late guarantees redelivery on worker death,
    so a queued job that still holds a task_id is only waiting, not lost.
    """
    stale_time = datetime.utcnow() - timedelta(minutes=120)
    exp = _mk_exp(db_session, exp_id="exp_lost", status="queued", task_id="task_gone")
    exp.updated_at = stale_time
    exp.created_at = stale_time
    db_session.commit()

    # Empty inspect: a queued-but-unprefetched task is normally invisible here.
    class _Ctl:
        def inspect(self):
            return SimpleNamespace(
                active=lambda: {},
                reserved=lambda: {},
                scheduled=lambda: {},
            )

    svc = MaintenanceService(db_session)
    res = svc.check_stalled_jobs(
        stall_timeout_minutes=30,
        celery_app=SimpleNamespace(control=_Ctl()),
    )

    db_session.refresh(exp)
    assert res["marked_failed"] == 0
    assert exp.status == "queued"  # left alone — waiting for a worker slot


def test_stalled_queued_without_task_id_fails(db_session):
    """Queued experiment with NO celery_task_id is genuinely stuck -> failed."""
    stale_time = datetime.utcnow() - timedelta(minutes=120)
    exp = _mk_exp(db_session, exp_id="exp_notask", status="queued", task_id=None)
    exp.updated_at = stale_time
    exp.created_at = stale_time
    db_session.commit()

    class _Ctl:
        def inspect(self):
            return SimpleNamespace(
                active=lambda: {}, reserved=lambda: {}, scheduled=lambda: {}
            )

    svc = MaintenanceService(db_session)
    res = svc.check_stalled_jobs(
        stall_timeout_minutes=30,
        celery_app=SimpleNamespace(control=_Ctl()),
    )

    db_session.refresh(exp)
    assert res["marked_failed"] == 1
    assert exp.status == "failed"
    assert "No Celery task" in (exp.error_message or "")


def test_stalled_building_with_lost_task_fails(db_session):
    """A 'building' job is mid-execution on a worker, so it MUST appear in the
    active snapshot; genuine absence means the task vanished -> failed."""
    stale_time = datetime.utcnow() - timedelta(minutes=120)
    exp = _mk_exp(
        db_session, exp_id="exp_building_gone", status="building", task_id="task_gone"
    )
    exp.updated_at = stale_time
    exp.created_at = stale_time
    db_session.commit()

    class _Ctl:
        def inspect(self):
            return SimpleNamespace(
                active=lambda: {}, reserved=lambda: {}, scheduled=lambda: {}
            )

    svc = MaintenanceService(db_session)
    res = svc.check_stalled_jobs(
        stall_timeout_minutes=30,
        celery_app=SimpleNamespace(control=_Ctl()),
    )

    db_session.refresh(exp)
    assert res["marked_failed"] == 1
    assert exp.status == "failed"
    assert "missing from broker" in (exp.error_message or "")


def test_stalled_queued_with_task_in_broker_survives(db_session):
    """Queued experiment whose task is still in broker should NOT be failed."""
    stale_time = datetime.utcnow() - timedelta(minutes=120)
    exp = _mk_exp(db_session, exp_id="exp_waiting", status="queued", task_id="task_queued_ok")
    exp.updated_at = stale_time
    exp.created_at = stale_time
    db_session.commit()

    # Task is visible in reserved queue
    class _Ctl:
        def inspect(self):
            return SimpleNamespace(
                active=lambda: {},
                reserved=lambda: {
                    "worker@host": [{"id": "task_queued_ok", "name": "run_simulation"}]
                },
                scheduled=lambda: {},
            )

    svc = MaintenanceService(db_session)
    svc.check_stalled_jobs(
        stall_timeout_minutes=30,
        celery_app=SimpleNamespace(control=_Ctl()),
    )

    db_session.refresh(exp)
    assert exp.status == "queued"  # NOT failed
