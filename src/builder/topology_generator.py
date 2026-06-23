"""
Topology generator for LAMMPS data files.

Generates LAMMPS data files from molecular structures with
proper atom types, bonds, angles, and dihedrals.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from common.constants import ATOMIC_WEIGHTS
from common.hashing import compute_topology_hash
from common.logging import get_logger
from contracts.schemas import MoleculeInfo

logger = get_logger("builder.topology")


@dataclass
class AtomData:
    """Atom data for LAMMPS."""

    atom_id: int
    mol_id: int
    atom_type: int
    charge: float
    x: float
    y: float
    z: float
    element: str = "C"


@dataclass
class BondData:
    """Bond data for LAMMPS."""

    bond_id: int
    bond_type: int
    atom1: int
    atom2: int


@dataclass
class TopologyData:
    """Complete topology data for LAMMPS."""

    atoms: list[AtomData] = field(default_factory=list)
    bonds: list[BondData] = field(default_factory=list)
    box_bounds: tuple[float, float, float, float, float, float] = (0, 100, 0, 100, 0, 100)
    atom_types: dict[str, int] = field(default_factory=dict)
    bond_types: dict[str, int] = field(default_factory=dict)
    masses: dict[int, float] = field(default_factory=dict)


class TopologyGenerator:
    """
    Generator for LAMMPS data files.

    Converts XYZ/PDB structures to LAMMPS data format with
    proper topology information.
    """

    def __init__(self, ff_name: str = "GAFF2", ff_version: str = "1.0"):
        """
        Initialize topology generator.

        Args:
            ff_name: Force field name
            ff_version: Force field version
        """
        self.ff_name = ff_name
        self.ff_version = ff_version

    def generate(
        self,
        xyz_file: Path,
        output_file: Path,
        mol_counts: dict[str, int],
        molecules: dict[str, MoleculeInfo],
        box_size: float | None = None,
    ) -> tuple[Path, str]:
        """
        Generate LAMMPS data file from XYZ structure.

        Args:
            xyz_file: Input XYZ file from Packmol
            output_file: Output LAMMPS data file
            mol_counts: Molecule counts by category
            molecules: Molecule info dictionary
            box_size: Box size (auto-detected if None)

        Returns:
            Tuple of (output path, topology hash)
        """
        # Read XYZ file
        topology = self._read_xyz(xyz_file)

        # Set box bounds
        if box_size is not None:
            topology.box_bounds = (0, box_size, 0, box_size, 0, box_size)
        else:
            # Auto-detect from atom positions
            topology.box_bounds = self._calculate_box_bounds(topology.atoms)

        # Generate LAMMPS data file
        self._write_lammps_data(topology, output_file)

        # Calculate topology hash
        mol_ids = list(mol_counts.keys())
        topo_hash = compute_topology_hash(mol_ids, mol_counts, self.ff_name, self.ff_version)

        return output_file, topo_hash

    def _read_xyz(self, xyz_file: Path) -> TopologyData:
        """
        Read XYZ file and create topology data.

        Args:
            xyz_file: Path to XYZ file

        Returns:
            TopologyData with atoms
        """
        topology = TopologyData()
        atom_type_map = {}
        current_type = 0

        lines = xyz_file.read_text().strip().split("\n")
        if len(lines) < 3:
            raise ValueError(f"Invalid XYZ file: {xyz_file}")

        try:
            n_atoms = int(lines[0].strip())
        except ValueError as e:
            raise ValueError(f"Invalid atom count in XYZ file: {lines[0]}") from e

        # Skip header line
        atom_lines = lines[2 : 2 + n_atoms]

        for i, line in enumerate(atom_lines):
            parts = line.split()
            if len(parts) < 4:
                continue

            element = parts[0].strip()
            x = float(parts[1])
            y = float(parts[2])
            z = float(parts[3])

            # Assign atom type
            if element not in atom_type_map:
                current_type += 1
                atom_type_map[element] = current_type
                topology.masses[current_type] = ATOMIC_WEIGHTS.get(element, 12.0)

            topology.atoms.append(
                AtomData(
                    atom_id=i + 1,
                    mol_id=1,  # Simplified: all in one molecule
                    atom_type=atom_type_map[element],
                    charge=0.0,  # Neutral for now
                    x=x,
                    y=y,
                    z=z,
                    element=element,
                )
            )

        topology.atom_types = atom_type_map
        return topology

    def _calculate_box_bounds(
        self,
        atoms: list[AtomData],
        margin: float = 5.0,
    ) -> tuple[float, float, float, float, float, float]:
        """Calculate box bounds from atom positions."""
        if not atoms:
            return (0, 100, 0, 100, 0, 100)

        x_coords = [a.x for a in atoms]
        y_coords = [a.y for a in atoms]
        z_coords = [a.z for a in atoms]

        return (
            min(x_coords) - margin,
            max(x_coords) + margin,
            min(y_coords) - margin,
            max(y_coords) + margin,
            min(z_coords) - margin,
            max(z_coords) + margin,
        )

    def _write_lammps_data(self, topology: TopologyData, output_file: Path) -> None:
        """
        Write LAMMPS data file.

        Args:
            topology: Topology data
            output_file: Output file path
        """
        output_file.parent.mkdir(parents=True, exist_ok=True)

        xlo, xhi, ylo, yhi, zlo, zhi = topology.box_bounds
        n_atoms = len(topology.atoms)
        n_bonds = len(topology.bonds)
        n_atom_types = len(topology.atom_types)
        n_bond_types = max(1, len(topology.bond_types))

        lines = [
            f"LAMMPS data file - Generated by TopologyGenerator ({self.ff_name} {self.ff_version})",
            "",
            f"{n_atoms} atoms",
            f"{n_bonds} bonds",
            "0 angles",
            "0 dihedrals",
            "0 impropers",
            "",
            f"{n_atom_types} atom types",
            f"{n_bond_types} bond types",
            "0 angle types",
            "0 dihedral types",
            "0 improper types",
            "",
            f"{xlo:.6f} {xhi:.6f} xlo xhi",
            f"{ylo:.6f} {yhi:.6f} ylo yhi",
            f"{zlo:.6f} {zhi:.6f} zlo zhi",
            "",
            "Masses",
            "",
        ]

        # Write masses
        for atom_type, mass in sorted(topology.masses.items()):
            lines.append(f"{atom_type} {mass:.4f}")

        lines.extend(["", "Atoms  # full", ""])

        # Write atoms
        for atom in topology.atoms:
            lines.append(
                f"{atom.atom_id} {atom.mol_id} {atom.atom_type} "
                f"{atom.charge:.6f} {atom.x:.6f} {atom.y:.6f} {atom.z:.6f}"
            )

        if topology.bonds:
            lines.extend(["", "Bonds", ""])
            for bond in topology.bonds:
                lines.append(f"{bond.bond_id} {bond.bond_type} {bond.atom1} {bond.atom2}")

        output_file.write_text("\n".join(lines))
        logger.info(f"Generated LAMMPS data file: {output_file} ({n_atoms} atoms)")

    def get_atom_count(self, data_file: Path) -> int:
        """Get atom count from LAMMPS data file."""
        content = data_file.read_text()
        match = re.search(r"(\d+)\s+atoms", content)
        if match:
            return int(match.group(1))
        return 0

    def get_box_volume(self, data_file: Path) -> float:
        """Get box volume from LAMMPS data file (Angstrom^3)."""
        content = data_file.read_text()

        xlo, xhi, ylo, yhi, zlo, zhi = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0

        for line in content.split("\n"):
            if "xlo xhi" in line:
                parts = line.split()
                xlo, xhi = float(parts[0]), float(parts[1])
            elif "ylo yhi" in line:
                parts = line.split()
                ylo, yhi = float(parts[0]), float(parts[1])
            elif "zlo zhi" in line:
                parts = line.split()
                zlo, zhi = float(parts[0]), float(parts[1])

        return (xhi - xlo) * (yhi - ylo) * (zhi - zlo)
