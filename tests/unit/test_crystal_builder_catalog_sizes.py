"""Coverage tests for crystal builder across catalog materials and sizes."""

import pytest

from builder.crystal_builder import CrystalBuilder
from builder.layer_spec import CrystalMaterial, CrystalSpec

_XY_SIZES = [20.0, 30.0, 40.0, 60.0]


@pytest.fixture(scope="module")
def builder() -> CrystalBuilder:
    return CrystalBuilder()


@pytest.mark.parametrize("material", list(CrystalMaterial))
@pytest.mark.parametrize("xy_size", _XY_SIZES)
def test_crystal_builder_generates_all_materials_across_sizes(
    builder: CrystalBuilder,
    material: CrystalMaterial,
    xy_size: float,
) -> None:
    slab = builder.build(
        CrystalSpec(
            material=material,
            thickness_angstrom=max(12.0, xy_size / 2.0),
            xy_size_angstrom=xy_size,
            hydroxylated=True,
        )
    )

    assert slab.n_atoms == len(slab.atoms)
    assert slab.n_atoms > 0
    assert slab.box[0] > 0.0 and slab.box[1] > 0.0 and slab.box[2] > 0.0

    xs = [atom.x for atom in slab.atoms]
    ys = [atom.y for atom in slab.atoms]
    zs = [atom.z for atom in slab.atoms]
    tol = 1e-6

    assert min(xs) >= -tol
    assert max(xs) <= slab.box[0] + tol
    assert min(ys) >= -tol
    assert max(ys) <= slab.box[1] + tol
    assert min(zs) >= -tol
    assert max(zs) <= slab.box[2] + tol

    # Charge neutrality check
    total_q = sum(a.charge for a in slab.atoms)
    assert abs(total_q) < 0.01, f"Charge not neutral for {material}: {total_q:.4f}"

    if slab.transformation_matrix is not None:
        assert slab.n_cells_xy is not None
        assert slab.error_xy_pct is not None
