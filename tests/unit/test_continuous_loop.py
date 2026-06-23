"""Tests for orchestrator.continuous_loop."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("sqlalchemy")

from database.connection import init_memory_db
from orchestrator.continuous_loop import ContinuousLearningLoop


def test_continuous_loop_skips_when_not_enough_new_samples():
    session = init_memory_db()
    loop = ContinuousLearningLoop(session)
    result = loop.run_check()
    assert result["retrained"] is False
    assert result["trigger_reason"] in {
        "insufficient_new_samples",
        "insufficient_density_samples",
        "no_trigger",
    }


# --- New tests ---


def test_drift_check_only_no_retraining():
    """drift_check_only() should never trigger retraining."""
    session = init_memory_db()
    loop = ContinuousLearningLoop(session)
    result = loop.drift_check_only()
    assert "drift" in result
    assert "checked_at" in result
    assert "retrained" not in result or result.get("retrained") is not True


def test_run_check_result_structure():
    """run_check() result must have required keys."""
    session = init_memory_db()
    loop = ContinuousLearningLoop(session)
    result = loop.run_check()
    required_keys = {
        "checked_at",
        "new_samples",
        "drift",
        "retrained",
        "version_id",
        "trigger_reason",
    }
    assert required_keys.issubset(result.keys())
    assert isinstance(result["new_samples"], int)
    assert isinstance(result["retrained"], bool)


def test_drift_check_only_result_structure():
    """drift_check_only() result must have required keys."""
    session = init_memory_db()
    loop = ContinuousLearningLoop(session)
    result = loop.drift_check_only()
    required_keys = {"checked_at", "new_samples", "drift"}
    assert required_keys.issubset(result.keys())
    assert isinstance(result["new_samples"], int)


def test_run_check_triggers_post_retrain_auto_batch_on_promotion(monkeypatch):
    session = init_memory_db()
    loop = ContinuousLearningLoop(session)
    auto_batch = MagicMock(return_value={"ok": True, "queued": 2})

    monkeypatch.setattr(loop, "_count_new_completed_samples", lambda: 100)
    monkeypatch.setattr(loop, "_save_last_check", lambda ts: None)
    monkeypatch.setattr(
        loop,
        "_check_multi_target_drift",
        lambda champion: (
            {
                "feature_drift_fraction": 0.3,
                "rmse_drift_pct": 0.2,
                "page_hinkley_detected": True,
            },
            ["density"],
        ),
    )

    class FakeRegistry:
        def __init__(self, _session):
            pass

        def get_champion_predictor(self):
            return SimpleNamespace(fitted_targets={"density"})

    class FakeRetrainer:
        # Mirrors ModelRetrainer.__init__(db_session, model_registry, *, e_intra_method=None)
        def __init__(self, _session, _registry, *, e_intra_method=None):
            self._e_intra_method = e_intra_method

        def run(self, **kwargs):
            return SimpleNamespace(
                success=True,
                promoted=True,
                version_id="model-v2",
                trigger_reason="continuous_loop",
            )

    monkeypatch.setattr("orchestrator.continuous_loop.ModelRegistry", FakeRegistry)
    monkeypatch.setattr("orchestrator.continuous_loop.ModelRetrainer", FakeRetrainer)
    monkeypatch.setattr(
        "features.recommendations.active_learning.run_post_retrain_auto_batch",
        auto_batch,
    )

    result = loop.run_check()

    auto_batch.assert_called_once_with(source="continuous_loop_auto")
    assert result["retrained"] is True
    assert result["version_id"] == "model-v2"
    assert result["auto_recommendations"] == {"ok": True, "queued": 2}
