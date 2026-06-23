import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, "src")

from contracts.errors import ContractError
from contracts.policies.ml_policy import DEFAULT_ML_POLICY
from contracts.policies.recommendation_policy import DEFAULT_RECOMMENDATION_POLICY
from features.recommendations import active_learning
from recommendation.active_learning import ActiveLearningWorkflow
from recommendation.agent import AgentConfig, RecommendationAgent


def test_get_al_workflow_wires_mlops_retrain(monkeypatch):
    active_learning._al_workflow = None
    trigger = MagicMock(return_value=True)

    monkeypatch.setattr("api.deps.get_ml_predictor_fn", lambda: None)
    monkeypatch.setattr("features.mlops.service.trigger_retraining_if_needed", trigger)

    workflow = active_learning._get_al_workflow()
    assert workflow.min_retrain_samples == DEFAULT_ML_POLICY.retraining.min_new_samples

    workflow.retrain_fn([])
    trigger.assert_called_once_with(
        triggered_by="active_learning",
        new_samples=DEFAULT_ML_POLICY.retraining.min_new_samples,
        completed_exp_ids=[],
    )

    active_learning._al_workflow = None


def test_get_al_workflow_auto_prepares_next_batch_after_retrain(monkeypatch):
    active_learning._al_workflow = None
    trigger = MagicMock(return_value=True)
    auto_batch = MagicMock(return_value={"ok": True, "generated": 3, "queued": 3})

    def _predictor(_composition):
        return {"cohesive_energy_density": 320.0, "adhesion_energy": 1.2}

    monkeypatch.setattr("api.deps.get_ml_predictor_fn", lambda: _predictor)
    monkeypatch.setattr("features.mlops.service.trigger_retraining_if_needed", trigger)
    monkeypatch.setattr(
        "features.recommendations.active_learning.run_post_retrain_auto_batch", auto_batch
    )

    workflow = active_learning._get_al_workflow()
    workflow.retrain_fn([SimpleNamespace(exp_id="exp-auto-1")])

    trigger.assert_called_once_with(
        triggered_by="active_learning",
        new_samples=DEFAULT_ML_POLICY.retraining.min_new_samples,
        completed_exp_ids=["exp-auto-1"],
    )
    auto_batch.assert_called_once_with(source="active_learning_auto")

    active_learning._al_workflow = None


def test_run_post_retrain_auto_batch_persists_and_auto_queues(monkeypatch):
    memory_rec = SimpleNamespace(
        id="mem-rec-1",
        composition={
            "asphaltene": 20.0,
            "resin": 30.0,
            "aromatic": 35.0,
            "saturate": 15.0,
        },
        predicted_properties={"density": 1.01},
        uncertainty={"density": 0.05},
    )
    workflow = SimpleNamespace(
        suggest_next=MagicMock(
            return_value=SimpleNamespace(batch_id="batch-auto-1", recommendations=[memory_rec])
        ),
        approve=MagicMock(return_value=SimpleNamespace(queued_exp_id="exp-auto-1")),
    )
    persisted_row = SimpleNamespace(id="prec-auto-1")
    add_pending = MagicMock(return_value=[persisted_row])
    mark_queued = MagicMock()
    mark_failed = MagicMock()

    monkeypatch.setattr(
        active_learning,
        "_refresh_workflow_predictor",
        lambda: (workflow, object()),
    )
    monkeypatch.setattr(
        active_learning,
        "_get_current_model_lineage",
        lambda: ("model-v1", "v3"),
    )
    monkeypatch.setattr(
        "features.recommendations.pending_service.add_candidates_to_pending",
        add_pending,
    )
    monkeypatch.setattr(
        "features.recommendations.pending_service.mark_auto_approved_and_queued",
        mark_queued,
    )
    monkeypatch.setattr(
        "features.recommendations.pending_service.mark_pending_failed",
        mark_failed,
    )

    result = active_learning.run_post_retrain_auto_batch(
        n_candidates=1,
        source="active_learning_auto",
    )

    assert result["ok"] is True
    assert result["generated"] == 1
    assert result["persisted"] == 1
    assert result["queued"] == 1
    add_pending.assert_called_once()
    workflow.approve.assert_called_once_with(
        "mem-rec-1",
        notes="Auto-approved after retraining (active_learning_auto)",
    )
    mark_queued.assert_called_once_with(
        "prec-auto-1",
        exp_id="exp-auto-1",
        notes="Auto-approved after retraining (active_learning_auto)",
    )
    mark_failed.assert_not_called()


