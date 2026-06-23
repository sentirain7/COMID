from types import SimpleNamespace

from database.models import ExperimentModel
from orchestrator.gpu_service import GPUService
from orchestrator.run_scheduler import RunScheduler


def _add_ready_experiment(db_session, exp_id: str) -> ExperimentModel:
    exp = ExperimentModel(
        exp_id=exp_id,
        run_tier="screening",
        ff_type="bulk_ff_gaff2",
        status="ready",
        comp_asphaltene_wt=20.0,
        comp_resin_wt=30.0,
        comp_aromatic_wt=35.0,
        comp_saturate_wt=15.0,
        prepared_artifact_json={"build_request": {}, "protocol_request": {}},
    )
    db_session.add(exp)
    db_session.commit()
    return exp


def test_schedule_ready_experiments_submits_when_gpu_available(db_session):
    exp = _add_ready_experiment(db_session, "exp_ready_1")

    gpu_service = GPUService()
    gpu_service.initialize(selected_gpus=[0])

    submitted = []

    class StubCelery:
        def send_task(self, name, kwargs=None, queue=None):
            submitted.append((name, kwargs, queue))
            return SimpleNamespace(id="task-run-ready-1")

    scheduler = RunScheduler(gpu_service=gpu_service, celery_app=StubCelery())
    result = scheduler.schedule_ready_experiments(max_submissions=5)

    assert result["submitted"] == 1
    assert submitted and submitted[0][0] == "orchestrator.tasks.run_prepared_simulation"
    sent_kwargs = submitted[0][1] or {}
    assert sent_kwargs.get("exp_id") == "exp_ready_1"
    assert sent_kwargs.get("gpu_id") == 0
    assert isinstance(sent_kwargs.get("dispatch_attempt_id"), str)
    assert len(sent_kwargs["dispatch_attempt_id"]) > 0

    db_session.refresh(exp)
    # Status stays ready until worker actually starts run_prepared_simulation.
    assert exp.status == "ready"
    assert exp.celery_task_id == "task-run-ready-1"
    assert exp.gpu_id_allocated == 0
    assert exp.metadata_json.get("dispatch_attempt_id") == sent_kwargs["dispatch_attempt_id"]


def test_validate_prepared_run_owner_atomic_claim_single_winner(db_session):
    """Duplicate dispatches of the same exp_id -> exactly one wins the claim.

    Regression guard for the v01.06.10 duplicate-dispatch bug: overlapping
    scheduler ticks (post-restart churn) launched multiple run_prepared_simulation
    tasks for the same experiment, all passing the read-only validation. The
    atomic ready->running claim must let only ONE proceed; the rest are skipped.
    """
    from orchestrator.task_runners import _validate_prepared_run_owner

    exp = _add_ready_experiment(db_session, "exp_dup_claim")
    exp.gpu_id_allocated = 0
    exp.metadata_json = {"dispatch_attempt_id": "TOK"}
    db_session.commit()

    # Two tasks reach validation with the same (valid) dispatch token + gpu.
    ok_a, reason_a = _validate_prepared_run_owner("exp_dup_claim", "taskA", 0, "TOK")
    ok_b, reason_b = _validate_prepared_run_owner("exp_dup_claim", "taskB", 0, "TOK")

    assert ok_a is True, reason_a
    assert ok_b is False
    assert reason_b.startswith("duplicate_claim"), reason_b

    db_session.expire_all()
    refreshed = db_session.get(ExperimentModel, exp.id)
    assert refreshed.status == "running"
    assert refreshed.active_attempt_id == "taskA"


def test_schedule_ready_experiments_keeps_ready_when_no_gpu(db_session):
    exp = _add_ready_experiment(db_session, "exp_ready_2")

    class NoGpuService:
        def allocate_gpu(self, job_id, exp_id=None):
            return None

        def release(self, gpu_id, exp_id=None, task_id=None):
            return True

    class StubCelery:
        def send_task(self, name, kwargs=None, queue=None):
            raise AssertionError("send_task must not be called without GPU")

    scheduler = RunScheduler(gpu_service=NoGpuService(), celery_app=StubCelery())
    result = scheduler.schedule_ready_experiments(max_submissions=5)

    assert result["submitted"] == 0
    assert result["skipped_no_gpu"] == 1

    db_session.refresh(exp)
    assert exp.status == "ready"
    assert exp.celery_task_id is None


def test_caps_needs_gpu_robust_to_degraded_cache(monkeypatch):
    """_caps_needs_gpu must NOT trust a DEGRADED cache (empty packages == probe
    timed out). Trusting its bogus mpi_only would make the scheduler dispatch GPU
    jobs with gpu_id=-1 (CPU) -> 'Package kokkos without KOKKOS' failures. It must
    return conservative True for None/degraded, and only False for a genuine
    (packages-present) non-GPU build."""
    from contracts.schema_enums import AccelMode, KokkosBackend
    from contracts.schemas import LammpsCaps
    from orchestrator.run_scheduler import _caps_needs_gpu

    def _caps(packages, mode):
        return LammpsCaps(
            executable_path="/usr/bin/lmp",
            version_string="22 Jul 2025",
            installed_packages=packages,
            kokkos_backend=KokkosBackend.CUDA if packages else KokkosBackend.NONE,
            gpu_detected=True,
            gpu_count=1,
            cpu_cores=8,
            accel_mode=mode,
        )

    attr = "orchestrator.lammps_probe._cached_caps"

    monkeypatch.setattr(attr, None, raising=False)
    assert _caps_needs_gpu() is True  # unavailable -> conservative

    monkeypatch.setattr(attr, _caps([], AccelMode.MPI_ONLY), raising=False)
    assert _caps_needs_gpu() is True  # DEGRADED (empty pkgs) -> NOT False

    monkeypatch.setattr(attr, _caps(["KOKKOS"], AccelMode.KOKKOS_GPU), raising=False)
    assert _caps_needs_gpu() is True  # genuine GPU build

    monkeypatch.setattr(attr, _caps(["KSPACE"], AccelMode.MPI_ONLY), raising=False)
    assert _caps_needs_gpu() is False  # genuine non-GPU build (packages present)


