"""API tests for job dependency management endpoints."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest

TestClient = pytest.importorskip(
    "fastapi.testclient",
    reason="FastAPI not installed",
).TestClient

from api.application import app  # noqa: E402
from database.connection import close_db, session_scope  # noqa: E402
from database.models import ExperimentModel, JobDependencyModel  # noqa: E402


class _FakeDelayResult:
    id = "task-dep-001"


class TestJobDependenciesAPI:
    @pytest.fixture
    def client(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ASPHALT_PROJECT_ROOT", str(tmp_path))
        db_path = tmp_path / "test_job_dep_api.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        close_db()

        @asynccontextmanager
        async def _lifespan(_app):
            yield

        app.router.lifespan_context = _lifespan
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
        close_db()

    def _seed(self):
        with session_scope() as session:
            if (
                session.query(ExperimentModel)
                .filter(ExperimentModel.exp_id == "parent_exp")
                .first()
                is None
            ):
                session.add(
                    ExperimentModel(
                        exp_id="parent_exp",
                        run_tier="screening",
                        ff_type="bulk_ff_gaff2",
                        status="completed",
                        comp_asphaltene_wt=20.0,
                        comp_resin_wt=30.0,
                        comp_aromatic_wt=35.0,
                        comp_saturate_wt=15.0,
                        target_atoms=1000,
                        temperature_K=298.0,
                        pressure_atm=1.0,
                        seed=1,
                        created_at=datetime.now(UTC),
                    )
                )
            if (
                session.query(ExperimentModel).filter(ExperimentModel.exp_id == "child_exp").first()
                is None
            ):
                session.add(
                    ExperimentModel(
                        exp_id="child_exp",
                        run_tier="screening",
                        ff_type="bulk_ff_gaff2",
                        status="pending",
                        comp_asphaltene_wt=20.0,
                        comp_resin_wt=30.0,
                        comp_aromatic_wt=35.0,
                        comp_saturate_wt=15.0,
                        target_atoms=1000,
                        temperature_K=298.0,
                        pressure_atm=1.0,
                        seed=2,
                        created_at=datetime.now(UTC),
                    )
                )
            if (
                session.query(JobDependencyModel)
                .filter(JobDependencyModel.parent_exp_id == "parent_exp")
                .filter(JobDependencyModel.child_exp_id == "child_exp")
                .first()
                is None
            ):
                session.add(
                    JobDependencyModel(
                        parent_exp_id="parent_exp",
                        child_exp_id="child_exp",
                        status="blocked",
                    )
                )
            session.commit()

    def test_list_job_dependencies(self, client):
        self._seed()
        resp = client.get("/queue/dependencies?status=blocked&limit=10")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["count"] == 1
        assert body["items"][0]["parent_exp_id"] == "parent_exp"
        assert body["items"][0]["child_exp_id"] == "child_exp"

    def test_trigger_dependency_reconcile(self, client, monkeypatch):
        self._seed()
        monkeypatch.setattr(
            "orchestrator.tasks.reconcile_dependency_chains.delay",
            lambda **_kwargs: _FakeDelayResult(),
        )
        resp = client.post("/queue/dependencies/reconcile?max_submissions=3")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "queued"
        assert body["task_id"] == "task-dep-001"

    def test_create_job_dependency(self, client):
        self._seed()
        resp = client.post(
            "/queue/dependencies/link?parent_exp_id=parent_exp&child_exp_id=child_exp"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["parent_exp_id"] == "parent_exp"
        assert body["child_exp_id"] == "child_exp"
        assert body["status"] == "blocked"
