"""
Unit tests for ML module.
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from ml.data_loader import (
    DataLoader,
    DataSplitter,
    TargetVariable,
    TrainingDataset,
)
from ml.feature_store import (
    CompositionFeatures,
    CompositionFeaturesV2,
    Feature,
    FeatureStore,
    FeatureType,
)
from ml.models import (
    EnsemblePredictor,
    ModelConfig,
    ModelType,
    PropertyPredictor,
)
from ml.predictor import (
    PredictionInput,
    PredictionInputV2,
    Predictor,
)
from ml.trainer import (
    Trainer,
    TrainingConfig,
    TrainingResult,
)


def _has_sklearn() -> bool:
    try:
        import sklearn  # noqa: F401

        return True
    except ImportError:
        return False


class TestFeatureStore:
    """Tests for FeatureStore."""

    def test_add_feature(self):
        """Test adding a feature."""
        store = FeatureStore()
        feature = Feature(
            exp_id="exp_001",
            feature_type=FeatureType.COMPOSITION,
            feature_name="asphaltene_wt",
            feature_value=20.0,
        )
        store.add_feature(feature)
        assert "exp_001" in store
        assert len(store) == 1

    def test_get_features(self):
        """Test getting features."""
        store = FeatureStore()
        store.add_feature(
            Feature(
                exp_id="exp_001",
                feature_type=FeatureType.COMPOSITION,
                feature_name="asphaltene_wt",
                feature_value=20.0,
            )
        )
        store.add_feature(
            Feature(
                exp_id="exp_001",
                feature_type=FeatureType.SIMULATION,
                feature_name="temperature_k",
                feature_value=298.0,
            )
        )

        all_features = store.get_features("exp_001")
        assert len(all_features) == 2

        comp_features = store.get_features("exp_001", FeatureType.COMPOSITION)
        assert len(comp_features) == 1
        assert comp_features[0].feature_name == "asphaltene_wt"

    def test_extract_composition_features(self):
        """Test composition feature extraction."""
        store = FeatureStore()
        features = store.extract_composition_features(
            exp_id="exp_001",
            asphaltene=20.0,
            resin=30.0,
            aromatic=35.0,
            saturate=15.0,
        )

        assert len(features) == 8  # 5 base + 3 derived
        assert "exp_001" in store

        # Check derived features
        feature_dict = {f.feature_name: f.feature_value for f in features}
        assert feature_dict["polar_fraction"] == 50.0
        assert feature_dict["nonpolar_fraction"] == 50.0
        assert feature_dict["asphaltene_resin_ratio"] == pytest.approx(0.667, rel=0.01)

    def test_save_and_load(self):
        """Test saving and loading feature store."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "features.json"

            # Create and save
            store = FeatureStore()
            store.extract_composition_features("exp_001", 20.0, 30.0, 35.0, 15.0)
            store.save_to_disk(store_path)

            # Load
            store2 = FeatureStore(store_path)
            assert "exp_001" in store2
            features = store2.get_features("exp_001")
            assert len(features) == 8


class TestCompositionFeatures:
    """Tests for CompositionFeatures."""

    def test_from_composition(self):
        """Test creating from composition."""
        comp = CompositionFeatures.from_composition(
            asphaltene=20.0,
            resin=30.0,
            aromatic=35.0,
            saturate=15.0,
        )

        assert comp.asphaltene_wt == 20.0
        assert comp.polar_fraction == 50.0
        assert comp.nonpolar_fraction == 50.0
        assert comp.asphaltene_resin_ratio == pytest.approx(0.667, rel=0.01)

    def test_to_vector(self):
        """Test converting to vector."""
        comp = CompositionFeatures.from_composition(20.0, 30.0, 35.0, 15.0)
        vec = comp.to_vector()

        assert len(vec) == 8
        assert vec[0] == 20.0  # asphaltene
        assert vec[5] == 50.0  # polar_fraction


