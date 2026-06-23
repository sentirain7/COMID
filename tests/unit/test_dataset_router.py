"""Tests for ML dataset router — bulk/layered routing and downgrade protection."""

import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, "src")

from contracts.policies.ml_policy import FeatureSetVersion
from ml.data_loader import TargetVariable


class TestRouterBulkTarget:
    """Bulk targets should use DataLoader."""

    def test_density_uses_data_loader(self):
        with patch("ml.data_loader.DataLoader") as mock_dl:
            mock_dl.return_value.load_from_database.return_value = None
            from ml.dataset_router import load_training_dataset

            load_training_dataset(MagicMock(), TargetVariable.DENSITY, min_samples=1)
            mock_dl.return_value.load_from_database.assert_called_once()


class TestRouterLayeredTarget:
    """Layered targets should use LayeredDataLoader."""

    def test_work_of_separation_uses_layered_loader(self):
        with patch("ml.layered_data_loader.LayeredDataLoader") as mock_ll:
            mock_ll.return_value.load_from_database.return_value = None
            from ml.dataset_router import load_training_dataset

            load_training_dataset(MagicMock(), TargetVariable.WORK_OF_SEPARATION, min_samples=1)
            mock_ll.return_value.load_from_database.assert_called_once()


class TestRouterDowngradeProtection:
    """Layered targets should never be downgraded below V4."""

    def test_layered_target_with_v3_request_stays_v4(self):
        with patch("ml.layered_data_loader.LayeredDataLoader") as mock_ll:
            mock_ll.return_value.load_from_database.return_value = None
            from ml.dataset_router import load_training_dataset

            load_training_dataset(
                MagicMock(),
                TargetVariable.WORK_OF_SEPARATION,
                requested_feature_set=FeatureSetVersion.V3,
                min_samples=1,
            )
            call_args = mock_ll.return_value.load_from_database.call_args
            fsv = call_args.kwargs.get(
                "feature_set_version", call_args[1].get("feature_set_version")
            )
            assert fsv == FeatureSetVersion.V4

    def test_layered_target_with_v6_request_uses_v6(self):
        with patch("ml.layered_data_loader.LayeredDataLoader") as mock_ll:
            mock_ll.return_value.load_from_database.return_value = None
            from ml.dataset_router import load_training_dataset

            load_training_dataset(
                MagicMock(),
                TargetVariable.WORK_OF_SEPARATION,
                requested_feature_set=FeatureSetVersion.V6,
                min_samples=1,
            )
            call_args = mock_ll.return_value.load_from_database.call_args
            fsv = call_args.kwargs.get(
                "feature_set_version", call_args[1].get("feature_set_version")
            )
            assert fsv == FeatureSetVersion.V6
