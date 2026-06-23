"""
Unit tests for V3/V4 serving adapter dispatch (Step 4-1).
"""

import numpy as np

from contracts.policies.ml_policy import FeatureSetVersion
from ml.feature_registry import V2_FEATURES, V3_FEATURES, FeatureRegistry


class TestFeatureRegistryV3V4:
    """Test V3/V4 feature registry extensions."""

    def test_v3_count_40(self):
        assert FeatureRegistry.get_feature_count(FeatureSetVersion.V3) == 40

    def test_v4_count_53(self):
        assert FeatureRegistry.get_feature_count(FeatureSetVersion.V4) == 53

    def test_v3_starts_with_v2(self):
        """V3 features must start with all V2 features."""
        v3 = FeatureRegistry.get_features(FeatureSetVersion.V3)
        assert v3[:24] == V2_FEATURES

    def test_v4_starts_with_v3(self):
        """V4 features must start with all V3 features."""
        v4 = FeatureRegistry.get_features(FeatureSetVersion.V4)
        assert v4[:40] == V3_FEATURES

    def test_v3_validate_vector(self):
        vec = np.zeros(40)
        assert FeatureRegistry.validate_feature_vector(vec, FeatureSetVersion.V3)

    def test_v4_validate_vector(self):
        vec = np.zeros(53)
        assert FeatureRegistry.validate_feature_vector(vec, FeatureSetVersion.V4)

    def test_v3_reject_v2_dim(self):
        vec = np.zeros(24)
        assert not FeatureRegistry.validate_feature_vector(vec, FeatureSetVersion.V3)

    def test_no_duplicates_v3(self):
        v3 = FeatureRegistry.get_features(FeatureSetVersion.V3)
        assert len(v3) == len(set(v3))

    def test_no_duplicates_v4(self):
        v4 = FeatureRegistry.get_features(FeatureSetVersion.V4)
        assert len(v4) == len(set(v4))

    def test_v4_in_version_to_features(self):
        """V4 should be resolved by _get_v4_features()."""
        from ml.feature_registry import _get_v4_features

        v4 = _get_v4_features()
        assert len(v4) == 53

    def test_molecule_feature_canonical_order(self):
        """MOLECULE_FEATURE_NAMES should match V3 suffix in canonical order."""
        from ml.molecule_features import MOLECULE_FEATURE_NAMES

        v3 = FeatureRegistry.get_features(FeatureSetVersion.V3)
        v3_mol_suffix = v3[24:]  # V3 = V2(24) + mol(16)
        assert v3_mol_suffix == MOLECULE_FEATURE_NAMES


class TestMLPolicyV3V4:
    """Test ML policy extensions for V3/V4."""

    def test_feature_counts(self):
        from contracts.policies.ml_policy import DEFAULT_ML_POLICY

        assert DEFAULT_ML_POLICY.v3_feature_count == 40
        assert DEFAULT_ML_POLICY.v4_feature_count == 53

    def test_min_samples_gates(self):
        from contracts.policies.ml_policy import DEFAULT_ML_POLICY

        assert DEFAULT_ML_POLICY.min_molecule_level_samples_for_v3 == 50
        assert DEFAULT_ML_POLICY.min_layered_samples_for_v4 == 20

    def test_target_feature_set_mapping(self):
        from contracts.policies.ml_policy import DEFAULT_ML_POLICY

        mapping = DEFAULT_ML_POLICY.target_feature_sets
        # Bulk targets → V3
        assert mapping.get_version("density") == FeatureSetVersion.V3
        assert mapping.get_version("cohesive_energy_density") == FeatureSetVersion.V3
        # Layered targets → V4
        assert mapping.get_version("adhesion_energy") == FeatureSetVersion.V4
        assert mapping.get_version("interfacial_tensile_strength") == FeatureSetVersion.V4
        # Unknown → V3 (default)
        assert mapping.get_version("unknown_metric") == FeatureSetVersion.V3


