"""Phase 0 tests for bulk/layered dataset isolation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.sql.elements import BinaryExpression

from contracts.policies.ml_policy import DEFAULT_ML_POLICY, FeatureSetVersion
from database.connection import close_db, init_memory_db
from database.models import ExperimentModel, MetricModel
from ml.data_loader import DataLoader, TargetVariable
from ml.feature_registry import FeatureRegistry
from ml.layered_data_loader import LayeredDataLoader


class _QuerySpy:
    def __init__(self) -> None:
        self.filter_args = None

    def filter(self, *args):
        self.filter_args = args
        return self

    def options(self, *_args, **_kwargs):
        return self

    def all(self):
        return []


@pytest.fixture()
def query_spy():
    return _QuerySpy()


def test_data_loader_filters_bulk_study_type(query_spy):
    loader = DataLoader()
    db_session = MagicMock()
    db_session.query.return_value = query_spy

    with patch("sqlalchemy.orm.joinedload", return_value=None):
        dataset = loader.load_from_database(
            db_session,
            target=TargetVariable.DENSITY,
            min_samples=1,
        )

    assert dataset is None
    assert any(
        isinstance(arg, BinaryExpression)
        and getattr(arg.left, "name", None) == "study_type"
        and getattr(arg.right, "value", None) == "bulk"
        for arg in query_spy.filter_args
    )


def test_layered_loader_filters_layer_bulkff_study_type(query_spy):
    loader = LayeredDataLoader()
    db_session = MagicMock()
    db_session.query.return_value = query_spy

    with patch("sqlalchemy.orm.joinedload", return_value=None):
        dataset = loader.load_from_database(
            db_session,
            target=TargetVariable.ADHESION,
            min_samples=1,
        )

    assert dataset is None
    assert any(
        isinstance(arg, BinaryExpression)
        and getattr(arg.left, "name", None) == "study_type"
        and getattr(arg.right, "value", None) == "layer_bulkff"
        for arg in query_spy.filter_args
    )


def test_data_loader_excludes_layered_rows_from_mixed_dataset():
    session = init_memory_db()
    try:
        bulk = ExperimentModel(
            exp_id="bulk_exp",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            study_type="bulk",
            status="completed",
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
            temperature_K=298.0,
            pressure_atm=1.0,
            target_atoms=100000,
        )
        layered = ExperimentModel(
            exp_id="layer_exp",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            study_type="layer_bulkff",
            status="completed",
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
            temperature_K=298.0,
            pressure_atm=1.0,
            target_atoms=100000,
        )
        session.add_all([bulk, layered])
        session.flush()
        session.add_all(
            [
                MetricModel(
                    experiment_id=bulk.id,
                    exp_id=bulk.exp_id,
                    metric_name="density",
                    value=1.01,
                    unit="g/cm3",
                    namespace="bulk_ff_gaff2",
                ),
                MetricModel(
                    experiment_id=layered.id,
                    exp_id=layered.exp_id,
                    metric_name="density",
                    value=1.99,
                    unit="g/cm3",
                    namespace="bulk_ff_gaff2",
                ),
            ]
        )
        session.commit()

        dataset = DataLoader().load_from_database(
            session,
            target=TargetVariable.DENSITY,
            ff_type="bulk_ff_gaff2",
            min_samples=1,
        )

        assert dataset is not None
        assert dataset.exp_ids == ["bulk_exp"]
        assert dataset.y.tolist() == [pytest.approx(1.01)]
    finally:
        session.close()
        close_db()


def test_data_loader_v5_falls_back_to_v3_when_context_coverage_is_insufficient(monkeypatch):
    session = init_memory_db()
    monkeypatch.setattr(DEFAULT_ML_POLICY, "min_molecule_level_samples_for_v3", 0)
    monkeypatch.setattr(DEFAULT_ML_POLICY, "min_additive_samples_for_v2", 0)
    try:
        for i in range(10):
            exp = ExperimentModel(
                exp_id=f"bulk_v5_fallback_{i}",
                run_tier="screening",
                ff_type="bulk_ff_gaff2",
                study_type="bulk",
                status="completed",
                comp_asphaltene_wt=20.0,
                comp_resin_wt=30.0,
                comp_aromatic_wt=35.0,
                comp_saturate_wt=15.0,
                temperature_K=298.0,
                pressure_atm=1.0,
                target_atoms=100000,
                binder_type="AAA1",
                aging_state="non_aging",
            )
            session.add(exp)
            session.flush()
            session.add(
                MetricModel(
                    experiment_id=exp.id,
                    exp_id=exp.exp_id,
                    metric_name="density",
                    value=1.0 + i * 0.001,
                    unit="g/cm3",
                    namespace="bulk_ff_gaff2",
                )
            )
        session.commit()

        dataset = DataLoader().load_from_database(
            session,
            target=TargetVariable.DENSITY,
            ff_type="bulk_ff_gaff2",
            min_samples=5,
            feature_set_version=FeatureSetVersion.V5,
        )

        assert dataset is not None
        assert dataset.metadata["requested_feature_set"] == "v5"
        assert dataset.metadata["actual_feature_set"] == "v3"
        assert dataset.n_features == FeatureRegistry.get_feature_count(FeatureSetVersion.V3)
    finally:
        session.close()
        close_db()


def test_data_loader_keeps_v5_when_context_coverage_is_sufficient(monkeypatch):
    session = init_memory_db()
    monkeypatch.setattr(DEFAULT_ML_POLICY, "min_molecule_level_samples_for_v3", 0)
    monkeypatch.setattr(DEFAULT_ML_POLICY, "min_additive_samples_for_v2", 0)
    try:
        for i in range(20):
            exp = ExperimentModel(
                exp_id=f"bulk_v5_ok_{i}",
                run_tier="screening",
                ff_type="bulk_ff_gaff2",
                study_type="bulk",
                status="completed",
                comp_asphaltene_wt=20.0,
                comp_resin_wt=30.0,
                comp_aromatic_wt=35.0,
                comp_saturate_wt=15.0,
                temperature_K=298.0,
                pressure_atm=1.0,
                target_atoms=100000,
                binder_type="AAA1" if i % 2 == 0 else "AAK1",
                aging_state="non_aging",
                tensile_strain_rate_1_per_ps=0.01 + i * 0.0001,
            )
            session.add(exp)
            session.flush()
            session.add(
                MetricModel(
                    experiment_id=exp.id,
                    exp_id=exp.exp_id,
                    metric_name="density",
                    value=1.0 + i * 0.001,
                    unit="g/cm3",
                    namespace="bulk_ff_gaff2",
                )
            )
        session.commit()

        dataset = DataLoader().load_from_database(
            session,
            target=TargetVariable.DENSITY,
            ff_type="bulk_ff_gaff2",
            min_samples=5,
            feature_set_version=FeatureSetVersion.V5,
        )

        assert dataset is not None
        assert dataset.metadata["requested_feature_set"] == "v5"
        assert dataset.metadata["actual_feature_set"] == "v5"
        assert dataset.n_features == FeatureRegistry.get_feature_count(FeatureSetVersion.V5)
    finally:
        session.close()
        close_db()
