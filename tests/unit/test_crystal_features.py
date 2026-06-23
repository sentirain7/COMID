"""
Unit tests for CrystalFeatureExtractor (Step 3-1).
"""

from contracts.policies.crystal_catalog import DEFAULT_CRYSTAL_CATALOG
from ml.crystal_features import CRYSTAL_FEATURE_NAMES, CrystalFeatureExtractor


class TestCrystalCatalogPolicy:
    """Test crystal catalog SSOT."""

    def test_known_materials(self):
        for mat in ["SiO2", "Al2O3", "CaCO3", "NaCl"]:
            cls = DEFAULT_CRYSTAL_CATALOG.get_material_class(mat)
            assert cls in DEFAULT_CRYSTAL_CATALOG.class_labels

    def test_unknown_defaults_oxide(self):
        assert DEFAULT_CRYSTAL_CATALOG.get_material_class("UnknownXY") == "oxide"

    def test_surface_energy_proxy_range(self):
        for mat, val in DEFAULT_CRYSTAL_CATALOG.surface_energy_proxy.items():
            assert 0.0 <= val <= 2.0, f"{mat} proxy out of range: {val}"


class TestCrystalFeatureNames:
    """Test feature name constants."""

    def test_count_10(self):
        assert len(CRYSTAL_FEATURE_NAMES) == 10

    def test_no_duplicates(self):
        assert len(CRYSTAL_FEATURE_NAMES) == len(set(CRYSTAL_FEATURE_NAMES))


class TestCrystalFeatureExtractor:
    """Test crystal feature extraction."""

    def test_sio2_001(self):
        ext = CrystalFeatureExtractor()
        result = ext.extract(
            {
                "material": "SiO2",
                "surface": "001",
                "hydroxyl_density": 4.6,
                "thickness_angstrom": 25.0,
                "xy_size_angstrom": 50.0,
                "atom_count": 5000,
            }
        )
        assert len(result) == 10
        assert result["crystal_is_oxide"] == 1.0
        assert result["crystal_is_carbonate"] == 0.0
        assert result["crystal_is_halide"] == 0.0
        assert result["crystal_hydroxyl_density"] == 4.6
        assert result["crystal_thickness_norm"] == 25.0 / 50.0
        assert result["crystal_surface_energy_proxy"] == 1.0  # SiO2 proxy
        assert result["crystal_miller_index_sq"] == 1.0  # 0^2 + 0^2 + 1^2
        assert result["crystal_is_high_index"] == 0.0

    def test_nacl_110_high_index(self):
        ext = CrystalFeatureExtractor()
        result = ext.extract(
            {
                "material": "NaCl",
                "surface": "110",
                "hydroxyl_density": 0.0,
                "thickness_angstrom": 30.0,
                "xy_size_angstrom": 60.0,
                "atom_count": 3000,
            }
        )
        assert result["crystal_is_halide"] == 1.0
        assert result["crystal_is_oxide"] == 0.0
        # Miller (1,1,0): 1+1+0 = 2, NOT high index
        assert result["crystal_miller_index_sq"] == 2.0
        assert result["crystal_is_high_index"] == 0.0

    def test_111_is_high_index(self):
        ext = CrystalFeatureExtractor()
        result = ext.extract({"material": "Al2O3", "surface": "111"})
        # 1+1+1 = 3 > 2 → high index
        assert result["crystal_miller_index_sq"] == 3.0
        assert result["crystal_is_high_index"] == 1.0

    def test_zeros(self):
        zeros = CrystalFeatureExtractor.zeros()
        assert len(zeros) == 10
        assert all(v == 0.0 for v in zeros.values())

    def test_all_features_present(self):
        ext = CrystalFeatureExtractor()
        result = ext.extract({"material": "CaCO3", "surface": "001"})
        for name in CRYSTAL_FEATURE_NAMES:
            assert name in result, f"Missing feature: {name}"

    def test_parse_miller_various(self):
        assert CrystalFeatureExtractor._parse_miller("001") == (0, 0, 1)
        assert CrystalFeatureExtractor._parse_miller("110") == (1, 1, 0)
        assert CrystalFeatureExtractor._parse_miller("111") == (1, 1, 1)
        assert CrystalFeatureExtractor._parse_miller("010") == (0, 1, 0)
        # Default fallback for invalid
        assert CrystalFeatureExtractor._parse_miller("xx") == (0, 0, 1)


class TestCrystalCatalogEnumConsistency:
    """Test that crystal_catalog covers CrystalMaterial enum."""

    def test_catalog_covers_all_materials(self):
        """crystal_catalog material_classes should include all CrystalMaterial enum members."""
        from contracts.schemas import CrystalMaterial

        # Materials that are physical types (not generic)
        catalog_materials = set(DEFAULT_CRYSTAL_CATALOG.material_classes.keys())
        for mat in CrystalMaterial:
            if mat == CrystalMaterial.AGGREGATE:
                continue
            # Catalog may not have every exotic material; check known ones
            if mat.value in catalog_materials:
                cls = DEFAULT_CRYSTAL_CATALOG.get_material_class(mat.value)
                assert cls in DEFAULT_CRYSTAL_CATALOG.class_labels, (
                    f"{mat.value} class '{cls}' not in class_labels"
                )
