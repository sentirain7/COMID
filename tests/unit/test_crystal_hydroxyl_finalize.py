"""Tests for hydroxyl type finalization in crystal builder.

Validates charge neutrality, type reclassification, and cation selection
across all oxide materials in the CHARGES dict.
"""

import sys

import pytest

sys.path.insert(0, "src")

from builder.crystal_builder import CrystalBuilder, _base_element
from builder.layer_spec import CrystalMaterial, CrystalSpec


@pytest.fixture(scope="module")
def builder() -> CrystalBuilder:
    return CrystalBuilder()


def _build_hydroxylated(
    builder: CrystalBuilder,
    material: CrystalMaterial,
    xy: float = 25.0,
    thick: float = 15.0,
) -> "CrystalBuilder":
    """Helper to build a hydroxylated slab."""
    spec = CrystalSpec(
        material=material,
        thickness_angstrom=thick,
        xy_size_angstrom=xy,
        hydroxylated=True,
    )
    return builder.build(spec)


class TestSiO2Hydroxylation:
    """Core SiO2 hydroxylation tests."""

    def test_hydroxylated_sio2_charge_neutral(self, builder):
        slab = _build_hydroxylated(builder, CrystalMaterial.SIO2)
        total_q = sum(a.charge for a in slab.atoms)
        assert abs(total_q) < 1e-4, f"SiO2 charge not neutral: {total_q}"

    def test_hydroxylated_sio2_has_surface_types(self, builder):
        slab = _build_hydroxylated(builder, CrystalMaterial.SIO2)
        assert "Si_s" in slab.atom_types
        assert "Os" in slab.atom_types
        assert "Hoh" in slab.atom_types
        assert "Si" in slab.atom_types
        assert "O" in slab.atom_types
        assert "H" not in slab.atom_types

    def test_os_charge_derived_from_ssot(self, builder):
        slab = _build_hydroxylated(builder, CrystalMaterial.SIO2)
        charges = CrystalBuilder.CHARGES[CrystalMaterial.SIO2]
        expected_q_os = charges["O"] - 0.4
        os_atoms = [a for a in slab.atoms if a.element == "Os"]
        assert len(os_atoms) > 0
        for a in os_atoms:
            assert abs(a.charge - expected_q_os) < 1e-6

    def test_cation_s_charge_unchanged(self, builder):
        slab = _build_hydroxylated(builder, CrystalMaterial.SIO2)
        charges = CrystalBuilder.CHARGES[CrystalMaterial.SIO2]
        si_s_atoms = [a for a in slab.atoms if a.element == "Si_s"]
        assert len(si_s_atoms) > 0
        for a in si_s_atoms:
            assert abs(a.charge - charges["Si"]) < 1e-6


class TestCarbonateSelection:
    """Finding 1 fix: CaCO3/MgCO3 must select Ca/Mg, not C."""

    def test_hydroxylated_calcite_selects_ca_not_c(self, builder):
        slab = _build_hydroxylated(builder, CrystalMaterial.CITE)
        assert "Ca_s" in slab.atom_types
        assert "C_s" not in slab.atom_types

    def test_hydroxylated_mgco3_selects_mg_not_c(self, builder):
        slab = _build_hydroxylated(builder, CrystalMaterial.MGCO3)
        assert "Mg_s" in slab.atom_types
        assert "C_s" not in slab.atom_types


class TestCountInvariants:
    """Hoh/Os count invariants."""

    def test_hoh_count_equals_os_count(self, builder):
        slab = _build_hydroxylated(builder, CrystalMaterial.SIO2)
        n_hoh = sum(1 for a in slab.atoms if a.element == "Hoh")
        n_os = sum(1 for a in slab.atoms if a.element == "Os")
        assert n_hoh == n_os, f"Hoh={n_hoh} != Os={n_os}"

    def test_cation_s_count_bounded(self, builder):
        slab = _build_hydroxylated(builder, CrystalMaterial.SIO2)
        n_os = sum(1 for a in slab.atoms if a.element == "Os")
        n_si_s = sum(1 for a in slab.atoms if a.element == "Si_s")
        assert 0 < n_si_s <= n_os


