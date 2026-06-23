"""Tests for CrystalBuilder.preferred_surface() — dynamic surface inference."""

from builder.crystal_builder import CrystalBuilder
from builder.layer_spec import CrystalMaterial, SurfaceOrientation


class TestPreferredSurface:
    """Verify preferred surface is derived from crystal structure properties."""

    # -- Hexagonal / Trigonal: always (001) basal plane --

    def test_sio2_hexagonal_returns_001(self):
        assert (
            CrystalBuilder.preferred_surface(CrystalMaterial.SIO2) == SurfaceOrientation.ORIENT_001
        )

    def test_caco3_hexagonal_returns_001(self):
        assert (
            CrystalBuilder.preferred_surface(CrystalMaterial.CITE) == SurfaceOrientation.ORIENT_001
        )

    def test_al2o3_hexagonal_returns_001(self):
        assert (
            CrystalBuilder.preferred_surface(CrystalMaterial.AL2O3) == SurfaceOrientation.ORIENT_001
        )

    def test_fe2o3_hexagonal_returns_001(self):
        assert (
            CrystalBuilder.preferred_surface(CrystalMaterial.FE2O3) == SurfaceOrientation.ORIENT_001
        )

    def test_mgco3_hexagonal_returns_001(self):
        assert (
            CrystalBuilder.preferred_surface(CrystalMaterial.MGCO3) == SurfaceOrientation.ORIENT_001
        )

    def test_zno_hexagonal_returns_001(self):
        assert (
            CrystalBuilder.preferred_surface(CrystalMaterial.ZNO) == SurfaceOrientation.ORIENT_001
        )

    # -- Rocksalt (cubic, 8 atoms, 2 elements): (001) --

    def test_mgo_rocksalt_returns_001(self):
        assert (
            CrystalBuilder.preferred_surface(CrystalMaterial.MGO) == SurfaceOrientation.ORIENT_001
        )

    def test_cao_rocksalt_returns_001(self):
        assert (
            CrystalBuilder.preferred_surface(CrystalMaterial.CAO) == SurfaceOrientation.ORIENT_001
        )

    def test_nacl_rocksalt_returns_001(self):
        assert (
            CrystalBuilder.preferred_surface(CrystalMaterial.NACL) == SurfaceOrientation.ORIENT_001
        )

    def test_kcl_rocksalt_returns_001(self):
        assert (
            CrystalBuilder.preferred_surface(CrystalMaterial.KCL) == SurfaceOrientation.ORIENT_001
        )

    # -- Rutile (tetragonal, 6 atoms): (110) --

    def test_tio2_rutile_returns_110(self):
        assert (
            CrystalBuilder.preferred_surface(CrystalMaterial.TIO2) == SurfaceOrientation.ORIENT_110
        )

    # -- FCC metals (cubic, 4 atoms, 1 element): (111) --

    def test_al_fcc_returns_111(self):
        assert CrystalBuilder.preferred_surface(CrystalMaterial.AL) == SurfaceOrientation.ORIENT_111

    def test_cu_fcc_returns_111(self):
        assert CrystalBuilder.preferred_surface(CrystalMaterial.CU) == SurfaceOrientation.ORIENT_111

    def test_ni_fcc_returns_111(self):
        assert CrystalBuilder.preferred_surface(CrystalMaterial.NI) == SurfaceOrientation.ORIENT_111

    # -- BCC metal (cubic, 2 atoms, 1 element): (110) --

    def test_fe_bcc_returns_110(self):
        assert CrystalBuilder.preferred_surface(CrystalMaterial.FE) == SurfaceOrientation.ORIENT_110

    # -- Fallback for unknown material --

    def test_aggregate_fallback_returns_001(self):
        assert (
            CrystalBuilder.preferred_surface(CrystalMaterial.AGGREGATE)
            == SurfaceOrientation.ORIENT_001
        )

    # -- Structural inference, not hardcoding --

    def test_inference_is_from_unit_cell_not_material_name(self):
        """Verify the function reads UNIT_CELLS properties, not the material enum name."""
        # TiO2 is tetragonal (a=b != c), 6 atoms, 2 elements → 110
        uc = CrystalBuilder.UNIT_CELLS[CrystalMaterial.TIO2]
        assert uc["a"] == uc["b"]  # tetragonal: a = b
        assert uc["a"] != uc["c"]  # tetragonal: a != c
        assert len(uc["atoms"]) == 6
        assert len({e for e, *_ in uc["atoms"]}) == 2
        # All these properties lead to (110) — not a lookup by name
        assert (
            CrystalBuilder.preferred_surface(CrystalMaterial.TIO2) == SurfaceOrientation.ORIENT_110
        )

    def test_fe_inference_from_bcc_structure(self):
        """Verify Fe → 110 comes from 2-atom cubic cell, not from name."""
        uc = CrystalBuilder.UNIT_CELLS[CrystalMaterial.FE]
        assert len(uc["atoms"]) == 2  # BCC
        assert len({e for e, *_ in uc["atoms"]}) == 1  # pure metal
        assert uc["a"] == uc["b"] == uc["c"]  # cubic
        assert CrystalBuilder.preferred_surface(CrystalMaterial.FE) == SurfaceOrientation.ORIENT_110
