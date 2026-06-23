"""Tests for MOL V3000 parsing support in MoleculeDB."""

from pathlib import Path

from builder.molecule_db import MoleculeDB


def test_parse_mol_v3000_topology(tmp_path: Path) -> None:
    """V3000 parser should extract atoms, bonds, and molecular weight."""
    mol_file = tmp_path / "ethane_v3000.mol"
    mol_file.write_text(
        """Ethane
  Program

  0  0  0  0  0  0            999 V3000
M  V30 BEGIN CTAB
M  V30 COUNTS 2 1 0 0 0
M  V30 BEGIN ATOM
M  V30 1 C 0.0 0.0 0.0 0
M  V30 2 C 1.54 0.0 0.0 0
M  V30 END ATOM
M  V30 BEGIN BOND
M  V30 1 1 1 2
M  V30 END BOND
M  V30 END CTAB
M  END
"""
    )

    db = MoleculeDB()
    topology = db.parse_mol_topology(mol_file, "ETHANE")

    assert topology is not None
    assert topology.mol_id == "ETHANE"
    assert topology.n_atoms == 2
    assert topology.n_bonds == 1
    assert topology.bonds[0].atom1 == 1
    assert topology.bonds[0].atom2 == 2
    assert topology.molecular_weight > 24.0


def test_parse_mol_v3000_invalid_returns_none(tmp_path: Path) -> None:
    """Invalid V3000 blocks should return None instead of crashing."""
    mol_file = tmp_path / "invalid_v3000.mol"
    mol_file.write_text(
        """Invalid
  Program

  0  0  0  0  0  0            999 V3000
M  V30 BEGIN CTAB
M  V30 COUNTS 0 0 0 0 0
M  V30 END CTAB
M  END
"""
    )

    db = MoleculeDB()
    topology = db.parse_mol_topology(mol_file)
    assert topology is None


def test_parse_mol_v3000_charge_flag(tmp_path: Path) -> None:
    """V3000 CHG token should mark atom charge as explicitly defined."""
    mol_file = tmp_path / "charged_v3000.mol"
    mol_file.write_text(
        """Charged
  Program

  0  0  0  0  0  0            999 V3000
M  V30 BEGIN CTAB
M  V30 COUNTS 2 1 0 0 0
M  V30 BEGIN ATOM
M  V30 1 N 0.0 0.0 0.0 0 CHG=1
M  V30 2 C 1.4 0.0 0.0 0
M  V30 END ATOM
M  V30 BEGIN BOND
M  V30 1 1 1 2
M  V30 END BOND
M  V30 END CTAB
M  END
"""
    )

    db = MoleculeDB()
    topology = db.parse_mol_topology(mol_file, "CHARGED")
    assert topology is not None
    assert topology.atoms[0].charge_defined is True
    assert topology.atoms[0].charge == 1.0
    assert topology.atoms[1].charge_defined is False
