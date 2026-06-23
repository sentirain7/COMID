"""역설계 파이프라인 REST API 테스트 (P3, LAMMPS 불필요 dry-run)."""

from contextlib import asynccontextmanager

import pytest

TestClient = pytest.importorskip(
    "fastapi.testclient",
    reason="FastAPI not installed",
).TestClient

from api.application import app  # noqa: E402
from database.connection import close_db, session_scope  # noqa: E402
from database.models import ExperimentModel, MetricModel  # noqa: E402
from features.inverse_design_pipeline import execution  # noqa: E402

_PLAN_BODY = {
    "custom_targets": [{"metric_name": "density", "target_min": 0.95, "direction": "maximize"}]
}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("ASPHALT_PROJECT_ROOT", str(tmp_path))
    db_path = tmp_path / "test_inverse_pipeline_api.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    close_db()

    # 후보 조합은 binder YAML SSOT(sara_fractions)를 읽는다 — 격리 워크스페이스에
    # 가벼운 yaml 카탈로그만 시드(분자 .mol 파일은 plan dry-run에 불필요).
    import shutil
    from pathlib import Path

    import api.deps as api_deps

    repo_molecules = Path(__file__).resolve().parents[2] / "data" / "molecules"
    seeded = tmp_path / "data" / "molecules"
    seeded.mkdir(parents=True, exist_ok=True)
    for name in ("asphalt_binder.yaml", "single_moles.yaml", "additives.yaml"):
        src = repo_molecules / name
        if src.exists():
            shutil.copy2(src, seeded / name)
    api_deps.get_aging_config.cache_clear()

    @asynccontextmanager
    async def _lifespan(_app):
        yield

    app.router.lifespan_context = _lifespan
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    close_db()
    api_deps.get_aging_config.cache_clear()


