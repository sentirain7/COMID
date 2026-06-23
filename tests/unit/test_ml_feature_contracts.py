"""Tests for canonical feature builder parity across training/serving paths."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np

from contracts.policies.ml_policy import FeatureSetVersion
from ml.feature_builder import FeatureBuildInput, build_feature_result, build_feature_results
from ml.feature_registry import FeatureRegistry
from ml.predictor import PredictionInputV2


def test_prediction_input_v2_matches_canonical_builder() -> None:
    input_v2 = PredictionInputV2(
        asphaltene=20.0,
        resin=30.0,
        aromatic=35.0,
        saturate=10.0,
        additive=5.0,
        additive_type="SBS",
        additive_mol_id="ADD_001",
    )

    built = build_feature_result(
        FeatureBuildInput(
            asphaltene_wt=20.0,
            resin_wt=30.0,
            aromatic_wt=35.0,
            saturate_wt=10.0,
            additive_wt=5.0,
            additive_type="SBS",
            additive_mol_id="ADD_001",
        ),
        FeatureSetVersion.V2,
    )

    np.testing.assert_allclose(input_v2.to_feature_vector(), built.values)
    assert built.feature_names == FeatureRegistry.get_features(FeatureSetVersion.V2)
    assert built.schema_hash == FeatureRegistry.compute_schema_hash(FeatureSetVersion.V2)


def test_api_layered_predictor_dispatch_uses_canonical_v3_v4_contracts(monkeypatch) -> None:
    from ml.multi_target import MultiTargetResult

    mock_mtp = MagicMock()
    mock_mtp.fitted_targets = ["density", "adhesion_energy"]
    mock_mtp.config.get_feature_set_for_target.side_effect = lambda name: (
        "v4" if name == "adhesion_energy" else "v3"
    )
    mock_mtp.predict_multi.return_value = MultiTargetResult(predictions={"density": 1.0})

    monkeypatch.setattr("api.deps._load_mtp", lambda: mock_mtp)

    from api.deps import get_layered_predictor_fn

    predictor = get_layered_predictor_fn(
        crystal_features={"crystal_hydroxyl_density": 0.5},
        amorphous_features={"amorphous_density": 0.95},
    )
    assert predictor is not None

    composition = {
        "asphaltene": 20.0,
        "resin": 30.0,
        "aromatic": 35.0,
        "saturate": 15.0,
    }
    predictor(composition)

    inputs_by_feature_set = mock_mtp.predict_multi.call_args.args[0]
    built = build_feature_results(
        FeatureBuildInput.from_prediction_composition(
            composition,
            crystal_features={"crystal_hydroxyl_density": 0.5},
            amorphous_features={"amorphous_density": 0.95},
        ),
        [FeatureSetVersion.V3, FeatureSetVersion.V4],
    )

    np.testing.assert_allclose(
        inputs_by_feature_set["v3"], built[FeatureSetVersion.V3.value].values.reshape(1, -1)
    )
    np.testing.assert_allclose(
        inputs_by_feature_set["v4"], built[FeatureSetVersion.V4.value].values.reshape(1, -1)
    )


def test_inverse_designer_ood_uses_canonical_v2_contract() -> None:
    from recommendation.inverse_designer import InverseDesigner
    from recommendation.property_targets import PropertyTarget, PropertyTargetSet

    detector = MagicMock()
    detector.detect.return_value = [MagicMock(is_ood=True)]

    designer = InverseDesigner(
        predictor_fn=lambda comp: {"viscosity": 1500.0},
        target_set=PropertyTargetSet(
            name="test",
            description="test",
            targets=[
                PropertyTarget(metric_name="viscosity", target_max=3000.0, direction="minimize")
            ],
        ),
        additive_type="SBS",
        ood_detector=detector,
    )

    composition = {
        "asphaltene": 20.0,
        "resin": 30.0,
        "aromatic": 35.0,
        "saturate": 10.0,
        "additive": 5.0,
    }
    assert designer._check_ood(composition) is True

    built = build_feature_result(
        FeatureBuildInput.from_prediction_composition(composition, additive_type="SBS"),
        FeatureSetVersion.V2,
    )
    np.testing.assert_allclose(detector.detect.call_args.args[0], built.values.reshape(1, -1))


def test_load_from_dict_sets_feature_schema_hash() -> None:
    from ml.data_loader import DataLoader, TargetVariable

    loader = DataLoader()
    dataset = loader.load_from_dict(
        [
            {
                "exp_id": "exp_1",
                "asphaltene_wt": 20.0,
                "resin_wt": 30.0,
                "aromatic_wt": 35.0,
                "saturate_wt": 15.0,
                "additive_wt": 0.0,
                "polar_fraction": 50.0,
                "nonpolar_fraction": 50.0,
                "asphaltene_resin_ratio": 20.0 / 30.0,
                "temperature_k": 298.0,
                "pressure_atm": 1.0,
                "target_atoms": 4000.0,
                "density": 1.02,
            }
        ],
        target=TargetVariable.DENSITY,
        feature_names=FeatureRegistry.get_features(FeatureSetVersion.V1),
    )

    assert dataset.metadata["feature_schema_hash"] == FeatureRegistry.compute_schema_hash(
        FeatureSetVersion.V1
    )


def test_v5_context_features_change_vector_for_same_composition() -> None:
    base = FeatureBuildInput.from_prediction_composition(
        {
            "asphaltene": 20.0,
            "resin": 30.0,
            "aromatic": 35.0,
            "saturate": 10.0,
            "additive": 5.0,
        }
    )
    changed = FeatureBuildInput.from_prediction_composition(
        {
            "asphaltene": 20.0,
            "resin": 30.0,
            "aromatic": 35.0,
            "saturate": 10.0,
            "additive": 5.0,
            "binder_type": "AAA1",
            "aging_state": "short_aging",
            "force_field_version": "gaff2_2.11",
            "tensile_strain_rate_1_per_ps": 0.02,
            "shear_rate_1_per_ps": 0.03,
        }
    )

    base_v5 = build_feature_result(base, FeatureSetVersion.V5)
    changed_v5 = build_feature_result(changed, FeatureSetVersion.V5)

    assert base_v5.feature_names == FeatureRegistry.get_features(FeatureSetVersion.V5)
    assert base_v5.schema_hash == changed_v5.schema_hash
    assert not np.allclose(base_v5.values, changed_v5.values)


def test_api_layered_predictor_includes_v6_when_stack_features_supplied(monkeypatch) -> None:
    from ml.multi_target import MultiTargetResult

    mock_mtp = MagicMock()
    mock_mtp.fitted_targets = ["adhesion_energy"]
    mock_mtp.config.get_feature_set_for_target.return_value = "v6"
    mock_mtp.predict_multi.return_value = MultiTargetResult(predictions={"adhesion_energy": 12.0})

    monkeypatch.setattr("api.deps._load_mtp", lambda: mock_mtp)

    from api.deps import get_layered_predictor_fn

    predictor = get_layered_predictor_fn(
        crystal_features={"crystal_hydroxyl_density": 0.5},
        amorphous_features={"amorphous_density": 0.95},
        stack_features={
            "stack_n_layers": 3.0,
            "stack_signature_code": 0.25,
            "layer_0_is_crystal": 1.0,
            "layer_1_is_binder": 1.0,
            "layer_2_is_crystal": 1.0,
        },
    )
    assert predictor is not None

    predictor(
        {
            "asphaltene": 20.0,
            "resin": 30.0,
            "aromatic": 35.0,
            "saturate": 15.0,
        }
    )

    inputs_by_feature_set = mock_mtp.predict_multi.call_args.args[0]
    assert "v6" in inputs_by_feature_set
    built_v6 = build_feature_result(
        FeatureBuildInput.from_prediction_composition(
            {
                "asphaltene": 20.0,
                "resin": 30.0,
                "aromatic": 35.0,
                "saturate": 15.0,
            },
            crystal_features={"crystal_hydroxyl_density": 0.5},
            amorphous_features={"amorphous_density": 0.95},
            stack_features={
                "stack_n_layers": 3.0,
                "stack_signature_code": 0.25,
                "layer_0_is_crystal": 1.0,
                "layer_1_is_binder": 1.0,
                "layer_2_is_crystal": 1.0,
            },
        ),
        FeatureSetVersion.V6,
    )
    np.testing.assert_allclose(inputs_by_feature_set["v6"], built_v6.values.reshape(1, -1))
