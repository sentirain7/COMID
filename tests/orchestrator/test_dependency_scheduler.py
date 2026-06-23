"""Tests for dependency scheduler reconciliation/submission flow."""

from contextlib import contextmanager
from datetime import UTC, datetime

from contracts.schemas import BuildRequest, FFType, ProtocolRequest, RunTier
from database.models import ExperimentModel
from database.repositories.job_dependency_repo import JobDependencyRepository
from orchestrator.dependency_scheduler import DependencyScheduler


class _FakeGPU:
    def __init__(self, gpu_id: int, busy: bool = False):
        self.gpu_id = gpu_id
        self.current_job_id = "busy" if busy else None


class _FakeGPUTracker:
    def get_all_gpus(self):
        return [_FakeGPU(0, busy=False)]


class _FakeJobManager:
    def __init__(self):
        self.gpu_tracker = _FakeGPUTracker()
        self._task_by_job: dict[str, str] = {}
        self._seq = 0

    def submit(self, **_kwargs) -> str:
        self._seq += 1
        job_id = f"job-{self._seq}"
        self._task_by_job[job_id] = f"task-{self._seq}"
        return job_id

    def get_task_id(self, job_id: str) -> str | None:
        return self._task_by_job.get(job_id)


def _add_exp(
    session,
    *,
    exp_id: str,
    status: str,
    metadata_json: dict | None = None,
) -> None:
    session.add(
        ExperimentModel(
            exp_id=exp_id,
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            status=status,
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
            target_atoms=1000,
            temperature_K=298.0,
            pressure_atm=1.0,
            seed=1,
            metadata_json=metadata_json,
            created_at=datetime.now(UTC),
        )
    )


def test_submit_ready_edge_updates_child_and_edge(db_session, monkeypatch) -> None:
    build = BuildRequest(
        composition={"asphaltene": 20, "resin": 30, "aromatic": 35, "saturate": 15},
        target_atoms=1000,
        seed=1,
    )
    protocol = ProtocolRequest(
        ff_type=FFType.BULK_FF_GAFF2,
        run_tier=RunTier.SCREENING,
        temperature_K=298.0,
        pressure_atm=1.0,
        data_file_path="dummy.data",
    )
    _add_exp(db_session, exp_id="parent", status="completed")
    _add_exp(
        db_session,
        exp_id="child",
        status="pending",
        metadata_json={
            "deferred_submission": {
                "build_request": build.model_dump(),
                "protocol_request": protocol.model_dump(),
                "material_id": "dep_material",
            }
        },
    )
    db_session.commit()

    dep_repo = JobDependencyRepository(db_session)
    dep_repo.create_dependency("parent", "child")
    dep_repo.update_status("parent", "child", status="ready")
    db_session.commit()

    @contextmanager
    def _session_scope():
        yield db_session

    monkeypatch.setattr("orchestrator.dependency_scheduler.session_scope", _session_scope)
    scheduler = DependencyScheduler(_FakeJobManager())

    result = scheduler.submit_ready(max_submissions=5)
    assert result["submitted"] == 1

    child = db_session.query(ExperimentModel).filter(ExperimentModel.exp_id == "child").first()
    assert child is not None
    assert str(child.status) == "queued"
    assert str(child.celery_task_id).startswith("task-")

    edge = dep_repo.list_dependents("parent")[0]
    assert edge["status"] == "submitted"
    assert edge["reason"] is None


def test_submit_ready_missing_payload_sets_normalized_reason(db_session, monkeypatch) -> None:
    _add_exp(db_session, exp_id="parent", status="completed")
    _add_exp(db_session, exp_id="child", status="pending", metadata_json={"foo": "bar"})
    db_session.commit()

    dep_repo = JobDependencyRepository(db_session)
    dep_repo.create_dependency("parent", "child")
    dep_repo.update_status("parent", "child", status="ready")
    db_session.commit()

    @contextmanager
    def _session_scope():
        yield db_session

    monkeypatch.setattr("orchestrator.dependency_scheduler.session_scope", _session_scope)
    scheduler = DependencyScheduler(_FakeJobManager())

    result = scheduler.submit_ready(max_submissions=3)
    assert result["blocked"] == 1
    edge = dep_repo.list_dependents("parent")[0]
    assert edge["status"] == "blocked"
    assert edge["reason"] == "MISSING_DEFERRED_PAYLOAD"


def test_submit_ready_submit_failure_sets_normalized_reason(db_session, monkeypatch) -> None:
    build = BuildRequest(
        composition={"asphaltene": 20, "resin": 30, "aromatic": 35, "saturate": 15},
        target_atoms=1000,
        seed=1,
    )
    protocol = ProtocolRequest(
        ff_type=FFType.BULK_FF_GAFF2,
        run_tier=RunTier.SCREENING,
        temperature_K=298.0,
        pressure_atm=1.0,
        data_file_path="dummy.data",
    )
    _add_exp(db_session, exp_id="parent", status="completed")
    _add_exp(
        db_session,
        exp_id="child",
        status="pending",
        metadata_json={
            "deferred_submission": {
                "build_request": build.model_dump(),
                "protocol_request": protocol.model_dump(),
                "material_id": "dep_material",
            }
        },
    )
    db_session.commit()

    dep_repo = JobDependencyRepository(db_session)
    dep_repo.create_dependency("parent", "child")
    dep_repo.update_status("parent", "child", status="ready")
    db_session.commit()

    @contextmanager
    def _session_scope():
        yield db_session

    class _FailingJobManager(_FakeJobManager):
        def submit(self, **_kwargs) -> str:
            raise RuntimeError("broker down")

    monkeypatch.setattr("orchestrator.dependency_scheduler.session_scope", _session_scope)
    scheduler = DependencyScheduler(_FailingJobManager())

    result = scheduler.submit_ready(max_submissions=3)
    assert result["blocked"] == 1
    edge = dep_repo.list_dependents("parent")[0]
    assert edge["status"] == "blocked"
    assert str(edge["reason"]).startswith("SUBMIT_FAILED:")


