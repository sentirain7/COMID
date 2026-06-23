"""Tests for crystal auto-match in layered structure service."""

import pytest

from api.schemas import LayerStackItemRequest
from contracts.errors import ContractError
from contracts.schemas import LayerSourceType
from features.layered_structures.service import _auto_select_crystal, _crystal_row_box_size


class TestCrystalRowBoxSize:
    """Test box size extraction from YAML rows."""

    def test_prefers_actual_lx_ly(self):
        row = {
            "xy_size_angstrom": 40.0,
            "thickness_angstrom": 25.0,
            "metadata": {
                "actual_lx_angstrom": 44.22,
                "actual_ly_angstrom": 42.55,
            },
        }
        lx, ly, lz = _crystal_row_box_size(row)
        assert abs(lx - 44.22) < 0.01
        assert abs(ly - 42.55) < 0.01
        assert abs(lz - 25.0) < 0.01

    def test_falls_back_to_xy_size(self):
        row = {
            "xy_size_angstrom": 40.0,
            "thickness_angstrom": 25.0,
            "metadata": {},
        }
        lx, ly, lz = _crystal_row_box_size(row)
        assert abs(lx - 40.0) < 0.01
        assert abs(ly - 40.0) < 0.01

    def test_missing_metadata(self):
        row = {
            "xy_size_angstrom": 38.0,
            "thickness_angstrom": 20.0,
        }
        lx, ly, lz = _crystal_row_box_size(row)
        assert abs(lx - 38.0) < 0.01
        assert abs(ly - 38.0) < 0.01
        assert abs(lz - 20.0) < 0.01

    def test_empty_row(self):
        row = {}
        lx, ly, lz = _crystal_row_box_size(row)
        assert lx == 0.0
        assert ly == 0.0
        assert lz == 0.0


