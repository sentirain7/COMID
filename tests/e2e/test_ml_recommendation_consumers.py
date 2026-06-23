"""E2E Level 6 — ML / Recommendation consumption verification.

Reference: ``docs/WORKFLOW_VERIFICATION_PLAN.md`` §6 (Level 6).

Goal:
    Verify that *completed* experiments are actually consumed by the
    downstream ML / recommendation surfaces, end to end, through
    the real HTTP routes and the real DB-backed services:

      - ``POST /ml/models/retrain``       → loads a real training dataset,
                                            trains, registers + promotes a
                                            champion.
      - ``GET  /ml/models/champion``      → champion lineage is updated.
      - ``GET  /ml/models/history``       → version history is updated.
      - ``GET  /ml/diagnostics/parity``   → non-empty parity points.
      - ``GET  /ml/diagnostics/residuals``→ non-empty residuals.
      - ``GET  /ml/diagnostics/data-coverage`` → coverage is computed.
      - ``POST /recommendations/suggest`` → driven by the champion that was
                                            trained from completed experiments.
      - ``POST /recommendations/inverse/run`` → champion-compatible custom
                                            targets optimise without error.

Design / mock boundaries:
    * The retrain runs for real — it loads the seeded completed experiments
      via the production ``data_loader`` / ``dataset_router`` DB query and
      trains a real (lightweight) multi-target model on the density + CED
      labels.  This keeps the *consumption* path (DB → dataset → model →
      champion → diagnostics) fully exercised.
    * No real LLM is invoked.
    * No GPU / Celery submission happens.

Isolation:
    Each test uses an isolated in-memory SQLite DB *and* an isolated
    ``ASPHALT_PROJECT_ROOT`` tmp dir so the model registry artifacts and the
    DB path never touch the developer's working tree.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest

TestClient = pytest.importorskip(
    "fastapi.testclient",
    reason="FastAPI not installed",
).TestClient


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------

# Number of completed bulk experiments to seed.  Needs to comfortably survive
# the retrainer holdout split (train/val/test) so the test split is non-empty
# and parity/residual diagnostics have points to report.  ``force=True`` on the
# retrain request bypasses the ``min_training_samples`` (=100) policy gate, so
# this can stay small enough to keep the real training step fast.
_N_EXPERIMENTS = 44

# Targets we seed metrics for.  Both are bulk V1-trainable and downstream
# consumers (suggest, custom inverse design) only require these two.
_SEED_TARGETS = ("density", "cohesive_energy_density")


def _seed_completed_experiments(session) -> list[str]:
    """Seed completed bulk experiments with density + CED metrics.

    The ``MetricModel.experiment`` relationship joins on the integer
    ``experiment_id`` FK (``exp_id`` is only a denormalised convenience
    column), so the metric rows MUST be linked via ``experiment_id=exp.id`` or
    the data loader will see metric-less experiments and skip them.
    """
    from database.models import ExperimentModel, MetricModel

    exp_ids: list[str] = []
    for i in range(_N_EXPERIMENTS):
        asphaltene = 10.0 + (i % 15)
        aromatic = 40.0 - (i % 8)
        exp = ExperimentModel(
            exp_id=f"e2e_l6_exp_{i:03d}",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            study_type="bulk",
            status="completed",
            comp_asphaltene_wt=asphaltene,
            comp_resin_wt=30.0,
            comp_aromatic_wt=aromatic,
            comp_saturate_wt=20.0,
            composition_error_l1=0.0,
            target_atoms=100000,
            actual_atoms=99000,
            seed=1000 + i,
            topology_hash=f"topo_{i:04d}",
            protocol_hash=f"prot_{i:04d}",
            temperature_K=298.0 + (i % 3),
            pressure_atm=1.0,
            created_at=datetime.now(UTC),
        )
        session.add(exp)
        session.flush()  # populate exp.id for the FK link

        density = 1.0 + 0.001 * asphaltene + 0.0003 * (i % 7)
        ced = 300.0 + 2.0 * asphaltene + (i % 5)
        session.add(
            MetricModel(
                experiment_id=exp.id,
                exp_id=exp.exp_id,
                metric_name="density",
                namespace="bulk_ff_gaff2",
                value=density,
                unit="g/cm3",
                created_at=datetime.now(UTC),
            )
        )
        session.add(
            MetricModel(
                experiment_id=exp.id,
                exp_id=exp.exp_id,
                metric_name="cohesive_energy_density",
                namespace="bulk_ff_gaff2",
                value=ced,
                unit="MJ/m3",
                created_at=datetime.now(UTC),
            )
        )
        exp_ids.append(exp.exp_id)

    session.commit()
    return exp_ids


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def isolated_root(tmp_path, monkeypatch) -> Generator[str, None, None]:
    """Isolate DB path + model registry artifacts under a tmp project root.

    ``common.pathing.get_project_root`` and the DB path resolver both honour
    ``ASPHALT_PROJECT_ROOT``; the model registry writes artifacts to
    ``{root}/models/registry``.  Pointing it at a tmp dir keeps the working
    tree clean.
    """
    monkeypatch.setenv("ASPHALT_PROJECT_ROOT", str(tmp_path))
    yield str(tmp_path)


@pytest.fixture()
def seeded_client(isolated_root) -> Generator[TestClient, None, None]:
    """In-memory DB seeded with completed experiments + a TestClient.

    ``init_memory_db`` installs the in-memory engine as the process-global
    session factory, so every ``run_in_session`` / ``session_scope`` call made
    by the API services hits the same seeded DB.  We tear it down afterwards to
    avoid leaking the global engine into other test modules.
    """
    from database.connection import close_db, init_memory_db

    session = init_memory_db()
    try:
        _seed_completed_experiments(session)

        from api.application import app

        @asynccontextmanager
        async def _noop_lifespan(_app):
            yield

        app.router.lifespan_context = _noop_lifespan
        client = TestClient(app, raise_server_exceptions=False)
        yield client
    finally:
        session.close()
        close_db()


@pytest.fixture()
def trained_champion(seeded_client) -> TestClient:
    """Run a real retrain so a champion (trained from completed exps) exists."""
    resp = seeded_client.post(
        "/ml/models/retrain", json={"force": True, "triggered_by": "e2e_level6"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # First successful model auto-promotes to champion (no prior champion).
    assert body["promoted"] is True, body
    assert body["version_id"], body
    return seeded_client


# ---------------------------------------------------------------------------
# ML retrain / champion / history
# ---------------------------------------------------------------------------


def test_retrain_loads_completed_dataset_and_promotes_champion(seeded_client):
    """Retrain consumes completed experiments → trains → promotes a champion."""
    resp = seeded_client.post(
        "/ml/models/retrain", json={"force": True, "triggered_by": "e2e_level6"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["success"] is True
    assert body["version_id"]
    # The seeded completed experiments were actually loaded as training data.
    assert body["training_samples"] == _N_EXPERIMENTS
    assert body["promoted"] is True

    # Champion lineage reflects the freshly trained model.
    champ = seeded_client.get("/ml/models/champion")
    assert champ.status_code == 200, champ.text
    champ_body = champ.json()
    assert champ_body["version_id"] == body["version_id"]
    assert champ_body["status"] == "champion"
    # Targets are exactly the labels we seeded.
    assert set(champ_body["target_names"]) == set(_SEED_TARGETS)
    assert champ_body["training_samples"] == _N_EXPERIMENTS


def test_model_history_updated_after_retrain(trained_champion):
    """History endpoint reflects the registered model version."""
    resp = trained_champion.get("/ml/models/history")
    assert resp.status_code == 200, resp.text
    models = resp.json()["models"]
    assert len(models) >= 1
    assert any(m["status"] == "champion" for m in models)


def test_retrain_without_enough_data_does_not_promote(isolated_root):
    """Without enough samples and no force, retrain reports no trigger.

    Asserts the negative contract: an under-populated DB must not silently
    fabricate a champion.
    """
    from database.connection import close_db, init_memory_db
    from database.models import ExperimentModel, MetricModel

    session = init_memory_db()
    try:
        # Seed only a couple of completed experiments — below the policy gate.
        for i in range(3):
            exp = ExperimentModel(
                exp_id=f"thin_{i}",
                run_tier="screening",
                ff_type="bulk_ff_gaff2",
                study_type="bulk",
                status="completed",
                comp_asphaltene_wt=20.0,
                comp_resin_wt=30.0,
                comp_aromatic_wt=35.0,
                comp_saturate_wt=15.0,
                composition_error_l1=0.0,
                target_atoms=100000,
                actual_atoms=99000,
                seed=i,
                topology_hash=f"t{i}",
                protocol_hash=f"p{i}",
                temperature_K=298.0,
                pressure_atm=1.0,
                created_at=datetime.now(UTC),
            )
            session.add(exp)
            session.flush()
            session.add(
                MetricModel(
                    experiment_id=exp.id,
                    exp_id=exp.exp_id,
                    metric_name="density",
                    namespace="bulk_ff_gaff2",
                    value=1.02,
                    unit="g/cm3",
                    created_at=datetime.now(UTC),
                )
            )
        session.commit()

        from api.application import app

        @asynccontextmanager
        async def _noop_lifespan(_app):
            yield

        app.router.lifespan_context = _noop_lifespan
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post("/ml/models/retrain", json={"force": False})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["promoted"] is False
        assert body["version_id"] is None
        assert body["trigger_reason"] == "insufficient_total_samples"

        # No champion should have been created.
        champ = client.get("/ml/models/champion")
        assert champ.status_code != 200
    finally:
        session.close()
        close_db()


# ---------------------------------------------------------------------------
# ML diagnostics — parity / residual / coverage must be non-empty
# ---------------------------------------------------------------------------


def test_parity_diagnostics_non_empty(trained_champion):
    """Parity plot reconstructs test-set predictions from the snapshot."""
    resp = trained_champion.get("/ml/diagnostics/parity", params={"target": "density"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["target"] == "density"
    assert len(body["points"]) > 0
    # Metrics block (rmse/r2/...) is populated.
    assert body["metrics"]
    point = body["points"][0]
    assert "predicted" in point and "actual" in point


def test_residual_diagnostics_non_empty(trained_champion):
    """Residual distribution is reconstructed and non-empty."""
    resp = trained_champion.get("/ml/diagnostics/residuals", params={"target": "density"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["target"] == "density"
    assert len(body["residuals"]) > 0
    assert body["stats"]


def test_data_coverage_diagnostics_reflects_completed_experiments(trained_champion):
    """Data-coverage diagnostics are computed from the seeded experiments."""
    resp = trained_champion.get("/ml/diagnostics/data-coverage")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # The response must carry concrete coverage content, not an empty stub.
    assert isinstance(body, dict)
    assert body  # non-empty payload


# ---------------------------------------------------------------------------
# Recommendation consumers
# ---------------------------------------------------------------------------


def test_suggest_recommendations_uses_champion(trained_champion):
    """Active-learning suggest is driven by the champion trained from data."""
    resp = trained_champion.post("/recommendations/suggest", params={"n_candidates": 5})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["batch_id"]
    assert body["n_recommendations"] == len(body["recommendations"])
    assert body["n_recommendations"] >= 1
    # Each recommendation carries champion-predicted properties.
    first = body["recommendations"][0]
    assert "composition" in first
    assert "predicted_properties" in first


def test_suggest_recommendations_requires_champion(seeded_client):
    """Without a champion, suggest fails closed (no heuristic fabrication)."""
    resp = seeded_client.post("/recommendations/suggest", params={"n_candidates": 5})
    # SERVICE_UNAVAILABLE — no champion predictor is loadable.
    assert resp.status_code in (404, 409, 422, 503), resp.text


def test_inverse_design_run_with_champion_compatible_targets(trained_champion):
    """Inverse design optimises over champion-supported custom targets."""
    resp = trained_champion.post(
        "/recommendations/inverse/run",
        json={
            "custom_targets": [
                {
                    "metric_name": "density",
                    "direction": "target",
                    "target_min": 1.0,
                    "target_max": 1.05,
                },
                {"metric_name": "cohesive_energy_density", "direction": "maximize"},
            ],
            "max_iterations": 3,
            "n_results": 2,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["n_iterations"] > 0
    assert len(body["results"]) <= 2
    assert "hypervolume_history" in body


