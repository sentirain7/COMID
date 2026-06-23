"""Tests for exp_id generation helper."""

import sys

import pytest

sys.path.insert(0, "src")

from common.pathing import (
    exp_id_to_material_id,
    generate_amorphous_exp_id,
    parse_exp_id,
)
from orchestrator.exp_id_helper import generate_exp_id_from_material, parse_material_id


class TestParseMaterialId:
    """Test material_id parsing with aging_state bug fix."""

    def test_non_aging(self):
        assert parse_material_id("AAA1_X1_non_aging") == ("AAA1", "X1", "non_aging")

    def test_short_aging(self):
        """Bug fix: parts[2] alone returned 'short' instead of 'short_aging'."""
        assert parse_material_id("AAK1_X3_short_aging") == ("AAK1", "X3", "short_aging")

    def test_long_aging(self):
        assert parse_material_id("AAA1_X1_long_aging") == ("AAA1", "X1", "long_aging")

    def test_single_part(self):
        assert parse_material_id("custom") == ("custom", "X1", "non_aging")

    def test_two_parts(self):
        assert parse_material_id("AAA1_X2") == ("AAA1", "X2", "non_aging")

    def test_empty_string(self):
        assert parse_material_id("") == ("", "X1", "non_aging")


class TestGenerateExpIdFromMaterial:
    """Test exp_id generation delegation."""

    def test_deterministic(self):
        kwargs = {
            "material_id": "AAA1_X1_non_aging",
            "temperature_k": 298.0,
            "ff_type": "bulk_ff_gaff2",
            "atom_count": 100000,
            "seed": 42,
        }
        id1 = generate_exp_id_from_material(**kwargs)
        id2 = generate_exp_id_from_material(**kwargs)
        assert id1 == id2

    def test_different_aging_produces_different_id(self):
        common = {
            "temperature_k": 298.0,
            "ff_type": "bulk_ff_gaff2",
            "atom_count": 100000,
            "seed": 42,
        }
        id_non = generate_exp_id_from_material(material_id="AAA1_X1_non_aging", **common)
        id_short = generate_exp_id_from_material(material_id="AAA1_X1_short_aging", **common)
        assert id_non != id_short

    def test_with_additive(self):
        exp_id = generate_exp_id_from_material(
            material_id="AAA1_X1_non_aging",
            temperature_k=298.0,
            ff_type="bulk_ff_gaff2",
            atom_count=100000,
            seed=42,
            additive="SBS",
        )
        assert isinstance(exp_id, str)
        assert len(exp_id) > 0


class TestGenerateAmorphousExpId:
    """Test amorphous cell exp_id generation."""

    def test_format(self):
        exp_id = generate_amorphous_exp_id(
            mol_id="H2O", boundary_mode="ppp", temperature_k=298.0, density=1.0, seed=42
        )
        assert exp_id.startswith("H2O_ppp_298K_d1.00_")
        assert len(exp_id.split("_")) == 5

    def test_deterministic(self):
        kwargs = {
            "mol_id": "H2O",
            "boundary_mode": "ppp",
            "temperature_k": 298.0,
            "density": 1.0,
            "seed": 42,
        }
        assert generate_amorphous_exp_id(**kwargs) == generate_amorphous_exp_id(**kwargs)

    def test_different_density_produces_different_id(self):
        common = {"mol_id": "Toluene", "boundary_mode": "ppf", "temperature_k": 323.0, "seed": 1}
        id1 = generate_amorphous_exp_id(density=0.87, **common)
        id2 = generate_amorphous_exp_id(density=1.00, **common)
        assert id1 != id2

    def test_different_mol_produces_different_id(self):
        common = {"boundary_mode": "ppp", "temperature_k": 298.0, "density": 1.0, "seed": 42}
        assert generate_amorphous_exp_id(mol_id="H2O", **common) != generate_amorphous_exp_id(
            mol_id="Toluene", **common
        )


class TestAmorphousBoundaryModeSync:
    """Verify _AMORPHOUS_BOUNDARY_MODES matches contracts SSOT."""

    def test_boundary_modes_match_contracts_enum(self):
        from common.pathing import _AMORPHOUS_BOUNDARY_MODES
        from contracts.schemas import AmorphousBoundaryMode

        enum_values = {m.value for m in AmorphousBoundaryMode}
        assert _AMORPHOUS_BOUNDARY_MODES == enum_values


class TestParseExpIdAmorphous:
    """Test parse_exp_id with amorphous format."""

    def test_parse_amorphous(self):
        exp_id = "H2O_ppp_298K_d1.00_a1b2c3"
        parsed = parse_exp_id(exp_id)
        assert parsed["binder_type"] == "H2O"
        assert parsed["structure_size"] == "ppp"
        assert parsed["temperature_k"] == 298.0
        assert parsed["density"] == 1.0
        assert parsed["hash"] == "a1b2c3"

    def test_parse_binder_unchanged(self):
        exp_id = "A1_X1_NA_none_298K_a1b2c3"
        parsed = parse_exp_id(exp_id)
        assert parsed["binder_type"] == "A1"
        assert parsed["structure_size"] == "X1"
        assert parsed["aging_state"] == "non_aging"
        assert parsed["temperature_k"] == 298.0

    def test_exp_id_to_material_id_amorphous(self):
        assert exp_id_to_material_id("H2O_ppp_298K_d1.00_a1b2c3") == "H2O"

    def test_exp_id_to_material_id_binder(self):
        material_id = exp_id_to_material_id("A1_X1_NA_none_298K_a1b2c3")
        assert material_id == "AAA1_X1_non_aging"