def test_submit_layered_deferred_uses_replicates_when_seeds(db_session, monkeypatch) -> None:
    """payload.replicate_seeds ≥2 → submit_layered_replicates로 위임 (v01.05.31)."""
    calls: dict[str, object] = {}

    class _Resp:
        exp_id = "lay-real-1"

    async def fake_replicates(request):
        calls["fn"] = "replicates"
        calls["request"] = request
        return _Resp()

    async def fake_single(request):
        calls["fn"] = "single"
        calls["request"] = request
        return _Resp()

    monkeypatch.setattr(
        "features.layered_structures.service.submit_layered_replicates", fake_replicates
    )
    monkeypatch.setattr("features.layered_structures.service.submit_layered_structure", fake_single)

    scheduler = DependencyScheduler(_FakeJobManager())
    payload = {
        "kind": "layered",
        "name": "inverse-exp-002",
        "layers": [
            {"source_type": "crystal_structure", "auto_match_material": "SiO2"},
            {"source_type": "binder_cell", "prereq_exp_id": "parent_real"},
        ],
        "run_tier": "screening",
        "ff_type": "bulk_ff_gaff2",
        "temperature_K": 293.0,
        "tensile_enabled": True,
        "replicate_seeds": [101, 102, 103],
    }
    exp_id = scheduler._submit_layered_deferred(None, payload, db_session, "parent_real")

    assert exp_id == "lay-real-1"
    assert calls["fn"] == "replicates"
    request = calls["request"]
    assert request.replicate_seeds == [101, 102, 103]
    assert request.tensile_enabled is True
    # prereq_exp_id가 source_id로 해석됨
    assert request.layers[1].source_id == "parent_real"


def test_submit_layered_deferred_single_without_seeds(db_session, monkeypatch) -> None:
    """replicate_seeds 미지정 → 기존 단일 제출 경로 그대로."""
    calls: dict[str, object] = {}

    class _Resp:
        exp_id = "lay-real-2"

    async def fake_replicates(request):
        calls["fn"] = "replicates"
        return _Resp()

    async def fake_single(request):
        calls["fn"] = "single"
        calls["request"] = request
        return _Resp()

    monkeypatch.setattr(
        "features.layered_structures.service.submit_layered_replicates", fake_replicates
    )
    monkeypatch.setattr("features.layered_structures.service.submit_layered_structure", fake_single)

    scheduler = DependencyScheduler(_FakeJobManager())
    payload = {
        "kind": "layered",
        "layers": [
            {"source_type": "crystal_structure", "auto_match_material": "SiO2"},
            {"source_type": "binder_cell", "prereq_exp_id": "p2"},
        ],
        "temperature_K": 298.0,
    }
    exp_id = scheduler._submit_layered_deferred(None, payload, db_session, "p2")

    assert exp_id == "lay-real-2"
    assert calls["fn"] == "single"
    assert calls["request"].replicate_seeds is None


def test_submit_ready_layered_propagates_pipeline_block(db_session, monkeypatch) -> None:
    """layered deferred 제출 시 pipeline 블록이 실제 실험으로 전파(role=layered)."""
    _add_exp(db_session, exp_id="parent", status="completed")
    _add_exp(
        db_session,
        exp_id="placeholder",
        status="pending",
        metadata_json={
            "pipeline": {"id": "pl-x", "plan_exp_id": "exp-002", "role": "layered_placeholder"},
            "deferred_submission": {
                "kind": "layered",
                "layers": [
                    {"source_type": "crystal_structure", "auto_match_material": "SiO2"},
                    {"source_type": "binder_cell", "prereq_exp_id": "parent"},
                ],
                "temperature_K": 293.0,
            },
        },
    )
    _add_exp(db_session, exp_id="lay-real-3", status="queued")
    db_session.commit()

    dep_repo = JobDependencyRepository(db_session)
    dep_repo.create_dependency("parent", "placeholder")
    dep_repo.update_status("parent", "placeholder", status="ready")
    db_session.commit()

    @contextmanager
    def _session_scope():
        yield db_session

    monkeypatch.setattr("orchestrator.dependency_scheduler.session_scope", _session_scope)
    scheduler = DependencyScheduler(_FakeJobManager())
    monkeypatch.setattr(
        scheduler,
        "_submit_layered_deferred",
        lambda child, payload, session, parent_exp_id: "lay-real-3",
    )

    result = scheduler.submit_ready(max_submissions=5)
    assert result["submitted"] == 1

    placeholder = (
        db_session.query(ExperimentModel).filter(ExperimentModel.exp_id == "placeholder").first()
    )
    assert str(placeholder.status) == "cancelled"
    assert placeholder.metadata_json["real_layered_exp_id"] == "lay-real-3"

    real = db_session.query(ExperimentModel).filter(ExperimentModel.exp_id == "lay-real-3").first()
    assert real.metadata_json["pipeline"]["id"] == "pl-x"
    assert real.metadata_json["pipeline"]["role"] == "layered"
