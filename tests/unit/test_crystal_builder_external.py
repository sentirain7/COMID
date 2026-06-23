"""Tests for external unit-cell build path in CrystalBuilder."""

import pytest

from builder.crystal_builder import CrystalBuilder
from builder.layer_spec import CrystalCellMode, CrystalMaterial, CrystalSpec, SurfaceOrientation


def test_build_from_external_unit_cell():
    builder = CrystalBuilder()
    spec = CrystalSpec(
        material=CrystalMaterial.AGGREGATE,
        surface=SurfaceOrientation.ORIENT_001,
        thickness_angstrom=4.0,
        xy_size_angstrom=4.0,
        nx=2,
        ny=2,
        nz=2,
        hydroxylated=False,
        hydroxyl_density=4.6,
        use_matrix_search=False,
    )

    unit_cell = {
        "a": 2.0,
        "b": 2.0,
        "c": 2.0,
        "alpha": 90.0,
        "beta": 90.0,
        "gamma": 90.0,
        "atoms": [
            ("Si", 0.0, 0.0, 0.0),
            ("O", 0.5, 0.5, 0.5),
        ],
    }

    slab = builder.build_from_unit_cell(spec, unit_cell, material=CrystalMaterial.AGGREGATE)
    assert slab.material == CrystalMaterial.AGGREGATE
    assert slab.n_atoms == 16  # 2 atoms/cell * 2*2*2 replication
    assert set(slab.atom_types.keys()) == {"Si", "O"}


def test_build_from_external_unit_cell_missing_fields():
    builder = CrystalBuilder()
    spec = CrystalSpec(
        material=CrystalMaterial.AGGREGATE,
        surface=SurfaceOrientation.ORIENT_001,
        thickness_angstrom=4.0,
        xy_size_angstrom=4.0,
        nx=1,
        ny=1,
        nz=1,
        hydroxylated=False,
        hydroxyl_density=4.6,
        use_matrix_search=False,
    )

    invalid_unit_cell = {"a": 2.0, "b": 2.0, "c": 2.0, "atoms": [("Si", 0.0, 0.0, 0.0)]}
    with pytest.raises(ValueError, match="missing required fields"):
        builder.build_from_unit_cell(spec, invalid_unit_cell)


def test_build_from_external_unit_cell_rejects_triclinic_alpha_beta():
    builder = CrystalBuilder()
    spec = CrystalSpec(
        material=CrystalMaterial.AGGREGATE,
        surface=SurfaceOrientation.ORIENT_001,
        thickness_angstrom=4.0,
        xy_size_angstrom=4.0,
        nx=1,
        ny=1,
        nz=1,
        hydroxylated=False,
        hydroxyl_density=4.6,
        use_matrix_search=False,
    )

    triclinic_unit_cell = {
        "a": 2.0,
        "b": 2.0,
        "c": 2.0,
        "alpha": 88.0,
        "beta": 92.0,
        "gamma": 90.0,
        "atoms": [("Si", 0.0, 0.0, 0.0)],
    }

    with pytest.raises(ValueError, match="non-orthogonal alpha/beta"):
        builder.build_from_unit_cell(spec, triclinic_unit_cell)


def test_build_from_external_unit_cell_orthogonalizes_xy_when_enabled():
    builder = CrystalBuilder()
    unit_cell = {
        "a": 2.0,
        "b": 2.0,
        "c": 2.0,
        "alpha": 90.0,
        "beta": 90.0,
        "gamma": 120.0,
        "atoms": [("Si", 0.0, 0.0, 0.0)],
    }

    native = CrystalSpec(
        material=CrystalMaterial.AGGREGATE,
        surface=SurfaceOrientation.ORIENT_001,
        cell_mode=CrystalCellMode.NATIVE_SKEW,
        thickness_angstrom=4.0,
        xy_size_angstrom=4.0,
        nx=2,
        ny=2,
        nz=1,
        hydroxylated=False,
        hydroxyl_density=4.6,
        use_matrix_search=False,
    )
    ortho = CrystalSpec(
        material=CrystalMaterial.AGGREGATE,
        surface=SurfaceOrientation.ORIENT_001,
        cell_mode=CrystalCellMode.ORTHOGONALIZED,
        thickness_angstrom=4.0,
        xy_size_angstrom=4.0,
        nx=2,
        ny=2,
        nz=1,
        hydroxylated=False,
        hydroxyl_density=4.6,
        use_matrix_search=False,
    )

    native_slab = builder.build_from_unit_cell(
        native, unit_cell, material=CrystalMaterial.AGGREGATE
    )
    ortho_slab = builder.build_from_unit_cell(ortho, unit_cell, material=CrystalMaterial.AGGREGATE)

    native_unique_x = {round(atom.x, 6) for atom in native_slab.atoms}
    ortho_unique_x = {round(atom.x, 6) for atom in ortho_slab.atoms}

    # Native skew keeps iy-dependent x-shift, while orthogonalized removes it.
    assert len(native_unique_x) > len(ortho_unique_x)
    assert min(atom.x for atom in ortho_slab.atoms) >= 0.0
    assert max(atom.x for atom in ortho_slab.atoms) <= ortho_slab.box[0] + 1e-6


