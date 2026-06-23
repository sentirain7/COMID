"""
Unit tests for recommendation.active_learning module.

Tests the ActiveLearningWorkflow: suggest → approve/reject →
feed_result → retrain loop, ensuring no autonomous execution.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from recommendation.active_learning import (
    ActiveLearningState,
    ActiveLearningWorkflow,
    TrainingDatum,
)
from recommendation.agent import (
    AgentConfig,
    RecommendationAgent,
    RecommendationStatus,
)


def _predictor(composition: dict[str, float]) -> dict[str, float]:
    """Deterministic predictor for active-learning tests."""
    asphaltene = float(composition.get("asphaltene", 0.0))
    resin = float(composition.get("resin", 0.0))
    return {
        "density": 0.92 + asphaltene * 0.003,
        "cohesive_energy_density": 260.0 + asphaltene * 4.5 + resin,
    }


# ── fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def mock_queue_fn():
    """Queue function that returns a fake exp_id."""
    fn = MagicMock(return_value="exp_mock_001")
    return fn


@pytest.fixture
def mock_retrain_fn():
    return MagicMock()


@pytest.fixture
def workflow(mock_queue_fn, mock_retrain_fn):
    config = AgentConfig(
        objectives=[
            {"name": "density", "direction": "maximize", "weight": 1.0},
        ],
        n_recommendations_per_batch=3,
        auto_run=False,
        require_approval=True,
        include_additive=False,
    )
    agent = RecommendationAgent(config=config, predictor=_predictor)
    return ActiveLearningWorkflow(
        agent=agent,
        queue_fn=mock_queue_fn,
        retrain_fn=mock_retrain_fn,
        min_retrain_samples=3,
    )


# ── TrainingDatum ─────────────────────────────────────────────────


class TestTrainingDatum:
    def test_to_dict(self):
        d = TrainingDatum(
            composition={"asphaltene": 20},
            observed_properties={"density": 1.02},
            exp_id="exp_001",
            temperature_k=293.0,
        )
        result = d.to_dict()
        assert result["exp_id"] == "exp_001"
        assert result["temperature_k"] == 293.0
        assert "timestamp" in result


# ── ActiveLearningState ───────────────────────────────────────────


class TestActiveLearningState:
    def test_initial_state(self):
        s = ActiveLearningState()
        assert s.iteration == 0
        assert s.n_observations == 0
        assert s.summary()["n_pending"] == 0

    def test_summary_with_data(self):
        s = ActiveLearningState(iteration=3)
        s.training_data.append(
            TrainingDatum(
                composition={},
                observed_properties={},
                exp_id="e1",
                temperature_k=293.0,
            )
        )
        assert s.n_observations == 1
        assert s.summary()["iteration"] == 3


# ── suggest_next ──────────────────────────────────────────────────


class TestSuggestNext:
    def test_generates_batch(self, workflow):
        batch = workflow.suggest_next(n_candidates=10)
        assert len(batch.recommendations) > 0
        assert all(r.status == RecommendationStatus.PENDING for r in batch.recommendations)

    def test_history_recorded(self, workflow):
        workflow.suggest_next(n_candidates=10)
        assert len(workflow.state.history) == 1
        assert workflow.state.history[0]["action"] == "suggest"


# ── approve ───────────────────────────────────────────────────────


class TestApprove:
    def test_approve_queues_experiment(self, workflow, mock_queue_fn):
        batch = workflow.suggest_next(n_candidates=10)
        rec_id = batch.recommendations[0].id

        result = workflow.approve(rec_id, notes="Looks promising")
        assert result is not None
        assert result.status == RecommendationStatus.QUEUED
        assert result.queued_exp_id == "exp_mock_001"
        mock_queue_fn.assert_called_once()

    def test_approve_records_pending(self, workflow):
        batch = workflow.suggest_next(n_candidates=10)
        rec_id = batch.recommendations[0].id
        workflow.approve(rec_id)

        assert rec_id in workflow.state.pending_experiments

    def test_approve_nonexistent_returns_none(self, workflow):
        workflow.suggest_next(n_candidates=10)
        result = workflow.approve("nonexistent_id")
        assert result is None

    def test_approve_history_recorded(self, workflow):
        batch = workflow.suggest_next(n_candidates=10)
        workflow.approve(batch.recommendations[0].id)
        actions = [h["action"] for h in workflow.state.history]
        assert "approve" in actions


# ── reject ────────────────────────────────────────────────────────


class TestReject:
    def test_reject_marks_rejected(self, workflow):
        batch = workflow.suggest_next(n_candidates=10)
        rec_id = batch.recommendations[0].id
        result = workflow.reject(rec_id, reason="Too risky")
        assert result is not None
        assert result.status == RecommendationStatus.REJECTED

    def test_reject_history(self, workflow):
        batch = workflow.suggest_next(n_candidates=10)
        workflow.reject(batch.recommendations[0].id, reason="Testing")
        actions = [h["action"] for h in workflow.state.history]
        assert "reject" in actions


# ── feed_result ───────────────────────────────────────────────────


class TestFeedResult:
    def test_stores_training_datum(self, workflow):
        workflow.feed_result(
            exp_id="exp_001",
            composition={"asphaltene": 20, "resin": 30, "aromatic": 35, "saturate": 15},
            observed_properties={"density": 1.02},
            temperature_k=293.0,
        )
        assert workflow.state.n_observations == 1

    def test_removes_pending_experiment(self, workflow, mock_queue_fn):
        batch = workflow.suggest_next(n_candidates=10)
        rec_id = batch.recommendations[0].id
        workflow.approve(rec_id)

        exp_id = mock_queue_fn.return_value
        workflow.feed_result(
            exp_id=exp_id,
            composition={"asphaltene": 20, "resin": 30, "aromatic": 35, "saturate": 15},
            observed_properties={"density": 1.02},
        )

        assert rec_id not in workflow.state.pending_experiments

    def test_triggers_retrain_after_threshold(self, workflow, mock_retrain_fn):
        comp = {"asphaltene": 20, "resin": 30, "aromatic": 35, "saturate": 15}
        for i in range(3):  # min_retrain_samples=3
            workflow.feed_result(
                exp_id=f"exp_{i}",
                composition=comp,
                observed_properties={"density": 1.0 + i * 0.01},
            )
        mock_retrain_fn.assert_called_once()
        assert len(mock_retrain_fn.call_args[0][0]) == 3

    def test_no_retrain_before_threshold(self, workflow, mock_retrain_fn):
        comp = {"asphaltene": 20, "resin": 30, "aromatic": 35, "saturate": 15}
        for i in range(2):  # < min_retrain_samples=3
            workflow.feed_result(
                exp_id=f"exp_{i}",
                composition=comp,
                observed_properties={"density": 1.0},
            )
        mock_retrain_fn.assert_not_called()

    def test_history_recorded(self, workflow):
        workflow.feed_result(
            exp_id="exp_test",
            composition={"asphaltene": 20, "resin": 30, "aromatic": 35, "saturate": 15},
            observed_properties={"density": 1.0},
        )
        actions = [h["action"] for h in workflow.state.history]
        assert "feed_result" in actions


# ── no retrain_fn ─────────────────────────────────────────────────


class TestNoRetrainFn:
    def test_no_crash_without_retrain_fn(self):
        wf = ActiveLearningWorkflow(min_retrain_samples=1)
        wf.feed_result(
            exp_id="e1",
            composition={"asphaltene": 20, "resin": 30, "aromatic": 35, "saturate": 15},
            observed_properties={"density": 1.0},
        )
        # Should not raise even though threshold is exceeded
        assert wf.state.n_observations == 1


# ── no queue_fn ───────────────────────────────────────────────────


class TestNoQueueFn:
    def test_approve_without_queue_fn(self):
        wf = ActiveLearningWorkflow(agent=RecommendationAgent(predictor=_predictor))
        batch = wf.suggest_next(n_candidates=10)
        rec_id = batch.recommendations[0].id
        with pytest.raises(RuntimeError, match="Queue integration is required"):
            wf.approve(rec_id)

    def test_suggest_without_predictor_fails_fast(self):
        wf = ActiveLearningWorkflow()
        with pytest.raises(RuntimeError, match="ML predictor is required"):
            wf.suggest_next(n_candidates=5)


# ── full loop integration ─────────────────────────────────────────


class TestFullLoop:
    def test_suggest_approve_feed_loop(self, workflow, mock_queue_fn):
        # Iteration 1: suggest → approve → feed
        batch1 = workflow.suggest_next(n_candidates=10)
        rec = batch1.recommendations[0]
        workflow.approve(rec.id)

        workflow.feed_result(
            exp_id=mock_queue_fn.return_value,
            composition=rec.composition,
            observed_properties={"density": 1.02},
        )

        # Iteration 2: should work with updated model
        batch2 = workflow.suggest_next(n_candidates=10)
        assert len(batch2.recommendations) > 0

    def test_policy_auto_run_disabled(self, workflow):
        """Verify that auto_run is always disabled per spec."""
        assert workflow.agent.config.auto_run is False
        assert workflow.agent.config.require_approval is True


# ── get_state_summary ─────────────────────────────────────────────


class TestGetStateSummary:
    def test_summary_structure(self, workflow):
        summary = workflow.get_state_summary()
        assert "iteration" in summary
        assert "n_observations" in summary
        assert "agent_summary" in summary

    def test_get_pending(self, workflow):
        batch = workflow.suggest_next(n_candidates=10)
        pending = workflow.get_pending()
        assert len(pending) == len(batch.recommendations)