class TestMultiTargetDualPredict:
    """Test MultiTargetPredictor.predict_dual dispatch."""

    def test_predict_dual_dispatches(self):
        """predict_dual should dispatch V3/V4 features based on target."""
        from ml.multi_target import MultiTargetConfig

        config = MultiTargetConfig(
            targets=[],
            target_feature_sets={
                "density": "v3",
                "adhesion_energy": "v4",
            },
        )

        assert config.get_feature_set_for_target("density") == "v3"
        assert config.get_feature_set_for_target("adhesion_energy") == "v4"


class TestDataLoaderV4Features:
    """Test that DataLoader._version_to_features includes V4."""

    def test_v4_feature_names_in_data_loader(self):
        """DataLoader should resolve V4 features correctly."""
        from ml.feature_registry import _get_v4_features

        # V4 features should have 53 entries
        v4 = _get_v4_features()
        assert len(v4) == 53
        # Verify it starts with V3
        v3 = FeatureRegistry.get_features(FeatureSetVersion.V3)
        assert v4[:40] == v3


class TestDimensionGuard:
    """Test predict / predict_dual dimension guard for legacy model compatibility."""

    def test_predict_dual_truncates_v3_to_v2(self):
        """V3 vector (40 dim) should be truncated to V2 (24 dim) for V2-trained model."""
        from ml.models import EnsemblePredictor, ModelConfig, ModelType, PropertyPredictor
        from ml.multi_target import MultiTargetConfig, MultiTargetPredictor

        # Create a V2-trained ensemble with 24 features
        config24 = ModelConfig(
            model_type=ModelType.RANDOM_FOREST,
            target_name="density",
            feature_names=[f"f{i}" for i in range(24)],
        )
        pred = PropertyPredictor(config24)
        # Fit with 24-dim data
        X_train = np.random.randn(10, 24)
        y_train = np.random.randn(10)
        pred.fit(X_train, y_train)

        ensemble = EnsemblePredictor(predictors=[pred])
        mtp = MultiTargetPredictor(
            config=MultiTargetConfig(target_feature_sets={}),
        )
        mtp._ensembles["density"] = ensemble

        # Pass V3 vector (40 dim) — should truncate to 24, not error
        X_v3 = np.random.randn(1, 40)
        result = mtp.predict_dual(X_v3=X_v3)
        assert "density" in result.predictions

    def test_predict_dual_skips_when_too_few_features(self):
        """If input has fewer features than model expects, target should be skipped."""
        from ml.models import EnsemblePredictor, ModelConfig, ModelType, PropertyPredictor
        from ml.multi_target import MultiTargetConfig, MultiTargetPredictor

        # Create a V4-trained ensemble with 53 features
        config53 = ModelConfig(
            model_type=ModelType.RANDOM_FOREST,
            target_name="adhesion_energy",
            feature_names=[f"f{i}" for i in range(53)],
        )
        pred = PropertyPredictor(config53)
        X_train = np.random.randn(10, 53)
        y_train = np.random.randn(10)
        pred.fit(X_train, y_train)

        ensemble = EnsemblePredictor(predictors=[pred])
        mtp = MultiTargetPredictor(
            config=MultiTargetConfig(
                target_feature_sets={"adhesion_energy": "v3"},
            ),
        )
        mtp._ensembles["adhesion_energy"] = ensemble

        # Pass V3 (40 dim) but model expects 53 → should skip
        X_v3 = np.random.randn(1, 40)
        result = mtp.predict_dual(X_v3=X_v3)
        assert "adhesion_energy" not in result.predictions

    def test_predict_truncates_for_legacy(self):
        """predict() should also truncate when input > trained dim."""
        from ml.models import EnsemblePredictor, ModelConfig, ModelType, PropertyPredictor
        from ml.multi_target import MultiTargetConfig, MultiTargetPredictor

        config24 = ModelConfig(
            model_type=ModelType.RANDOM_FOREST,
            target_name="density",
            feature_names=[f"f{i}" for i in range(24)],
        )
        pred = PropertyPredictor(config24)
        pred.fit(np.random.randn(10, 24), np.random.randn(10))

        ensemble = EnsemblePredictor(predictors=[pred])
        mtp = MultiTargetPredictor(config=MultiTargetConfig())
        mtp._ensembles["density"] = ensemble

        # Pass 40-dim input to predict() → should truncate to 24
        X = np.random.randn(1, 40)
        result = mtp.predict(X)
        assert "density" in result.predictions
