"""
Unit tests for parsers.data_parser module.

Tests LAMMPS data file parsing, atom/bond extraction,
XYZ conversion, and element estimation from masses.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from parsers.data_parser import DataFileAtom, DataFileBond, DataFileInfo, DataParser

# ── Fixtures ──────────────────────────────────────────────────────

MINIMAL_DATA_FILE = """\
LAMMPS data file via Packmol

100 atoms
3 atom types
50 bonds
2 bond types

0.0 50.0 xlo xhi
0.0 50.0 ylo yhi
0.0 50.0 zlo zhi

Masses

1 12.011
2 1.008
3 15.999

Atoms # full

1 1 1 -0.10  1.0  2.0  3.0
2 1 2  0.05  4.0  5.0  6.0
3 1 3 -0.20  7.0  8.0  9.0

Bonds

1 1 1 2
2 2 2 3
"""


@pytest.fixture
def data_file(tmp_path):
    """Write minimal LAMMPS data file and return its path."""
    p = tmp_path / "data.lammps"
    p.write_text(MINIMAL_DATA_FILE)
    return p


@pytest.fixture
def parser():
    return DataParser()


# ── DataParser.parse ──────────────────────────────────────────────


class TestDataParserParse:
    """Tests for DataParser.parse()."""

    def test_parse_atoms(self, parser, data_file):
        info = parser.parse(data_file)
        assert info.n_atoms == 3
        assert info.atoms[0].atom_id == 1
        assert info.atoms[0].x == 1.0
        assert info.atoms[0].y == 2.0
        assert info.atoms[0].z == 3.0
        assert info.atoms[0].mol_id == 1
        assert info.atoms[0].atom_type == 1
        assert info.atoms[0].charge == pytest.approx(-0.10)

    def test_parse_bonds(self, parser, data_file):
        info = parser.parse(data_file)
        assert info.n_bonds == 2
        assert info.bonds[0].bond_id == 1
        assert info.bonds[0].bond_type == 1
        assert info.bonds[0].atom1_id == 1
        assert info.bonds[0].atom2_id == 2

    def test_parse_box_bounds(self, parser, data_file):
        info = parser.parse(data_file)
        xlo, xhi, ylo, yhi, zlo, zhi = info.box_bounds
        assert xlo == 0.0
        assert xhi == 50.0
        assert ylo == 0.0
        assert yhi == 50.0
        assert zlo == 0.0
        assert zhi == 50.0

    def test_parse_masses(self, parser, data_file):
        info = parser.parse(data_file)
        assert info.masses[1] == pytest.approx(12.011)
        assert info.masses[2] == pytest.approx(1.008)
        assert info.masses[3] == pytest.approx(15.999)
        assert info.n_atom_types == 3

    def test_parse_nonexistent_file_raises(self, parser, tmp_path):
        from contracts.errors import ParserError

        with pytest.raises(ParserError, match="not found"):
            parser.parse(tmp_path / "missing.lammps")

    def test_parse_empty_atoms_raises(self, parser, tmp_path):
        from contracts.errors import ParserError

        empty_file = tmp_path / "empty.lammps"
        empty_file.write_text("LAMMPS data\n\n0 atoms\n")
        with pytest.raises(ParserError, match="No atoms"):
            parser.parse(empty_file)


# ── Sections and edge cases ───────────────────────────────────────


class TestDataParserEdgeCases:
    """Edge cases for data file parsing."""

    def test_velocities_section_ignored(self, parser, tmp_path):
        """Velocities section should terminate Atoms parsing."""
        content = """\
LAMMPS data

2 atoms
1 atom types

0.0 10.0 xlo xhi
0.0 10.0 ylo yhi
0.0 10.0 zlo zhi

Atoms # full

1 1 1 0.0  1.0 2.0 3.0
2 1 1 0.0  4.0 5.0 6.0

Velocities

1 0.001 0.002 0.003
2 0.004 0.005 0.006
"""
        f = tmp_path / "data.lammps"
        f.write_text(content)
        info = parser.parse(f)
        assert info.n_atoms == 2

    def test_dihedrals_section_ignored(self, parser, tmp_path):
        """Non-atom/bond sections should be cleanly ignored."""
        content = """\
LAMMPS data

1 atoms
1 atom types

0.0 10.0 xlo xhi
0.0 10.0 ylo yhi
0.0 10.0 zlo zhi

Atoms # full

1 1 1 0.0  5.0 5.0 5.0

Dihedrals