class TestNonHydroxylated:
    """Non-hydroxylated slabs remain unchanged."""

    def test_non_hydroxylated_unchanged(self, builder):
        spec = CrystalSpec(
            material=CrystalMaterial.SIO2,
            thickness_angstrom=15.0,
            xy_size_angstrom=25.0,
            hydroxylated=False,
        )
        slab = builder.build(spec)
        assert "Os" not in slab.atom_types
        assert "Hoh" not in slab.atom_types
        assert "Si_s" not in slab.atom_types


# Materials with oxygen in CHARGES (oxide materials)
_OXIDE_MATERIALS = [m for m in CrystalMaterial if "O" in CrystalBuilder.CHARGES.get(m, {})]


@pytest.mark.parametrize("material", _OXIDE_MATERIALS)
def test_all_oxide_materials_neutral(builder, material):
    """All oxide materials must be charge neutral after hydroxylation."""
    slab = _build_hydroxylated(builder, material, xy=20.0, thick=12.0)
    total_q = sum(a.charge for a in slab.atoms)
    assert abs(total_q) < 0.01, f"{material.value} charge not neutral: {total_q:.4f}"


class TestMetalHydroxylation:
    """Metals (no O in CHARGES) skip finalize gracefully."""

    def test_metal_hydroxylated_skips_finalize(self, builder):
        spec = CrystalSpec(
            material=CrystalMaterial.AL,
            thickness_angstrom=12.0,
            xy_size_angstrom=20.0,
            hydroxylated=True,
        )
        slab = builder.build(spec)
        # No O in CHARGES → finalize skipped, no Os/Hoh/Si_s
        assert "Os" not in slab.atom_types
        assert "Hoh" not in slab.atom_types


class TestLAMMPSDataMasses:
    """Mass lookup via _base_element for subtype labels."""

    def test_lammps_data_masses_correct(self, builder, tmp_path):
        from common.constants import ATOMIC_WEIGHTS

        slab = _build_hydroxylated(builder, CrystalMaterial.SIO2)
        data_file = tmp_path / "crystal.data"
        slab.to_lammps_data(data_file)
        content = data_file.read_text()

        # Si_s should have Si mass
        assert f"{ATOMIC_WEIGHTS['Si']:.4f}" in content
        # Os should have O mass
        assert f"{ATOMIC_WEIGHTS['O']:.4f}" in content
        # Hoh should have H mass
        assert f"{ATOMIC_WEIGHTS['H']:.4f}" in content


class TestSmallSlab:
    """Charge neutrality on small slabs."""

    def test_charge_neutrality_small_slab(self, builder):
        spec = CrystalSpec(
            material=CrystalMaterial.SIO2,
            nx=2,
            ny=2,
            nz=1,
            hydroxylated=True,
        )
        slab = builder.build(spec)
        total_q = sum(a.charge for a in slab.atoms)
        assert abs(total_q) < 0.01


class TestTypeIdContiguous:
    """atom_types values should be contiguous 1..N."""

    def test_type_id_contiguous(self, builder):
        slab = _build_hydroxylated(builder, CrystalMaterial.SIO2)
        type_ids = sorted(slab.atom_types.values())
        assert type_ids == list(range(1, len(type_ids) + 1))


class TestBaseElement:
    """Test module-level _base_element function."""

    def test_os(self):
        assert _base_element("Os") == "O"

    def test_hoh(self):
        assert _base_element("Hoh") == "H"

    def test_si_s(self):
        assert _base_element("Si_s") == "Si"

    def test_ca_s(self):
        assert _base_element("Ca_s") == "Ca"

    def test_plain(self):
        assert _base_element("Si") == "Si"
        assert _base_element("O") == "O"
        assert _base_element("H") == "H"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