class TestPlanEndpoint:
    def test_plan_returns_bootstrap_dry_run(self, client):
        """champion 부재 + 라벨 0 → BOOTSTRAP 계획 (제출 없음)."""
        resp = client.post("/inverse-design/plan", json=_PLAN_BODY)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["plan_hash"]
        plan = body["plan"]
        assert plan["mode"] == "bootstrap"
        assert len(plan["candidates"]) >= 1
        assert all(e["kind"] == "binder_cell" for e in plan["experiments"])
        # dry-run: 어떤 실험도 생성되지 않음
        with session_scope() as s:
            assert s.query(ExperimentModel).count() == 0

    def test_plan_requires_custom_targets(self, client):
        resp = client.post("/inverse-design/plan", json={"custom_targets": []})
        assert resp.status_code == 422  # pydantic min_length=1

    def test_plan_rejects_unknown_metric(self, client):
        resp = client.post(
            "/inverse-design/plan",
            json={"custom_targets": [{"metric_name": "no_such_metric"}]},
        )
        assert resp.status_code == 400

    def test_plan_mechanical_requires_aggregate_specs(self, client):
        resp = client.post(
            "/inverse-design/plan",
            json={"custom_targets": [{"metric_name": "work_of_separation"}]},
        )
        assert resp.status_code == 400
        assert "aggregate_specs" in resp.text

    def test_plan_moisture_flag_round_trip(self, client):
        resp = client.post(
            "/inverse-design/plan",
            json={
                **_PLAN_BODY,
                "moisture_damage": True,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["plan"]["moisture_damage"]["enabled"] is True


class TestApproveEndpoint:
    def test_approve_runs_plan(self, client, monkeypatch):
        plan_resp = client.post("/inverse-design/plan", json=_PLAN_BODY).json()

        def fake_binder(entry, candidate, pipeline_block, plan_hash):
            return f"real-{entry['plan_exp_id']}", "job-1"

        monkeypatch.setattr(execution, "_submit_binder_cell", fake_binder)
        resp = client.post(
            "/inverse-design/plan/approve",
            json={"plan": plan_resp["plan"], "plan_hash": plan_resp["plan_hash"]},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["pipeline_id"].startswith("pl-")
        assert body["counts"]["submitted"] == len(plan_resp["plan"]["candidates"])
        assert all(m["action"] == "submitted" for m in body["members"])

    def test_approve_rejects_tampered_plan(self, client):
        plan_resp = client.post("/inverse-design/plan", json=_PLAN_BODY).json()
        tampered = dict(plan_resp["plan"])
        tampered["mode"] = "bo"
        resp = client.post(
            "/inverse-design/plan/approve",
            json={"plan": tampered, "plan_hash": plan_resp["plan_hash"]},
        )
        assert resp.status_code == 400
        assert "plan_hash mismatch" in resp.text


class TestProgressAndResults:
    def _seed_member(
        self,
        pipeline_id,
        exp_id,
        *,
        status="completed",
        candidate_index=0,
        targets=None,
        metrics=None,
    ):
        with session_scope() as s:
            exp = ExperimentModel(
                exp_id=exp_id,
                run_tier="screening",
                ff_type="bulk_ff_gaff2",
                status=status,
                comp_asphaltene_wt=15.0,
                comp_resin_wt=30.0,
                comp_aromatic_wt=35.0,
                comp_saturate_wt=20.0,
                temperature_K=293.0,
                metadata_json={
                    "pipeline": {
                        "id": pipeline_id,
                        "plan_exp_id": f"plan-{exp_id}",
                        "kind": "binder_cell",
                        "candidate_index": candidate_index,
                        "targets": targets or [],
                    }
                },
            )
            s.add(exp)
            s.flush()
            for name, value in (metrics or {}).items():
                s.add(
                    MetricModel(
                        experiment_id=exp.id,
                        exp_id=exp_id,
                        metric_name=name,
                        namespace="bulk_ff",
                        value=value,
                        unit="g/cm3",
                    )
                )
            s.commit()

    def test_progress_counts(self, client):
        pid = "pl-api-prog"
        self._seed_member(pid, "e1", status="completed")
        self._seed_member(pid, "e2", status="running", candidate_index=1)

        resp = client.get(f"/inverse-design/{pid}/progress")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 2
        assert body["completed"] == 1
        assert body["status_counts"] == {"completed": 1, "running": 1}

    def test_progress_empty_pipeline(self, client):
        resp = client.get("/inverse-design/pl-none/progress")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_results_target_satisfaction(self, client):
        pid = "pl-api-res"
        targets = [
            {
                "metric_name": "density",
                "target_min": 1.0,
                "target_max": None,
                "direction": "maximize",
                "weight": 1.0,
            }
        ]
        self._seed_member(
            pid, "good", candidate_index=0, targets=targets, metrics={"density": 1.05}
        )
        self._seed_member(pid, "bad", candidate_index=1, targets=targets, metrics={"density": 0.90})

        resp = client.get(f"/inverse-design/{pid}/results")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["completed_experiments"] == 2
        by_ci = {c["candidate_index"]: c for c in body["candidates"]}
        assert by_ci[0]["targets_satisfied"] is True
        assert by_ci[0]["per_target"]["density"]["value"] == 1.05
        assert by_ci[1]["targets_satisfied"] is False

    def test_results_pending_metrics_unknown(self, client):
        pid = "pl-api-pend"
        targets = [
            {
                "metric_name": "density",
                "target_min": 1.0,
                "target_max": None,
                "direction": "maximize",
                "weight": 1.0,
            }
        ]
        self._seed_member(pid, "pend", status="running", targets=targets)

        body = client.get(f"/inverse-design/{pid}/results").json()
        assert body["completed_experiments"] == 0
        assert body["candidates"][0]["targets_satisfied"] is None


class TestLoopStep:
    def test_loop_step_disabled_by_default(self, client):
        """닫힌 루프는 정책 기본 OFF — 명시 활성화 전 호출은 400 (R8)."""
        plan_resp = client.post("/inverse-design/plan", json=_PLAN_BODY).json()
        resp = client.post(
            "/inverse-design/loop/step",
            json={
                "pipeline_id": f"pl-{plan_resp['plan_hash']}-xxxx",
                "plan": plan_resp["plan"],
                "plan_hash": plan_resp["plan_hash"],
            },
        )
        assert resp.status_code == 400
        assert "disabled" in resp.text