def test_ingest_completed_experiment_deduplicates():
    active_learning._al_workflow = ActiveLearningWorkflow(
        agent=RecommendationAgent(config=AgentConfig(auto_run=False)),
        min_retrain_samples=999,
    )

    created = active_learning.ingest_completed_experiment(
        exp_id="exp-1",
        composition={"asphaltene": 20.0, "resin": 30.0, "aromatic": 35.0, "saturate": 15.0},
        observed_properties={"density": 1.02},
    )
    duplicate = active_learning.ingest_completed_experiment(
        exp_id="exp-1",
        composition={"asphaltene": 20.0, "resin": 30.0, "aromatic": 35.0, "saturate": 15.0},
        observed_properties={"density": 1.02},
    )

    assert created is True
    assert duplicate is False
    assert active_learning._al_workflow.state.n_observations == 1

    active_learning._al_workflow = None


def test_ingest_completed_experiment_normalizes_incomplete_composition():
    active_learning._al_workflow = ActiveLearningWorkflow(
        agent=RecommendationAgent(config=AgentConfig(auto_run=False)),
        min_retrain_samples=999,
    )

    created = active_learning.ingest_completed_experiment(
        exp_id="exp-2",
        composition={"asphaltene": 20.0, "resin": 30.0, "aromatic": 35.0},
        observed_properties={"density": 1.02},
    )

    assert created is True
    datum = active_learning._al_workflow.state.training_data[0]
    assert datum.composition["saturate"] == 0.0

    active_learning._al_workflow = None


def test_ingest_completed_experiment_rejects_invalid_composition():
    active_learning._al_workflow = ActiveLearningWorkflow(
        agent=RecommendationAgent(config=AgentConfig(auto_run=False)),
        min_retrain_samples=999,
    )

    with pytest.raises(ContractError):
        active_learning.ingest_completed_experiment(
            exp_id="exp-3",
            composition={},
            observed_properties={"density": 1.02},
        )

    active_learning._al_workflow = None


@pytest.mark.asyncio
async def test_suggest_recommendations_requires_ml_predictor(monkeypatch):
    active_learning._al_workflow = ActiveLearningWorkflow(
        agent=RecommendationAgent(config=AgentConfig(auto_run=False), predictor=None),
        min_retrain_samples=999,
    )

    monkeypatch.setattr("api.deps.get_ml_predictor_fn", lambda: None)

    with pytest.raises(ContractError, match="ML predictor not available"):
        await active_learning.suggest_recommendations(n_candidates=4)

    active_learning._al_workflow = None


def test_run_post_retrain_auto_batch_handles_partial_failure(monkeypatch):
    """Post-retrain batch: first approve succeeds, second fails."""
    rec1 = SimpleNamespace(
        id="mem-1",
        composition={"asphaltene": 20.0, "resin": 30.0, "aromatic": 35.0, "saturate": 15.0},
        predicted_properties={"density": 1.01},
        uncertainty={"density": 0.05},
    )
    rec2 = SimpleNamespace(
        id="mem-2",
        composition={"asphaltene": 18.0, "resin": 32.0, "aromatic": 35.0, "saturate": 15.0},
        predicted_properties={"density": 1.02},
        uncertainty={"density": 0.04},
    )

    call_count = {"n": 0}

    def _approve(rec_id, notes=""):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return SimpleNamespace(queued_exp_id="exp-auto-ok")
        raise RuntimeError("GPU unavailable")

    workflow = SimpleNamespace(
        suggest_next=MagicMock(
            return_value=SimpleNamespace(batch_id="batch-partial", recommendations=[rec1, rec2])
        ),
        approve=_approve,
    )
    persisted1 = SimpleNamespace(id="prec-1")
    persisted2 = SimpleNamespace(id="prec-2")

    monkeypatch.setattr(
        active_learning,
        "_refresh_workflow_predictor",
        lambda: (workflow, object()),
    )
    monkeypatch.setattr(
        active_learning,
        "_get_current_model_lineage",
        lambda: ("model-v1", "v3"),
    )
    monkeypatch.setattr(
        "features.recommendations.pending_service.add_candidates_to_pending",
        MagicMock(return_value=[persisted1, persisted2]),
    )
    mark_queued = MagicMock()
    mark_failed = MagicMock()
    monkeypatch.setattr(
        "features.recommendations.pending_service.mark_auto_approved_and_queued",
        mark_queued,
    )
    monkeypatch.setattr(
        "features.recommendations.pending_service.mark_pending_failed",
        mark_failed,
    )

    result = active_learning.run_post_retrain_auto_batch(
        n_candidates=2,
        source="active_learning_auto",
    )

    assert result["ok"] is True
    assert result["generated"] == 2
    assert result["queued"] == 1
    assert result["failed"] == 1
    mark_queued.assert_called_once()
    mark_failed.assert_called_once()
    assert mark_failed.call_args[0][0] == "prec-2"


