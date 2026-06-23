import sys
from datetime import datetime

import pytest

sys.path.insert(0, "src")

from contracts.errors import ContractError
from contracts.schema_enums import RecommendationMode, SimulationPriority
from database.connection import close_db, init_memory_db
from database.models import ExperimentModel
from features.recommendations import pending_service


@pytest.fixture
def memory_db():
    session = init_memory_db()
    yield session
    session.close()
    close_db()


def _sample_candidate():
    return {
        "candidate_id": "cand-1",
        "origin": "db",
        "additive_type": "SBS",
        "recommended_wt_pct_min": 3.0,
        "recommended_wt_pct_max": 5.0,
        "score": 0.88,
        "rationale": "high rutting resistance",
        "composition": {
            "asphaltene": 20.0,
            "resin": 30.0,
            "aromatic": 35.0,
            "saturate": 15.0,
        },
        "predicted_properties": {"density": 1.01},
    }


def test_add_and_get_pending_detail(memory_db):
    created = pending_service.add_candidates_to_pending(
        candidates=[_sample_candidate()],
        source="quick",
        session_id="sess-1",
        mode="known",
        model_version_id="model-v1",
        feature_set_version="v3",
        simulation_priority="screen",
        pg_decision={"pg_label": "PG 76-22"},
        decision_trace=[{"step": "select_pg", "queue_params": {"run_tier": "confirm"}}],
        source_records=[{"source_type": "weather", "source_name": "open-meteo"}],
        literature_refs=[{"title": "Binder paper", "doi": "10.1000/example"}],
    )
    assert len(created) == 1
    assert created[0].status == "pending"
    assert created[0].source == "quick"

    detail = pending_service.get_detail(created[0].id)
    assert detail.pg_decision["pg_label"] == "PG 76-22"
    assert detail.source_records[0]["source_name"] == "open-meteo"
    assert detail.decision_trace[0]["step"] == "select_pg"
    assert detail.literature_refs[0]["doi"] == "10.1000/example"
    assert detail.mode == RecommendationMode.KNOWN
    assert detail.model_version_id == "model-v1"
    assert detail.feature_set_version == "v3"
    assert detail.simulation_priority == SimulationPriority.SCREEN


def test_approve_pending_transitions_to_queued(memory_db, monkeypatch):
    created = pending_service.add_candidates_to_pending(
        candidates=[_sample_candidate()],
        source="pg_select",
    )[0]

    calls = {}

    def _fake_queue(**kwargs):
        calls.update(kwargs)
        return "exp-test-001"

    monkeypatch.setattr(
        "features.recommendations.active_learning._queue_active_learning_experiment",
        _fake_queue,
    )

    updated = pending_service.approve_pending(created.id, notes="ship it", expected_version=1)
    assert updated.status == "queued"
    assert updated.queued_exp_id == "exp-test-001"
    assert updated.version == 3  # pending->approved->queued
    assert calls["temperature_k"] == 298.0
    assert calls["run_tier"] == "screening"


def test_reject_pending_state_guard(memory_db):
    created = pending_service.add_candidates_to_pending(
        candidates=[_sample_candidate()],
        source="ai_advisor",
    )[0]

    rejected = pending_service.reject_pending(
        created.id, reason="manual reject", expected_version=1
    )
    assert rejected.status == "rejected"

    with pytest.raises(ContractError):
        pending_service.reject_pending(created.id, reason="again")


def test_mark_auto_approved_and_stop_execution(memory_db):
    created = pending_service.add_candidates_to_pending(
        candidates=[_sample_candidate()],
        source="post_retrain_auto",
    )[0]

    pending_service.mark_auto_approved_and_queued(
        created.id,
        exp_id="exp-auto-stop-1",
        notes="auto-approved",
    )

    memory_db.add(
        ExperimentModel(
            exp_id="exp-auto-stop-1",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            status="queued",
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
            target_atoms=1000,
            temperature_K=298.0,
            pressure_atm=1.0,
            seed=1,
            created_at=datetime.utcnow(),
        )
    )
    memory_db.commit()

    stopped = pending_service.stop_pending_execution(created.id, reason="operator stop")
    assert stopped.status == "cancelled"
    assert stopped.queued_exp_id == "exp-auto-stop-1"

    experiment = (
        memory_db.query(ExperimentModel).filter(ExperimentModel.exp_id == "exp-auto-stop-1").first()
    )
    assert experiment is not None
    assert experiment.status == "cancelled"
    assert experiment.error_message == "operator stop"


def test_approve_pending_uses_stored_queue_params(memory_db, monkeypatch):
    created = pending_service.add_candidates_to_pending(
        candidates=[_sample_candidate()],
        source="quick",
        pg_decision={"temperature_k": 313.0, "run_tier": "confirm"},
    )[0]
    seen = {}

    def _fake_queue(**kwargs):
        seen.update(kwargs)
        return "exp-test-002"

    monkeypatch.setattr(
        "features.recommendations.active_learning._queue_active_learning_experiment",
        _fake_queue,
    )
    pending_service.approve_pending(created.id, expected_version=1)
    assert seen["temperature_k"] == 313.0
    assert seen["run_tier"] == "confirm"


