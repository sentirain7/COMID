from datetime import datetime
from unittest.mock import MagicMock

import pytest

from database.models import ExperimentModel, MetricModel, PendingRecommendationModel
from orchestrator import tasks
from orchestrator.maintenance import MaintenanceService


def _make_experiment(exp_id: str, *, source: str) -> ExperimentModel:
    return ExperimentModel(
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
        created_at=datetime.utcnow(),
        metadata_json={"source": source},
    )


def test_completed_feedback_backfills_pending_recommendation(db_session, monkeypatch):
    exp_id = "exp-feedback-001"
    db_session.add(_make_experiment(exp_id, source="pending_recommendation"))
    db_session.add(
        MetricModel(
            exp_id=exp_id,
            metric_name="density",
            namespace="bulk_ff_gaff2",
            value=1.02,
            unit="g/cm3",
            created_at=datetime.utcnow(),
        )
    )
    db_session.add(
        PendingRecommendationModel(
            id="prec-feedback-1",
            source="quick",
            status="queued",
            composition_json={
                "asphaltene": 20.0,
                "resin": 30.0,
                "aromatic": 35.0,
                "saturate": 15.0,
            },
            predicted_properties_json={"density": 1.0},
            score=0.8,
            origin="optimizer",
            queued_exp_id=exp_id,
        )
    )
    db_session.commit()

    ingest = MagicMock(return_value=True)
    monkeypatch.setattr(
        "features.recommendations.active_learning.ingest_completed_experiment",
        ingest,
    )

    tasks._handle_completed_experiment_feedback(exp_id)

    row = (
        db_session.query(PendingRecommendationModel)
        .filter(PendingRecommendationModel.id == "prec-feedback-1")
        .first()
    )
    exp = db_session.query(ExperimentModel).filter(ExperimentModel.exp_id == exp_id).first()
    assert row is not None
    assert exp is not None
    assert row.status == "completed"
    assert row.result_metrics_json["density"] == 1.02
    assert row.prediction_error_json["density"] == pytest.approx(0.02)
    assert exp.feedback_processed_at is not None
    ingest.assert_called_once()


def test_completed_feedback_uses_active_learning_metadata_without_pending_row(
    db_session, monkeypatch
):
    exp_id = "exp-feedback-002"
    db_session.add(_make_experiment(exp_id, source="active_learning"))
    db_session.add(
        MetricModel(
            exp_id=exp_id,
            metric_name="density",
            namespace="bulk_ff_gaff2",
            value=1.03,
            unit="g/cm3",
            created_at=datetime.utcnow(),
        )
    )
    db_session.commit()

    ingest = MagicMock(return_value=True)
    monkeypatch.setattr(
        "features.recommendations.active_learning.ingest_completed_experiment",
        ingest,
    )

    tasks._handle_completed_experiment_feedback(exp_id)
    exp = db_session.query(ExperimentModel).filter(ExperimentModel.exp_id == exp_id).first()
    assert exp is not None
    assert exp.feedback_processed_at is not None
    ingest.assert_called_once()


def test_pending_recommendation_metadata_without_row_does_not_ingest(db_session, monkeypatch):
    exp_id = "exp-feedback-003"
    db_session.add(_make_experiment(exp_id, source="pending_recommendation"))
    db_session.add(
        MetricModel(
            exp_id=exp_id,
            metric_name="density",
            namespace="bulk_ff_gaff2",
            value=1.01,
            unit="g/cm3",
            created_at=datetime.utcnow(),
        )
    )
    db_session.commit()

    ingest = MagicMock(return_value=True)
    monkeypatch.setattr(
        "features.recommendations.active_learning.ingest_completed_experiment",
        ingest,
    )

    tasks._handle_completed_experiment_feedback(exp_id)
    exp = db_session.query(ExperimentModel).filter(ExperimentModel.exp_id == exp_id).first()
    assert exp is not None
    assert exp.feedback_processed_at is not None
    ingest.assert_not_called()


def test_reconcile_unprocessed_completions_only_returns_relevant_sources(db_session, monkeypatch):
    db_session.add(_make_experiment("exp-reconcile-active", source="active_learning"))
    db_session.add(_make_experiment("exp-reconcile-manual", source="manual_import"))
    db_session.commit()

    handled = []
    monkeypatch.setattr(
        tasks,
        "_handle_completed_experiment_feedback",
        lambda exp_id: handled.append(exp_id) or True,
    )

    result = tasks.reconcile_unprocessed_completions(limit=10)

    assert result == {"scanned": 1, "processed": 1}
    assert handled == ["exp-reconcile-active"]


def test_maintenance_service_reconcile_prefers_linked_or_al_sources(db_session):
    db_session.add(_make_experiment("exp-maint-active", source="active_learning"))
    db_session.add(
        _make_experiment(
            "exp-maint-linked",
            source="manual_import",
        )
    )
    db_session.add(_make_experiment("exp-maint-manual", source="manual_import"))
    db_session.add(
        PendingRecommendationModel(
            id="prec-maint-1",
            source="post_retrain_auto",
            status="queued",
            composition_json={
                "asphaltene": 20.0,
                "resin": 30.0,
                "aromatic": 35.0,
                "saturate": 15.0,
            },
            predicted_properties_json={"density": 1.0},
            score=0.8,
            origin="optimizer",
            queued_exp_id="exp-maint-linked",
        )
    )
    db_session.commit()

    exp_ids = MaintenanceService(db_session).reconcile_unprocessed_completions(limit=10)

    assert exp_ids == ["exp-maint-active", "exp-maint-linked"]


def test_completed_feedback_skips_duplicate_processing(db_session, monkeypatch):
    """Already-processed experiments should not be re-processed by reconcile."""
    exp_id = "exp-feedback-dup-001"
    exp = _make_experiment(exp_id, source="active_learning")
    exp.feedback_processed_at = datetime.utcnow()
    db_session.add(exp)
    db_session.add(
        MetricModel(
            exp_id=exp_id,
            metric_name="density",
            namespace="bulk_ff_gaff2",
            value=1.02,
            unit="g/cm3",
            created_at=datetime.utcnow(),
        )
    )
    db_session.commit()

    handled = []
    monkeypatch.setattr(
        tasks,
        "_handle_completed_experiment_feedback",
        lambda eid: handled.append(eid) or True,
    )

    tasks.reconcile_unprocessed_completions(limit=10)

    # Already processed — should NOT appear in reconcile scan
    assert exp_id not in handled


def test_reconcile_filters_by_source_and_linked_row(db_session, monkeypatch):
    """Reconcile should only include experiments with AL source or linked pending row."""
    # campaign source without a linked pending row → should NOT trigger
    db_session.add(_make_experiment("exp-campaign-only", source="campaign"))
    db_session.commit()

    handled = []
    monkeypatch.setattr(
        tasks,
        "_handle_completed_experiment_feedback",
        lambda eid: handled.append(eid) or True,
    )

    tasks.reconcile_unprocessed_completions(limit=10)

    assert "exp-campaign-only" not in handled
