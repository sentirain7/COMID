"""
Molecule data types for builder module.

Dataclass definitions for atoms, bonds, topology, and molecule records.
"""

from dataclasses import dataclass
from pathlib import Path

from contracts.schemas import MoleculeSpec


@dataclass
class MolAtom:
    """Atom data from MOL file."""

    index: int
    x: float
    y: float
    z: float
    element: str
    ff_type: str | None = None
    charge: float = 0.0
    # True only when charge was explicitly provided by source data
    # (e.g., LigParGen per-atom charges or MOL V3000 CHG token).
    charge_defined: bool = False


@dataclass
class MolBond:
    """Bond data from MOL file."""

    atom1: int  # 1-indexed
    atom2: int  # 1-indexed
    order: int  # 1=single, 2=double, 3=triple, 4=aromatic


@dataclass
class MolTopology:
    """Complete topology from MOL file."""

    mol_id: str
    atoms: list[MolAtom]
    bonds: list[MolBond]
    molecular_weight: float = 0.0
    # Improper instances from artifact (atom index 4-tuples, 1-based).
    # Set by apply_artifact_to_topology when the artifact includes them.
    improper_instances: list[tuple[int, int, int, int]] | None = None

    @property
    def n_atoms(self) -> int:
        return len(self.atoms)

    @property
    def n_bonds(self) -> int:
        return len(self.bonds)

    def get_angles(self) -> list[tuple[int, int, int]]:
        """Generate angles from bond connectivity."""
        # Build adjacency list
        adj: dict[int, list[int]] = {}
        for bond in self.bonds:
            adj.setdefault(bond.atom1, []).append(bond.atom2)
            adj.setdefault(bond.atom2, []).append(bond.atom1)

        angles = []
        for center, neighbors in adj.items():
            if len(neighbors) >= 2:
                for i in range(len(neighbors)):
                    for j in range(i + 1, len(neighbors)):
                        angles.append((neighbors[i], center, neighbors[j]))
        return angles

    def get_dihedrals(self) -> list[tuple[int, int, int, int]]:
        """Generate dihedrals from bond connectivity."""
        adj: dict[int, list[int]] = {}
        for bond in self.bonds:
            adj.setdefault(bond.atom1, []).append(bond.atom2)
            adj.setdefault(bond.atom2, []).append(bond.atom1)

        dihedrals = []
        for bond in self.bonds:
            a2, a3 = bond.atom1, bond.atom2
            for a1 in adj.get(a2, []):
                if a1 == a3:
                    continue
                for a4 in adj.get(a3, []):
                    if a4 == a2 or a4 == a1:
                        continue
                    dihedrals.append((a1, a2, a3, a4))
        return dihedrals


@dataclass
class MoleculeRecord:
    """Internal molecule record with file paths."""

    spec: MoleculeSpec
    xyz_path: Path | None = None
    mol2_path: Path | None = None
    pdb_path: Path | None = None
    mol_path: Path | None = None
    topology: MolTopology | None = None
