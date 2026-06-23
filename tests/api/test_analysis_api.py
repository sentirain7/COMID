"""API tests for binder-cell analysis summaries."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest

TestClient = pytest.importorskip(
    "fastapi.testclient",
    reason="FastAPI not installed",
).TestClient

from api.application import app  # noqa: E402
from database.connection import close_db, session_scope  # noqa: E402
from database.models import ExperimentModel, MetricModel  # noqa: E402


class TestAnalysisAPI:
    @pytest.fixture
    def client(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ASPHALT_PROJECT_ROOT", str(tmp_path))
        db_path = tmp_path / "test_analysis_api.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        close_db()

        @asynccontextmanager
        async def _lifespan(_app):
            yield

        app.router.lifespan_context = _lifespan
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
        close_db()

    def _seed_experiments(self):
        with session_scope() as session:
            session.add_all(
                [
                    ExperimentModel(
                        exp_id="A1_X1_NA_none_298K_abc001",
                        run_tier="screening",
                        ff_type="bulk_ff_gaff2",
                        status="completed",
                        comp_asphaltene_wt=20.0,
                        comp_resin_wt=30.0,
                        comp_aromatic_wt=35.0,
                        comp_saturate_wt=15.0,
                        temperature_K=298.0,
                        pressure_atm=1.0,
                        box_lx=40.0,
                        box_ly=42.0,
                        box_lz=25.0,
                        metadata_json={
                            "binder_type": "AAA1",
                            "structure_size": "X1",
                            "aging_state": "non_aging",
                        },
                        created_at=datetime.now(UTC),
                    ),
                    ExperimentModel(
                        exp_id="A1_X2_NA_SBS_298K_abc002",
                        run_tier="screening",
                        ff_type="bulk_ff_gaff2",
                        status="completed",
                        comp_asphaltene_wt=20.0,
                        comp_resin_wt=30.0,
                        comp_aromatic_wt=35.0,
                        comp_saturate_wt=15.0,
                        additive_type="SBS",
                        additive_mol_id="SBS",
                        temperature_K=298.0,
                        pressure_atm=1.0,
                        box_lx=44.0,
                        box_ly=46.0,
                        box_lz=25.0,
                        metadata_json={
                            "binder_type": "AAA1",
                            "structure_size": "X2",
                            "aging_state": "non_aging",
                        },
                        created_at=datetime.now(UTC),
                    ),
                    ExperimentModel(
                        exp_id="K1_X1_SA_none_298K_abc003",
                        run_tier="confirm",
                        ff_type="bulk_ff_gaff2",
                        status="completed",
                        comp_asphaltene_wt=22.0,
                        comp_resin_wt=28.0,
                        comp_aromatic_wt=35.0,
                        comp_saturate_wt=15.0,
                        temperature_K=298.0,
                        pressure_atm=1.0,
                        box_lx=50.0,
                        box_ly=48.0,
                        box_lz=25.0,
                        metadata_json={
                            "binder_type": "AAK1",
                            "structure_size": "X1",
                            "aging_state": "short_aging",
                        },
                        created_at=datetime.now(UTC),
                    ),
                ]
            )
            session.add_all(
                [
                    MetricModel(
                        exp_id="A1_X1_NA_none_298K_abc001",
                        metric_name="density",
                        namespace="bulk_ff_gaff2",
                        value=1.01,
                        unit="g/cm3",
                    ),
                    MetricModel(
                        exp_id="A1_X1_NA_none_298K_abc001",
                        metric_name="total_energy",
                        namespace="bulk_ff_gaff2",
                        value=-1000.0,
                        unit="kcal/mol",
                    ),
                    MetricModel(
                        exp_id="A1_X1_NA_none_298K_abc001",
                        metric_name="potential_energy",
                        namespace="bulk_ff_gaff2",
                        value=-1200.0,
                        unit="kcal/mol",
                    ),
                    MetricModel(
                        exp_id="A1_X1_NA_none_298K_abc001",
                        metric_name="kinetic_energy",
                        namespace="bulk_ff_gaff2",
                        value=200.0,
                        unit="kcal/mol",
                    ),
                    MetricModel(
                        exp_id="A1_X2_NA_SBS_298K_abc002",
                        metric_name="density",
                        namespace="bulk_ff_gaff2",
                        value=1.03,
                        unit="g/cm3",
                    ),
                    MetricModel(
                        exp_id="A1_X2_NA_SBS_298K_abc002",
                        metric_name="total_energy",
                        namespace="bulk_ff_gaff2",
                        value=-980.0,
                        unit="kcal/mol",
                    ),
                    MetricModel(
                        exp_id="A1_X2_NA_SBS_298K_abc002",
                        metric_name="potential_energy",
                        namespace="bulk_ff_gaff2",
                        value=-1180.0,
                        unit="kcal/mol",
                    ),
                    MetricModel(
                        exp_id="A1_X2_NA_SBS_298K_abc002",
                        metric_name="kinetic_energy",
                        namespace="bulk_ff_gaff2",
                        value=200.0,
                        unit="kcal/mol",
                    ),
                    MetricModel(
                        exp_id="K1_X1_SA_none_298K_abc003",
                        metric_name="density",
                        namespace="bulk_ff_gaff2",
                        value=0.99,
                        unit="g/cm3",
                    ),
                    MetricModel(
                        exp_id="K1_X1_SA_none_298K_abc003",
                        metric_name="total_energy",
                        namespace="bulk_ff_gaff2",
                        value=-960.0,
                        unit="kcal/mol",
                    ),
                    MetricModel(
                        exp_id="K1_X1_SA_none_298K_abc003",
                        metric_name="potential_energy",
                        namespace="bulk_ff_gaff2",
                        value=-1160.0,
                        unit="kcal/mol",
                    ),
                    MetricModel(
                        exp_id="K1_X1_SA_none_298K_abc003",
                        metric_name="kinetic_energy",
                        namespace="bulk_ff_gaff2",
                        value=200.0,
                        unit="kcal/mol",
                    ),
                ]
            )
            session.commit()

    def test_binder_cell_xy_summary_groups_completed_runs(self, client):
        self._seed_experiments()

        resp = client.get("/analysis/binder-cells/xy-summary?group_by=binder&ff_type=bulk_ff_gaff2")
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["group_by"] == "binder"
        assert body["total_samples"] == 3
        assert body["overview"]["sample_count"] == 3
        assert body["overview"]["avg_density"] == pytest.approx((1.01 + 1.03 + 0.99) / 3)

        items = {item["group_label"]: item for item in body["items"]}
        assert items["A1"]["sample_count"] == 2
        assert items["A1"]["avg_lx"] == pytest.approx(42.0)
        assert items["A1"]["avg_ly"] == pytest.approx(44.0)
        assert items["K1"]["sample_count"] == 1
        assert items["K1"]["avg_xy"] == pytest.approx(49.0)

    def test_binder_cell_xy_summary_rejects_invalid_group(self, client):
        resp = client.get("/analysis/binder-cells/xy-summary?group_by=invalid")
        assert resp.status_code == 422