class TestDataLoader:
    """Tests for DataLoader."""

    def test_load_from_dict(self):
        """Test loading from dictionary."""
        data = [
            {
                "exp_id": "exp_001",
                "asphaltene_wt": 20.0,
                "resin_wt": 30.0,
                "aromatic_wt": 35.0,
                "saturate_wt": 15.0,
                "additive_wt": 0.0,
                "polar_fraction": 50.0,
                "nonpolar_fraction": 50.0,
                "asphaltene_resin_ratio": 0.667,
                "temperature_k": 298.0,
                "pressure_atm": 1.0,
                "target_atoms": 100000,
                "density": 1.02,
            },
            {
                "exp_id": "exp_002",
                "asphaltene_wt": 25.0,
                "resin_wt": 25.0,
                "aromatic_wt": 30.0,
                "saturate_wt": 20.0,
                "additive_wt": 0.0,
                "polar_fraction": 50.0,
                "nonpolar_fraction": 50.0,
                "asphaltene_resin_ratio": 1.0,
                "temperature_k": 298.0,
                "pressure_atm": 1.0,
                "target_atoms": 100000,
                "density": 1.05,
            },
        ]

        loader = DataLoader()
        dataset = loader.load_from_dict(data, TargetVariable.DENSITY)

        assert dataset.n_samples == 2
        assert dataset.n_features == 11
        assert dataset.target_name == "density"
        assert np.allclose(dataset.y, [1.02, 1.05])

    def test_normalize_features(self):
        """Test feature normalization."""
        loader = DataLoader()
        data = [
            {
                "exp_id": f"exp_{i}",
                **{f: float(i) for f in DataLoader.ML_V1_FEATURES},
                "density": 1.0,
            }
            for i in range(10)
        ]
        dataset = loader.load_from_dict(data, TargetVariable.DENSITY)

        normalized, params = loader.normalize_features(dataset, method="standard")

        # Check normalization
        assert normalized.X.shape == dataset.X.shape
        assert params["method"] == "standard"

        # Mean should be ~0, std should be ~1 for normalized data
        assert np.abs(np.mean(normalized.X)) < 1e-10
        assert np.abs(np.std(normalized.X) - 1.0) < 0.2


class TestDataSplitter:
    """Tests for DataSplitter."""

    def test_random_split(self):
        """Test random split."""
        # Create mock dataset
        n_samples = 100
        X = np.random.randn(n_samples, 10)
        y = np.random.randn(n_samples)
        exp_ids = [f"exp_{i}" for i in range(n_samples)]

        dataset = TrainingDataset(
            X=X,
            y=y,
            exp_ids=exp_ids,
            feature_names=[f"f{i}" for i in range(10)],
            target_name="density",
        )

        splitter = DataSplitter(train_ratio=0.7, val_ratio=0.15, test_ratio=0.15)
        split = splitter.split(dataset)

        # Check sizes
        assert split.train.n_samples == 70
        assert split.val.n_samples == 15
        assert split.test.n_samples == 15

        # Check no overlap
        train_ids = set(split.train.exp_ids)
        val_ids = set(split.val.exp_ids)
        test_ids = set(split.test.exp_ids)

        assert len(train_ids & val_ids) == 0
        assert len(train_ids & test_ids) == 0
        assert len(val_ids & test_ids) == 0

    def test_group_split(self):
        """Test group-based split."""
        n_samples = 100
        X = np.random.randn(n_samples, 10)
        y = np.random.randn(n_samples)
        exp_ids = [f"exp_{i}" for i in range(n_samples)]
        groups = np.array([i % 10 for i in range(n_samples)])  # 10 groups

        dataset = TrainingDataset(
            X=X,
            y=y,
            exp_ids=exp_ids,
            feature_names=[f"f{i}" for i in range(10)],
            target_name="density",
        )

        splitter = DataSplitter()
        split = splitter.split(dataset, groups=groups)

        # Check that entire groups are in same split
        assert split.split_info["method"] == "group"
        assert len(split.split_info["train_groups"]) == 7  # 70% of 10 groups


