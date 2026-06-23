"""Tests for ml.model_registry utilities."""

from datetime import UTC, datetime

import numpy as np
import pytest

pytest.importorskip("sqlalchemy")

from database.connection import init_memory_db
from database.models import MLModelVersionModel
from database.repositories.model_version_repo import ModelVersionRepository
from ml.model_registry import ModelRegistry


def test_generate_version_id_prefix():
    session = init_memory_db()
    registry = ModelRegistry(session)
    version_id = registry.generate_version_id()
    assert version_id.startswith("mt_")


def test_ece_non_negative():
    session = init_memory_db()
    registry = ModelRegistry(session)
    means = [1.0, 2.0, 3.0, 4.0]
    stds = [0.1, 0.2, 0.3, 0.4]
    actuals = [1.1, 1.8, 3.2, 3.9]
    ece = registry.compute_ece(means, stds, actuals)
    assert ece >= 0.0


def test_compare_with_champion_returns_result():
    session = init_memory_db()
    registry = ModelRegistry(session)

    y_true = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    challenger = np.array([1.0, 2.1, 2.9, 3.9, 4.8])
    champion = np.array([1.3, 2.3, 3.3, 4.2, 5.2])

    result = registry.compare_with_champion(challenger, champion, y_true)
    assert result.test_type in {"wilcoxon", "paired_t"}
    assert 0.0 <= result.p_value <= 1.0


# --- New tests ---


def test_wilcoxon_tied_inputs_valid_p_value():
    """Wilcoxon with many tied differences => valid p_value in [0, 1]."""
    session = init_memory_db()
    registry = ModelRegistry(session)

    # Many identical differences => tied ranks
    a = np.array([1.0, 1.0, 1.0, 2.0, 2.0, 3.0, 3.0, 3.0, 4.0, 4.0])
    b = np.array([0.5, 0.5, 0.5, 1.5, 1.5, 2.5, 2.5, 2.5, 3.5, 3.5])
    stat, p = registry._wilcoxon_signed_rank_test(a, b)
    assert 0.0 <= p <= 1.0
    assert stat >= 0.0


def test_wilcoxon_clear_difference_significant():
    """Clear systematic difference => p < 0.05."""
    session = init_memory_db()
    registry = ModelRegistry(session)

    rng = np.random.default_rng(42)
    a = rng.normal(0.0, 0.1, 50)
    b = rng.normal(1.0, 0.1, 50)

    stat, p = registry._wilcoxon_signed_rank_test(a, b)
    assert p < 0.05


def test_paired_t_identical_high_p_value():
    """Identical arrays => p ≈ 1.0."""
    session = init_memory_db()
    registry = ModelRegistry(session)

    a = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    b = np.array([1.0, 2.0, 3.0, 4.0, 5.0])

    stat, p = registry._paired_t_test(a, b)
    assert p == 1.0


def test_ece_perfect_calibration_near_zero():
    """Perfectly calibrated predictions => ECE ≈ 0."""
    session = init_memory_db()
    registry = ModelRegistry(session)

    rng = np.random.default_rng(0)
    means = rng.normal(0, 1, 500).tolist()
    stds = [1.0] * 500
    actuals = [m + rng.normal(0, 1) for m in means]

    ece = registry.compute_ece(means, stds, actuals, n_bins=10)
    assert ece < 0.15  # well-calibrated should be near 0


def test_ece_underconfident_positive():
    """Overly wide intervals (large std) => positive ECE."""
    session = init_memory_db()
    registry = ModelRegistry(session)

    means = [0.0] * 100
    stds = [100.0] * 100  # absurdly wide
    actuals = [0.01] * 100

    ece = registry.compute_ece(means, stds, actuals, n_bins=10)
    assert ece > 0.0


def test_promote_sets_champion_status():
    """promote_to_champion => status becomes 'champion'."""
    session = init_memory_db()
    repo = ModelVersionRepository(session)

    row = MLModelVersionModel(
        version_id="test_v1",
        model_type="multi_target",
        target_names=["density"],
        feature_set_version="v1",
        status="challenger",
        training_samples=100,
        training_seed=42,
        model_artifact_path="/tmp/test",
    )
    repo.save(row)
    session.flush()

    promoted = repo.promote_to_champion("test_v1")
    assert promoted is not None
    assert promoted.status == "champion"
    assert promoted.promoted_at is not None


def test_rollback_restores_previous_model():
    """Rollback should restore the previous champion, not the current one."""
    session = init_memory_db()
    repo = ModelVersionRepository(session)
    now = datetime.now(UTC)

    # Create v1 as retired (was previous champion)
    v1 = MLModelVersionModel(
        version_id="v1",
        model_type="multi_target",
        target_names=["density"],
        feature_set_version="v1",
        status="retired",
        training_samples=100,
        training_seed=42,
        model_artifact_path="/tmp/v1",
        promoted_at=now,
        retired_at=now,
    )
    repo.save(v1)

    # Create v2 as current champion
    v2 = MLModelVersionModel(
        version_id="v2",
        model_type="multi_target",
        target_names=["density"],
        feature_set_version="v1",
        status="champion",
        training_samples=200,
        training_seed=42,
        model_artifact_path="/tmp/v2",
        promoted_at=now,
    )
    repo.save(v2)
    session.flush()

    # Rollback: v2 should be retired, v1 should become champion
    restored = repo.rollback_to_previous()
    assert restored is not None
    assert restored.version_id == "v1"
    assert restored.status == "champion"
    assert v2.status == "retired"
