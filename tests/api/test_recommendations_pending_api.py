"""API response-model contract tests for pending recommendation endpoints."""

from __future__ import annotations

import sys

import pytest
from pydantic import TypeAdapter

sys.path.insert(0, "src")

from api.schemas import RecommendationDetailResponse, UnifiedRecommendation
from contracts.schema_enums import RecommendationMode, SimulationPriority
from features.recommendations.router import get_pending_detail, list_recent_pending


@pytest.mark.asyncio
async def test_recent_pending_contract(monkeypatch) -> None:
    monkeypatch.setattr(
        "features.recommendations.pending_service.list_recent",
        lambda limit=200: [
            {
                "id": "prec-1",
                "source": "quick",
                "status": "pending",
                "mode": RecommendationMode.KNOWN,
                "version": 2,
                "score": 0.8,
                "origin": "optimizer",
                "simulation_priority": SimulationPriority.SCREEN,
                "composition": {
                    "asphaltene": 20.0,
                    "resin": 30.0,
                    "aromatic": 35.0,
                    "saturate": 15.0,
                },
                "predicted_properties": {"density": 1.01},
                "uncertainty": {"density": 0.03},
                "result_metrics": {"density": 1.02},
                "prediction_error": {"density": 0.01},
                "used_in_retraining": False,
            }
        ],
    )

    payload = await list_recent_pending()
    validated = TypeAdapter(list[UnifiedRecommendation]).validate_python(payload)

    assert len(validated) == 1
    assert validated[0].mode == RecommendationMode.KNOWN
    assert validated[0].simulation_priority == SimulationPriority.SCREEN
    assert validated[0].result_metrics["density"] == pytest.approx(1.02)
    assert validated[0].prediction_error["density"] == pytest.approx(0.01)


@pytest.mark.asyncio
async def test_pending_detail_contract(monkeypatch) -> None:
    monkeypatch.setattr(
        "features.recommendations.pending_service.get_detail",
        lambda recommendation_id: {
            "id": recommendation_id,
            "source": "quick",
            "status": "pending",
            "mode": RecommendationMode.KNOWN,
            "version": 1,
            "score": 0.7,
            "origin": "optimizer",
            "simulation_priority": SimulationPriority.CONFIRM,
            "composition": {
                "asphaltene": 20.0,
                "resin": 30.0,
                "aromatic": 35.0,
                "saturate": 15.0,
            },
            "predicted_properties": {"density": 1.01},
            "uncertainty": {"density": 0.03},
            "result_metrics": {"density": 1.02},
            "prediction_error": {"density": 0.01},
            "used_in_retraining": True,
            "pg_decision": {"pg_label": "PG 76-22"},
            "decision_trace": [{"step": "rank", "score": 0.7}],
            "source_records": [{"source_type": "weather", "source_name": "open-meteo"}],
            "literature_refs": [{"title": "Binder paper", "doi": "10.1000/example"}],
        },
    )

    payload = await get_pending_detail("prec-1")
    validated = RecommendationDetailResponse.model_validate(payload)

    assert validated.mode == RecommendationMode.KNOWN
    assert validated.simulation_priority == SimulationPriority.CONFIRM
    assert validated.decision_trace[0]["step"] == "rank"
    assert validated.literature_refs[0]["doi"] == "10.1000/example"