class TestPropertyPredictor:
    """Tests for PropertyPredictor."""

    def test_create_model(self):
        """Test model creation."""
        config = ModelConfig(model_type=ModelType.RANDOM_FOREST)
        predictor = PropertyPredictor(config)

        assert predictor.config.model_type == ModelType.RANDOM_FOREST
        assert not predictor.is_fitted

    def test_fit_and_predict(self):
        """Test fitting and prediction."""
        # Create simple dataset
        np.random.seed(42)
        n_samples = 100
        X = np.random.randn(n_samples, 5)
        y = np.sum(X, axis=1) + np.random.randn(n_samples) * 0.1  # Simple linear relationship

        config = ModelConfig(
            model_type=ModelType.RANDOM_FOREST,
            n_estimators=50,  # More estimators for better fit
            max_depth=5,
        )
        predictor = PropertyPredictor(config)
        predictor.fit(X, y)

        assert predictor.is_fitted

        # Make predictions
        preds = predictor.predict(X)
        assert len(preds) == n_samples

        # Check that predictions are reasonable (on training data, should fit well)
        rmse = np.sqrt(np.mean((y - preds) ** 2))
        assert rmse < 2.0  # Should fit reasonably well

    def test_feature_importances(self):
        """Test getting feature importances."""
        np.random.seed(42)
        X = np.random.randn(50, 5)
        y = X[:, 0] * 2 + X[:, 1]  # Feature 0 and 1 are important

        config = ModelConfig(
            model_type=ModelType.RANDOM_FOREST,
            n_estimators=10,
            feature_names=["f0", "f1", "f2", "f3", "f4"],
        )
        predictor = PropertyPredictor(config)
        predictor.fit(X, y)

        importances = predictor.get_feature_importances()
        assert importances is not None
        assert "f0" in importances
        assert "f1" in importances

        # f0 and f1 should be more important
        assert importances["f0"] > importances["f3"]

    def test_save_and_load(self):
        """Test saving and loading model."""
        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = Path(tmpdir) / "model"

            # Train model
            np.random.seed(42)
            X = np.random.randn(50, 5)
            y = np.sum(X, axis=1)

            config = ModelConfig(
                model_type=ModelType.RANDOM_FOREST,
                n_estimators=10,
                feature_names=["f0", "f1", "f2", "f3", "f4"],
            )
            predictor = PropertyPredictor(config)
            predictor.fit(X, y)
            predictor.save(model_path)

            # Load model
            predictor2 = PropertyPredictor.load(model_path)

            assert predictor2.is_fitted
            assert predictor2.config.model_type == ModelType.RANDOM_FOREST

            # Predictions should match
            preds1 = predictor.predict(X)
            preds2 = predictor2.predict(X)
            assert np.allclose(preds1, preds2)


class TestEnsemblePredictor:
    """Tests for EnsemblePredictor."""

    def test_ensemble_prediction(self):
        """Test ensemble prediction."""
        np.random.seed(42)
        X = np.random.randn(50, 5)
        y = np.sum(X, axis=1)

        # Create ensemble
        ensemble = EnsemblePredictor()
        for seed in [1, 2, 3]:
            config = ModelConfig(
                model_type=ModelType.RANDOM_FOREST,
                n_estimators=10,
                random_state=seed,
            )
            predictor = PropertyPredictor(config)
            ensemble.add_predictor(predictor)

        ensemble.fit(X, y)

        assert ensemble.is_fitted

        # Make predictions
        preds = ensemble.predict(X)
        assert len(preds) == 50

        # Get uncertainty
        preds_mean, preds_std = ensemble.predict(X, return_std=True)
        assert len(preds_std) == 50
        assert all(s >= 0 for s in preds_std)


