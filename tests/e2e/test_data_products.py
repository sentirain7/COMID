"""E2E Level 5: Data Product 검증 (docs/WORKFLOW_VERIFICATION_PLAN.md §6 Level 5).

완료된 실험 + 메트릭이 실제 소비 계층(metrics/analysis API)에서 조회 가능한지 검증한다.

필수 소비 경로:
- ``GET /metrics/{exp_id}``                       -> scalar metric 존재
- ``GET /metrics/temperature-scan/{exp_id}``      -> 온도 스캔(동일 조성 다른 온도) 집계
- ``GET /analysis/embedding``                     -> 신규 완료 실험 반영
- ``GET /analysis/molecule-impact``               -> SARA 영향도 집계(>=3 완료 실험)
- ``GET /analysis/binder-cells/xy-summary``       -> 박스 크기/메트릭 그룹 집계
- ``GET /analysis/scatter3d``                     -> 3축 산점도 + 잘못된 축 422
- ``GET /experiments/{exp_id}/array-metrics``     -> array metric 메타데이터 조회

검증 포인트:
- scalar metric 존재
- array metric 존재 시 조회 가능 (array_file_path 설정된 MetricModel)
- analysis 응답에 신규 데이터 반영 (시드한 exp_id가 등장)
- 잘못된 축 입력에 대한 422 처리 (존재하지 않는 metric 축)

LAMMPS / Celery / Packmol / antechamber 불필요.
완료 실험과 메트릭을 DB(SQLite)에 직접 삽입하고 소비 API만 실제 코드 경로로 검증한다.
시드/격리 패턴은 tests/api/test_analysis_api.py 및
tests/e2e/test_source_lineage_chain.py의 client fixture를 그대로 따른다.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest

TestClient = pytest.importorskip(
    "fastapi.testclient",
    reason="FastAPI not installed",
).TestClient

from api.application import app  # noqa: E402
from config.settings import reset_settings  # noqa: E402
from database.connection import close_db, session_scope  # noqa: E402
from database.models import ExperimentModel, MetricModel  # noqa: E402

NAMESPACE = "bulk_ff_gaff2"
FF_TYPE = "bulk_ff_gaff2"


def _experiment(exp_id: str, *, temp: float, lx: float, ly: float, tier: str = "screening", **kw):
    """Build a completed bulk-ff ExperimentModel (same shape as tests/api fixtures)."""
    defaults = {
        "exp_id": exp_id,
        "run_tier": tier,
        "ff_type": FF_TYPE,
        "status": "completed",
        "comp_asphaltene_wt": 20.0,
        "comp_resin_wt": 30.0,
        "comp_aromatic_wt": 35.0,
        "comp_saturate_wt": 15.0,
        "temperature_K": temp,
        "pressure_atm": 1.0,
        "box_lx": lx,
        "box_ly": ly,
        "box_lz": 25.0,
        "created_at": datetime.now(UTC),
    }
    defaults.update(kw)
    return ExperimentModel(**defaults)


def _scalar(exp_id: str, name: str, value: float, unit: str) -> MetricModel:
    return MetricModel(
        exp_id=exp_id,
        metric_name=name,
        namespace=NAMESPACE,
        value=value,
        unit=unit,
    )


def _scalar_bundle(
    exp_id: str, *, density: float, ced: float, viscosity: float
) -> list[MetricModel]:
    """Core scalar metrics needed by embedding / molecule-impact / scatter3d."""
    return [
        _scalar(exp_id, "density", density, "g/cm3"),
        _scalar(exp_id, "cohesive_energy_density", ced, "MJ/m3"),
        _scalar(exp_id, "viscosity", viscosity, "mPa.s"),
        _scalar(exp_id, "total_energy", -1000.0, "kcal/mol"),
        _scalar(exp_id, "potential_energy", -1200.0, "kcal/mol"),
        _scalar(exp_id, "kinetic_energy", 200.0, "kcal/mol"),
    ]


def _array_metric(exp_id: str) -> MetricModel:
    """An array metric row (value=None, array_file_path set) — see metric_repo.list_array_metrics."""
    return MetricModel(
        exp_id=exp_id,
        metric_name="rdf_curve",
        namespace=NAMESPACE,
        value=None,
        unit="-",
        array_file_path=f"data/array_storage/{exp_id}/rdf_curve.parquet",
        array_shape=[100, 2],
    )


class TestDataProducts:
    @pytest.fixture
    def client(self, monkeypatch, tmp_path):
        # ASPHALT_PROJECT_ROOT + per-test sqlite DB isolation (tests/api pattern).
        monkeypatch.setenv("ASPHALT_PROJECT_ROOT", str(tmp_path))
        db_path = tmp_path / "test_data_products.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        # reset_settings(): get_settings() is cached, so without this the engine
        # rebuilds against a previous test's DATABASE_URL (test_source_lineage_chain pattern).
        close_db()
        reset_settings()

        # lifespan no-op (test_source_lineage_chain pattern) — skip startup side effects.
        @asynccontextmanager
        async def _lifespan(_app):
            yield

        app.router.lifespan_context = _lifespan
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
        close_db()
        reset_settings()

    def _seed(self):
        """Seed >=3 completed bulk-ff experiments + scalar/array metrics.

        - 3개 서로 다른 조성/바인더의 완료 실험 (molecule-impact 최소 3개 요건 충족).
        - base 조성에 동일한 추가 온도 실험 1개 (temperature-scan 집계 검증용).
        - base 실험에 array metric 1개 (array-metrics 조회 검증용).
        """
        base_id = "A1_X1_NA_none_298K_dp0001"
        base_hot_id = "A1_X1_NA_none_348K_dp0002"  # same composition, different temp
        sbs_id = "A1_X2_NA_SBS_298K_dp0003"
        aak_id = "K1_X1_SA_none_298K_dp0004"

        with session_scope() as session:
            session.add_all(
                [
                    _experiment(base_id, temp=298.0, lx=40.0, ly=42.0),
                    _experiment(base_hot_id, temp=348.0, lx=41.0, ly=43.0),
                    _experiment(
                        sbs_id,
                        temp=298.0,
                        lx=44.0,
                        ly=46.0,
                        run_tier="screening",
                        additive_type="SBS",
                        additive_mol_id="SBS",
                        comp_asphaltene_wt=18.0,
                        comp_resin_wt=32.0,
                        comp_aromatic_wt=35.0,
                        comp_saturate_wt=15.0,
                    ),
                    _experiment(
                        aak_id,
                        temp=298.0,
                        lx=50.0,
                        ly=48.0,
                        run_tier="confirm",
                        comp_asphaltene_wt=22.0,
                        comp_resin_wt=28.0,
                        comp_aromatic_wt=35.0,
                        comp_saturate_wt=15.0,
                    ),
                ]
            )
            session.add_all(
                [
                    *_scalar_bundle(base_id, density=1.01, ced=300.0, viscosity=120.0),
                    *_scalar_bundle(base_hot_id, density=0.97, ced=280.0, viscosity=60.0),
                    *_scalar_bundle(sbs_id, density=1.03, ced=320.0, viscosity=150.0),
                    *_scalar_bundle(aak_id, density=0.99, ced=290.0, viscosity=110.0),
                    _array_metric(base_id),
                ]
            )
            session.commit()

        return {
            "base": base_id,
            "base_hot": base_hot_id,
            "sbs": sbs_id,
            "aak": aak_id,
        }

    # ------------------------------------------------------------------
    # scalar metric 존재
    # ------------------------------------------------------------------
    def test_get_metrics_returns_scalar_metrics(self, client):
        ids = self._seed()
        resp = client.get(f"/metrics/{ids['base']}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["exp_id"] == ids["base"]
        names = {m["metric_name"]: m for m in body["metrics"]}
        assert "density" in names
        assert names["density"]["value"] == pytest.approx(1.01)
        assert names["density"]["unit"] == "g/cm3"
        assert "cohesive_energy_density" in names

    # ------------------------------------------------------------------
    # temperature scan (동일 조성, 다른 온도)
    # ------------------------------------------------------------------
    def test_temperature_scan_collects_related_temperatures(self, client):
        ids = self._seed()
        resp = client.get(f"/metrics/temperature-scan/{ids['base']}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["exp_id"] == ids["base"]
        # base(298K) + base_hot(348K) share composition -> both present, sorted by T.
        assert 298.0 in body["temperatures"]
        assert 348.0 in body["temperatures"]
        assert body["temperatures"] == sorted(body["temperatures"])
        assert len(body["densities"]) == len(body["temperatures"])
        assert all(d is not None for d in body["densities"])

    # ------------------------------------------------------------------
    # array metric 조회 가능
    # ------------------------------------------------------------------
    def test_array_metrics_listed_when_present(self, client):
        ids = self._seed()
        resp = client.get(f"/experiments/{ids['base']}/array-metrics")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["exp_id"] == ids["base"]
        names = {m["metric_name"]: m for m in body["array_metrics"]}
        assert "rdf_curve" in names
        assert names["rdf_curve"]["array_file_path"].endswith("rdf_curve.parquet")
        assert names["rdf_curve"]["array_shape"] == [100, 2]

    def test_array_metrics_graceful_empty_when_absent(self, client):
        ids = self._seed()
        # sbs experiment has scalar metrics only -> empty array-metric list, not error.
        resp = client.get(f"/experiments/{ids['sbs']}/array-metrics")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["exp_id"] == ids["sbs"]
        assert body["array_metrics"] == []

    # ------------------------------------------------------------------
    # analysis embedding 신규 데이터 반영
    # ------------------------------------------------------------------
    def test_analysis_embedding_reflects_seeded_experiments(self, client):
        ids = self._seed()
        resp = client.get(f"/analysis/embedding?ff_type={FF_TYPE}")
        assert resp.status_code == 200, resp.text
        points = resp.json()
        assert isinstance(points, list)
        seen = {p["exp_id"] for p in points}
        # every seeded completed experiment has density+ced -> embedding point.
        for key in ("base", "base_hot", "sbs", "aak"):
            assert ids[key] in seen
        for p in points:
            assert len(p["position"]) == 3
            assert p["density"] is not None and p["ced"] is not None

    # ------------------------------------------------------------------
    # molecule-impact 집계 (>=3 완료 실험)
    # ------------------------------------------------------------------
    def test_molecule_impact_aggregates_sara(self, client):
        self._seed()
        resp = client.get(f"/analysis/molecule-impact?ff_type={FF_TYPE}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["columns"] == ["density", "ced", "viscosity"]
        # 4 completed exps (>=3) -> aggregation produced rows + cells.
        assert "aromatic" in body["rows"]
        assert len(body["cells"]) > 0
        cell = body["cells"][0]
        assert {"mol_id", "metric", "z_score", "raw_value"} <= set(cell)

    # ------------------------------------------------------------------
    # binder-cell xy summary
    # ------------------------------------------------------------------
    def test_binder_cell_xy_summary_reflects_data(self, client):
        self._seed()
        resp = client.get(f"/analysis/binder-cells/xy-summary?group_by=binder&ff_type={FF_TYPE}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["group_by"] == "binder"
        assert body["total_samples"] == 4
        assert body["overview"]["sample_count"] == 4
        assert body["overview"]["avg_density"] is not None
        labels = {item["group_label"] for item in body["items"]}
        assert labels  # at least one grouped bucket
        for item in body["items"]:
            assert item["avg_xy"] == pytest.approx((item["avg_lx"] + item["avg_ly"]) * 0.5)

    def test_binder_cell_xy_summary_rejects_invalid_group(self, client):
        resp = client.get("/analysis/binder-cells/xy-summary?group_by=__nope__")
        assert resp.status_code == 422

    # ------------------------------------------------------------------
    # scatter3d (positive + negative axis)
    # ------------------------------------------------------------------
    def test_scatter3d_returns_points(self, client):
        ids = self._seed()
        resp = client.get(
            "/analysis/scatter3d"
            f"?axis_x=density&axis_y=cohesive_energy_density&axis_z=viscosity&ff_type={FF_TYPE}"
        )
        assert resp.status_code == 200, resp.text
        points = resp.json()
        assert isinstance(points, list)
        seen = {p["exp_id"] for p in points}
        assert ids["base"] in seen
        for p in points:
            assert len(p["position"]) == 3
            assert p["axis_x_value"] is not None

    def test_scatter3d_rejects_unknown_axis(self, client):
        self._seed()
        resp = client.get(
            "/analysis/scatter3d"
            f"?axis_x=density&axis_y=cohesive_energy_density&axis_z=not_a_metric&ff_type={FF_TYPE}"
        )
        assert resp.status_code == 422, resp.text
