"""E2E Level 7: Failure / Recovery / Idempotency (docs/WORKFLOW_VERIFICATION_PLAN.md §6).

수백~수천 건 운영 시 더 중요한 비정상 흐름을 라우터 → service → repository → DB
경로로 실제 검증한다. LAMMPS / Celery worker / GPU 하드웨어 없이 통과해야 한다.

검증 시나리오 (구현):
1. 중복 single-molecule batch submit → 두 번째 제출이 ``skipped_existing`` 으로 감지 (idempotent)
2. similar existing decision required → 동일 분자/온도 active 실험 존재 시 skip (유사 판정)
3. child dependency 대기 후 부모 완료 시 ``blocked`` → ``ready`` 해제
   (``DependencyScheduler.reconcile_parent``)
5. ``GET /recovery/check`` → ``POST /recovery/execute`` (orphaned running 실험 abandon)
6. cancel 후 retry (``/experiments/{id}/cancel`` → ``/experiments/{id}/retry``)
7. timeout/stale process row cleanup (``POST /recovery/cleanup``)
8. scan-database import 중 중복 데이터 처리 (두 번째 import → ``skipped``)

Mock 경계 (시뮬레이션 / 외부 실행 경계에서만):
- Celery / GPU 제출: ``SubmissionFacade.submit_experiment``, ``job_manager.submit`` 등은
  fake 로 대체. 라우터 → service → repository → DB(SQLite) 는 전부 실제로 탄다.

미구현 (사유는 모듈 docstring 하단 참조):
- 4. running 중 프로세스 추적 유실 (heartbeat stale) — 시나리오 5/7 이 stale/orphaned
  탐지 + cleanup 을 이미 실제 코드로 커버하므로 별도 중복 테스트 생략.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

TestClient = pytest.importorskip(
    "fastapi.testclient",
    reason="FastAPI not installed",
).TestClient

from api.application import app  # noqa: E402
from api.runtime_state import (  # noqa: E402
    clear_recovery_components,
    set_recovery_components,
)
from database.connection import close_db, session_scope  # noqa: E402
from database.models import (  # noqa: E402
    ExperimentModel,
    JobDependencyModel,
    ProcessInfoModel,
)


def _make_experiment(
    exp_id: str,
    *,
    status: str,
    seed: int = 1,
    **overrides,
) -> ExperimentModel:
    """Build a minimal valid ExperimentModel row (bulk binder shape)."""
    fields = {
        "exp_id": exp_id,
        "run_tier": "screening",
        "ff_type": "bulk_ff_gaff2",
        "status": status,
        "comp_asphaltene_wt": 20.0,
        "comp_resin_wt": 30.0,
        "comp_aromatic_wt": 35.0,
        "comp_saturate_wt": 15.0,
        "target_atoms": 1000,
        "temperature_K": 298.0,
        "pressure_atm": 1.0,
        "seed": seed,
        "created_at": datetime.now(UTC),
    }
    fields.update(overrides)
    return ExperimentModel(**fields)


class _TestBase:
    """Shared client fixture: isolated SQLite DB + ASPHALT_PROJECT_ROOT, no-op lifespan."""

    @pytest.fixture
    def client(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ASPHALT_PROJECT_ROOT", str(tmp_path))
        db_path = tmp_path / "test_recovery_idempotency.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        close_db()

        @asynccontextmanager
        async def _lifespan(_app):
            yield

        app.router.lifespan_context = _lifespan
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
        close_db()

    @pytest.fixture
    def recovery_components(self, client):
        """Wire real ProcessTracker + ProcessRecoveryService against the test DB.

        The no-op lifespan does not initialise recovery singletons, so tests that
        hit ``/recovery/*`` must set them up explicitly.
        """
        from orchestrator.process_recovery import ProcessRecoveryService
        from orchestrator.process_tracker import ProcessTracker

        tracker = ProcessTracker()
        service = ProcessRecoveryService(tracker)
        set_recovery_components(tracker, service)
        yield tracker
        clear_recovery_components()


# ---------------------------------------------------------------------------
# Scenarios 1 & 2: duplicate / similar-existing single-molecule batch submit
# ---------------------------------------------------------------------------


class TestDuplicateAndSimilarSubmission(_TestBase):
    """Single-molecule E_intra batch is idempotent: a re-submit at the same
    temperature is detected as ``skipped_existing`` instead of double-running.
    """

    _MOL_ID = "U-AS-Thio"
    _TEMPS = [293.0, 313.0]

    def _patches(self):
        """Mock the simulation-submission boundary; keep DB writes real."""
        mol_db = SimpleNamespace(
            get=lambda _mol_id: SimpleNamespace(atom_count=42),
            get_temperature_code=lambda _config, _temp: "0293",
        )

        submitted: list[str] = []

        def _fake_submit_experiment(*, exp_id, **_kwargs):
            # Persist a DB stub mirroring the real SubmissionFacade so the
            # second batch call sees an *active* experiment for that temp.
            with session_scope() as session:
                if (
                    session.query(ExperimentModel).filter(ExperimentModel.exp_id == exp_id).first()
                    is None
                ):
                    temp = float(_kwargs.get("temperature_k", 293.0))
                    session.add(
                        _make_experiment(
                            exp_id,
                            status="pending",
                            study_type="single_molecule_vacuum",
                            additive_mol_id=_kwargs.get("additive_mol_id"),
                            additive_type=_kwargs.get("additive_type"),
                            temperature_K=temp,
                            comp_asphaltene_wt=0.0,
                            comp_resin_wt=0.0,
                            comp_aromatic_wt=0.0,
                            comp_saturate_wt=0.0,
                            metadata_json={
                                "study_type": "single_molecule_vacuum",
                                "e_intra_method": "single_molecule_vacuum",
                            },
                        )
                    )
                    session.commit()
            submitted.append(exp_id)
            return ("job-" + exp_id, "task-" + exp_id)

        return (
            mol_db,
            submitted,
            [
                patch("api.deps.get_molecule_db", return_value=mol_db),
                patch("api.deps.get_job_manager", return_value=SimpleNamespace()),
                patch(
                    "features.molecules.catalog.resolve_ff_hint",
                    return_value={
                        "submit_ff_type": "bulk_ff_gaff2",
                        "is_submittable": True,
                        "blocked_reason": None,
                        "ff_hint": "gaff2",
                        "ff_display_label": "GAFF2",
                    },
                ),
                patch(
                    "orchestrator.submission_facade.SubmissionFacade.submit_experiment",
                    side_effect=_fake_submit_experiment,
                ),
            ],
        )

    def test_first_submit_runs_then_resubmit_is_skipped(self, client):
        mol_db, submitted, patches = self._patches()
        payload = {
            "selected_mol_id": self._MOL_ID,
            "temperatures_k": self._TEMPS,
            "ff_type": "bulk_ff_gaff2",
            "force_recompute": False,
        }

        # First submit: both temperatures are new → submitted.
        from contextlib import ExitStack

        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            resp1 = client.post("/experiments/single-molecule/batch", json=payload)
        assert resp1.status_code == 200, resp1.text
        body1 = resp1.json()
        assert body1["submitted"] == 2, body1
        assert body1["skipped_existing"] == 0, body1
        assert len(submitted) == 2

        # Re-create fresh patches (submitted list reset) for the second call.
        mol_db2, submitted2, patches2 = self._patches()
        with ExitStack() as stack:
            for p in patches2:
                stack.enter_context(p)
            resp2 = client.post("/experiments/single-molecule/batch", json=payload)
        assert resp2.status_code == 200, resp2.text
        body2 = resp2.json()

        # Scenario 1 + 2: identical inputs → idempotent / similar-existing detect.
        assert body2["submitted"] == 0, body2
        assert body2["skipped_existing"] == 2, body2
        assert len(submitted2) == 0, "no new simulation should be launched on re-submit"
        statuses = {item["status"] for item in body2["items"]}
        assert statuses == {"skipped_existing"}, body2


# ---------------------------------------------------------------------------
# Scenario 3: dependency release (blocked -> ready) after parent completes
# ---------------------------------------------------------------------------


class TestDependencyRelease(_TestBase):
    """A blocked child edge is promoted to ``ready`` once the parent reaches a
    terminal-success state, via ``DependencyScheduler.reconcile_parent``.
    """

    def _seed(self, suffix: str, parent_status: str):
        """Seed a parent/child pair with unique exp_ids.

        The test DB engine is reused across tests in a run, so each test uses a
        distinct exp_id suffix instead of relying on a per-test fresh DB.
        """
        parent = f"dep_parent_{suffix}"
        child = f"dep_child_{suffix}"
        with session_scope() as session:
            session.add(_make_experiment(parent, status=parent_status, seed=1))
            session.add(_make_experiment(child, status="pending", seed=2))
            session.add(
                JobDependencyModel(
                    parent_exp_id=parent,
                    child_exp_id=child,
                    status="blocked",
                )
            )
            session.commit()
        return parent, child

    def _edge_status(self, child: str) -> str:
        with session_scope() as session:
            edge = (
                session.query(JobDependencyModel)
                .filter(JobDependencyModel.child_exp_id == child)
                .first()
            )
            return edge.status

    def test_blocked_child_stays_blocked_while_parent_pending(self, client):
        parent, child = self._seed("pending", parent_status="running")
        from orchestrator.dependency_scheduler import DependencyScheduler

        sched = DependencyScheduler(job_manager=SimpleNamespace())
        result = sched.reconcile_parent(parent)
        assert result["ready"] == 0, result
        assert result["blocked"] == 1, result
        assert self._edge_status(child) == "blocked"

    @staticmethod
    def _job_manager_with_free_gpu():
        """Fake job_manager exposing a single idle GPU for the budget check."""
        free_gpu = SimpleNamespace(gpu_id=0, current_job_id=None)
        gpu_tracker = SimpleNamespace(get_all_gpus=lambda: [free_gpu])
        return SimpleNamespace(gpu_tracker=gpu_tracker)

    def test_child_released_to_ready_when_parent_completed(self, client):
        parent, child = self._seed("completed", parent_status="completed")
        from orchestrator.dependency_scheduler import DependencyScheduler

        sched = DependencyScheduler(job_manager=self._job_manager_with_free_gpu())
        result = sched.reconcile_parent(parent)
        assert result["ready"] == 1, result
        assert result["blocked"] == 0, result
        assert result["failed"] == 0, result
        assert self._edge_status(child) == "ready"

    def test_child_failed_when_parent_blocked_state(self, client):
        # Parent ends in a non-success terminal state → child edge fails out.
        parent, child = self._seed("failed", parent_status="failed")
        from orchestrator.dependency_scheduler import DependencyScheduler

        sched = DependencyScheduler(job_manager=SimpleNamespace())
        result = sched.reconcile_parent(parent)
        assert result["failed"] == 1, result
        assert self._edge_status(child) == "failed"


# ---------------------------------------------------------------------------
# Scenario 5: recovery check -> execute (orphaned running experiment)
# ---------------------------------------------------------------------------


class TestRecoveryCheckExecute(_TestBase):
    """A ``running`` experiment with no ProcessInfo row is detected as an
    orphaned recovery candidate; ``/recovery/execute`` (abandon) cleans it up.
    """

    def test_check_then_execute_abandon(self, client, recovery_components):
        # Seed a running experiment WITHOUT a ProcessInfo row -> orphaned.
        with session_scope() as session:
            session.add(
                _make_experiment(
                    "orphan_exp",
                    status="running",
                    lammps_pid=999999,
                    last_heartbeat_at=datetime.utcnow() - timedelta(minutes=10),
                )
            )
            session.commit()

        check = client.get("/recovery/check")
        assert check.status_code == 200, check.text
        check_body = check.json()
        assert check_body["needs_recovery"] is True
        assert check_body["candidate_count"] >= 1

        candidates = client.get("/recovery/candidates")
        assert candidates.status_code == 200, candidates.text
        cand_body = candidates.json()
        orphan = next((c for c in cand_body if c["exp_id"] == "orphan_exp"), None)
        assert orphan is not None, cand_body
        assert orphan["recommended_action"] == "abandon"

        execute = client.post(
            "/recovery/execute",
            json={"exp_id": "orphan_exp", "action": "abandon"},
        )
        assert execute.status_code == 200, execute.text
        exec_body = execute.json()
        assert exec_body["success"] is True
        assert exec_body["action"] == "abandon"

        with session_scope() as session:
            exp = (
                session.query(ExperimentModel)
                .filter(ExperimentModel.exp_id == "orphan_exp")
                .first()
            )
            assert exp.status == "failed"
            assert exp.recovery_status == "abandoned"

    def test_invalid_recovery_action_rejected(self, client, recovery_components):
        resp = client.post(
            "/recovery/execute",
            json={"exp_id": "whatever", "action": "not_a_real_action"},
        )
        assert resp.status_code >= 400, resp.text


# ---------------------------------------------------------------------------
# Scenario 6: cancel then retry
# ---------------------------------------------------------------------------


class TestCancelThenRetry(_TestBase):
    """Cancel a running experiment, then retry it (cancelled is retryable)."""

    def test_cancel_then_retry(self, client):
        with session_scope() as session:
            session.add(
                _make_experiment(
                    "cancel_retry_exp",
                    status="running",
                    seed=5,
                )
            )
            session.commit()

        # Cancel: revoke is mocked away; GPU release path skipped (no gpu allocated).
        with patch("orchestrator.celery_app.celery_app") as fake_celery:
            fake_celery.control.revoke.return_value = None
            cancel = client.post("/experiments/cancel_retry_exp/cancel")
        assert cancel.status_code == 200, cancel.text
        cancel_body = cancel.json()
        assert cancel_body.get("cancelled") is True, cancel_body

        with session_scope() as session:
            exp = (
                session.query(ExperimentModel)
                .filter(ExperimentModel.exp_id == "cancel_retry_exp")
                .first()
            )
            assert exp.status == "cancelled"

        # Retry: resubmit with seed+1. Mock the job-manager submission boundary.
        fake_jm = SimpleNamespace(
            submit=lambda **_kwargs: "retry-job-1",
            get_task_id=lambda _job_id: "retry-task-1",
        )
        with (
            patch("api.deps.get_job_manager", return_value=fake_jm),
            patch("config.dashboard_settings.load_dashboard_settings", return_value={}),
        ):
            retry = client.post("/experiments/cancel_retry_exp/retry")
        assert retry.status_code == 200, retry.text
        retry_body = retry.json()
        assert retry_body["status"] == "queued", retry_body
        assert retry_body["job_id"] == "retry-job-1"

        with session_scope() as session:
            exp = (
                session.query(ExperimentModel)
                .filter(ExperimentModel.exp_id == "cancel_retry_exp")
                .first()
            )
            assert exp.status == "queued"
            assert exp.seed == 6  # seed incremented on retry

    def test_retry_active_experiment_rejected(self, client):
        with session_scope() as session:
            session.add(_make_experiment("active_exp", status="running", seed=1))
            session.commit()

        fake_jm = SimpleNamespace(
            submit=lambda **_kwargs: "x",
            get_task_id=lambda _job_id: "y",
        )
        with (
            patch("api.deps.get_job_manager", return_value=fake_jm),
            patch("config.dashboard_settings.load_dashboard_settings", return_value={}),
        ):
            resp = client.post("/experiments/active_exp/retry")
        assert resp.status_code >= 400, resp.text


# ---------------------------------------------------------------------------
# Scenario 7: timeout / stale process row cleanup
# ---------------------------------------------------------------------------


class TestStaleProcessCleanup(_TestBase):
    """``POST /recovery/cleanup`` removes stale ProcessInfo rows whose process
    is no longer running (heartbeat older than 2x timeout window).
    """

    def test_cleanup_removes_stale_terminated_record(self, client, recovery_components):
        # heartbeat_timeout_minutes default = 30 -> cleanup window is 60 min.
        stale_ts = datetime.utcnow() - timedelta(minutes=240)
        with session_scope() as session:
            session.add(_make_experiment("stale_exp", status="running", seed=1))
            session.add(
                ProcessInfoModel(
                    exp_id="stale_exp",
                    pid=999998,  # nonexistent PID -> detect_process_state == TERMINATED
                    hostname=recovery_components.hostname,
                    working_dir="/tmp/stale_exp",
                    last_heartbeat=stale_ts,
                    started_at=stale_ts,
                )
            )
            session.commit()

        resp = client.post("/recovery/cleanup")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["cleaned"] >= 1, body

        with session_scope() as session:
            remaining = (
                session.query(ProcessInfoModel)
                .filter(ProcessInfoModel.exp_id == "stale_exp")
                .first()
            )
            assert remaining is None, "stale terminated process row should be deleted"

    def test_cleanup_keeps_fresh_record(self, client, recovery_components):
        with session_scope() as session:
            session.add(_make_experiment("fresh_exp", status="running", seed=1))
            session.add(
                ProcessInfoModel(
                    exp_id="fresh_exp",
                    pid=999997,
                    hostname=recovery_components.hostname,
                    working_dir="/tmp/fresh_exp",
                    last_heartbeat=datetime.utcnow(),
                    started_at=datetime.utcnow(),
                )
            )
            session.commit()

        resp = client.post("/recovery/cleanup")
        assert resp.status_code == 200, resp.text

        with session_scope() as session:
            remaining = (
                session.query(ProcessInfoModel)
                .filter(ProcessInfoModel.exp_id == "fresh_exp")
                .first()
            )
            assert remaining is not None, "fresh process row must not be cleaned up"


# ---------------------------------------------------------------------------
# Scenario 8: scan-database import duplicate handling
# ---------------------------------------------------------------------------


class TestScanImportDuplicate(_TestBase):
    """A second ``/scan-database/import`` of an already-imported exp_id is
    reported as ``skipped`` (Already in database), not double-inserted.
    """

    def _fake_scanned(self, exp_id: str):
        """Minimal ScannedExperiment-like object for import path."""
        from features.scan_database.scanner import ScannedExperiment

        return ScannedExperiment(
            exp_id=exp_id,
            directory=f"/data/{exp_id}",
            has_in_lammps=True,
            has_log_lammps=True,
            has_data_lammps=True,
            tier="screening",
            ff_type="bulk_ff_gaff2",
            temperature_k=298.0,
            total_atoms=1000,
            protocol_hash_found="abc",
            protocol_hash_current="abc",
            compatibility="compatible",
            compatibility_reason="ok",
            lammps_completed=False,
            already_in_db=False,
            seed=1,
            box_dims=[10.0, 10.0, 10.0],
            study_type="bulk",
            additive_mol_id=None,
        )

    def test_second_import_is_skipped(self, client):
        exp_id = "scan_dup_exp"
        scanned = self._fake_scanned(exp_id)

        # Patch the filesystem scan so import() resolves our synthetic exp.
        with patch(
            "features.scan_database.service.scan_experiment_directories",
            return_value=[scanned],
        ):
            resp1 = client.post(
                "/scan-database/import",
                json={"exp_ids": [exp_id], "force_import": False},
            )
            assert resp1.status_code == 200, resp1.text
            body1 = resp1.json()
            assert body1["imported"] == 1, body1

            # Second import of the same exp_id must be skipped (idempotent).
            resp2 = client.post(
                "/scan-database/import",
                json={"exp_ids": [exp_id], "force_import": False},
            )
            assert resp2.status_code == 200, resp2.text
            body2 = resp2.json()
            assert body2["imported"] == 0, body2
            statuses = {r["status"] for r in body2["results"]}
            assert "skipped" in statuses, body2

        # DB must contain exactly one row for the exp_id.
        with session_scope() as session:
            rows = session.query(ExperimentModel).filter(ExperimentModel.exp_id == exp_id).all()
            assert len(rows) == 1, "duplicate import must not create a second DB row"
