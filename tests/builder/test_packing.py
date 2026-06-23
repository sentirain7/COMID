"""Tests for packing validator."""

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, "src")

from builder.packing_validator import PackingValidator


class TestPackingValidator:
    """Test packing validator."""

    @pytest.fixture
    def validator(self):
        return PackingValidator(min_distance=1.5, max_pe_per_atom=100.0)

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def good_data_file(self, temp_dir):
        """Create a data file with good packing."""
        content = """LAMMPS data file

10 atoms
0 bonds
0 angles
0 dihedrals
0 impropers

1 atom types
0 bond types
0 angle types
0 dihedral types
0 improper types

0.0 100.0 xlo xhi
0.0 100.0 ylo yhi
0.0 100.0 zlo zhi

Masses

1 12.0

Atoms  # full

1 1 1 0.0 10.0 10.0 10.0
2 1 1 0.0 20.0 10.0 10.0
3 1 1 0.0 30.0 10.0 10.0
4 1 1 0.0 40.0 10.0 10.0
5 1 1 0.0 50.0 10.0 10.0
6 1 1 0.0 60.0 10.0 10.0
7 1 1 0.0 70.0 10.0 10.0
8 1 1 0.0 80.0 10.0 10.0
9 1 1 0.0 90.0 10.0 10.0
10 1 1 0.0 95.0 10.0 10.0
"""
        data_file = temp_dir / "good.lammps"
        data_file.write_text(content)
        return data_file

    @pytest.fixture
    def bad_data_file(self, temp_dir):
        """Create a data file with overlapping atoms from DIFFERENT molecules.

        mol_id column (col 2) differs per atom → these 0.1 Å separations are
        *inter*-molecular overlaps (a real packing defect), not intra-molecular
        bonds. The validator must flag this.
        """
        content = """LAMMPS data file

5 atoms
0 bonds
0 angles
0 dihedrals
0 impropers

1 atom types
0 bond types
0 angle types
0 dihedral types
0 improper types

0.0 100.0 xlo xhi
0.0 100.0 ylo yhi
0.0 100.0 zlo zhi

Masses

1 12.0

Atoms  # full

1 1 1 0.0 10.0 10.0 10.0
2 2 1 0.0 10.1 10.0 10.0
3 3 1 0.0 10.2 10.0 10.0
4 4 1 0.0 10.3 10.0 10.0
5 5 1 0.0 10.4 10.0 10.0
"""
        data_file = temp_dir / "bad.lammps"
        data_file.write_text(content)
        return data_file

    @pytest.fixture
    def intra_bond_data_file(self, temp_dir):
        """A single molecule whose bonded atoms sit at C–H/C–C distances.

        All atoms share mol_id=1; the 1.1–1.5 Å separations are physical bonds.
        The historical bug counted these as overlaps → every structure invalid.
        The fixed validator must report this VALID (intra-molecular excluded).
        """
        content = """LAMMPS data file

4 atoms
0 bonds
0 angles
0 dihedrals
0 impropers

2 atom types
0 bond types
0 angle types
0 dihedral types
0 improper types

0.0 100.0 xlo xhi
0.0 100.0 ylo yhi
0.0 100.0 zlo zhi

Masses

1 12.0
2 1.0

Atoms  # full

1 1 1 0.0 10.0 10.0 10.0
2 1 1 0.0 11.5 10.0 10.0
3 1 2 0.0 10.0 11.1 10.0
4 1 2 0.0 11.5 11.1 10.0
"""
        data_file = temp_dir / "intra.lammps"
        data_file.write_text(content)
        return data_file

    def test_good_packing_valid(self, validator, good_data_file):
        """Test that good packing passes validation."""
        result = validator.validate(good_data_file)

        assert result.valid is True
        assert result.min_distance > 1.5
        assert result.min_distance_violations == 0
        assert result.stability_flag is None

    def test_bad_packing_invalid(self, validator, bad_data_file):
        """Inter-molecular overlap (different mol_ids, 0.1 Å) → invalid."""
        result = validator.validate(bad_data_file)

        assert result.valid is False
        assert result.min_distance < 1.5
        assert result.min_distance_violations > 0
        assert result.stability_flag is not None

    def test_intra_molecular_bonds_not_flagged(self, validator, intra_bond_data_file):
        """Bonded atoms in one molecule (1.1–1.5 Å) must NOT count as overlaps.

        Regression for the historical bug: ``_read_atoms`` dropped mol_id so
        every C–H/C–C bond was counted as a distance violation, making every
        structure report invalid (and the gate get demoted to a warning).
        """
        result = validator.validate(intra_bond_data_file)

        assert result.valid is True
        assert result.min_distance_violations == 0

    def test_quick_check(self, validator, good_data_file, bad_data_file):
        """Test quick check method."""
        assert validator.quick_check(good_data_file) is True
        # Bad file might or might not fail quick check depending on severity

    def test_empty_file(self, validator, temp_dir):
        """Test handling of empty file."""
        empty_file = temp_dir / "empty.lammps"
        empty_file.write_text("")

        result = validator.validate(empty_file)
        assert result.valid is False

    def test_validation_result_fields(self, validator, good_data_file):
        """Test that validation result has all required fields."""
        result = validator.validate(good_data_file)

        assert hasattr(result, "valid")
        assert hasattr(result, "min_distance")
        assert hasattr(result, "min_distance_violations")
        assert hasattr(result, "overlap_pairs")
        assert hasattr(result, "estimated_pe_per_atom")
        assert hasattr(result, "stability_flag")
        assert hasattr(result, "message")


class TestPackingValidatorEdgeCases:
    """Test edge cases for packing validator."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_single_atom(self, temp_dir):
        """Test validation with single atom."""
        validator = PackingValidator()

        content = """LAMMPS data file

1 atoms
0 bonds

1 atom types
0 bond types

0.0 100.0 xlo xhi
0.0 100.0 ylo yhi
0.0 100.0 zlo zhi

Masses

1 12.0

Atoms  # full

1 1 1 0.0 50.0 50.0 50.0
"""
        data_file = temp_dir / "single.lammps"
        data_file.write_text(content)

        result = validator.validate(data_file)
        # Single atom should always be valid
        assert result.min_distance_violations == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