class TestLayeredExpIdFormat:
    """Test layered exp_id derives material from binder source."""

    def test_layered_exp_id_binder_derived(self):
        """material_id='AAA1_X1_non_aging' → exp_id starts with 'A1_X1_NA_'."""
        exp_id = generate_exp_id_from_material(
            material_id="AAA1_X1_non_aging",
            temperature_k=433.0,
            ff_type="bulk_ff_gaff2",
            atom_count=5000,
            seed=42,
            additive="SiO2",
        )
        assert exp_id.startswith("A1_X1_NA_")

    def test_layered_exp_id_crystal_material(self):
        """additive='SiO2' → exp_id contains 'SiO2'."""
        exp_id = generate_exp_id_from_material(
            material_id="AAA1_X1_non_aging",
            temperature_k=433.0,
            ff_type="bulk_ff_gaff2",
            atom_count=5000,
            seed=42,
            additive="SiO2",
        )
        assert "SiO2" in exp_id

    def test_layered_exp_id_parse_roundtrip(self):
        """parse_exp_id roundtrip for layered exp_id."""
        exp_id = generate_exp_id_from_material(
            material_id="AAA1_X1_non_aging",
            temperature_k=433.0,
            ff_type="bulk_ff_gaff2",
            atom_count=5000,
            seed=42,
            additive="SiO2",
        )
        parsed = parse_exp_id(exp_id)
        assert parsed["additive"] == "SiO2"
        assert parsed["binder_type"] == "A1"
        assert parsed["temperature_k"] == 433.0
        assert len(exp_id.split("_")) == 6

    def test_layered_exp_id_material_id_roundtrip(self):
        """exp_id_to_material_id restores binder material from layered exp_id."""
        exp_id = generate_exp_id_from_material(
            material_id="AAA1_X1_non_aging",
            temperature_k=433.0,
            ff_type="bulk_ff_gaff2",
            atom_count=5000,
            seed=42,
            additive="SiO2",
        )
        assert exp_id_to_material_id(exp_id) == "AAA1_X1_non_aging"

    def test_layered_exp_id_different_additives_distinct(self):
        """Different crystal materials produce different exp_ids."""
        common = {
            "material_id": "AAA1_X1_non_aging",
            "temperature_k": 433.0,
            "ff_type": "bulk_ff_gaff2",
            "atom_count": 5000,
            "seed": 42,
        }
        id_sio2 = generate_exp_id_from_material(additive="SiO2", **common)
        id_caco3 = generate_exp_id_from_material(additive="CaCO3", **common)
        assert id_sio2 != id_caco3
        assert "SiO2" in id_sio2
        assert "CaCO3" in id_caco3

    def test_crystal_descriptor_roundtrip(self):
        """additive='SiO2-001-OH' survives generate + parse roundtrip."""
        exp_id = generate_exp_id_from_material(
            material_id="AAA1_X1_non_aging",
            temperature_k=433.0,
            ff_type="bulk_ff_gaff2",
            atom_count=5000,
            seed=42,
            additive="SiO2-001-OH",
        )
        parsed = parse_exp_id(exp_id)
        assert parsed["additive"] == "SiO2-001-OH"
        assert parsed["binder_type"] == "A1"
        assert parsed["temperature_k"] == 433.0
        assert len(exp_id.split("_")) == 6

    def test_crystal_descriptor_uniqueness(self):
        """SiO2 vs SiO2-001 vs SiO2-001-OH produce distinct exp_ids."""
        common = {
            "material_id": "AAA1_X1_non_aging",
            "temperature_k": 433.0,
            "ff_type": "bulk_ff_gaff2",
            "atom_count": 5000,
            "seed": 42,
        }
        id_bare = generate_exp_id_from_material(additive="SiO2", **common)
        id_surface = generate_exp_id_from_material(additive="SiO2-001", **common)
        id_full = generate_exp_id_from_material(additive="SiO2-001-OH", **common)
        assert len({id_bare, id_surface, id_full}) == 3

    def test_old_format_still_parses(self):
        """Old-format additive='SiO2' (no surface) still parses correctly."""
        parsed = parse_exp_id("A1_X1_NA_SiO2_433K_abc123")
        assert parsed["additive"] == "SiO2"
        assert parsed["binder_type"] == "A1"

    def test_crystal_descriptor_path_safe(self):
        """get_experiment_path works with hyphenated crystal descriptor."""
        from common.pathing import get_experiment_path

        exp_id = generate_exp_id_from_material(
            material_id="AAA1_X1_non_aging",
            temperature_k=433.0,
            ff_type="bulk_ff_gaff2",
            atom_count=5000,
            seed=42,
            additive="SiO2-001-OH",
        )
        path = get_experiment_path(exp_id)
        assert "SiO2-001-OH" in str(path)
        # Path should be constructible (no invalid chars)
        assert path.name == exp_id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
