"""Tests for topology generator."""

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, "src")

from builder.topology_generator import TopologyGenerator
from contracts.schemas import MoleculeCategory, MoleculeInfo


class TestTopologyGenerator:
    """Test topology generator."""

    @pytest.fixture
    def generator(self):
        return TopologyGenerator(ff_name="GAFF2", ff_version="1.0")

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def sample_xyz(self, temp_dir):
        """Create a sample XYZ file."""
        xyz_content = """10
Sample molecule
C 0.0 0.0 0.0
C 1.5 0.0 0.0
C 3.0 0.0 0.0
H 0.0 1.0 0.0
H 1.5 1.0 0.0
H 3.0 1.0 0.0
O 0.0 0.0 1.5
O 1.5 0.0 1.5
N 3.0 0.0 1.5
S 0.0 1.5 1.5
"""
        xyz_file = temp_dir / "test.xyz"
        xyz_file.write_text(xyz_content)
        return xyz_file

    def test_generate_data_file(self, generator, sample_xyz, temp_dir):
        """Test LAMMPS data file generation."""
        output_file = temp_dir / "data.lammps"

        mol_counts = {"asphaltene": 1}
        molecules = {
            "asphaltene": MoleculeInfo(
                mol_id="asp_01",
                molecular_weight=100.0,
                atom_count=10,
                category=MoleculeCategory.ASPHALTENE,
            ),
        }

        result_path, topo_hash = generator.generate(
            xyz_file=sample_xyz,
            output_file=output_file,
            mol_counts=mol_counts,
            molecules=molecules,
            box_size=50.0,
        )

        assert result_path.exists()
        assert len(topo_hash) == 8

        content = result_path.read_text()
        assert "10 atoms" in content
        assert "atom types" in content
        assert "xlo xhi" in content

    def test_atom_count(self, generator, sample_xyz, temp_dir):
        """Test atom count extraction."""
        output_file = temp_dir / "data.lammps"

        mol_counts = {"test": 1}
        molecules = {
            "test": MoleculeInfo(
                mol_id="test_01",
                molecular_weight=100.0,
                atom_count=10,
                category=MoleculeCategory.AROMATIC,
            ),
        }

        generator.generate(
            xyz_file=sample_xyz,
            output_file=output_file,
            mol_counts=mol_counts,
            molecules=molecules,
        )

        atom_count = generator.get_atom_count(output_file)
        assert atom_count == 10

    def test_box_volume(self, generator, sample_xyz, temp_dir):
        """Test box volume calculation."""
        output_file = temp_dir / "data.lammps"

        mol_counts = {"test": 1}
        molecules = {
            "test": MoleculeInfo(
                mol_id="test_01",
                molecular_weight=100.0,
                atom_count=10,
                category=MoleculeCategory.AROMATIC,
            ),
        }

        generator.generate(
            xyz_file=sample_xyz,
            output_file=output_file,
            mol_counts=mol_counts,
            molecules=molecules,
            box_size=100.0,
        )

        volume = generator.get_box_volume(output_file)
        assert volume == pytest.approx(100.0**3, rel=0.01)

    def test_multiple_atom_types(self, generator, sample_xyz, temp_dir):
        """Test handling of multiple atom types."""
        output_file = temp_dir / "data.lammps"

        mol_counts = {"test": 1}
        molecules = {
            "test": MoleculeInfo(
                mol_id="test_01",
                molecular_weight=100.0,
                atom_count=10,
                category=MoleculeCategory.AROMATIC,
            ),
        }

        generator.generate(
            xyz_file=sample_xyz,
            output_file=output_file,
            mol_counts=mol_counts,
            molecules=molecules,
        )

        content = output_file.read_text()
        # Should have C, H, O, N, S = 5 atom types
        assert "5 atom types" in content

    def test_topology_hash_reproducible(self, generator):
        """Test that topology hash is reproducible."""
        mol_counts = {"asphaltene": 10, "resin": 20}

        generator.generate.__wrapped__ if hasattr(generator.generate, "__wrapped__") else None

        # Just test the hash function directly from common
        from common.hashing import compute_topology_hash

        h1 = compute_topology_hash(list(mol_counts.keys()), mol_counts, "GAFF2", "1.0")
        h2 = compute_topology_hash(list(mol_counts.keys()), mol_counts, "GAFF2", "1.0")

        assert h1 == h2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
