"""Tests for visualization_service dataset routing."""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

sys.path.insert(0, "src")


def _load_visualization_service_module():
    module_name = "_test_visualization_service"
    module_path = Path("src/features/mlops/visualization_service.py")
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.pop(module_name, None)
    spec.loader.exec_module(module)
    return module


def _coverage_dataset():
    from ml.data_loader import TrainingDataset

    return TrainingDataset(
        X=np.array(
            [
                [20.0, 30.0, 35.0, 15.0, 298.0],
                [18.0, 32.0, 34.0, 16.0, 323.0],
            ],
            dtype=float,
        ),
        y=np.array([1.0, 1.1], dtype=float),
        exp_ids=["exp1", "exp2"],
        feature_names=[
            "asphaltene_wt",
            "resin_wt",
            "aromatic_wt",
            "saturate_wt",
            "temperature_k",
        ],
        target_name="density",
        metadata={"actual_feature_set": "v1"},
    )


class TestCoverageUsesRouter:
    """Coverage diagnostics should use dataset_router, not DataLoader directly."""

    def test_uses_load_training_dataset(self):
        get_data_coverage = _load_visualization_service_module().get_data_coverage

        source = inspect.getsource(get_data_coverage)
        assert "load_training_dataset" in source, (
            "get_data_coverage should use load_training_dataset from dataset_router"
        )

    def test_no_direct_dataloader_instantiation(self):
        get_data_coverage = _load_visualization_service_module().get_data_coverage

        source = inspect.getsource(get_data_coverage)
        assert "DataLoader()" not in source, (
            "get_data_coverage should not instantiate DataLoader directly"
        )


def test_reconstruct_test_data_uses_dataset_router_runtime():
    from contracts.policies.ml_policy import FeatureSetVersion
    from ml.data_loader import TrainingDataset

    _reconstruct_test_data = _load_visualization_service_module()._reconstruct_test_data

    dataset = TrainingDataset(
        X=np.array([[1.0, 2.0], [3.0, 4.0]], dtype=float),
        y=np.array([10.0, 20.0], dtype=float),
        exp_ids=["exp1", "exp2"],
        feature_names=["f1", "f2"],
        target_name="work_of_separation",
    )
    predictor = MagicMock()
    predictor.predict_batch.return_value = [
        SimpleNamespace(
            predictions={"work_of_separation": 11.0},
            uncertainties={"work_of_separation": 0.5},
        )
    ]
    snapshot = {"test_exp_ids": ["exp1"]}
    champion_row = SimpleNamespace(feature_set_version="v4")

    with patch(
        "ml.dataset_router.load_training_dataset",
        autospec=True,
        return_value=dataset,
    ) as load_training_dataset:
        actual, predicted, exp_ids, uncertainties = _reconstruct_test_data(
            session=MagicMock(),
            predictor=predictor,
            snapshot=snapshot,
            target_name="work_of_separation",
            champion_row=champion_row,
        )

    kwargs = load_training_dataset.call_args.kwargs
    assert kwargs["target"].value == "work_of_separation"
    assert kwargs["requested_feature_set"] == FeatureSetVersion.V4
    assert kwargs["min_samples"] == 1
    assert exp_ids == ["exp1"]
    assert actual.tolist() == [10.0]
    assert predicted.tolist() == [11.0]
    assert uncertainties.tolist() == [0.5]


def test_reconstruct_test_data_source_has_no_direct_loader_instantiation():
    _reconstruct_test_data = _load_visualization_service_module()._reconstruct_test_data

    source = inspect.getsource(_reconstruct_test_data)
    assert "DataLoader()" not in source
    assert "LayeredDataLoader()" not in source
    assert "load_training_dataset" in source


def test_get_data_coverage_exposes_method_diagnostics_from_ssot():
    from contracts.schema_enums import EIntraMethod

    get_data_coverage = _load_visualization_service_module().get_data_coverage

    session = MagicMock()
    session.query.return_value.filter.return_value.count.return_value = 7
    dataset = _coverage_dataset()

    with (
        patch(
            "api.deps._resolve_champion_e_intra_method",
            autospec=True,
            return_value=EIntraMethod.SINGLE_MOLECULE_VACUUM_EXTENDED_CUTOFF.value,
        ) as resolve_champion,
        patch(
            "config.dashboard_settings.resolve_submission_e_intra_method",
            autospec=True,
            return_value=EIntraMethod.SINGLE_MOLECULE_VACUUM,
        ) as resolve_submission_default,
        patch(
            "ml.dataset_router.load_training_dataset",
            autospec=True,
            return_value=dataset,
        ) as load_training_dataset,
    ):
        response = get_data_coverage(session)

    resolve_champion.assert_called_once_with(session, strict=True)
    resolve_submission_default.assert_called_once_with()
    assert response.champion_e_intra_method == (
        EIntraMethod.SINGLE_MOLECULE_VACUUM_EXTENDED_CUTOFF.value
    )
    assert response.e_intra_method == response.champion_e_intra_method
    assert response.submission_default_e_intra_method == (EIntraMethod.SINGLE_MOLECULE_VACUUM.value)
    assert response.e_intra_method_mismatch is True
    assert response.method_resolution_status == "champion_lineage"

    forwarded_methods = [
        call.kwargs.get("e_intra_method") for call in load_training_dataset.call_args_list
    ]
    assert forwarded_methods
    assert set(forwarded_methods) == {EIntraMethod.SINGLE_MOLECULE_VACUUM_EXTENDED_CUTOFF.value}


def test_get_data_coverage_reports_submission_default_without_overriding_cold_start():
    from contracts.schema_enums import EIntraMethod

    get_data_coverage = _load_visualization_service_module().get_data_coverage

    session = MagicMock()
    session.query.return_value.filter.return_value.count.return_value = 3
    dataset = _coverage_dataset()

    with (
        patch(
            "api.deps._resolve_champion_e_intra_method",
            autospec=True,
            return_value=None,
        ),
        patch(
            "config.dashboard_settings.resolve_submission_e_intra_method",
            autospec=True,
            return_value=EIntraMethod.SINGLE_MOLECULE_VACUUM_EXTENDED_CUTOFF,
        ),
        patch(
            "ml.dataset_router.load_training_dataset",
            autospec=True,
            return_value=dataset,
        ) as load_training_dataset,
    ):
        response = get_data_coverage(session)

    assert response.champion_e_intra_method is None
    assert response.e_intra_method is None
    assert response.submission_default_e_intra_method == (
        EIntraMethod.SINGLE_MOLECULE_VACUUM_EXTENDED_CUTOFF.value
    )
    assert response.e_intra_method_mismatch is False
    assert response.method_resolution_status == "cold_start_no_champion"

    forwarded_methods = [
        call.kwargs.get("e_intra_method") for call in load_training_dataset.call_args_list
    ]
    assert forwarded_methods
    assert set(forwarded_methods) == {None}
