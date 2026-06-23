"""Tests for additive classification in metrics analytics."""

import asyncio
from datetime import datetime

import pytest

pytest.importorskip("fastapi")

from features.metrics.analytics import get_ced_by_additive


class _Exp:
    def __init__(
        self,
        exp_id: str,
        ff_type: str = "bulk_ff_gaff2",
        additive_mol_id: str | None = None,
        additive_type: str | None = None,
        additive_wt: float | None = None,
    ) -> None:
        self.exp_id = exp_id
        self.ff_type = ff_type
        self.additive_mol_id = additive_mol_id
        self.additive_type = additive_type
        self.additive_wt = additive_wt
        self.created_at = datetime.utcnow()
        self.temperature_K = 298.0


def test_get_ced_by_additive_uses_db_fields_only(monkeypatch):
    from features.metrics import analytics as module

    exps = {
        "exp_1": _Exp("exp_1", additive_mol_id="sbs_linear_01", additive_wt=3.0),
        "exp_2": _Exp("exp_2", additive_type="ppa", additive_wt=2.0),
        # exp_id includes additive-like token but DB fields are empty -> should remain "None"
        "exp_sbs_5wt_foo": _Exp("exp_sbs_5wt_foo"),
    }

    class FakeMetricRepository:
        def __init__(self, session):
            _ = session

        def get_values_by_metric(self, metric_name: str, namespace: str):
            _ = (metric_name, namespace)
            return [("exp_1", 100.0), ("exp_2", 110.0), ("exp_sbs_5wt_foo", 120.0)]

    class FakeExperimentRepository:
        def __init__(self, session):
            _ = session

        def get_by_id(self, exp_id: str):
            return exps.get(exp_id)

    def fake_run_in_session(fn):
        fn(object())

    monkeypatch.setattr(module, "run_in_session", fake_run_in_session)
    monkeypatch.setattr("database.repositories.metric_repo.MetricRepository", FakeMetricRepository)
    monkeypatch.setattr(
        "database.repositories.experiment_repo.ExperimentRepository",
        FakeExperimentRepository,
    )

    result = asyncio.run(get_ced_by_additive(ff_type="bulk_ff_gaff2"))
    points = {p["exp_id"]: p for p in result["points"]}

    assert points["exp_1"]["additive"] == "sbs_linear_01"
    assert points["exp_1"]["additive_wt"] == 3.0
    assert points["exp_2"]["additive"] == "PPA"
    assert points["exp_2"]["additive_wt"] == 2.0
    assert points["exp_sbs_5wt_foo"]["additive"] == "None"
    assert points["exp_sbs_5wt_foo"]["additive_wt"] == 0.0
