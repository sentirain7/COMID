"""Tests for per-target feature selection."""

import tempfile
from pathlib import Path

import numpy as np

from ml.feature_selector import PerTargetFeatureSelector


class TestPerTargetFeatureSelector:
    def test_select_basic(self) -> None:
        selector = PerTargetFeatureSelector()
        importances = {"f0": 0.5, "f1": 0.3, "f2": 0.1, "f3": 0.05, "f4": 0.05}
        feature_names = ["f0", "f1", "f2", "f3", "f4"]

        mask = selector.select(
            "density",
            importances,
            feature_names,
            min_features=2,
            importance_threshold=0.80,
        )
        # f0 (0.5) + f1 (0.3) = 0.8 → covers 80%
        assert len(mask) >= 2
        assert 0 in mask  # f0
        assert 1 in mask  # f1

    def test_min_features_enforced(self) -> None:
        selector = PerTargetFeatureSelector()
        importances = {"f0": 0.99, "f1": 0.005, "f2": 0.005}
        feature_names = ["f0", "f1", "f2"]

        mask = selector.select(
            "density",
            importances,
            feature_names,
            min_features=3,
            importance_threshold=0.50,
        )
        assert len(mask) == 3

    def test_apply_mask(self) -> None:
        selector = PerTargetFeatureSelector()
        selector._masks["density"] = np.array([0, 2, 4])

        X = np.arange(20).reshape(4, 5)
        X_sub = selector.apply_mask("density", X)
        assert X_sub.shape == (4, 3)
        np.testing.assert_array_equal(X_sub[:, 0], X[:, 0])
        np.testing.assert_array_equal(X_sub[:, 1], X[:, 2])

    def test_apply_mask_unknown_target(self) -> None:
        selector = PerTargetFeatureSelector()
        X = np.zeros((2, 3))
        assert selector.apply_mask("unknown", X) is None

    def test_save_load_roundtrip(self) -> None:
        selector = PerTargetFeatureSelector()
        selector._masks = {
            "density": np.array([0, 1, 3]),
            "viscosity": np.array([2, 4]),
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "masks.json"
            selector.save(path)

            loaded = PerTargetFeatureSelector()
            loaded.load(path)

            assert set(loaded.masks.keys()) == {"density", "viscosity"}
            np.testing.assert_array_equal(loaded.masks["density"], [0, 1, 3])
            np.testing.assert_array_equal(loaded.masks["viscosity"], [2, 4])

    def test_to_dict_from_dict(self) -> None:
        selector = PerTargetFeatureSelector()
        selector._masks = {"density": np.array([1, 3, 5])}

        d = selector.to_dict()
        assert d == {"density": [1, 3, 5]}

        restored = PerTargetFeatureSelector.from_dict(d)
        np.testing.assert_array_equal(restored.masks["density"], [1, 3, 5])

    def test_zero_importance_keeps_all(self) -> None:
        selector = PerTargetFeatureSelector()
        importances = {"f0": 0.0, "f1": 0.0, "f2": 0.0}
        feature_names = ["f0", "f1", "f2"]

        mask = selector.select("density", importances, feature_names)
        assert len(mask) == 3
