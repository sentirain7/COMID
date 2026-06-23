"""API tests for deferred dependent molecule experiment submission."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

TestClient = pytest.importorskip(
    "fastapi.testclient",
    reason="FastAPI not installed",
).TestClient

from api.application import app  # noqa: E402
from database.connection import close_db, session_scope  # noqa: E402
from database.models import ExperimentModel, JobDependencyModel  # noqa: E402
from features.experiments.composition_builder import MoleculeCompositionBuildResult  # noqa: E402


class TestDependentExperimentSubmissionAPI:
    @pytest.fixture
    def client(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ASPHALT_PROJECT_ROOT", str(tmp_path))
        db_path = tmp_path / "test_dependent_submit.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        close_db()

        @asynccontextmanager
        async def _lifespan(_app):
            yield

        app.router.lifespan_context = _lifespan
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
        close_db()

    def _seed_parent(self, exp_id: str = "parent_exp_001") -> None:
        with session_scope() as session:
            if (
                session.query(ExperimentModel).filter(ExperimentModel.exp_id == exp_id).first()
                is None
            ):
                session.add(
                    ExperimentModel(
                        exp_id=exp_id,
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
            session.commit()

    def test_submit_dependent_experiment_creates_pending_child_and_blocked_edge(self, client):
        self._seed_parent()
        payload = {
            "parent_exp_id": "parent_exp_001",
            "binder_type": "AAA1",
            "structure_size": "X1",
            "aging_state": "non_aging",
            "molecule_counts": [{"mol_id": "SA-Squalane", "count": 10}],
            "temperature_K": 298.0,
            "run_tier": "screening",
            "ff_type": "bulk_ff_gaff2",
        }
        mock_db = SimpleNamespace(get_temperature_code=lambda _config, _temp: "0298")

        with (
            patch("api.deps.get_molecule_db", return_value=mock_db),
            patch("api.deps.get_aging_config", return_value={}),
            patch("config.dashboard_settings.load_dashboard_settings", return_value={}),
            patch("features.experiments.submission.generate_seed", return_value=777),
            patch(
                "orchestrator.exp_id_helper.generate_exp_id_from_material",
                return_value="child_exp_001",
            ),
            patch("features.experiments.submission.validate_molecule_request_config"),
            patch(
                "forcefield.eligibility.collect_binder_ff_issues",
                return_value={"blocked_items": [], "warning_items": [], "has_blocked": False},
            ),
            patch(
                "features.experiments.submission.build_molecule_composition",
                return_value=MoleculeCompositionBuildResult(
                    mol_composition={"SA-Squalane": 10},
                    sara_composition={
                        "saturate": 0.2,
                        "aromatic": 0.3,
                        "resin": 0.3,
                        "asphaltene": 0.2,
                    },
                    estimated_atoms=1200,
                    total_molecules=10,
                ),
            ),
        ):
            resp = client.post("/experiments/molecule-based/dependent", json=payload)

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["exp_id"] == "child_exp_001"
        assert body["job_id"] == "deferred"
        assert body["status"] == "pending"
        assert body["dependency_status"] == "blocked"
        assert body["parent_exp_id"] == "parent_exp_001"

        with session_scope() as session:
            child = (
                session.query(ExperimentModel)
                .filter(ExperimentModel.exp_id == "child_exp_001")
                .first()
            )
            assert child is not None
            assert str(child.status) == "pending"
            assert isinstance(child.metadata_json, dict)
            assert "deferred_submission" in child.metadata_json

            edge = (
                session.query(JobDependencyModel)
                .filter(JobDependencyModel.parent_exp_id == "parent_exp_001")
                .filter(JobDependencyModel.child_exp_id == "child_exp_001")
                .first()
            )
            assert edge is not None
            assert edge.status == "blocked"

    def test_submit_dependent_experiment_requires_parent(self, client):
        payload = {
            "parent_exp_id": "missing_parent",
            "binder_type": "AAA1",
            "structure_size": "X1",
            "aging_state": "non_aging",
            "molecule_counts": [{"mol_id": "SA-Squalane", "count": 10}],
            "temperature_K": 298.0,
            "run_tier": "screening",
            "ff_type": "bulk_ff_gaff2",
        }
        mock_db = SimpleNamespace(get_temperature_code=lambda _config, _temp: "0298")

        with (
            patch("api.deps.get_molecule_db", return_value=mock_db),
            patch("api.deps.get_aging_config", return_value={}),
            patch("config.dashboard_settings.load_dashboard_settings", return_value={}),
            patch("features.experiments.submission.generate_seed", return_value=777),
            patch(
                "orchestrator.exp_id_helper.generate_exp_id_from_material",
                return_value="child_exp_missing_parent",
            ),
            patch("features.experiments.submission.validate_molecule_request_config"),
            patch(
                "forcefield.eligibility.collect_binder_ff_issues",
                return_value={"blocked_items": [], "warning_items": [], "has_blocked": False},
            ),
            patch(
                "features.experiments.submission.build_molecule_composition",
                return_value=MoleculeCompositionBuildResult(
                    mol_composition={"SA-Squalane": 10},
                    sara_composition={
                        "saturate": 0.2,
                        "aromatic": 0.3,
                        "resin": 0.3,
                        "asphaltene": 0.2,
                    },
                    estimated_atoms=1200,
                    total_molecules=10,
                ),
            ),
        ):
            resp = client.post("/experiments/molecule-based/dependent", json=payload)

        assert resp.status_code == 404, resp.text
        body = resp.json()
        assert body["code"] == "E7001"
        assert "Parent experiment not found" in body["detail"]