def test_update_celery_task_id_does_not_set_active_attempt_id(db_session):
    """Fix B (v01.06.22): active_attempt_id is the atomic claim's exclusive token.

    update_celery_task_id must NOT write it — otherwise a concurrent scheduler
    tick that publishes a 2nd task rewrites active_attempt_id and poisons the
    claim filter's idempotent-retry branch, letting the 2nd run win -> duplicate lmp.
    """
    from database.repositories.experiment_repo import ExperimentRepository

    exp = _add_ready_experiment(db_session, "exp_no_poison")
    assert (exp.active_attempt_id or None) is None

    ExperimentRepository(db_session).update_celery_task_id("exp_no_poison", "task-XYZ")
    db_session.commit()
    db_session.expire_all()

    refreshed = db_session.get(ExperimentModel, exp.id)
    assert refreshed.celery_task_id == "task-XYZ"
    assert (refreshed.active_attempt_id or None) is None


def test_validate_prepared_run_owner_resists_active_attempt_poisoning(db_session):
    """Fix B (v01.06.22) regression: the live duplicate-lmp scenario.

    taskA wins the claim (status->running, active=taskA). A second overlapping
    scheduler tick then rewrites celery_task_id to taskB and publishes a fresh
    dispatch token. taskB MUST NOT also win the claim — historically
    update_celery_task_id rewrote active_attempt_id=taskB, satisfying the claim
    filter's `active_attempt_id == task_id` branch and launching a 2nd lmp.
    """
    from database.repositories.experiment_repo import ExperimentRepository
    from orchestrator.task_runners import _validate_prepared_run_owner

    exp = _add_ready_experiment(db_session, "exp_poison")
    exp.gpu_id_allocated = 0
    exp.metadata_json = {"dispatch_attempt_id": "TOK_A"}
    db_session.commit()

    ok_a, reason_a = _validate_prepared_run_owner("exp_poison", "taskA", 0, "TOK_A")
    assert ok_a is True, reason_a

    # Concurrent tick B overwrites task id + dispatch token while taskA owns the run.
    db_session.expire_all()
    repo = ExperimentRepository(db_session)
    repo.update_celery_task_id("exp_poison", "taskB")
    repo.set_dispatch_attempt_id("exp_poison", "TOK_B")
    db_session.commit()

    ok_b, reason_b = _validate_prepared_run_owner("exp_poison", "taskB", 0, "TOK_B")
    assert ok_b is False, "taskB must not win after taskA already owns the run"
    assert reason_b.startswith("duplicate_claim"), reason_b

    db_session.expire_all()
    refreshed = db_session.get(ExperimentModel, exp.id)
    assert refreshed.status == "running"
    assert refreshed.active_attempt_id == "taskA"


def test_schedule_ready_experiments_single_flight_lock(db_session):
    """Fix A (v01.06.22): only one dispatcher runs at a time across processes.

    While another instance holds the cross-process dispatch lock, a scheduler
    tick must no-op (skipped_locked) and dispatch nothing — closing the
    concurrent-tick mis-dispatch / GPU-churn race at its source.
    """
    import pytest

    import orchestrator.run_scheduler as rs

    if rs.fcntl is None:
        pytest.skip("POSIX fcntl unavailable; single-flight lock is a no-op")

    held = rs._acquire_dispatch_lock()
    assert held is not None and held is not rs._NO_LOCK_SENTINEL
    try:
        _add_ready_experiment(db_session, "exp_locked")

        gpu_service = GPUService()
        gpu_service.initialize(selected_gpus=[0])

        submitted = []

        class StubCelery:
            def send_task(self, name, kwargs=None, queue=None):
                submitted.append((name, kwargs, queue))
                return SimpleNamespace(id="t")

        scheduler = RunScheduler(gpu_service=gpu_service, celery_app=StubCelery())
        result = scheduler.schedule_ready_experiments(max_submissions=5)

        assert result.get("skipped_locked") == 1
        assert result.get("submitted") == 0
        assert submitted == []
    finally:
        rs._release_dispatch_lock(held)


def test_trigger_ready_scheduler_routes_to_control(monkeypatch):
    """Fix C (v01.06.22): the fire-and-forget trigger must use the control queue,
    not 'default' (build@/cpu@), so the dispatcher does not fan out across pools."""
    import orchestrator.task_maintenance as tm

    sent = {}

    class StubApp:
        def send_task(self, name, kwargs=None, queue=None):
            sent.update(name=name, kwargs=kwargs, queue=queue)

    monkeypatch.setattr("orchestrator.celery_app.celery_app", StubApp(), raising=False)
    tm._trigger_ready_scheduler(7)

    assert sent.get("name") == "orchestrator.tasks.schedule_ready_experiments"
    assert sent.get("queue") == "control"
