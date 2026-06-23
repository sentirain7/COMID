"""Tests for MultiTargetPredictor (Phase 5.2).

Covers config defaults, multi-target training, prediction with uncertainty,
ensemble save/load, and v1 backward compatibility.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from ml.data_loader import TargetVariable, TrainingDataset
from ml.models import EnsemblePredictor, ModelConfig, ModelType, PropertyPredictor
from ml.multi_target import MultiTargetConfig, MultiTargetPredictor, MultiTargetResult


def _has_sklearn() -> bool:
    try:
        import sklearn  # noqa: F401

        return True
    except ImportError:
        return False


_sklearn_skip = pytest.mark.skipif(not _has_sklearn(), reason="sklearn not installed")


# ── Fixtures ────────────────────────────────────────────────────────


def _make_dataset(target_name: str, n: int = 50, n_features: int = 5) -> TrainingDataset:
    """Create a simple synthetic training dataset."""
    rng = np.random.RandomState(42)
    X = rng.randn(n, n_features)
    y = X[:, 0] * 2.0 + X[:, 1] + rng.randn(n) * 0.1
    return TrainingDataset(
        X=X,
        y=y,
        exp_ids=[f"exp_{i:04d}" for i in range(n)],
        feature_names=[f"f{i}" for i in range(n_features)],
        target_name=target_name,
    )


# ── Tests ───────────────────────────────────────────────────────────


class TestMultiTargetConfig:
    def test_config_defaults(self):
        """Default config has DENSITY and CED targets."""
        config = MultiTargetConfig()
        assert TargetVariable.DENSITY in config.targets
        assert TargetVariable.CED in config.targets
        assert config.ensemble_size >= 1

    def test_get_config_for_target_default(self):
        """Returns ModelConfig with default model type when no override."""
        config = MultiTargetConfig(model_type=ModelType.XGBOOST)
        mc = config.get_config_for_target(TargetVariable.DENSITY)
        assert mc.model_type == ModelType.XGBOOST
        assert mc.target_name == "density"

    def test_get_config_for_target_override(self):
        """Per-target override is respected."""
        override = ModelConfig(model_type=ModelType.LINEAR, target_name="density")
        config = MultiTargetConfig(target_configs={"density": override})
        mc = config.get_config_for_target(TargetVariable.DENSITY)
        assert mc.model_type == ModelType.LINEAR


class TestMultiTargetPredictor:
    @_sklearn_skip
    def test_train_multiple_targets(self):
        """Training on 2+ targets creates one ensemble per target."""
        datasets = {
            "density": _make_dataset("density"),
            "cohesive_energy_density": _make_dataset("cohesive_energy_density"),
        }
        config = MultiTargetConfig(
            targets=[TargetVariable.DENSITY, TargetVariable.CED],
            ensemble_size=2,
            model_type=ModelType.LINEAR,
        )
        predictor = MultiTargetPredictor(config=config)
        results = predictor.train(datasets)

        assert "density" in results
        assert "cohesive_energy_density" in results
        assert results["density"].ensemble_size == 2
        assert len(predictor.fitted_targets) == 2

    @_sklearn_skip
    def test_predict_all_targets(self):
        """Prediction returns values for all trained targets."""
        datasets = {
            "density": _make_dataset("density"),
            "cohesive_energy_density": _make_dataset("cohesive_energy_density"),
        }
        config = MultiTargetConfig(
            targets=[TargetVariable.DENSITY, TargetVariable.CED],
            ensemble_size=2,
            model_type=ModelType.LINEAR,
        )
        predictor = MultiTargetPredictor(config=config)
        predictor.train(datasets)

        X_test = np.random.randn(1, 5)
        result = predictor.predict(X_test)

        assert isinstance(result, MultiTargetResult)
        assert "density" in result.predictions
        assert "cohesive_energy_density" in result.predictions

    @_sklearn_skip
    def test_predict_with_uncertainty(self):
        """Prediction includes uncertainty and CI fields."""
        datasets = {"density": _make_dataset("density")}
        config = MultiTargetConfig(
            targets=[TargetVariable.DENSITY],
            ensemble_size=3,
            model_type=ModelType.LINEAR,
        )
        predictor = MultiTargetPredictor(config=config)
        predictor.train(datasets)

        X_test = np.random.randn(1, 5)
        result = predictor.predict(X_test)

        assert "density" in result.uncertainties
        assert result.uncertainties["density"] >= 0.0
        assert "density" in result.confidence_intervals
        ci_lo, ci_hi = result.confidence_intervals["density"]
        assert ci_lo <= result.predictions["density"] <= ci_hi

    @_sklearn_skip
    def test_v1_backward_compat(self):
        """Existing PropertyPredictor single-target workflow still works."""
        config = ModelConfig(model_type=ModelType.LINEAR, target_name="density")
        predictor = PropertyPredictor(config)

        rng = np.random.RandomState(42)
        X = rng.randn(30, 5)
        y = X[:, 0] + rng.randn(30) * 0.1
        predictor.fit(X, y)

        preds = predictor.predict(X[:5])
        assert preds.shape == (5,)
        assert predictor.is_fitted

    @_sklearn_skip
    def test_ensemble_save_and_load(self, tmp_path: Path):
        """EnsemblePredictor round-trips through save/load [FIX-5]."""
        rng = np.random.RandomState(42)
        X = rng.randn(30, 3)
        y = X[:, 0] * 2.0 + rng.randn(30) * 0.1

        predictors = []
        for i in range(3):
            cfg = ModelConfig(model_type=ModelType.LINEAR, random_state=42 + i)
            predictors.append(PropertyPredictor(cfg))

        ensemble = EnsemblePredictor(predictors)
        ensemble.fit(X, y)

        # Save
        save_dir = tmp_path / "ensemble"
        ensemble.save(save_dir)

        # Verify files
        assert (save_dir / "ensemble_meta.json").exists()

        # Load
        loaded = EnsemblePredictor.load(save_dir)
        assert loaded.is_fitted
        assert len(loaded.predictors) == 3

        # Predictions should match
        preds_orig = ensemble.predict(X[:5])
        preds_loaded = loaded.predict(X[:5])
        np.testing.assert_allclose(preds_orig, preds_loaded, rtol=1e-5)

    @_sklearn_skip
    def test_partial_target_data(self):
        """Training with missing target data doesn't crash."""
        datasets = {
            "density": _make_dataset("density"),
            # "cohesive_energy_density" missing
        }
        config = MultiTargetConfig(
            targets=[TargetVariable.DENSITY, TargetVariable.CED],
            ensemble_size=2,
            model_type=ModelType.LINEAR,
        )
        predictor = MultiTargetPredictor(config=config)
        results = predictor.train(datasets)

        assert "density" in results
        assert "cohesive_energy_density" not in results
        assert "density" in predictor.fitted_targets

    @_sklearn_skip
    def test_predict_multi_dispatches_per_target_feature_sets(self):
        """predict_multi should route each target to its configured feature contract."""
        datasets = {
            "density": _make_dataset("density", n_features=5),
            "viscosity": _make_dataset("viscosity", n_features=6),
        }
        config = MultiTargetConfig(
            targets=[TargetVariable.DENSITY, TargetVariable.VISCOSITY],
            ensemble_size=1,
            model_type=ModelType.LINEAR,
            target_feature_sets={"density": "v3", "viscosity": "v5"},
        )
        predictor = MultiTargetPredictor(config=config)
        predictor.train(datasets)

        result = predictor.predict_multi(
            {
                "v3": np.random.randn(1, 5),
                "v5": np.random.randn(1, 6),
            }
        )

        assert "density" in result.predictions
        assert "viscosity" in result.predictions

    @_sklearn_skip
    def test_predict_multi_uses_feature_set_specific_ood_detectors(self):
        """predict_multi should use OOD detectors bound to each feature contract."""
        datasets = {
            "density": _make_dataset("density", n_features=5),
            "viscosity": _make_dataset("viscosity", n_features=6),
        }
        config = MultiTargetConfig(
            targets=[TargetVariable.DENSITY, TargetVariable.VISCOSITY],
            ensemble_size=1,
            model_type=ModelType.LINEAR,
            target_feature_sets={"density": "v3", "viscosity": "v5"},
        )
        predictor = MultiTargetPredictor(config=config)
        predictor.train(datasets)

        ood_v3 = MagicMock()
        ood_v3.detect.return_value = ["ood-v3"]
        ood_v5 = MagicMock()
        ood_v5.detect.return_value = ["ood-v5"]
        predictor.set_ood_detector(ood_v3, feature_set_version="v3")
        predictor.set_ood_detector(ood_v5, feature_set_version="v5")

        result = predictor.predict_multi(
            {
                "v3": np.random.randn(1, 5),
                "v5": np.random.randn(1, 6),
            }
        )

        assert result.ood_results is not None
        assert result.ood_results["density"] == "ood-v3"
        assert result.ood_results["viscosity"] == "ood-v5"

    @_sklearn_skip
    def test_predict_multi_uses_actual_fallback_contract_for_ood(self):
        """Fallback inputs should use the detector for the actual selected contract."""
        datasets = {
            "viscosity": _make_dataset("viscosity", n_features=6),
        }
        config = MultiTargetConfig(
            targets=[TargetVariable.VISCOSITY],
            ensemble_size=1,
            model_type=ModelType.LINEAR,
            target_feature_sets={"viscosity": "v5"},
        )
        predictor = MultiTargetPredictor(config=config)
        predictor.train(datasets)

        ood_v3 = MagicMock()
        ood_v3.detect.return_value = ["ood-v3-fallback"]
        ood_v5 = MagicMock()
        ood_v5.detect.return_value = ["ood-v5"]
        predictor.set_ood_detector(ood_v3, feature_set_version="v3")
        predictor.set_ood_detector(ood_v5, feature_set_version="v5")

        result = predictor.predict_multi({"v3": np.random.randn(1, 6)})

        assert result.ood_results is not None
        assert result.ood_results["viscosity"] == "ood-v3-fallback"