class TestTrainer:
    """Tests for Trainer."""

    def test_train(self):
        """Test training pipeline."""
        np.random.seed(42)
        n_samples = 120

        X = np.random.randn(n_samples, 5)
        y = np.sum(X, axis=1) + np.random.randn(n_samples) * 0.1

        # Create dataset
        dataset = TrainingDataset(
            X=X,
            y=y,
            exp_ids=[f"exp_{i}" for i in range(n_samples)],
            feature_names=["f0", "f1", "f2", "f3", "f4"],
            target_name="density",
        )

        # Split
        splitter = DataSplitter()
        data_split = splitter.split(dataset)

        # Train
        config = TrainingConfig(
            model_config=ModelConfig(
                model_type=ModelType.RANDOM_FOREST,
                n_estimators=10,
            ),
            normalize_features=True,
            use_cv=True,
            cv_folds=3,
            min_samples=50,
        )

        trainer = Trainer(config)
        result = trainer.train(data_split)

        # Check result
        assert result.n_train_samples == data_split.train.n_samples
        assert result.train_rmse < 2.0  # More lenient for random data
        assert result.test_rmse < 3.0  # More lenient for test set
        assert result.train_r2 > 0.5
        assert result.cv_rmse_mean is not None
        assert result.feature_importances is not None


class TestPredictionInput:
    """Tests for PredictionInput."""

    def test_valid_input(self):
        """Test valid input validation."""
        inp = PredictionInput(
            asphaltene=20.0,
            resin=30.0,
            aromatic=35.0,
            saturate=15.0,
        )
        valid, error = inp.validate()
        assert valid
        assert error is None

    def test_invalid_composition_sum(self):
        """Test invalid composition sum."""
        inp = PredictionInput(
            asphaltene=30.0,
            resin=30.0,
            aromatic=30.0,
            saturate=30.0,
        )
        valid, error = inp.validate()
        assert not valid
        assert "sum to 100%" in error

    def test_invalid_temperature(self):
        """Test invalid temperature."""
        inp = PredictionInput(
            asphaltene=25.0,
            resin=25.0,
            aromatic=25.0,
            saturate=25.0,
            temperature_k=1000.0,
        )
        valid, error = inp.validate()
        assert not valid
        assert "Temperature" in error

    def test_to_feature_vector(self):
        """Test feature vector generation."""
        inp = PredictionInput(
            asphaltene=20.0,
            resin=30.0,
            aromatic=35.0,
            saturate=15.0,
            temperature_k=300.0,
        )
        vec = inp.to_feature_vector()

        assert len(vec) == 11
        assert vec[0] == 20.0  # asphaltene
        assert vec[8] == 300.0  # temperature


class TestPredictor:
    """Tests for Predictor."""

    def test_predictor_with_mock_model(self):
        """Test predictor with a trained model."""
        with tempfile.TemporaryDirectory() as tmpdir:
            model_dir = Path(tmpdir)

            # Train and save a model
            np.random.seed(42)
            X = np.random.randn(100, 11)
            y = np.sum(X[:, :5], axis=1)  # Use first 5 features

            config = ModelConfig(
                model_type=ModelType.RANDOM_FOREST,
                n_estimators=10,
            )
            predictor_model = PropertyPredictor(config)
            predictor_model.fit(X, y)
            predictor_model.save(model_dir / "model_density")

            # Load and use predictor
            predictor = Predictor(model_dir)
            predictor.load_model("density")

            assert predictor.is_loaded("density")

            # Make prediction (will use unnormalized features)
            inp = PredictionInput(
                asphaltene=20.0,
                resin=30.0,
                aromatic=35.0,
                saturate=15.0,
            )
            result = predictor.predict(inp, "density")

            assert result.target == "density"
            assert isinstance(result.value, float)

    def test_available_targets(self):
        """Test getting available targets."""
        predictor = Predictor()
        assert predictor.available_targets == []

        # Add mock model
        predictor._models["density"] = PropertyPredictor()
        assert "density" in predictor.available_targets


