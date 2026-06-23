"""
Unit tests for ml.feature_registry — SSOT for feature names.
"""

import numpy as np

from contracts.policies.ml_policy import FeatureSetVersion
from ml.feature_registry import (
    V1_FEATURES,
    V2_FEATURES,
    FeatureRegistry,
)


class TestFeatureRegistry:
    """Tests for FeatureRegistry."""

    def test_v1_count_11(self):
        assert FeatureRegistry.get_feature_count(FeatureSetVersion.V1) == 11

    def test_v2_count_24(self):
        assert FeatureRegistry.get_feature_count(FeatureSetVersion.V2) == 24

    def test_v2_starts_with_v1(self):
        """V2 features must start with V1 features (backward compat)."""
        assert V2_FEATURES[:11] == V1_FEATURES

    def test_validate_v1_vector(self):
        vec = np.zeros(11)
        assert FeatureRegistry.validate_feature_vector(vec, FeatureSetVersion.V1)

    def test_validate_v2_vector(self):
        vec = np.zeros(24)
        assert FeatureRegistry.validate_feature_vector(vec, FeatureSetVersion.V2)

    def test_reject_wrong_dim(self):
        """11-element vector should fail V2 validation."""
        vec = np.zeros(11)
        assert not FeatureRegistry.validate_feature_vector(vec, FeatureSetVersion.V2)

    def test_no_duplicates(self):
        """V2 feature names must have no duplicates."""
        assert len(V2_FEATURES) == len(set(V2_FEATURES))

    def test_get_features_returns_copy(self):
        """get_features() returns a copy, not the original list."""
        f1 = FeatureRegistry.get_features(FeatureSetVersion.V1)
        f1.append("extra")
        assert len(FeatureRegistry.get_features(FeatureSetVersion.V1)) == 11
