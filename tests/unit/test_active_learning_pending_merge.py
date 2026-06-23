import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, "src")

from features.recommendations import active_learning


@pytest.mark.asyncio
async def test_get_pending_recommendations_merges_persistent_and_memory(monkeypatch):
    monkeypatch.setattr(
        "features.recommendations.pending_service.list_pending",
        lambda limit=200: [
            SimpleNamespace(
                id="prec-1",
                composition={"asphaltene": 20.0},
                predicted_properties={"density": 1.0},
                uncertainty={},
                status="pending",
            )
        ],
    )

    class _WF:
        def get_pending(self):
            return [
                SimpleNamespace(
                    id="mem-1",
                    composition={"asphaltene": 21.0},
                    predicted_properties={"density": 1.01},
                    uncertainty={},
                    validity_tags=[],
                    pareto_rank=1,
                    crowding_distance=0.0,
                    status=SimpleNamespace(value="pending"),
                )
            ]

    monkeypatch.setattr("features.recommendations.active_learning._get_al_workflow", lambda: _WF())

    result = await active_learning.get_pending_recommendations()
    ids = {item.id for item in result}
    assert ids == {"prec-1", "mem-1"}