class TestTrainingResult:
    """Tests for TrainingResult."""

    def test_to_dict(self):
        """Test converting to dictionary."""
        result = TrainingResult(
            train_rmse=0.1,
            val_rmse=0.15,
            test_rmse=0.2,
            train_r2=0.95,
            val_r2=0.90,
            test_r2=0.85,
            n_train_samples=100,
        )

        d = result.to_dict()
        assert d["train_rmse"] == 0.1
        assert d["n_train_samples"] == 100

    def test_summary(self):
        """Test summary generation."""
        result = TrainingResult(
            train_rmse=0.1,
            val_rmse=0.15,
            test_rmse=0.2,
            train_mae=0.08,
            val_mae=0.12,
            test_mae=0.16,
            train_r2=0.95,
            val_r2=0.90,
            test_r2=0.85,
            n_train_samples=100,
            n_val_samples=15,
            n_test_samples=15,
            feature_importances={"f0": 0.5, "f1": 0.3, "f2": 0.2},
        )

        summary = result.summary()
        assert "Train" in summary
        assert "0.1000" in summary  # train_rmse
        assert "Feature Importances" in summary


# =============================================================================
# V2 Feature Tests
# =============================================================================


class TestCompositionFeaturesV2:
    """Tests for CompositionFeaturesV2."""

    def test_vector_21_elements(self):
        """CompositionFeaturesV2.to_vector() should produce 21 elements."""
        comp = CompositionFeaturesV2(
            asphaltene_wt=20.0,
            resin_wt=30.0,
            aromatic_wt=35.0,
            saturate_wt=10.0,
            additive_wt=5.0,
            polar_fraction=50.0,
            nonpolar_fraction=45.0,
            asphaltene_resin_ratio=0.667,
            additive_is_polymer=1.0,
            additive_mw=104.15,
            additive_wt_x_asphaltene_wt=100.0,
        )
        vec = comp.to_vector()
        assert len(vec) == 21
        # First 8 are V1 composition features
        assert vec[0] == 20.0  # asphaltene_wt
        # Element 8 is additive_is_polymer
        assert vec[8] == 1.0

    def test_inherits_from_composition(self):
        """V2 is a subclass of CompositionFeatures."""
        comp = CompositionFeaturesV2()
        assert isinstance(comp, CompositionFeatures)


class TestPredictionInputV2:
    """Tests for PredictionInputV2."""

    def test_vector_24_elements(self):
        """PredictionInputV2.to_feature_vector() should produce 24 elements."""
        inp = PredictionInputV2(
            asphaltene=20.0,
            resin=30.0,
            aromatic=35.0,
            saturate=10.0,
            additive=5.0,
            additive_type="polymer",
            additive_mol_id="ADD_003",
        )
        vec = inp.to_feature_vector()
        assert len(vec) == 24

    def test_no_additive_v2_zero_fill(self):
        """No-additive V2 features should all be zeros."""
        inp = PredictionInputV2(
            asphaltene=20.0,
            resin=30.0,
            aromatic=35.0,
            saturate=15.0,
            additive=0.0,
        )
        vec = inp.to_feature_vector()
        assert len(vec) == 24
        assert all(vec[11:] == 0.0), "No-additive V2 features should be all zeros"


class TestV1BackwardCompat:
    """Tests for V1 backward compatibility."""

    def test_prediction_input_v1_unchanged(self):
        """PredictionInput should still produce 11-element vector."""
        inp = PredictionInput(
            asphaltene=20.0,
            resin=30.0,
            aromatic=35.0,
            saturate=15.0,
            additive=0.0,
        )
        vec = inp.to_feature_vector()
        assert len(vec) == 11

    def test_dataloader_v1_default(self):
        """DataLoader class-level ML_V1_FEATURES should have 11 entries."""
        assert len(DataLoader.ML_V1_FEATURES) == 11

    def test_dataloader_composition_features_alias(self):
        """DataLoader.COMPOSITION_FEATURES should still be accessible."""
        assert len(DataLoader.COMPOSITION_FEATURES) == 8

    def test_dataloader_simulation_features_alias(self):
        """DataLoader.SIMULATION_FEATURES should still be accessible."""
        assert len(DataLoader.SIMULATION_FEATURES) == 3