def test_build_from_external_unit_cell_auto_replicates_for_target_size():
    builder = CrystalBuilder()
    unit_cell = {
        "a": 2.0,
        "b": 2.0,
        "c": 2.0,
        "alpha": 90.0,
        "beta": 90.0,
        "gamma": 90.0,
        "atoms": [("Si", 0.0, 0.0, 0.0)],
    }
    spec = CrystalSpec(
        material=CrystalMaterial.AGGREGATE,
        surface=SurfaceOrientation.ORIENT_001,
        cell_mode=CrystalCellMode.ORTHOGONALIZED,
        thickness_angstrom=10.0,
        xy_size_angstrom=20.0,
        nx=1,
        ny=1,
        nz=1,
        hydroxylated=False,
        hydroxyl_density=4.6,
        use_matrix_search=False,
    )

    slab = builder.build_from_unit_cell(spec, unit_cell, material=CrystalMaterial.AGGREGATE)

    # Target size should be achieved primarily by replication (not heavy lattice distortion).
    assert slab.nx >= 10
    assert slab.ny >= 10
    assert slab.nz >= 5
    assert slab.box[0] >= 19.0
    assert slab.box[1] >= 19.0
    assert slab.box[2] >= 9.5


def test_build_from_external_unit_cell_matches_user_defined_size_rectangular():
    builder = CrystalBuilder()
    unit_cell = {
        "a": 5.035,
        "b": 5.035,
        "c": 13.750,
        "alpha": 90.0,
        "beta": 90.0,
        "gamma": 120.0,
        "atoms": [("Fe", 0.0, 0.0, 0.0), ("O", 0.3, 0.0, 0.25)],
    }
    spec = CrystalSpec(
        material=CrystalMaterial.AGGREGATE,
        surface=SurfaceOrientation.ORIENT_001,
        cell_mode=CrystalCellMode.ORTHOGONALIZED,
        thickness_angstrom=17.2,
        xy_size_angstrom=40.0,
        nx=7,
        ny=7,
        nz=1,
        hydroxylated=False,
        hydroxyl_density=4.6,
        use_matrix_search=False,
    )

    slab = builder.build_from_unit_cell(spec, unit_cell, material=CrystalMaterial.AGGREGATE)
    # XY achieved by integer replication (within one cell width of target)
    assert abs(max(slab.box[0], slab.box[1]) - 40.0) < unit_cell["a"]
    # Z is exact integer multiple of c — no lattice distortion
    import math

    sin_gamma = math.sin(math.radians(unit_cell["gamma"]))
    assert math.isclose(slab.box[2] % unit_cell["c"], 0.0, abs_tol=1e-6)
    # Density preserved: box volume matches replicated cell volume exactly
    expected_vol = slab.nx * unit_cell["a"] * slab.ny * unit_cell["b"] * sin_gamma * slab.box[2]
    actual_vol = slab.box[0] * slab.box[1] * slab.box[2]
    assert math.isclose(actual_vol, expected_vol, rel_tol=1e-6)


def test_build_from_external_unit_cell_uses_matrix_search_for_hexagonal_xy():
    builder = CrystalBuilder()
    unit_cell = {
        "a": 2.0,
        "b": 2.5,
        "c": 3.5,
        "alpha": 90.0,
        "beta": 90.0,
        "gamma": 120.0,
        "atoms": [("Si", 0.25, 0.0, 0.0), ("O", 0.5, 0.5, 0.25)],
    }
    spec = CrystalSpec(
        material=CrystalMaterial.AGGREGATE,
        surface=SurfaceOrientation.ORIENT_001,
        cell_mode=CrystalCellMode.ORTHOGONALIZED,
        thickness_angstrom=7.0,
        xy_size_angstrom=14.0,
        nx=1,
        ny=1,
        nz=1,
        hydroxylated=False,
        hydroxyl_density=4.6,
        use_matrix_search=True,
    )

    slab = builder.build_from_unit_cell(spec, unit_cell, material=CrystalMaterial.AGGREGATE)

    assert slab.matrix_search_used is True
    assert slab.transformation_matrix is not None
    assert slab.n_cells_xy is not None and slab.n_cells_xy > 0
    assert slab.error_xy_pct is not None
    assert slab.n_atoms == slab.n_cells_xy * slab.nz * len(unit_cell["atoms"])
    assert all(0.0 <= atom.x < slab.box[0] + 1e-6 for atom in slab.atoms)
    assert all(0.0 <= atom.y < slab.box[1] + 1e-6 for atom in slab.atoms)


def test_build_from_external_unit_cell_matrix_fallback_preserves_diagonal_behavior():
    builder = CrystalBuilder()
    unit_cell = {
        "a": 4.0,
        "b": 5.0,
        "c": 6.0,
        "alpha": 90.0,
        "beta": 90.0,
        "gamma": 100.0,
        "atoms": [("Si", 0.0, 0.0, 0.0)],
    }
    spec = CrystalSpec(
        material=CrystalMaterial.AGGREGATE,
        surface=SurfaceOrientation.ORIENT_001,
        cell_mode=CrystalCellMode.ORTHOGONALIZED,
        thickness_angstrom=12.0,
        xy_size_angstrom=20.0,
        nx=1,
        ny=1,
        nz=1,
        hydroxylated=False,
        hydroxyl_density=4.6,
        use_matrix_search=True,
        max_cells_xy=20,
        matrix_ortho_tolerance=1e-10,
    )

    slab = builder.build_from_unit_cell(spec, unit_cell, material=CrystalMaterial.AGGREGATE)

    assert slab.matrix_search_used is False
    assert slab.matrix_search_fallback_reason is not None
    assert slab.transformation_matrix is not None
    assert slab.n_cells_xy == slab.transformation_matrix[0][0] * slab.transformation_matrix[1][1]
