"""Smoke tests for builder.topology_helpers."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


def _has_rdkit() -> bool:
    try:
        import rdkit  # noqa: F401

        return True
    except ImportError:
        return False


def test_parse_xyz_coordinates_basic() -> None:
    """parse_xyz_coordinates reads a simple XYZ file."""
    from builder.topology_helpers import parse_xyz_coordinates

    with tempfile.NamedTemporaryFile(mode="w", suffix=".xyz", delete=False) as f:
        f.write("3\ntest\nO  0.0 0.0 0.0\nH  1.0 0.0 0.0\nH  0.0 1.0 0.0\n")
        f.flush()
        coords = parse_xyz_coordinates(Path(f.name))

    assert len(coords) == 3
    assert coords[0] == pytest.approx((0.0, 0.0, 0.0))
    assert coords[1] == pytest.approx((1.0, 0.0, 0.0))
    assert coords[2] == pytest.approx((0.0, 1.0, 0.0))


@pytest.mark.skip(reason="Phase 6: H2O curated artifact not yet generated")
def test_h2o_full_topology_smoke() -> None:
    """H2O single-component .data file has bonds, angles, and coefficients."""
    from builder.mol_parser import parse_mol_topology
    from builder.packmol_wrapper import PackmolMolecule, PackmolWrapper
    from builder.topology_helpers import (
        convert_mol_to_xyz,
        generate_single_component_topology,
    )

    mol_path = Path("data/molecules/single_moles/H2O.mol")
    if not mol_path.exists():
        pytest.skip("H2O.mol not found")

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)

        # Parse and convert MOL to XYZ
        topo = parse_mol_topology(mol_path, "H2O")
        assert topo is not None
        mol_xyz = convert_mol_to_xyz(topo, "H2O", work / "H2O.xyz")

        # Pack 4 molecules in a 10x10x10 box
        packed_xyz = work / "packed.xyz"
        packmol = PackmolWrapper(seed=42)
        result = packmol.pack(
            molecules=[PackmolMolecule(structure_file=mol_xyz, count=4, mol_id="H2O")],
            output_file=packed_xyz,
            total_mass_g_mol=18.015 * 4,
            box_dimensions=(10.0, 10.0, 10.0),
            work_dir=work,
        )

        if not result.success:
            pytest.skip(f"Packmol not available or failed: {result.error_message}")

        # Generate full topology
        data_path = work / "cell.data"
        generate_single_component_topology(
            mol_path=mol_path,
            mol_id="H2O",
            molecule_count=4,
            packed_xyz_path=packed_xyz,
            output_data_path=data_path,
            box_dimensions=(10.0, 10.0, 10.0),
            ff_assignment={
                "route": "organic_curated_artifact",
                "status": "active",
                "source_id": "H2O",
                "formal_charge": 0,
                "canonical_smiles": "O",
            },
        )

        # Verify .data has bonded sections
        content = data_path.read_text()
        assert "Bonds" in content, ".data missing Bonds section"
        assert "Angles" in content, ".data missing Angles section"
        assert "Bond Coeffs" in content, ".data missing Bond Coeffs"
        assert "Pair Coeffs" in content, ".data missing Pair Coeffs"

        # Verify atom count: 4 molecules x 3 atoms = 12
        assert "12 atoms" in content
        # Verify bond count: 4 molecules x 2 bonds = 8
        assert "8 bonds" in content