def test_run_post_retrain_auto_batch_skips_when_no_predictor(monkeypatch):
    """Post-retrain batch should skip when ML predictor unavailable."""
    monkeypatch.setattr(
        active_learning,
        "_refresh_workflow_predictor",
        lambda: (MagicMock(), None),
    )

    result = active_learning.run_post_retrain_auto_batch(source="test_auto")
    assert result["ok"] is False
    assert result["generated"] == 0


def test_run_post_retrain_auto_batch_skips_when_policy_disabled(monkeypatch):
    """Post-retrain batch should skip when automation policy is disabled."""
    monkeypatch.setattr(
        active_learning,
        "_refresh_workflow_predictor",
        lambda: (MagicMock(), object()),
    )
    monkeypatch.setattr(
        DEFAULT_RECOMMENDATION_POLICY.post_retrain_automation,
        "enabled",
        False,
    )

    result = active_learning.run_post_retrain_auto_batch(source="test_auto")
    assert result["ok"] is False


def test_run_post_retrain_auto_batch_persisted_length_mismatch(monkeypatch):
    """Post-retrain batch: zip(strict=False) handles length mismatch safely."""
    rec1 = SimpleNamespace(
        id="mem-short-1",
        composition={"asphaltene": 20.0, "resin": 30.0, "aromatic": 35.0, "saturate": 15.0},
        predicted_properties={"density": 1.01},
        uncertainty={"density": 0.05},
    )
    rec2 = SimpleNamespace(
        id="mem-short-2",
        composition={"asphaltene": 18.0, "resin": 32.0, "aromatic": 35.0, "saturate": 15.0},
        predicted_properties={"density": 1.02},
        uncertainty={"density": 0.04},
    )
    workflow = SimpleNamespace(
        suggest_next=MagicMock(
            return_value=SimpleNamespace(batch_id="batch-mismatch", recommendations=[rec1, rec2])
        ),
        approve=MagicMock(return_value=SimpleNamespace(queued_exp_id="exp-m1")),
    )
    # add_pending returns only 1 row instead of 2
    persisted1 = SimpleNamespace(id="prec-m1")

    monkeypatch.setattr(
        active_learning,
        "_refresh_workflow_predictor",
        lambda: (workflow, object()),
    )
    monkeypatch.setattr(
        active_learning,
        "_get_current_model_lineage",
        lambda: ("model-v1", "v3"),
    )
    monkeypatch.setattr(
        "features.recommendations.pending_service.add_candidates_to_pending",
        MagicMock(return_value=[persisted1]),
    )
    mark_queued = MagicMock()
    mark_failed = MagicMock()
    monkeypatch.setattr(
        "features.recommendations.pending_service.mark_auto_approved_and_queued",
        mark_queued,
    )
    monkeypatch.setattr(
        "features.recommendations.pending_service.mark_pending_failed",
        mark_failed,
    )

    result = active_learning.run_post_retrain_auto_batch(
        n_candidates=2,
        source="active_learning_auto",
    )

    assert result["ok"] is True
    assert result["generated"] == 2
    assert result["persisted"] == 1
    assert result["queued"] == 1
    mark_failed.assert_not_called()