class TestAutoSelectCrystal:
    """Test _auto_select_crystal with mocked YAML catalog."""

    def test_selects_closest_crystal(self, monkeypatch):
        fake_catalog = {
            "structures": [
                {
                    "crystal_id": "crys_001",
                    "material": "SiO2",
                    "status": "ready",
                    "xy_size_angstrom": 40.0,
                    "thickness_angstrom": 25.0,
                    "metadata": {"actual_lx_angstrom": 39.3, "actual_ly_angstrom": 38.3},
                },
                {
                    "crystal_id": "crys_002",
                    "material": "SiO2",
                    "status": "ready",
                    "xy_size_angstrom": 44.0,
                    "thickness_angstrom": 25.0,
                    "metadata": {"actual_lx_angstrom": 44.22, "actual_ly_angstrom": 42.55},
                },
                {
                    "crystal_id": "crys_003",
                    "material": "SiO2",
                    "status": "ready",
                    "xy_size_angstrom": 50.0,
                    "thickness_angstrom": 25.0,
                    "metadata": {"actual_lx_angstrom": 49.13, "actual_ly_angstrom": 46.80},
                },
            ]
        }
        monkeypatch.setattr(
            "features.layered_structures.layer_source_resolver.load_crystal_structures_config",
            lambda: fake_catalog,
        )
        # Target 43x43 should match crys_002 (44.22 x 42.55)
        result = _auto_select_crystal("SiO2", 43.0, 43.0)
        assert result == "crys_002"

    def test_filters_by_material(self, monkeypatch):
        fake_catalog = {
            "structures": [
                {
                    "crystal_id": "crys_sio2",
                    "material": "SiO2",
                    "status": "ready",
                    "xy_size_angstrom": 40.0,
                    "thickness_angstrom": 25.0,
                    "metadata": {},
                },
                {
                    "crystal_id": "crys_mgo",
                    "material": "MgO",
                    "status": "ready",
                    "xy_size_angstrom": 42.0,
                    "thickness_angstrom": 25.0,
                    "metadata": {},
                },
            ]
        }
        monkeypatch.setattr(
            "features.layered_structures.layer_source_resolver.load_crystal_structures_config",
            lambda: fake_catalog,
        )
        result = _auto_select_crystal("MgO", 42.0, 42.0)
        assert result == "crys_mgo"

    def test_raises_for_missing_material(self, monkeypatch):
        fake_catalog = {"structures": []}
        monkeypatch.setattr(
            "features.layered_structures.layer_source_resolver.load_crystal_structures_config",
            lambda: fake_catalog,
        )
        from contracts.errors import ContractError

        with pytest.raises(ContractError):
            _auto_select_crystal("Unknown", 40.0, 40.0)

    def test_case_insensitive_material(self, monkeypatch):
        fake_catalog = {
            "structures": [
                {
                    "crystal_id": "crys_001",
                    "material": "SiO2",
                    "status": "ready",
                    "xy_size_angstrom": 40.0,
                    "thickness_angstrom": 25.0,
                    "metadata": {},
                },
            ]
        }
        monkeypatch.setattr(
            "features.layered_structures.layer_source_resolver.load_crystal_structures_config",
            lambda: fake_catalog,
        )
        result = _auto_select_crystal("SIO2", 40.0, 40.0)
        assert result == "crys_001"

    def test_skips_non_ready_crystals(self, monkeypatch):
        fake_catalog = {
            "structures": [
                {
                    "crystal_id": "crys_failed",
                    "material": "SiO2",
                    "status": "failed",
                    "xy_size_angstrom": 40.0,
                    "thickness_angstrom": 25.0,
                    "metadata": {"actual_lx_angstrom": 40.0, "actual_ly_angstrom": 40.0},
                },
                {
                    "crystal_id": "crys_ready",
                    "material": "SiO2",
                    "status": "ready",
                    "xy_size_angstrom": 50.0,
                    "thickness_angstrom": 25.0,
                    "metadata": {"actual_lx_angstrom": 49.0, "actual_ly_angstrom": 47.0},
                },
            ]
        }
        monkeypatch.setattr(
            "features.layered_structures.layer_source_resolver.load_crystal_structures_config",
            lambda: fake_catalog,
        )
        result = _auto_select_crystal("SiO2", 40.0, 40.0)
        assert result == "crys_ready"

    def test_prefers_default_interface_variant(self, monkeypatch):
        fake_catalog = {
            "structures": [
                {
                    "crystal_id": "crys_nondefault",
                    "material": "SiO2",
                    "surface": "010",
                    "cell_mode": "orthogonalized",
                    "hydroxylated": True,
                    "status": "ready",
                    "xy_size_angstrom": 43.0,
                    "thickness_angstrom": 25.0,
                    "metadata": {"actual_lx_angstrom": 43.0, "actual_ly_angstrom": 43.0},
                },
                {
                    "crystal_id": "crys_default",
                    "material": "SiO2",
                    "surface": "001",
                    "cell_mode": "orthogonalized",
                    "hydroxylated": True,
                    "status": "ready",
                    "xy_size_angstrom": 45.0,
                    "thickness_angstrom": 25.0,
                    "metadata": {"actual_lx_angstrom": 44.2, "actual_ly_angstrom": 42.6},
                },
            ]
        }
        monkeypatch.setattr(
            "features.layered_structures.layer_source_resolver.load_crystal_structures_config",
            lambda: fake_catalog,
        )

        result = _auto_select_crystal("SiO2", 43.0, 43.0)
        assert result == "crys_default"

    def test_raises_for_ambiguous_nondefault_variants(self, monkeypatch):
        fake_catalog = {
            "structures": [
                {
                    "crystal_id": "crys_010",
                    "material": "SiO2",
                    "surface": "010",
                    "cell_mode": "orthogonalized",
                    "hydroxylated": True,
                    "status": "ready",
                    "xy_size_angstrom": 42.0,
                    "thickness_angstrom": 25.0,
                    "metadata": {"actual_lx_angstrom": 42.0, "actual_ly_angstrom": 42.0},
                },
                {
                    "crystal_id": "crys_dry",
                    "material": "SiO2",
                    "surface": "001",
                    "cell_mode": "orthogonalized",
                    "hydroxylated": False,
                    "status": "ready",
                    "xy_size_angstrom": 42.0,
                    "thickness_angstrom": 25.0,
                    "metadata": {"actual_lx_angstrom": 42.0, "actual_ly_angstrom": 42.0},
                },
            ]
        }
        monkeypatch.setattr(
            "features.layered_structures.layer_source_resolver.load_crystal_structures_config",
            lambda: fake_catalog,
        )

        with pytest.raises(ContractError, match="Auto-match is ambiguous"):
            _auto_select_crystal("SiO2", 42.0, 42.0)


class TestLayerStackItemRequest:
    """Validation tests for layer source request items."""

    def test_crystal_auto_match_requires_no_manual_source(self):
        item = LayerStackItemRequest(
            source_type=LayerSourceType.CRYSTAL_STRUCTURE,
            auto_match_material=" SiO2 ",
        )

        assert item.source_id is None
        assert item.auto_match_material == "SiO2"

    def test_crystal_auto_match_and_manual_source_are_mutually_exclusive(self):
        with pytest.raises(ValueError, match="exactly one"):
            LayerStackItemRequest(
                source_type=LayerSourceType.CRYSTAL_STRUCTURE,
                source_id="crys_001",
                auto_match_material="SiO2",
            )

    def test_non_crystal_layers_require_source_id(self):
        with pytest.raises(ValueError, match="source_id is required"):
            LayerStackItemRequest(
                source_type=LayerSourceType.BINDER_CELL,
            )

    def test_non_crystal_layers_reject_auto_match_material(self):
        with pytest.raises(ValueError, match="only supported for crystal_structure"):
            LayerStackItemRequest(
                source_type=LayerSourceType.BINDER_CELL,
                auto_match_material="SiO2",
            )
