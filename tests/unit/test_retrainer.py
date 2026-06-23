"""Tests for retraining trigger logic."""

from types import SimpleNamespace

import pytest

pytest.importorskip("sqlalchemy")

from ml.retrainer import ModelRetrainer, should_retrain


def test_should_retrain_force_true():
    ok, reason = should_retrain(
        current_samples=10,
        new_samples=0,
        drift_should_retrain=False,
        force=True,
    )
    assert ok is True
    assert reason == "force"


def test_should_retrain_on_new_samples_threshold():
    ok, reason = should_retrain(
        current_samples=500,
        new_samples=100,
        drift_should_retrain=False,
        force=False,
    )
    assert ok is True
    assert reason == "new_samples_threshold"


def test_should_retrain_no_trigger():
    ok, reason = should_retrain(
        current_samples=500,
        new_samples=1,
        drift_should_retrain=False,
        force=False,
    )
    assert ok is False
    assert reason in {"no_trigger", "insufficient_total_samples"}


# --- New tests ---


def test_should_retrain_drift_detected_triggers():
    """drift_should_retrain=True => should trigger."""
    ok, reason = should_retrain(
        current_samples=500,
        new_samples=1,
        drift_should_retrain=True,
        force=False,
    )
    assert ok is True
    assert reason == "drift_detected"


def test_should_retrain_insufficient_samples_rejects():
    """Below min_training_samples => reject even with drift."""
    ok, reason = should_retrain(
        current_samples=5,
        new_samples=1,
        drift_should_retrain=True,
        force=False,
    )
    assert ok is False
    assert reason == "insufficient_total_samples"


def test_holdout_rotation_same_cycle_same_split():
    """Same cycle => same split (deterministic)."""
    import numpy as np

    from database.connection import init_memory_db
    from ml.data_loader import TrainingDataset
    from ml.model_registry import ModelRegistry

    session = init_memory_db()
    registry = ModelRegistry(session)
    retrainer = ModelRetrainer(session, registry)

    ds = TrainingDataset(
        X=np.random.default_rng(0).normal(size=(50, 3)),
        y=np.random.default_rng(0).normal(size=50),
        exp_ids=[f"exp_{i}" for i in range(50)],
        feature_names=["f1", "f2", "f3"],
        target_name="density",
    )

    train1, val1, test1 = retrainer._split_with_holdout_rotation(ds, cycle=0)
    train2, val2, test2 = retrainer._split_with_holdout_rotation(ds, cycle=0)
    assert train1 == train2
    assert val1 == val2
    assert test1 == test2


def test_holdout_rotation_different_interval_different_split():
    """Different rotation interval => potentially different split."""
    import numpy as np

    from database.connection import init_memory_db
    from ml.data_loader import TrainingDataset
    from ml.model_registry import ModelRegistry

    session = init_memory_db()
    registry = ModelRegistry(session)
    retrainer = ModelRetrainer(session, registry)

    ds = TrainingDataset(
        X=np.random.default_rng(0).normal(size=(50, 3)),
        y=np.random.default_rng(0).normal(size=50),
        exp_ids=[f"exp_{i}" for i in range(50)],
        feature_names=["f1", "f2", "f3"],
        target_name="density",
    )

    train1, val1, test1 = retrainer._split_with_holdout_rotation(ds, cycle=0)
    # Use a cycle that crosses a rotation boundary
    train2, val2, test2 = retrainer._split_with_holdout_rotation(ds, cycle=100)
    assert train1 != train2 or val1 != val2 or test1 != test2


def test_promotion_metadata_guard_requires_lineage_fields():
    predictor = SimpleNamespace(
        _requested_feature_set="v5",
        _actual_feature_set="v5",
        _feature_schema_hash="abc123",
        _capability_manifest={"supported_targets": ["density"]},
    )
    assert ModelRetrainer._has_complete_promotion_metadata(predictor) is True

    predictor._capability_manifest = None
    assert ModelRetrainer._has_complete_promotion_metadata(predictor) is False


def test_overlapping_targets_not_degraded_requires_all_targets_improve_or_hold():
    assert (
        ModelRetrainer._overlapping_targets_not_degraded(
            {"density": 0.8, "viscosity": 1.2},
            {"density": 1.0, "viscosity": 1.2},
        )
        is True
    )
    assert (
        ModelRetrainer._overlapping_targets_not_degraded(
            {"density": 1.1, "viscosity": 1.1},
            {"density": 1.0, "viscosity": 1.2},
        )
        is False
    )
    assert ModelRetrainer._overlapping_targets_not_degraded({"density": 0.9}, {}) is False