class TestPredictorDimensionCheck:
    """Tests for Predictor._get_expected_features() priority chain."""

    def test_config_feature_names_priority(self):
        """config.feature_names takes priority over _model.n_features_in_."""
        predictor = Predictor()

        # Model with config.feature_names set
        config = ModelConfig(
            model_type=ModelType.RANDOM_FOREST,
            feature_names=["f0", "f1", "f2", "f3", "f4"],
        )
        model = PropertyPredictor(config)

        expected = predictor._get_expected_features(model)
        assert expected == 5

    @pytest.mark.skipif(not _has_sklearn(), reason="sklearn not installed")
    def test_n_features_in_fallback(self):
        """Falls back to _model.n_features_in_ when config.feature_names is empty."""
        predictor = Predictor()

        # Train a model so n_features_in_ is set
        np.random.seed(42)
        X = np.random.randn(20, 7)
        y = np.sum(X, axis=1)

        config = ModelConfig(
            model_type=ModelType.RANDOM_FOREST,
            n_estimators=5,
            feature_names=[],  # empty
        )
        model = PropertyPredictor(config)
        model.fit(X, y)

        expected = predictor._get_expected_features(model)
        assert expected == 7

    @pytest.mark.skipif(not _has_sklearn(), reason="sklearn not installed")
    def test_dimension_mismatch_raises(self):
        """Feature dimension mismatch should raise ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            model_dir = Path(tmpdir)

            # Train model on 11 features
            np.random.seed(42)
            X = np.random.randn(100, 11)
            y = np.sum(X[:, :5], axis=1)

            config = ModelConfig(
                model_type=ModelType.RANDOM_FOREST,
                n_estimators=10,
                feature_names=[f"f{i}" for i in range(11)],
            )
            model = PropertyPredictor(config)
            model.fit(X, y)
            model.save(model_dir / "model_density")

            predictor = Predictor(model_dir)
            predictor.load_model("density")

            # V2 input (24 features) with V1 model (11 features) → mismatch
            inp = PredictionInputV2(
                asphaltene=20.0,
                resin=30.0,
                aromatic=35.0,
                saturate=10.0,
                additive=5.0,
                additive_type="polymer",
                additive_mol_id="ADD_003",
            )
            with pytest.raises(ValueError, match="Feature dimension mismatch"):
                predictor.predict(inp, "density")


# =============================================================================
# DataLoader V2 Gate Tests
# =============================================================================


def _make_mock_experiment(
    exp_id: str,
    *,
    additive_type: str | None = None,
    additive_wt: float = 0.0,
    additive_mol_id: str | None = None,
    density_value: float = 1.02,
) -> MagicMock:
    """Create a mock ExperimentModel with standard composition fields."""
    exp = MagicMock()
    exp.exp_id = exp_id
    exp.status = "completed"
    exp.ff_type = "bulk_ff_gaff2"
    exp.run_tier = "screening"
    exp.comp_asphaltene_wt = 20.0
    exp.comp_resin_wt = 30.0
    exp.comp_aromatic_wt = 35.0
    exp.comp_saturate_wt = 15.0
    exp.additive_type = additive_type
    exp.additive_wt = additive_wt
    exp.additive_mol_id = additive_mol_id
    exp.temperature_K = 298.0
    exp.pressure_atm = 1.0
    exp.target_atoms = 100000

    metric = MagicMock()
    metric.metric_name = "density"
    metric.value = density_value
    exp.metrics = [metric]

    return exp


def _make_mock_session(experiments: list) -> MagicMock:
    """Create a mock DB session returning preset experiments."""
    session = MagicMock()
    query = MagicMock()
    session.query.return_value = query
    query.filter.return_value = query
    query.options.return_value = query
    query.all.return_value = experiments
    return session


def _patch_db_imports():
    """Context manager to mock sqlalchemy/database imports for load_from_database.

    When sqlalchemy is not installed, the local imports inside
    load_from_database fail. This patches sys.modules so the
    ``from sqlalchemy.orm import joinedload`` and
    ``from database.models import ExperimentModel`` succeed.
    """
    mock_sqlalchemy = MagicMock()
    mock_sqlalchemy_orm = MagicMock()
    mock_database = MagicMock()
    mock_database_models = MagicMock()

    modules = {
        "sqlalchemy": mock_sqlalchemy,
        "sqlalchemy.orm": mock_sqlalchemy_orm,
        "database": mock_database,
        "database.models": mock_database_models,
    }
    return patch.dict(sys.modules, modules)


class TestDataLoaderV2Gate:
    """Tests for DataLoader V2 gate logic."""

    def test_v2_fallback_insufficient_additive(self):
        """V2 request + insufficient additive samples -> V1 fallback + metadata."""
        from contracts.policies.ml_policy import FeatureSetVersion

        # 50 experiments: only 2 have real additive data (< 30 threshold)
        experiments = []
        for i in range(48):
            experiments.append(_make_mock_experiment(f"exp_{i:03d}"))
        for i in range(2):
            experiments.append(
                _make_mock_experiment(
                    f"exp_add_{i:03d}",
                    additive_type="polymer",
                    additive_wt=5.0,
                    additive_mol_id="ADD_003",
                )
            )

        session = _make_mock_session(experiments)
        loader = DataLoader()
        with _patch_db_imports():
            dataset = loader.load_from_database(
                session,
                target=TargetVariable.DENSITY,
                feature_set_version=FeatureSetVersion.V2,
                strict_feature_set=False,
                min_samples=5,
            )

        assert dataset is not None
        assert dataset.metadata["actual_feature_set"] == "v1"
        assert dataset.n_features == 11  # V1 fallback

    def test_v2_strict_raises_insufficient_additive(self):
        """V2 request + strict=True + insufficient additive -> ValueError."""
        from contracts.policies.ml_policy import FeatureSetVersion

        # 50 experiments, only 5 additive (< 30 threshold)
        experiments = []
        for i in range(45):
            experiments.append(_make_mock_experiment(f"exp_{i:03d}"))
        for i in range(5):
            experiments.append(
                _make_mock_experiment(
                    f"exp_add_{i:03d}",
                    additive_type="surfactant",
                    additive_wt=3.0,
                    additive_mol_id="ADD_002",
                )
            )

        session = _make_mock_session(experiments)
        loader = DataLoader()

        with _patch_db_imports():
            with pytest.raises(ValueError, match="V2 requires"):
                loader.load_from_database(
                    session,
                    target=TargetVariable.DENSITY,
                    feature_set_version=FeatureSetVersion.V2,
                    strict_feature_set=True,
                    min_samples=5,
                )

    def test_v2_gate_ignores_zero_wt_additive(self):
        """additive_type present but additive_wt=0 -> excluded from gate count."""
        from contracts.policies.ml_policy import FeatureSetVersion

        # 50 experiments: 35 have additive_type="polymer" but additive_wt=0.0
        # Only 5 have additive_wt > 0 → should NOT reach V2 threshold (30)
        experiments = []
        for i in range(10):
            experiments.append(_make_mock_experiment(f"exp_{i:03d}"))
        for i in range(35):
            experiments.append(
                _make_mock_experiment(
                    f"exp_zero_{i:03d}",
                    additive_type="polymer",
                    additive_wt=0.0,
                    additive_mol_id="ADD_003",
                )
            )
        for i in range(5):
            experiments.append(
                _make_mock_experiment(
                    f"exp_real_{i:03d}",
                    additive_type="polymer",
                    additive_wt=5.0,
                    additive_mol_id="ADD_003",
                )
            )

        session = _make_mock_session(experiments)
        loader = DataLoader()
        with _patch_db_imports():
            dataset = loader.load_from_database(
                session,
                target=TargetVariable.DENSITY,
                feature_set_version=FeatureSetVersion.V2,
                strict_feature_set=False,
                min_samples=5,
            )

        # 5 real additive < 30 threshold → should fallback to V1
        assert dataset is not None
        assert dataset.metadata["actual_feature_set"] == "v1"
        assert dataset.n_features == 11
