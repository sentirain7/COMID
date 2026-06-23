"""Tests for v15 trainable target promotion: 4 new ML targets."""

import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, "src")

from contracts.policies.metrics import DEFAULT_METRICS_REGISTRY
from contracts.policies.ml_policy import (
    FeatureSetVersion,
    TargetComparisonWeights,
    TargetFeatureSetMapping,
)
from ml.data_loader import TargetVariable


class TestTrainableContract:
    """Verify 4 new metrics are trainable, Tg is not."""

    def test_rdf_coordination_number_trainable(self):
        d = DEFAULT_METRICS_REGISTRY.get_definition("rdf_coordination_number")
        assert d is not None and d.trainable is True

    def test_e_inter_total_trainable(self):
        d = DEFAULT_METRICS_REGISTRY.get_definition("e_inter_total")
        assert d is not None and d.trainable is True

    def test_ductility_trainable(self):
        d = DEFAULT_METRICS_REGISTRY.get_definition("ductility")
        assert d is not None and d.trainable is True

    def test_toughness_trainable(self):
        d = DEFAULT_METRICS_REGISTRY.get_definition("toughness")
        assert d is not None and d.trainable is True

    def test_tg_not_trainable(self):
        d = DEFAULT_METRICS_REGISTRY.get_definition("glass_transition_temperature_k")
        assert d is not None and d.trainable is False

    def test_trainable_count_14(self):
        trainable = TargetVariable.trainable()
        assert len(trainable) == 14, (
            f"Expected 14, got {len(trainable)}: {[t.value for t in trainable]}"
        )


class TestFeatureSetMapping:
    """Verify bulk→V3, layered→V4 routing."""

    def test_bulk_targets_v3(self):
        m = TargetFeatureSetMapping()
        assert m.get_version("rdf_coordination_number") == FeatureSetVersion.V3
        assert m.get_version("e_inter_total") == FeatureSetVersion.V3

    def test_layered_targets_v4(self):
        m = TargetFeatureSetMapping()
        assert m.get_version("ductility") == FeatureSetVersion.V4
        assert m.get_version("toughness") == FeatureSetVersion.V4


class TestComparisonWeights:
    """New targets have weight 0.0, existing unchanged."""

    def test_new_weights_zero(self):
        w = TargetComparisonWeights()
        for name in ["rdf_coordination_number", "e_inter_total", "ductility", "toughness"]:
            assert w.get_weight(name) == 0.0, f"{name} weight should be 0.0"

    def test_existing_weights_unchanged(self):
        w = TargetComparisonWeights()
        assert w.density == 0.30
        assert w.cohesive_energy_density == 0.20
        assert w.viscosity == 0.10


class TestDatasetRouterRouting:
    """Verify bulk targets → DataLoader, layered → LayeredDataLoader."""

    def test_bulk_rdf_coordination(self):
        with patch("ml.data_loader.DataLoader") as mock_dl:
            mock_dl.return_value.load_from_database.return_value = None
            from ml.dataset_router import load_training_dataset

            load_training_dataset(
                MagicMock(), TargetVariable.RDF_COORDINATION_NUMBER, min_samples=1
            )
            mock_dl.return_value.load_from_database.assert_called_once()

    def test_layered_ductility(self):
        with patch("ml.layered_data_loader.LayeredDataLoader") as mock_ll:
            mock_ll.return_value.load_from_database.return_value = None
            from ml.dataset_router import load_training_dataset

            load_training_dataset(MagicMock(), TargetVariable.DUCTILITY, min_samples=1)
            mock_ll.return_value.load_from_database.assert_called_once()
