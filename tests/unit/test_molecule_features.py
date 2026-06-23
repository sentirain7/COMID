"""
Unit tests for MoleculeFeatureExtractor (Step 2-4).
"""

import pytest

from ml.molecule_features import MOLECULE_FEATURE_NAMES, MoleculeFeatureExtractor


class TestMoleculeFeatureNames:
    """Test feature name constants."""

    def test_count_16(self):
        assert len(MOLECULE_FEATURE_NAMES) == 16

    def test_no_duplicates(self):
        assert len(MOLECULE_FEATURE_NAMES) == len(set(MOLECULE_FEATURE_NAMES))

    def test_expected_categories(self):
        """All 4 SARA categories should have 4 features each."""
        for cat in ["saturate", "aromatic", "resin", "asphaltene"]:
            cat_feats = [f for f in MOLECULE_FEATURE_NAMES if f.startswith(cat)]
            assert len(cat_feats) == 4, f"Expected 4 features for {cat}, got {len(cat_feats)}"


class TestMoleculeFeatureExtractor:
    """Test extract_from_composition()."""

    def test_empty_composition(self):
        """Empty composition should return all zeros."""
        ext = MoleculeFeatureExtractor()
        result = ext.extract_from_composition({}, None)
        assert len(result) == 16
        assert all(v == 0.0 for v in result.values())

    def test_all_features_present(self):
        """Result should contain all 16 expected feature names."""
        ext = MoleculeFeatureExtractor()
        result = ext.extract_from_composition({}, None)
        for name in MOLECULE_FEATURE_NAMES:
            assert name in result, f"Missing feature: {name}"

    def test_compute_features_with_data(self):
        """Test with mock molecule data using 'weight' key."""
        ext = MoleculeFeatureExtractor()

        # Simulate categorized data (now uses 'weight' instead of 'count')
        cat_data = {
            "saturate": [
                {"mw": 226.44, "atoms": 50, "weight": 4.0},
                {"mw": 310.60, "atoms": 66, "weight": 4.0},
            ],
            "aromatic": [
                {"mw": 128.17, "atoms": 18, "weight": 11.0},
            ],
            "resin": [],
            "asphaltene": [],
        }

        features = ext._compute_features(cat_data)

        # Saturate: 2 species
        assert features["saturate_n_species"] == 2.0
        # Saturate avg_mw: equal weights, so (226.44 + 310.60) / 2
        assert abs(features["saturate_avg_mw"] - 268.52) < 0.01
        # Aromatic: 1 species
        assert features["aromatic_n_species"] == 1.0
        assert features["aromatic_avg_mw"] == pytest.approx(128.17, abs=0.01)
        assert features["aromatic_mw_std"] == 0.0  # single species
        # Resin and asphaltene should be zero
        assert features["resin_avg_mw"] == 0.0
        assert features["asphaltene_n_species"] == 0.0

    def test_weight_fraction_based_weighting(self):
        """Test that weight_fraction values produce mass-based weighted statistics."""
        ext = MoleculeFeatureExtractor()

        # Different weights should shift the average
        cat_data = {
            "saturate": [
                {"mw": 100.0, "atoms": 10, "weight": 1.0},
                {"mw": 200.0, "atoms": 20, "weight": 3.0},
            ],
            "aromatic": [],
            "resin": [],
            "asphaltene": [],
        }

        features = ext._compute_features(cat_data)

        # Weighted avg: (100*0.25 + 200*0.75) = 175
        assert features["saturate_avg_mw"] == pytest.approx(175.0, abs=0.01)
        assert features["saturate_avg_atoms"] == pytest.approx(17.5, abs=0.01)

    def test_mass_based_inference_weight(self):
        """extract_from_composition should use count*MW for mass-based weighting."""
        ext = MoleculeFeatureExtractor()

        # Mock molecule_db
        class MockInfo:
            def __init__(self, mw, atoms, cat):
                self.molecular_weight = mw
                self.atom_count = atoms
                self.category = cat

        class MockDB:
            def __init__(self):
                self._data = {
                    "SAT_001": MockInfo(200.0, 40, "saturate"),
                    "SAT_002": MockInfo(400.0, 80, "saturate"),
                }

            def get(self, mol_id):
                return self._data.get(mol_id)

        mol_counts = {"SAT_001": 10, "SAT_002": 5}
        db = MockDB()
        features = ext.extract_from_composition(mol_counts, db)

        # Mass-based: SAT_001: 10*200=2000, SAT_002: 5*400=2000 → equal weight
        assert features["saturate_avg_mw"] == pytest.approx(300.0, abs=0.01)

    def test_normalize_sara(self):
        """Test SARA type normalization."""
        ext = MoleculeFeatureExtractor()
        assert ext._normalize_sara("saturate") == "saturate"
        assert ext._normalize_sara("Saturate") == "saturate"
        assert ext._normalize_sara("SAT") == "saturate"
        assert ext._normalize_sara("aromatic") == "aromatic"
        assert ext._normalize_sara("aro") == "aromatic"
        assert ext._normalize_sara("") == ""
        assert ext._normalize_sara(None) == ""
