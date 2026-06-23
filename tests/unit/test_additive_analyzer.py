"""Tests for AdditiveEffectivenessAnalyzer using production implementation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from orchestrator.additive_analyzer import AdditiveEffectivenessAnalyzer


def _make_analyzer(record_map: dict[str, object], metric_map: dict[tuple[str, str], object]):
    exp_repo = MagicMock()
    metric_repo = MagicMock()

    exp_repo.get_by_id.side_effect = lambda exp_id: record_map.get(exp_id)
    metric_repo.get_by_name.side_effect = lambda exp_id, metric_name: metric_map.get(
        (exp_id, metric_name)
    )

    return AdditiveEffectivenessAnalyzer(exp_repo, metric_repo)


def test_group_by_treatment() -> None:
    record_map = {
        "c1": SimpleNamespace(additive_type=None, additive_wt=0.0),
        "c2": SimpleNamespace(additive_type=None, additive_wt=0.0),
        "t1": SimpleNamespace(additive_type="SiO2", additive_wt=5.0),
    }
    analyzer = _make_analyzer(record_map, {})
    groups = analyzer._group_by_treatment(["c1", "c2", "t1"])

    assert (None, 0.0) in groups
    assert ("SiO2", 5.0) in groups
    assert groups[(None, 0.0)] == ["c1", "c2"]


def test_delta_significant() -> None:
    exp_ids = ["c1", "c2", "c3", "t1", "t2", "t3"]
    record_map = {
        "c1": SimpleNamespace(additive_type=None, additive_wt=0.0),
        "c2": SimpleNamespace(additive_type=None, additive_wt=0.0),
        "c3": SimpleNamespace(additive_type=None, additive_wt=0.0),
        "t1": SimpleNamespace(additive_type="SiO2", additive_wt=5.0),
        "t2": SimpleNamespace(additive_type="SiO2", additive_wt=5.0),
        "t3": SimpleNamespace(additive_type="SiO2", additive_wt=5.0),
    }

    metric_map = {
        ("c1", "density"): SimpleNamespace(value=1.00),
        ("c2", "density"): SimpleNamespace(value=1.01),
        ("c3", "density"): SimpleNamespace(value=0.99),
        ("t1", "density"): SimpleNamespace(value=1.10),
        ("t2", "density"): SimpleNamespace(value=1.11),
        ("t3", "density"): SimpleNamespace(value=1.09),
    }

    analyzer = _make_analyzer(record_map, metric_map)
    result = analyzer.analyze_batch_job(exp_ids, metric_names=["density"])

    assert len(result.effects) == 1
    effect = result.effects[0]
    assert effect.additive_type == "SiO2"
    assert effect.significant is True
    assert effect.delta_mean > 0.05


def test_delta_not_significant() -> None:
    exp_ids = ["c1", "c2", "c3", "t1", "t2", "t3"]
    record_map = {
        "c1": SimpleNamespace(additive_type=None, additive_wt=0.0),
        "c2": SimpleNamespace(additive_type=None, additive_wt=0.0),
        "c3": SimpleNamespace(additive_type=None, additive_wt=0.0),
        "t1": SimpleNamespace(additive_type="SiO2", additive_wt=3.0),
        "t2": SimpleNamespace(additive_type="SiO2", additive_wt=3.0),
        "t3": SimpleNamespace(additive_type="SiO2", additive_wt=3.0),
    }

    metric_map = {
        ("c1", "density"): SimpleNamespace(value=1.00),
        ("c2", "density"): SimpleNamespace(value=1.01),
        ("c3", "density"): SimpleNamespace(value=0.99),
        ("t1", "density"): SimpleNamespace(value=1.00),
        ("t2", "density"): SimpleNamespace(value=1.01),
        ("t3", "density"): SimpleNamespace(value=0.99),
    }

    analyzer = _make_analyzer(record_map, metric_map)
    result = analyzer.analyze_batch_job(exp_ids, metric_names=["density"])

    assert len(result.effects) == 1
    effect = result.effects[0]
    assert effect.significant is False


def test_rank_additives() -> None:
    exp_ids = ["c1", "c2", "c3", "a1", "a2", "a3", "b1", "b2", "b3"]
    record_map = {
        "c1": SimpleNamespace(additive_type=None, additive_wt=0.0),
        "c2": SimpleNamespace(additive_type=None, additive_wt=0.0),
        "c3": SimpleNamespace(additive_type=None, additive_wt=0.0),
        "a1": SimpleNamespace(additive_type="SiO2", additive_wt=3.0),
        "a2": SimpleNamespace(additive_type="SiO2", additive_wt=3.0),
        "a3": SimpleNamespace(additive_type="SiO2", additive_wt=3.0),
        "b1": SimpleNamespace(additive_type="Lignin", additive_wt=3.0),
        "b2": SimpleNamespace(additive_type="Lignin", additive_wt=3.0),
        "b3": SimpleNamespace(additive_type="Lignin", additive_wt=3.0),
    }

    metric_map = {
        ("c1", "density"): SimpleNamespace(value=1.00),
        ("c2", "density"): SimpleNamespace(value=1.01),
        ("c3", "density"): SimpleNamespace(value=0.99),
        ("a1", "density"): SimpleNamespace(value=1.04),
        ("a2", "density"): SimpleNamespace(value=1.05),
        ("a3", "density"): SimpleNamespace(value=1.03),
        ("b1", "density"): SimpleNamespace(value=1.08),
        ("b2", "density"): SimpleNamespace(value=1.09),
        ("b3", "density"): SimpleNamespace(value=1.07),
    }

    analyzer = _make_analyzer(record_map, metric_map)
    result = analyzer.analyze_batch_job(exp_ids, metric_names=["density"])
    ranked = analyzer.rank_additives(result, target_metric="density", maximize=True)

    assert len(ranked) == 2
    assert ranked[0].delta_mean >= ranked[1].delta_mean


def test_ci_bounds() -> None:
    exp_ids = ["c1", "c2", "c3", "t1", "t2", "t3"]
    record_map = {
        "c1": SimpleNamespace(additive_type=None, additive_wt=0.0),
        "c2": SimpleNamespace(additive_type=None, additive_wt=0.0),
        "c3": SimpleNamespace(additive_type=None, additive_wt=0.0),
        "t1": SimpleNamespace(additive_type="SiO2", additive_wt=5.0),
        "t2": SimpleNamespace(additive_type="SiO2", additive_wt=5.0),
        "t3": SimpleNamespace(additive_type="SiO2", additive_wt=5.0),
    }
    metric_map = {
        ("c1", "density"): SimpleNamespace(value=1.00),
        ("c2", "density"): SimpleNamespace(value=1.01),
        ("c3", "density"): SimpleNamespace(value=0.99),
        ("t1", "density"): SimpleNamespace(value=1.10),
        ("t2", "density"): SimpleNamespace(value=1.11),
        ("t3", "density"): SimpleNamespace(value=1.09),
    }

    analyzer = _make_analyzer(record_map, metric_map)
    result = analyzer.analyze_batch_job(exp_ids, metric_names=["density"])
    effect = result.effects[0]

    assert effect.delta_ci_lower <= effect.delta_mean <= effect.delta_ci_upper
