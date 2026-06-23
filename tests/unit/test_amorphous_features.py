"""
Unit tests for AmorphousFeatureExtractor (Step 3-2).
"""

from ml.amorphous_features import AMORPHOUS_FEATURE_NAMES, AmorphousFeatureExtractor


class TestAmorphousFeatureNames:
    """Test feature name constants."""

    def test_count_3(self):
        assert len(AMORPHOUS_FEATURE_NAMES) == 3

    def test_no_duplicates(self):
        assert len(AMORPHOUS_FEATURE_NAMES) == len(set(AMORPHOUS_FEATURE_NAMES))


class TestAmorphousFeatureExtractor:
    """Test amorphous feature extraction."""

    def test_with_amorphous(self):
        ext = AmorphousFeatureExtractor()
        result = ext.extract({"density": 1.02, "atom_count": 5000})
        assert len(result) == 3
        assert result["amorphous_present"] == 1.0
        assert result["amorphous_density"] == 1.02
        assert result["amorphous_atom_count_norm"] == 5000 / 10000.0

    def test_without_amorphous(self):
        ext = AmorphousFeatureExtractor()
        result = ext.extract(None)
        assert len(result) == 3
        assert result["amorphous_present"] == 0.0
        assert result["amorphous_density"] == 0.0
        assert result["amorphous_atom_count_norm"] == 0.0

    def test_zeros(self):
        zeros = AmorphousFeatureExtractor.zeros()
        assert len(zeros) == 3
        assert all(v == 0.0 for v in zeros.values())

    def test_all_features_present(self):
        ext = AmorphousFeatureExtractor()
        result = ext.extract({"density": 0.95, "atom_count": 3000})
        for name in AMORPHOUS_FEATURE_NAMES:
            assert name in result, f"Missing feature: {name}"

    def test_none_values(self):
        """None density/atom_count should become 0."""
        ext = AmorphousFeatureExtractor()
        result = ext.extract({"density": None, "atom_count": None})
        assert result["amorphous_present"] == 1.0
        assert result["amorphous_density"] == 0.0
        assert result["amorphous_atom_count_norm"] == 0.0
