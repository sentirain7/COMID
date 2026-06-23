"""Closed-loop integration test for campaign, recommendation, completion, and retraining."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from database.models import ExperimentModel, MetricModel, PendingRecommendationModel
from features.campaign import service as campaign_service
from features.recommendations import active_learning, pending_service
from orchestrator import tasks
from orchestrator.batch_job_binder_cell import BatchJobBinderCellJob, BatchJobBinderCellResult
from recommendation.active_learning import ActiveLearningWorkflow
from recommendation.agent import AgentConfig, RecommendationAgent


def _experiment(exp_id: str, *, status: str, metadata_json: dict | None = None) -> ExperimentModel:
    return ExperimentModel(
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
        created_at=datetime.utcnow(),
        metadata_json=metadata_json or {},
    )


def test_closed_loop_campaign_to_retrain(db_session, monkeypatch):
    active_learning._al_workflow = None

    def _fake_wave_submit(session, spec):
        session.add(_experiment("exp-wave-bootstrap-001", status="queued"))
        session.flush()
        return BatchJobBinderCellResult(
            batch_job_id="batch-wave1",
            jobs=[
                BatchJobBinderCellJob(
                    exp_id="exp-wave-bootstrap-001",
                    binder_type="AAA1",
                    structure_size="X1",
                    temperature_k=293.0,
                    aging_state="non_aging",
                    tier="screening",
                    seed=1,
                    status="submitted",
                )
            ],
            total=1,
            new=1,
            duplicates=0,
            submitted=1,
            errors=0,
        )

    monkeypatch.setattr(campaign_service, "_submit_wave_spec", _fake_wave_submit)

    wave = campaign_service.submit_wave(
        campaign_service.CampaignWaveSubmitRequest(campaign_name="pilot", wave_no=1)
    )
    progress = campaign_service.get_progress(wave.campaign_id)
    assert progress.total_experiments == 1

    created = pending_service.add_candidates_to_pending(
        candidates=[
            {
                "origin": "optimizer",
                "score": 0.91,
                "composition": {
                    "asphaltene": 20.0,
                    "resin": 30.0,
                    "aromatic": 35.0,
                    "saturate": 15.0,
                },
                "predicted_properties": {"density": 1.0},
            }
        ],
        source="quick",
        model_version_id="mt_candidate_1",
        feature_set_version="v3",
        simulation_priority="screen",
    )[0]

    queue_calls = {}

    def _fake_queue(**kwargs):
        queue_calls.update(kwargs)
        return "exp-closed-loop-001"

    monkeypatch.setattr(
        "features.recommendations.active_learning._queue_active_learning_experiment",
        _fake_queue,
    )

    retrain = MagicMock(return_value=True)
    active_learning._al_workflow = ActiveLearningWorkflow(
        agent=RecommendationAgent(config=AgentConfig(auto_run=False)),
        min_retrain_samples=1,
        retrain_fn=lambda training_data: retrain(training_data),
    )

    approved = pending_service.approve_pending(created.id, expected_version=1)
    assert approved.status == "queued"
    assert approved.queued_exp_id == "exp-closed-loop-001"

    db_session.add(
        _experiment(
            "exp-closed-loop-001",
            status="completed",
            metadata_json={
                "source": "pending_recommendation",
                **dict(queue_calls.get("metadata_json") or {}),
            },
        )
    )
    db_session.add(
        MetricModel(
            exp_id="exp-closed-loop-001",
            metric_name="density",
            namespace="bulk_ff_gaff2",
            value=1.02,
            unit="g/cm3",
            created_at=datetime.utcnow(),
        )
    )
    db_session.commit()

    tasks._handle_completed_experiment_feedback("exp-closed-loop-001")
    db_session.expire_all()

    row = (
        db_session.query(PendingRecommendationModel)
        .filter(PendingRecommendationModel.id == created.id)
        .first()
    )
    assert row is not None
    assert row.status == "completed"
    assert row.result_metrics_json["density"] == 1.02
    assert row.prediction_error_json["density"] == pytest.approx(0.02)
    assert active_learning._al_workflow.state.n_observations == 1
    retrain.assert_called_once()

    active_learning._al_workflow = None