1 1 1 2 3 4
"""
        f = tmp_path / "data.lammps"
        f.write_text(content)
        info = parser.parse(f)
        assert info.n_atoms == 1

    def test_comment_lines_skipped(self, parser, tmp_path):
        content = """\
# LAMMPS data file comment
LAMMPS data

1 atoms
1 atom types

0.0 10.0 xlo xhi
0.0 10.0 ylo yhi
0.0 10.0 zlo zhi

Masses

# Mass section comment
1 12.011

Atoms # full

# Atom line comment
1 1 1 0.0  1.0 2.0 3.0
"""
        f = tmp_path / "data.lammps"
        f.write_text(content)
        info = parser.parse(f)
        assert info.n_atoms == 1
        assert info.masses[1] == pytest.approx(12.011)

    def test_malformed_atom_line_skipped(self, parser, tmp_path):
        """Lines with too few fields should be silently skipped."""
        content = """\
LAMMPS data

1 atoms
1 atom types

0.0 10.0 xlo xhi
0.0 10.0 ylo yhi
0.0 10.0 zlo zhi

Atoms # full

bad_line with not_enough fields
1 1 1 0.0  1.0 2.0 3.0
"""
        f = tmp_path / "data.lammps"
        f.write_text(content)
        info = parser.parse(f)
        assert info.n_atoms == 1

    def test_asymmetric_box(self, parser, tmp_path):
        content = """\
LAMMPS data

1 atoms
1 atom types

-5.0 15.0 xlo xhi
-10.0 20.0 ylo yhi
0.0 100.0 zlo zhi

Atoms # full

1 1 1 0.0  0.0 0.0 0.0
"""
        f = tmp_path / "data.lammps"
        f.write_text(content)
        info = parser.parse(f)
        assert info.box_bounds == (-5.0, 15.0, -10.0, 20.0, 0.0, 100.0)


# ── data_to_xyz ───────────────────────────────────────────────────


class TestDataToXYZ:
    """Tests for DataParser.data_to_xyz()."""

    def test_basic_conversion(self, parser, data_file):
        type_map = {"1": "C", "2": "H", "3": "O"}
        xyz_str, box_size = parser.data_to_xyz(data_file, type_map)

        lines = xyz_str.strip().split("\n")
        assert lines[0] == "3"  # atom count
        assert "C" in lines[2]
        assert "H" in lines[3]
        assert "O" in lines[4]

        assert box_size == (50.0, 50.0, 50.0)

    def test_unknown_type_maps_to_x(self, parser, data_file):
        type_map = {"1": "C"}  # types 2,3 not in map
        xyz_str, _ = parser.data_to_xyz(data_file, type_map)

        lines = xyz_str.strip().split("\n")
        assert lines[3].startswith("X")  # type 2 → X
        assert lines[4].startswith("X")  # type 3 → X


# ── estimate_elements_from_masses ─────────────────────────────────


class TestEstimateElements:
    """Tests for DataParser.estimate_elements_from_masses()."""

    def test_standard_elements(self, parser, data_file):
        type_map = parser.estimate_elements_from_masses(data_file)
        assert type_map["1"] == "C"
        assert type_map["2"] == "H"
        assert type_map["3"] == "O"

    def test_unknown_mass_maps_to_x(self, parser, tmp_path):
        content = """\
LAMMPS data

1 atoms
1 atom types

0.0 10.0 xlo xhi
0.0 10.0 ylo yhi
0.0 10.0 zlo zhi

Masses

1 999.999

Atoms # full

1 1 1 0.0  1.0 2.0 3.0
"""
        f = tmp_path / "data.lammps"
        f.write_text(content)
        type_map = parser.estimate_elements_from_masses(f)
        assert type_map["1"] == "X"


# ── Dataclass unit tests ─────────────────────────────────────────


class TestDataClasses:
    def test_data_file_atom(self):
        atom = DataFileAtom(1, 1, 2, -0.5, 1.0, 2.0, 3.0)
        assert atom.atom_id == 1
        assert atom.charge == -0.5

    def test_data_file_bond(self):
        bond = DataFileBond(1, 2, 10, 20)
        assert bond.bond_id == 1
        assert bond.atom1_id == 10

    def test_data_file_info(self):
        info = DataFileInfo(
            atoms=[],
            bonds=[],
            box_bounds=(0, 10, 0, 10, 0, 10),
            n_atoms=0,
            n_bonds=0,
            n_atom_types=1,
            masses={1: 12.0},
        )
        assert info.n_atom_types == 1