def test_sync_session_pending_candidates_updates_scores(memory_db):
    created = pending_service.add_candidates_to_pending(
        candidates=[_sample_candidate()],
        source="ai_advisor",
        session_id="agent-sync-1",
    )[0]
    changed = pending_service.sync_session_pending_candidates(
        session_id="agent-sync-1",
        candidates=[
            {
                "additive_type": "SBS",
                "composition": {
                    "asphaltene": 20.0,
                    "resin": 30.0,
                    "aromatic": 35.0,
                    "saturate": 15.0,
                },
                "predicted_properties": {"density": 1.03},
                "score": 0.93,
            }
        ],
    )
    assert changed == 1
    detail = pending_service.get_detail(created.id)
    assert detail.predicted_properties["density"] == pytest.approx(1.03)
    assert detail.score == pytest.approx(0.93)


def test_update_result_and_mark_fed_back(memory_db, monkeypatch):
    created = pending_service.add_candidates_to_pending(
        candidates=[_sample_candidate()],
        source="quick",
    )[0]

    updated = pending_service.update_recommendation_result(
        created.id,
        result_metrics={"density": 1.02},
        prediction_error={"density": 0.01},
    )
    assert updated.result_metrics["density"] == pytest.approx(1.02)
    assert updated.prediction_error["density"] == pytest.approx(0.01)
    assert updated.used_in_retraining is False

    def _fake_queue(**kwargs):
        return "exp-test-003"

    from database.repositories.recommendation_repo import PendingRecommendationRepository
    from features.common import run_in_session_commit

    monkeypatch.setattr(
        "features.recommendations.active_learning._queue_active_learning_experiment",
        _fake_queue,
    )

    queued = pending_service.approve_pending(created.id, expected_version=updated.version)
    completed = pending_service.update_recommendation_result(
        queued.id,
        result_metrics={"density": 1.03},
    )
    assert completed.status == "queued"

    def _mark_completed(session):
        repo = PendingRecommendationRepository(session)
        repo.transition(queued.id, to_status="running", expected_version=completed.version)
        return repo.transition(
            queued.id, to_status="completed", expected_version=completed.version + 1
        )

    run_in_session_commit(_mark_completed)
    fed_back = pending_service.mark_recommendation_fed_back(queued.id)
    assert fed_back.used_in_retraining is True
    assert fed_back.status == "fed_back"

    with pytest.raises(ContractError, match="fed_back"):
        pending_service.update_recommendation_result(
            queued.id,
            result_metrics={"density": 1.04},
        )


def test_backfill_prediction_error_handles_multiple_metrics(memory_db):
    from database.repositories.recommendation_repo import PendingRecommendationRepository
    from features.common import run_in_session_commit

    created = pending_service.add_candidates_to_pending(
        candidates=[
            {
                **_sample_candidate(),
                "predicted_properties": {
                    "density": 1.00,
                    "cohesive_energy_density": 300.0,
                },
            }
        ],
        source="quick",
    )[0]

    def _queue_and_set(session):
        repo = PendingRecommendationRepository(session)
        repo.transition(created.id, to_status="approved", queued_exp_id="exp-multi-metric")
        return repo.transition(created.id, to_status="queued", queued_exp_id="exp-multi-metric")

    run_in_session_commit(_queue_and_set)

    updated = pending_service.backfill_from_experiment(
        "exp-multi-metric",
        result_metrics={
            "density": 1.03,
            "cohesive_energy_density": 315.0,
            "viscosity": 2.0,
        },
    )

    assert updated is not None
    assert updated.status == "completed"
    assert updated.prediction_error["density"] == pytest.approx(0.03)
    assert updated.prediction_error["cohesive_energy_density"] == pytest.approx(15.0)
    assert "viscosity" not in updated.prediction_error


def test_stop_pending_execution_rejects_terminal_state(memory_db, monkeypatch):
    """stop_pending_execution() should reject already-cancelled recommendations."""
    created = pending_service.add_candidates_to_pending(
        candidates=[_sample_candidate()],
        source="post_retrain_auto",
    )[0]

    pending_service.mark_auto_approved_and_queued(
        created.id,
        exp_id="exp-terminal-1",
        notes="auto",
    )

    memory_db.add(
        ExperimentModel(
            exp_id="exp-terminal-1",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            status="queued",
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
            target_atoms=1000,
            temperature_K=298.0,
            pressure_atm=1.0,
            seed=1,
            created_at=datetime.utcnow(),
        )
    )
    memory_db.commit()

    # First stop succeeds
    pending_service.stop_pending_execution(created.id, reason="first stop")

    # Second stop fails — already in terminal state
    with pytest.raises(ContractError):
        pending_service.stop_pending_execution(created.id, reason="second stop")


def test_stop_pending_execution_rejects_no_linked_experiment(memory_db):
    """stop_pending_execution() should reject when no experiment is linked."""
    created = pending_service.add_candidates_to_pending(
        candidates=[_sample_candidate()],
        source="quick",
    )[0]

    with pytest.raises(ContractError, match="no linked experiment"):
        pending_service.stop_pending_execution(created.id, reason="no exp")


def test_approve_pending_rejects_stale_version(memory_db, monkeypatch):
    """approve_pending() should reject when expected_version doesn't match."""
    created = pending_service.add_candidates_to_pending(
        candidates=[_sample_candidate()],
        source="quick",
    )[0]

    def _fake_queue(**kwargs):
        return "exp-stale-001"

    monkeypatch.setattr(
        "features.recommendations.active_learning._queue_active_learning_experiment",
        _fake_queue,
    )

    with pytest.raises(ContractError):
        pending_service.approve_pending(created.id, expected_version=999)
