"""
Unit tests for ml.additive_features — V2 additive feature extraction.
"""

import logging

import pytest

from ml.additive_features import (
    ADDITIVE_DESCRIPTOR_TABLE,
    ADDITIVE_FEATURE_NAMES,
    AdditiveFeatureExtractor,
    normalize_additive_type,
)


class TestNormalizeAdditiveType:
    """Tests for normalize_additive_type()."""

    def test_none_returns_none(self):
        assert normalize_additive_type(None) is None

    def test_basic_lower(self):
        assert normalize_additive_type("SBS") == "sbs"

    def test_strip_whitespace(self):
        assert normalize_additive_type(" Sbs ") == "sbs"

    def test_remove_hyphens(self):
        assert normalize_additive_type("s-b-s") == "sbs"

    def test_remove_underscores(self):
        assert normalize_additive_type("anti_aging") == "antiaging"

    def test_remove_spaces(self):
        assert normalize_additive_type("anti aging") == "antiaging"

    def test_combined(self):
        assert normalize_additive_type(" S-B_S ") == "sbs"


class TestAdditiveFeatureExtractor:
    """Tests for AdditiveFeatureExtractor."""

    def setup_method(self):
        self.extractor = AdditiveFeatureExtractor()

    def test_extract_polymer(self):
        """SBS → polymer=1, surfactant=0, nanoparticle=0."""
        feats = self.extractor.extract(
            additive_type="polymer",
            additive_mol_id="ADD_003",
            additive_wt=5.0,
            asphaltene_wt=20.0,
            polar_fraction=50.0,
        )
        assert feats["additive_is_polymer"] == 1.0
        assert feats["additive_is_surfactant"] == 0.0
        assert feats["additive_is_nanoparticle"] == 0.0

    def test_extract_surfactant(self):
        """PPA → surfactant=1."""
        feats = self.extractor.extract(
            additive_type="surfactant",
            additive_mol_id="ADD_001",
            additive_wt=3.0,
            asphaltene_wt=20.0,
            polar_fraction=50.0,
        )
        assert feats["additive_is_surfactant"] == 1.0
        assert feats["additive_is_polymer"] == 0.0
        assert feats["additive_is_nanoparticle"] == 0.0

    def test_extract_nanoparticle(self):
        """SiO2 → nanoparticle=1."""
        feats = self.extractor.extract(
            additive_type="nanoparticle",
            additive_mol_id=None,
            additive_wt=2.0,
            asphaltene_wt=20.0,
            polar_fraction=50.0,
        )
        assert feats["additive_is_nanoparticle"] == 1.0
        assert feats["additive_is_polymer"] == 0.0
        assert feats["additive_is_surfactant"] == 0.0

    def test_no_additive_zero_fill(self):
        """additive_type=None → all 13 features = 0.0."""
        feats = self.extractor.extract(
            additive_type=None,
            additive_mol_id=None,
            additive_wt=0.0,
            asphaltene_wt=20.0,
            polar_fraction=50.0,
        )
        assert all(v == 0.0 for v in feats.values())

    def test_zero_wt_zero_fill(self):
        """additive_wt=0 → all 13 features = 0.0 (guard clause)."""
        feats = self.extractor.extract(
            additive_type="polymer",
            additive_mol_id="ADD_003",
            additive_wt=0.0,
            asphaltene_wt=20.0,
            polar_fraction=50.0,
        )
        assert all(v == 0.0 for v in feats.values())

    def test_molecular_descriptors(self):
        """ADD_001 → correct MW/logP/HBD/HBA."""
        feats = self.extractor.extract(
            additive_type="surfactant",
            additive_mol_id="ADD_001",
            additive_wt=5.0,
            asphaltene_wt=20.0,
            polar_fraction=50.0,
        )
        desc = ADDITIVE_DESCRIPTOR_TABLE["ADD_001"]
        assert feats["additive_mw"] == desc.mw
        assert feats["additive_logp"] == desc.logp
        assert feats["additive_hbd"] == float(desc.hbd)
        assert feats["additive_hba"] == float(desc.hba)

    def test_canonical_mol_id_descriptors(self):
        """Canonical SSOT mol_id values should map descriptors as well."""
        feats = self.extractor.extract(
            additive_type="SBS",
            additive_mol_id="sbs",
            additive_wt=3.0,
            asphaltene_wt=20.0,
            polar_fraction=50.0,
        )
        assert feats["additive_mw"] == pytest.approx(1200.0)
        assert feats["additive_logp"] == pytest.approx(4.5)

    def test_unknown_mol_id_warning(self, caplog):
        """Unregistered mol_id → descriptors 0.0 + warning log."""
        with caplog.at_level(logging.WARNING):
            feats = self.extractor.extract(
                additive_type="polymer",
                additive_mol_id="ADD_999",
                additive_wt=5.0,
                asphaltene_wt=20.0,
                polar_fraction=50.0,
            )
        assert feats["additive_mw"] == 0.0
        assert feats["additive_logp"] == 0.0
        assert "ADD_999" in caplog.text

    def test_unknown_type_warning(self, caplog):
        """Unrecognized type → one-hot 0.0 + warning log."""
        with caplog.at_level(logging.WARNING):
            feats = self.extractor.extract(
                additive_type="unknown_additive",
                additive_mol_id=None,
                additive_wt=5.0,
                asphaltene_wt=20.0,
                polar_fraction=50.0,
            )
        assert feats["additive_is_polymer"] == 0.0
        assert feats["additive_is_surfactant"] == 0.0
        assert feats["additive_is_nanoparticle"] == 0.0
        assert "unknown_additive" in caplog.text

    def test_interaction_features(self):
        """additive_wt * asphaltene_wt accuracy."""
        feats = self.extractor.extract(
            additive_type="polymer",
            additive_mol_id="ADD_003",
            additive_wt=5.0,
            asphaltene_wt=20.0,
            polar_fraction=50.0,
        )
        assert feats["additive_wt_x_asphaltene_wt"] == pytest.approx(100.0)
        assert feats["additive_wt_x_polar_fraction"] == pytest.approx(250.0)
        desc = ADDITIVE_DESCRIPTOR_TABLE["ADD_003"]
        assert feats["additive_mw_x_additive_wt"] == pytest.approx(desc.mw * 5.0)

    def test_feature_count_13(self):
        """extract() result keys = ADDITIVE_FEATURE_NAMES (13 total)."""
        feats = self.extractor.extract(
            additive_type="polymer",
            additive_mol_id="ADD_003",
            additive_wt=5.0,
            asphaltene_wt=20.0,
            polar_fraction=50.0,
        )
        assert set(feats.keys()) == set(ADDITIVE_FEATURE_NAMES)
        assert len(feats) == 13

    def test_functional_tag_one_hot(self):
        """Each functional tag maps correctly."""
        # SBS → modifier
        feats = self.extractor.extract(
            additive_type="SBS",
            additive_mol_id="ADD_003",
            additive_wt=5.0,
            asphaltene_wt=20.0,
            polar_fraction=50.0,
        )
        assert feats["additive_func_modifier"] == 1.0
        assert feats["additive_func_anti_aging"] == 0.0
        assert feats["additive_func_anti_stripping"] == 0.0

        # PPA → anti-stripping
        feats2 = self.extractor.extract(
            additive_type="PPA",
            additive_mol_id="ADD_001",
            additive_wt=3.0,
            asphaltene_wt=20.0,
            polar_fraction=50.0,
        )
        assert feats2["additive_func_anti_stripping"] == 1.0
        assert feats2["additive_func_modifier"] == 0.0

    def test_extract_features_adapter(self):
        """extract_features(record) adapter delegates correctly."""
        # Create a minimal mock record
        from unittest.mock import MagicMock

        record = MagicMock()
        record.additive_type = "polymer"
        record.additive_mol_id = "ADD_003"
        record.additive_wt = 5.0
        record.build_result.actual_composition_wt = {
            "asphaltene": 20.0,
            "resin": 30.0,
        }

        feats = self.extractor.extract_features(record)
        assert len(feats) == 13
        assert feats["additive_is_polymer"] == 1.0
        assert feats["additive_wt_x_asphaltene_wt"] == pytest.approx(100.0)
        assert feats["additive_wt_x_polar_fraction"] == pytest.approx(250.0)

    def test_get_feature_set_version(self):
        """get_feature_set_version() returns FeatureSetVersion.V2."""
        from contracts.policies.ml_policy import FeatureSetVersion

        assert self.extractor.get_feature_set_version() == FeatureSetVersion.V2
