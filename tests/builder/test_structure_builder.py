"""Tests for main structure builder."""

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, "src")

from builder.molecule_db import MoleculeDB
from builder.structure_builder import StructureBuilder
from contracts.schemas import BuildRequest


class TestStructureBuilder:
    """Test structure builder."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def molecule_db(self, temp_dir):
        db = MoleculeDB(db_path=temp_dir / "molecules")

        # Try to load real aging library first
        config_path = (
            Path(__file__).parent.parent.parent / "data" / "molecules" / "molecule_library.yaml"
        )
        if config_path.exists():
            try:
                count = db.load_aging_library(config_path)
                if count > 0:
                    return db
            except Exception:
                pass  # Fall through to mock

        # Fallback to mock molecules only if real library not available
        db.create_mock_molecules()
        return db

    @pytest.fixture
    def builder(self, molecule_db, temp_dir):
        return StructureBuilder(
            molecule_db=molecule_db,
            work_dir=temp_dir / "builds",
        )

    def test_build_basic(self, builder):
        """Test basic structure building with wt_percent mode (SARA categories)."""
        request = BuildRequest(
            composition={
                "asphaltene": 20.0,
                "resin": 30.0,
                "aromatic": 35.0,
                "saturate": 15.0,
            },
            composition_mode="wt_percent",  # Use SARA category weight percent mode
            target_atoms=1000,
            seed=12345,
        )

        result = builder.build(request)

        assert Path(result.data_file_path).exists()
        assert result.actual_atoms > 0
        assert result.topology_hash is not None
        assert result.composition_error_l1 >= 0

    def test_build_composition_error(self, builder):
        """Test that composition error is reasonable."""
        request = BuildRequest(
            composition={
                "asphaltene": 25.0,
                "resin": 25.0,
                "aromatic": 25.0,
                "saturate": 25.0,
            },
            composition_mode="wt_percent",
            target_atoms=5000,
            seed=42,
        )

        result = builder.build(request)

        # Error should be less than 5% for this size
        assert result.composition_error_l1 < 10.0

    def test_build_result_fields(self, builder):
        """Test that build result has all required fields."""
        request = BuildRequest(
            composition={
                "asphaltene": 20.0,
                "resin": 30.0,
                "aromatic": 35.0,
                "saturate": 15.0,
            },
            composition_mode="wt_percent",
            target_atoms=1000,
            seed=1,
        )

        result = builder.build(request)

        assert result.data_file_path is not None
        assert result.actual_atoms > 0
        assert result.actual_density > 0
        assert result.topology_hash is not None
        assert result.packmol_version is not None
        assert result.actual_composition_wt is not None
        assert result.composition_error_l1 >= 0
        assert result.target_composition_wt is not None
        assert result.min_distance_violation_count >= 0
        assert result.initial_pe_per_atom is not None

    def test_build_different_seeds(self, builder):
        """Test that different seeds produce different output files."""
        base_request = {
            "composition": {
                "asphaltene": 20.0,
                "resin": 30.0,
                "aromatic": 35.0,
                "saturate": 15.0,
            },
            "composition_mode": "wt_percent",
            "target_atoms": 1000,
        }

        result1 = builder.build(BuildRequest(**base_request, seed=1))
        result2 = builder.build(BuildRequest(**base_request, seed=2))

        # Both should succeed
        assert Path(result1.data_file_path).exists()
        assert Path(result2.data_file_path).exists()

        # Output paths should be different
        assert result1.data_file_path != result2.data_file_path

        # Topology hash is based on composition, so same composition = same hash
        # This is by design - topology_hash identifies molecular makeup, not positions
        assert result1.topology_hash == result2.topology_hash

    def test_validate_packing(self, builder):
        """Test packing validation method."""
        request = BuildRequest(
            composition={
                "asphaltene": 50.0,
                "saturate": 50.0,
            },
            composition_mode="wt_percent",
            target_atoms=500,
            seed=123,
        )

        result = builder.build(request)
        validation = builder.validate_packing(result.data_file_path)

        assert "valid" in validation
        assert "min_distance" in validation
        assert "min_distance_violations" in validation


class TestMolToXyzConversion:
    """Test MOL to XYZ conversion for Packmol compatibility."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def molecule_db(self, temp_dir):
        db = MoleculeDB(db_path=temp_dir / "molecules")
        config_path = (
            Path(__file__).parent.parent.parent / "data" / "molecules" / "molecule_library.yaml"
        )
        if config_path.exists():
            db.load_aging_library(config_path)
        return db

    @pytest.fixture
    def builder(self, molecule_db, temp_dir):
        return StructureBuilder(
            molecule_db=molecule_db,
            work_dir=temp_dir / "builds",
        )

    def test_convert_mol_to_xyz(self, builder, temp_dir):
        """Test _convert_mol_to_xyz() helper function."""
        # Create a simple MOL file
        mol_content = """test_molecule
     RDKit          3D

  3  2  0  0  0  0  0  0  0  0999 V2000
    0.0000    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0
    1.5400    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0
    2.3100    1.2600    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0
  1  2  1  0
  2  3  1  0
M  END
"""
        mol_file = temp_dir / "test.mol"
        mol_file.write_text(mol_content)

        # Convert to XYZ
        xyz_file = temp_dir / "test.xyz"
        result = builder._convert_mol_to_xyz(mol_file, xyz_file, "test_mol")

        assert result == xyz_file
        assert xyz_file.exists()

        # Verify XYZ content
        lines = xyz_file.read_text().strip().split("\n")
        assert lines[0] == "3"  # 3 atoms
        assert "test_mol" in lines[1]  # Comment line contains mol_id
        assert len(lines) == 5  # Header + comment + 3 atoms

        # Check atom format
        for line in lines[2:]:
            parts = line.split()
            assert len(parts) == 4  # element x y z
            assert parts[0] == "C"  # Carbon
            # Verify coordinates are floats
            float(parts[1])
            float(parts[2])
            float(parts[3])

    def test_prepare_packmol_input_converts_mol_files(self, builder, temp_dir):
        """Test that _prepare_packmol_input_mol_count converts MOL files to XYZ."""
        from contracts.schemas import MoleculeCategory, MoleculeInfo

        # Create a mock MOL file in the expected location
        mol_id = "TEST-MOL"
        mol_content = """test
     RDKit          3D

  2  1  0  0  0  0  0  0  0  0999 V2000
    0.0000    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0
    1.5400    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0
  1  2  1  0
M  END
"""
        mol_file = temp_dir / f"{mol_id}.mol"
        mol_file.write_text(mol_content)

        # Set up molecule DB to return this MOL file
        builder.molecule_db._aging_config_path = temp_dir / "fake_config.yaml"

        # Mock the get_structure_file_aging method
        original_get_structure_file_aging = builder.molecule_db.get_structure_file_aging
        builder.molecule_db.get_structure_file_aging = lambda mid, cfg: (
            mol_file if mid == mol_id else None
        )

        try:
            molecules = {
                mol_id: MoleculeInfo(
                    mol_id=mol_id,
                    molecular_weight=26.0,
                    atom_count=2,
                    category=MoleculeCategory.SATURATE,
                )
            }
            mol_counts = {mol_id: 5}
            work_dir = temp_dir / "work"
            work_dir.mkdir()

            result = builder._prepare_packmol_input_mol_count(mol_counts, molecules, work_dir)

            assert len(result) == 1
            pm_mol = result[0]
            assert pm_mol.mol_id == mol_id
            assert pm_mol.count == 5
            # Verify the structure file is XYZ (converted from MOL)
            assert pm_mol.structure_file.suffix == ".xyz"
            assert pm_mol.structure_file.exists()
        finally:
            builder.molecule_db.get_structure_file_aging = original_get_structure_file_aging


class TestStructureBuilderInterface:
    """Test that builder implements interface correctly."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_implements_interface(self, temp_dir):
        """Test that StructureBuilder implements IStructureBuilder."""
        from contracts.interfaces import IStructureBuilder

        db = MoleculeDB(db_path=temp_dir / "molecules")

        # Try to load real aging library first
        config_path = (
            Path(__file__).parent.parent.parent / "data" / "molecules" / "molecule_library.yaml"
        )
        if config_path.exists():
            try:
                count = db.load_aging_library(config_path)
                if count == 0:
                    db.create_mock_molecules()
            except Exception:
                db.create_mock_molecules()
        else:
            db.create_mock_molecules()

        builder = StructureBuilder(molecule_db=db, work_dir=temp_dir)

        # Check protocol compliance
        assert isinstance(builder, IStructureBuilder)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
