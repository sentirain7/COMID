"""Tests for model registry lineage and predictor metadata persistence."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("sqlalchemy")

from database.connection import init_memory_db
from ml.data_loader import TargetVariable, TrainingDataset
from ml.model_registry import ModelRegistry
from ml.models import ModelType
from ml.multi_target import MultiTargetConfig, MultiTargetPredictor


def _make_predictor(tmp_path: Path) -> MultiTargetPredictor:
    dataset = TrainingDataset(
        X=np.random.default_rng(42).normal(size=(20, 3)),
        y=np.random.default_rng(7).uniform(0.9, 1.1, size=20),
        exp_ids=[f"exp_{i}" for i in range(20)],
        feature_names=["f0", "f1", "f2"],
        target_name="density",
    )
    predictor = MultiTargetPredictor(
        config=MultiTargetConfig(
            targets=[TargetVariable.DENSITY],
            model_type=ModelType.LINEAR,
            target_feature_sets={"density": "v3"},
        ),
        model_dir=tmp_path,
    )
    predictor.train({"density": dataset})
    predictor._requested_feature_set = "v3"
    predictor._actual_feature_set = "v3"
    predictor._feature_schema_hash = "schema_hash_123"
    predictor._per_target_feature_schema_hashes = {"density": "schema_hash_density"}
    predictor._capability_manifest = {
        "supported_targets": ["density"],
        "per_target_feature_set": {"density": "v3"},
        "uncertainty_enabled": False,
        "ood_enabled": False,
    }
    return predictor


def test_generate_version_id_uses_collision_resistant_suffix() -> None:
    session = init_memory_db()
    registry = ModelRegistry(session)

    version_1 = registry.generate_version_id()
    version_2 = registry.generate_version_id()

    assert version_1.startswith("mt_")
    assert version_2.startswith("mt_")
    assert version_1 != version_2


def test_register_model_persists_feature_contract_metadata(tmp_path: Path) -> None:
    session = init_memory_db()
    registry = ModelRegistry(session)
    predictor = _make_predictor(tmp_path)

    row = registry.register_model(
        predictor,
        feature_set_version="v3",
        actual_feature_set="v3",
        per_target_feature_sets={"density": "v3"},
        feature_schema_hash="schema_hash_123",
        training_samples=20,
        training_seed=42,
        training_snapshot={"targets": ["density"], "train_exp_ids": ["exp_1"]},
        capability_manifest=predictor._capability_manifest,
    )

    assert row.feature_set_version == "v3"
    assert row.actual_feature_set == "v3"
    assert row.per_target_feature_sets_json == {"density": "v3"}
    assert row.feature_schema_hash == "schema_hash_123"
    assert row.training_manifest_hash
    assert row.capability_manifest_json == predictor._capability_manifest


def test_champion_predictor_load_restores_lineage_metadata(tmp_path: Path) -> None:
    session = init_memory_db()
    registry = ModelRegistry(session)
    predictor = _make_predictor(tmp_path)

    row = registry.register_model(
        predictor,
        feature_set_version="v3",
        actual_feature_set="mixed",
        per_target_feature_sets={"density": "v3"},
        feature_schema_hash="schema_hash_123",
        training_samples=20,
        training_seed=42,
        training_snapshot={"targets": ["density"], "train_exp_ids": ["exp_1"]},
        capability_manifest=predictor._capability_manifest,
    )
    registry.promote(row.version_id)

    loaded = registry.get_champion_predictor()
    assert loaded is not None
    assert loaded._requested_feature_set == "v3"
    assert loaded._actual_feature_set == "mixed"
    assert loaded._feature_schema_hash == "schema_hash_123"
    assert loaded._capability_manifest == predictor._capability_manifest
