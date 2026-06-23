"""API contract tests for MLOps routes."""

from __future__ import annotations

import sys

import pytest
from pydantic import TypeAdapter

sys.path.insert(0, "src")

from api.schemas import MLModelHistoryResponse, MLModelVersionResponse
from features.mlops.router import get_ml_champion, get_ml_model_history


@pytest.mark.asyncio
async def test_ml_champion_contract_includes_recommendation_visibility(monkeypatch):
    async def _fake_get_ml_champion():
        return {
            "version_id": "mt_20260311_010203",
            "status": "champion",
            "model_type": "multi_target",
            "feature_set_version": "v3",
            "target_names": ["density", "cohesive_energy_density"],
            "training_samples": 124,
            "calibration_ece": 0.07,
            "test_metrics": {
                "density": {"rmse": 0.03},
                "cohesive_energy_density": {"rmse": 18.0},
            },
            "recommendation_metrics": {
                "feasibility_rate": 0.82,
                "top_k_hit_rate": 0.76,
                "calibration_ece": 0.09,
                "ood_precision": 0.67,
            },
            "created_at": "2026-03-11T00:00:00+00:00",
            "promoted_at": "2026-03-11T01:00:00+00:00",
            "model_artifact_path": "models/registry/mt_20260311_010203/model",
            "triggered_by": "continuous_loop",
            "retraining_reason": "continuous_loop",
        }

    monkeypatch.setattr("features.mlops.service.get_ml_champion", _fake_get_ml_champion)

    payload = await get_ml_champion()
    validated = MLModelVersionResponse.model_validate(payload)

    assert validated.recommendation_metrics is not None
    assert validated.recommendation_metrics["top_k_hit_rate"] == 0.76
    assert validated.test_metrics is not None
    assert validated.test_metrics["density"]["rmse"] == 0.03
    assert validated.retraining_reason == "continuous_loop"


@pytest.mark.asyncio
async def test_ml_model_history_contract_includes_extended_fields(monkeypatch):
    async def _fake_get_ml_model_history(limit=20, status=None):
        return {
            "models": [
                {
                    "version_id": "mt_1",
                    "status": "champion",
                    "model_type": "multi_target",
                    "feature_set_version": "v3",
                    "target_names": ["density"],
                    "training_samples": 124,
                    "test_metrics": {"density": {"rmse": 0.03}},
                    "recommendation_metrics": {
                        "feasibility_rate": 0.8,
                        "top_k_hit_rate": 0.7,
                        "calibration_ece": 0.08,
                        "ood_precision": 0.6,
                    },
                    "model_artifact_path": "models/registry/mt_1/model",
                    "triggered_by": "active_learning",
                    "retraining_reason": "active_learning",
                }
            ]
        }

    monkeypatch.setattr(
        "features.mlops.service.get_ml_model_history",
        _fake_get_ml_model_history,
    )

    payload = await get_ml_model_history()
    validated = TypeAdapter(MLModelHistoryResponse).validate_python(payload)

    assert len(validated.models) == 1
    assert validated.models[0].retraining_reason == "active_learning"
    assert validated.models[0].test_metrics["density"]["rmse"] == 0.03


@pytest.mark.asyncio
async def test_structural_evaluate_endpoint_maps_winner(monkeypatch):
    """A2: POST /ml/structural/evaluate가 viz 래퍼 결과를 그대로 반환."""
    import features.common as common_mod
    from api.schemas.ml_visualization import (
        StructuralEvalRequest,
        StructuralEvalResponse,
        StructuralModelEval,
    )
    from features.mlops.router import evaluate_structural_v7

    async def _fake_async(fn):
        return fn(object())  # 세션 불필요 — viz 래퍼를 직접 호출

    monkeypatch.setattr(common_mod, "run_in_session_async", _fake_async)
    monkeypatch.setattr(
        "features.mlops.visualization_service.run_structural_eval",
        lambda *a, **k: StructuralEvalResponse(
            target="density",
            n_samples=165,
            n_repeats=3,
            models={
                "xgboost": StructuralModelEval(rmse_mean=0.02, rmse_std=0.003, per_repeat=[0.02]),
                "random_forest": StructuralModelEval(rmse_mean=0.03, rmse_std=0.004, per_repeat=[0.03]),
            },
            winner="xgboost",
        ),
    )
    out = await evaluate_structural_v7(StructuralEvalRequest(target="density", n_repeats=3))
    assert out.winner == "xgboost"
    assert set(out.models) == {"xgboost", "random_forest"}


@pytest.mark.asyncio
async def test_structural_train_endpoint_defaults_dry_run(monkeypatch):
    """A2: POST /ml/structural/train 기본은 register=False(dry-run)."""
    import features.common as common_mod
    from api.schemas.ml_visualization import StructuralTrainRequest, StructuralTrainResponse
    from features.mlops.router import train_structural_v7

    captured: dict = {}

    async def _fake_async(fn):
        return fn(object())

    def _fake_train(session, *, targets, register):
        captured["register"] = register
        captured["targets"] = targets
        return StructuralTrainResponse(
            targets_trained=["density"],
            training_samples=132,
            holdout_samples=33,
            promoted=False,
            model_types={"density": "xgboost"},
        )

    monkeypatch.setattr(common_mod, "run_in_session_async", _fake_async)
    monkeypatch.setattr(
        "features.mlops.visualization_service.run_structural_train", _fake_train
    )
    out = await train_structural_v7(StructuralTrainRequest(targets=["density"]))
    assert captured["register"] is False  # 와이어 미지정 → 안전한 dry-run
    assert out.model_types == {"density": "xgboost"}
