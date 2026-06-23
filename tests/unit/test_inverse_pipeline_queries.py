"""inverse_design_pipeline.queries 실 DB(in-memory) 통합 테스트 (P1, §4.5/§4.7)."""

from contracts.policies.inverse_pipeline import CompositionSimilarityPolicy
from database.models import ExperimentModel, MetricModel
from features.inverse_design_pipeline.queries import (
    count_training_labels,
    find_experiments_by_composition,
)

_POLICY = CompositionSimilarityPolicy()  # comp ±1.0wt, additive ±0.5wt, T ±5K


def _add_experiment(
    isolated_db_session,
    exp_id: str,
    *,
    status: str = "completed",
    asphaltene: float = 15.0,
    resin: float = 30.0,
    aromatic: float = 35.0,
    saturate: float = 20.0,
    additive_mol_id: str | None = None,
    additive_wt: float = 0.0,
    temperature_k: float = 293.0,
) -> ExperimentModel:
    exp = ExperimentModel(
        exp_id=exp_id,
        run_tier="screening",
        ff_type="bulk_ff",
        status=status,
        comp_asphaltene_wt=asphaltene,
        comp_resin_wt=resin,
        comp_aromatic_wt=aromatic,
        comp_saturate_wt=saturate,
        additive_mol_id=additive_mol_id,
        additive_wt=additive_wt,
        temperature_K=temperature_k,
    )
    isolated_db_session.add(exp)
    isolated_db_session.flush()
    return exp


def _add_metric(isolated_db_session, exp: ExperimentModel, metric_name: str, value: float | None):
    isolated_db_session.add(
        MetricModel(
            experiment_id=exp.id,
            exp_id=exp.exp_id,
            metric_name=metric_name,
            namespace="bulk_ff",
            value=value,
            unit="g/cm3",
        )
    )
    isolated_db_session.flush()


_BASE_COMP = {"asphaltene": 15.0, "resin": 30.0, "aromatic": 35.0, "saturate": 20.0}


class TestCountTrainingLabels:
    def test_counts_completed_scalar_labels_only(self, isolated_db_session):
        done = _add_experiment(isolated_db_session, "exp_done")
        running = _add_experiment(isolated_db_session, "exp_running", status="running")
        _add_metric(isolated_db_session, done, "density", 1.01)
        _add_metric(isolated_db_session, done, "rdf_curve", None)  # 배열 metric(value=None) 제외
        _add_metric(isolated_db_session, done, "viscosity", 250.0)  # 다른 metric 제외
        _add_metric(isolated_db_session, running, "density", 1.02)  # 미완료 실험 제외

        assert count_training_labels(isolated_db_session, "density") == 1
        assert count_training_labels(isolated_db_session, "rdf_curve") == 0

    def test_zero_when_no_labels(self, isolated_db_session):
        assert count_training_labels(isolated_db_session, "density") == 0


class TestFindExperimentsByComposition:
    def test_matches_within_tolerance(self, isolated_db_session):
        _add_experiment(isolated_db_session, "exp_near", asphaltene=15.5)  # +0.5 < ±1.0
        matches = find_experiments_by_composition(
            isolated_db_session,
            _BASE_COMP,
            additive_mol_id=None,
            additive_wt=0.0,
            temperature_k=293.0,
            policy=_POLICY,
        )
        assert [m.exp_id for m in matches] == ["exp_near"]

    def test_rejects_outside_composition_tolerance(self, isolated_db_session):
        _add_experiment(isolated_db_session, "exp_far", asphaltene=17.5)  # +2.5 > ±1.0
        matches = find_experiments_by_composition(
            isolated_db_session,
            _BASE_COMP,
            additive_mol_id=None,
            additive_wt=0.0,
            temperature_k=293.0,
            policy=_POLICY,
        )
        assert matches == []

    def test_rejects_non_completed(self, isolated_db_session):
        _add_experiment(isolated_db_session, "exp_pending", status="pending")
        matches = find_experiments_by_composition(
            isolated_db_session,
            _BASE_COMP,
            additive_mol_id=None,
            additive_wt=0.0,
            temperature_k=293.0,
            policy=_POLICY,
        )
        assert matches == []

    def test_rejects_outside_temperature_tolerance(self, isolated_db_session):
        _add_experiment(isolated_db_session, "exp_hot", temperature_k=313.0)  # +20K > ±5K
        matches = find_experiments_by_composition(
            isolated_db_session,
            _BASE_COMP,
            additive_mol_id=None,
            additive_wt=0.0,
            temperature_k=293.0,
            policy=_POLICY,
        )
        assert matches == []

    def test_no_additive_query_excludes_additive_experiments(self, isolated_db_session):
        _add_experiment(isolated_db_session, "exp_plain")
        _add_experiment(isolated_db_session, "exp_sbs", additive_mol_id="SBS_unit", additive_wt=3.0)
        matches = find_experiments_by_composition(
            isolated_db_session,
            _BASE_COMP,
            additive_mol_id=None,
            additive_wt=0.0,
            temperature_k=293.0,
            policy=_POLICY,
        )
        assert [m.exp_id for m in matches] == ["exp_plain"]

    def test_additive_query_matches_mol_id_and_wt(self, isolated_db_session):
        _add_experiment(isolated_db_session, "exp_plain")
        _add_experiment(
            isolated_db_session, "exp_sbs_3", additive_mol_id="SBS_unit", additive_wt=3.0
        )
        _add_experiment(
            isolated_db_session, "exp_sbs_9", additive_mol_id="SBS_unit", additive_wt=9.0
        )
        _add_experiment(isolated_db_session, "exp_evo", additive_mol_id="EVO_unit", additive_wt=3.0)
        matches = find_experiments_by_composition(
            isolated_db_session,
            _BASE_COMP,
            additive_mol_id="SBS_unit",
            additive_wt=3.2,  # ±0.5 → 3.0 매칭, 9.0 제외
            temperature_k=293.0,
            policy=_POLICY,
        )
        assert [m.exp_id for m in matches] == ["exp_sbs_3"]

    def test_limit_and_recency_order(self, isolated_db_session):
        for i in range(8):
            _add_experiment(isolated_db_session, f"exp_{i:02d}")
        matches = find_experiments_by_composition(
            isolated_db_session,
            _BASE_COMP,
            additive_mol_id=None,
            additive_wt=0.0,
            temperature_k=293.0,
            policy=_POLICY,
        )
        assert len(matches) == _POLICY.limit
        assert matches[0].exp_id == "exp_07"  # 최신순
