"""API schema default-value consistency tests."""

from api.schemas import CrystalStructureCreateRequest
from contracts.schemas import CrystalLayerSpec


def test_crystal_create_request_defaults_match_ssot_crystal_layer_spec():
    """CrystalStructureCreateRequest defaults should track CrystalLayerSpec (SSOT)."""
    req = CrystalStructureCreateRequest(name="default-check")
    ssot = CrystalLayerSpec()

    assert req.material == ssot.material
    assert req.surface == ssot.surface
    assert req.cell_mode == ssot.cell_mode
    assert req.thickness_angstrom == ssot.thickness_angstrom
    assert req.xy_size_angstrom == ssot.xy_size_angstrom
    assert req.nx == ssot.nx
    assert req.ny == ssot.ny
    assert req.nz == ssot.nz
    assert req.hydroxylated == ssot.hydroxylated
    assert req.hydroxyl_density == ssot.hydroxyl_density
