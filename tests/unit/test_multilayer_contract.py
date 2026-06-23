"""Tests for V6 stack-aware layered feature contract."""

from __future__ import annotations

import numpy as np

from contracts.policies.ml_policy import DEFAULT_ML_POLICY, FeatureSetVersion
from database.connection import close_db, init_memory_db
from database.models import ExperimentModel, LayeredExperimentSourceModel, MetricModel
from ml.data_loader import TargetVariable
from ml.feature_builder import FeatureBuildInput, build_feature_result
from ml.feature_registry import FeatureRegistry
from ml.layered_data_loader import LayeredDataLoader


def _add_layered_experiment(
    session,
    *,
    exp_id: str,
    metric_value: float,
    layers: list[tuple[int, str, str]],
) -> None:
    exp = ExperimentModel(
        exp_id=exp_id,
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
        binder_type="AAA1",
        aging_state="non_aging",
        tensile_strain_rate_1_per_ps=0.01,
    )
    session.add(exp)
    session.flush()
    session.add(
        MetricModel(
            experiment_id=exp.id,
            exp_id=exp.exp_id,
            metric_name="adhesion_energy",
            value=metric_value,
            unit="kcal/mol",
            namespace="layer_bulkff",
        )
    )
    for layer_index, source_type, source_id in layers:
        session.add(
            LayeredExperimentSourceModel(
                exp_id=exp.exp_id,
                layer_index=layer_index,
                source_type=source_type,
                source_id=source_id,
            )
        )
    session.commit()


def test_v6_feature_contract_extends_v5_with_stack_metadata() -> None:
    v5 = FeatureRegistry.get_features(FeatureSetVersion.V5)
    v6 = FeatureRegistry.get_features(FeatureSetVersion.V6)

    assert len(v6) == DEFAULT_ML_POLICY.v6_feature_count == 93
    assert v6[: len(v5)] == v5
    assert "stack_signature_code" in v6
    assert "layer_4_gap_after_norm" in v6


def test_v6_builder_distinguishes_stack_order_for_same_composition() -> None:
    base_kwargs = {
        "asphaltene_wt": 20.0,
        "resin_wt": 30.0,
        "aromatic_wt": 35.0,
        "saturate_wt": 15.0,
        "additive_wt": 0.0,
        "binder_type": "AAA1",
        "aging_state": "non_aging",
        "tensile_strain_rate_1_per_ps": 0.01,
    }
    built_a = build_feature_result(
        FeatureBuildInput(
            **base_kwargs,
            stack_features={
                "stack_n_layers": 3.0,
                "stack_signature_code": 0.11,
                "layer_0_is_crystal": 1.0,
                "layer_1_is_binder": 1.0,
                "layer_2_is_crystal": 1.0,
            },
        ),
        FeatureSetVersion.V6,
    )
    built_b = build_feature_result(
        FeatureBuildInput(
            **base_kwargs,
            stack_features={
                "stack_n_layers": 3.0,
                "stack_signature_code": 0.22,
                "layer_0_is_binder": 1.0,
                "layer_1_is_crystal": 1.0,
                "layer_2_is_binder": 1.0,
            },
        ),
        FeatureSetVersion.V6,
    )

    assert built_a.schema_hash == built_b.schema_hash
    assert not np.allclose(built_a.values, built_b.values)


def test_layered_loader_v6_falls_back_to_v4_with_insufficient_stack_coverage(monkeypatch):
    session = init_memory_db()
    monkeypatch.setattr(DEFAULT_ML_POLICY, "min_layered_samples_for_v6", 2)
    monkeypatch.setattr(DEFAULT_ML_POLICY, "min_three_plus_layer_samples_for_v6", 1)
    monkeypatch.setattr(DEFAULT_ML_POLICY, "min_distinct_stack_signatures_for_v6", 1)
    try:
        _add_layered_experiment(
            session,
            exp_id="v6_fallback_1",
            metric_value=10.0,
            layers=[
                (0, "crystal_structure", "c1"),
                (1, "binder_cell", "b1"),
            ],
        )
        _add_layered_experiment(
            session,
            exp_id="v6_fallback_2",
            metric_value=11.0,
            layers=[
                (0, "crystal_structure", "c2"),
                (1, "binder_cell", "b2"),
            ],
        )

        dataset = LayeredDataLoader().load_from_database(
            session,
            target=TargetVariable.ADHESION,
            min_samples=2,
            feature_set_version=FeatureSetVersion.V6,
        )

        assert dataset is not None
        assert dataset.metadata["requested_feature_set"] == "v6"
        assert dataset.metadata["actual_feature_set"] == "v4"
        assert dataset.n_features == FeatureRegistry.get_feature_count(FeatureSetVersion.V4)
    finally:
        session.close()
        close_db()


def test_layered_loader_keeps_v6_and_encodes_different_stack_orders(monkeypatch):
    session = init_memory_db()
    monkeypatch.setattr(DEFAULT_ML_POLICY, "min_layered_samples_for_v6", 2)
    monkeypatch.setattr(DEFAULT_ML_POLICY, "min_three_plus_layer_samples_for_v6", 2)
    monkeypatch.setattr(DEFAULT_ML_POLICY, "min_distinct_stack_signatures_for_v6", 2)
    try:
        _add_layered_experiment(
            session,
            exp_id="v6_keep_1",
            metric_value=10.0,
            layers=[
                (0, "crystal_structure", "c1"),
                (1, "binder_cell", "b1"),
                (2, "crystal_structure", "c2"),
            ],
        )
        _add_layered_experiment(
            session,
            exp_id="v6_keep_2",
            metric_value=11.0,
            layers=[
                (0, "binder_cell", "b3"),
                (1, "crystal_structure", "c3"),
                (2, "binder_cell", "b4"),
            ],
        )

        dataset = LayeredDataLoader().load_from_database(
            session,
            target=TargetVariable.ADHESION,
            min_samples=2,
            feature_set_version=FeatureSetVersion.V6,
        )

        assert dataset is not None
        assert dataset.metadata["requested_feature_set"] == "v6"
        assert dataset.metadata["actual_feature_set"] == "v6"
        assert dataset.n_features == FeatureRegistry.get_feature_count(FeatureSetVersion.V6)
        assert not np.allclose(dataset.X[0], dataset.X[1])
    finally:
        session.close()
        close_db()
