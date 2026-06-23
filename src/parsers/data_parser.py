"""
LAMMPS data file parser for structure visualization.

Parses LAMMPS data files (data.lammps) to extract atom coordinates
and box information for 3D visualization.
"""

from dataclasses import dataclass
from pathlib import Path

from common.constants import ATOMIC_WEIGHTS
from common.logging import get_logger
from contracts.errors import ErrorCode, ParserError

logger = get_logger("parsers.data_parser")


@dataclass
class DataFileAtom:
    """Atom data from LAMMPS data file."""

    atom_id: int
    mol_id: int
    atom_type: int
    charge: float
    x: float
    y: float
    z: float


@dataclass
class DataFileBond:
    """Bond data from LAMMPS data file."""

    bond_id: int
    bond_type: int
    atom1_id: int
    atom2_id: int


@dataclass
class DataFileAngle:
    """Angle data from LAMMPS data file."""

    angle_id: int
    angle_type: int
    atom1_id: int
    atom2_id: int
    atom3_id: int


@dataclass
class DataFileDihedral:
    """Dihedral data from LAMMPS data file."""

    dihedral_id: int
    dihedral_type: int
    atom1_id: int
    atom2_id: int
    atom3_id: int
    atom4_id: int


@dataclass
class DataFileImproper:
    """Improper data from LAMMPS data file."""

    improper_id: int
    improper_type: int
    atom1_id: int
    atom2_id: int
    atom3_id: int
    atom4_id: int


@dataclass
class DataFileInfo:
    """Parsed LAMMPS data file information."""

    atoms: list[DataFileAtom]
    bonds: list[DataFileBond]
    box_bounds: tuple[float, float, float, float, float, float]  # xlo, xhi, ylo, yhi, zlo, zhi
    n_atoms: int
    n_bonds: int
    n_atom_types: int
    masses: dict[int, float]  # type_id -> mass
    # Optional topology fields (backward-compatible defaults)
    angles: list[DataFileAngle] | None = None
    dihedrals: list[DataFileDihedral] | None = None
    impropers: list[DataFileImproper] | None = None
    n_bond_types: int = 0
    n_angle_types: int = 0
    n_dihedral_types: int = 0
    n_improper_types: int = 0
    raw_coeff_sections: dict[str, str] | None = None  # e.g. "Pair Coeffs" -> raw text


class DataParser:
    """
    Parser for LAMMPS data files.

    Extracts atom positions and box information for 3D visualization.
    """

    def __init__(self):
        """Initialize data parser."""
        pass

    def parse(self, data_file: Path) -> DataFileInfo:
        """
        Parse LAMMPS data file.

        Args:
            data_file: Path to LAMMPS data file

        Returns:
            DataFileInfo with atoms and box information

        Raises:
            ParserError: If parsing fails
        """
        data_file = Path(data_file)

        if not data_file.exists():
            raise ParserError(
                code=ErrorCode.PARSER_ERROR,
                message=f"Data file not found: {data_file}",
                file_path=str(data_file),
            )

        try:
            content = data_file.read_text()
        except Exception as e:
            raise ParserError(
                code=ErrorCode.PARSER_ERROR,
                message=f"Failed to read data file: {e}",
                file_path=str(data_file),
            ) from e

        return self._parse_content(content, str(data_file))

    # Known coeff section headers that should be captured verbatim.
    _COEFF_SECTIONS = frozenset(
        {
            "Pair Coeffs",
            "Bond Coeffs",
            "Angle Coeffs",
            "Dihedral Coeffs",
            "Improper Coeffs",
        }
    )

    # Known data section headers (non-coeff).
    _DATA_SECTIONS = frozenset(
        {
            "Masses",
            "Atoms",
            "Bonds",
            "Angles",
            "Dihedrals",
            "Impropers",
            "Velocities",
        }
    )

    def _parse_content(self, content: str, file_path: str) -> DataFileInfo:
        """Parse data file content."""
        lines = content.split("\n")

        n_atom_types = 0
        n_bond_types = 0
        n_angle_types = 0
        n_dihedral_types = 0
        n_improper_types = 0
        box_bounds = [0.0, 100.0, 0.0, 100.0, 0.0, 100.0]
        masses: dict[int, float] = {}
        atoms: list[DataFileAtom] = []
        bonds: list[DataFileBond] = []
        angles: list[DataFileAngle] = []
        dihedrals: list[DataFileDihedral] = []
        impropers: list[DataFileImproper] = []
        raw_coeff_sections: dict[str, str] = {}

        current_section: str | None = None
        current_coeff_header: str | None = None
        coeff_lines: list[str] = []

        def _flush_coeff() -> None:
            nonlocal current_coeff_header, coeff_lines
            if current_coeff_header and coeff_lines:
                raw_coeff_sections[current_coeff_header] = "\n".join(coeff_lines)
            current_coeff_header = None
            coeff_lines = []

        for i, line in enumerate(lines):
            line_stripped = line.strip()

            # Skip empty lines and comments — end data sections only when data exists
            if not line_stripped or line_stripped.startswith("#"):
                if current_section == "Atoms" and len(atoms) > 0:
                    current_section = None
                elif current_section == "Bonds" and len(bonds) > 0:
                    current_section = None
                elif current_section == "Angles" and len(angles) > 0:
                    current_section = None
                elif current_section == "Dihedrals" and len(dihedrals) > 0:
                    current_section = None
                elif current_section == "Impropers" and len(impropers) > 0:
                    current_section = None
                elif current_section == "Masses" and len(masses) > 0:
                    current_section = None
                # Coeff sections: blank line after data ends the section
                if current_coeff_header and coeff_lines:
                    _flush_coeff()
                continue

            # Parse header counts
            if "atoms" in line_stripped and "atom" not in line_stripped.lower().split()[0]:
                parts = line_stripped.split()
                if parts[0].isdigit():
                    int(parts[0])
                continue

            if "atom types" in line_stripped:
                parts = line_stripped.split()
                if parts[0].isdigit():
                    n_atom_types = int(parts[0])
                continue

            if "bond types" in line_stripped:
                parts = line_stripped.split()
                if parts[0].isdigit():
                    n_bond_types = int(parts[0])
                continue

            if "angle types" in line_stripped:
                parts = line_stripped.split()
                if parts[0].isdigit():
                    n_angle_types = int(parts[0])
                continue

            if "dihedral types" in line_stripped:
                parts = line_stripped.split()
                if parts[0].isdigit():
                    n_dihedral_types = int(parts[0])
                continue

            if "improper types" in line_stripped:
                parts = line_stripped.split()
                if parts[0].isdigit():
                    n_improper_types = int(parts[0])
                continue

            # Parse box bounds
            if "xlo xhi" in line_stripped:
                parts = line_stripped.split()
                box_bounds[0] = float(parts[0])
                box_bounds[1] = float(parts[1])
                continue

            if "ylo yhi" in line_stripped:
                parts = line_stripped.split()
                box_bounds[0 + 2] = float(parts[0])
                box_bounds[1 + 2] = float(parts[1])
                continue

            if "zlo zhi" in line_stripped:
                parts = line_stripped.split()
                box_bounds[0 + 4] = float(parts[0])
                box_bounds[1 + 4] = float(parts[1])
                continue

            # Detect section headers
            # Coeff sections (capture verbatim)
            coeff_match = None
            for hdr in self._COEFF_SECTIONS:
                if line_stripped == hdr or line_stripped.startswith(hdr + " "):
                    coeff_match = hdr
                    break
            if coeff_match:
                _flush_coeff()
                current_section = None
                current_coeff_header = coeff_match
                coeff_lines = []
                continue

            # Data sections
            matched_data = False
            for hdr in self._DATA_SECTIONS:
                if line_stripped == hdr or line_stripped.startswith(hdr + " "):
                    _flush_coeff()
                    current_section = hdr
                    matched_data = True
                    break
            if matched_data:
                continue

            # Accumulate coeff section lines
            if current_coeff_header:
                coeff_lines.append(line_stripped)
                continue

            # Parse Masses section
            if current_section == "Masses":
                parts = line_stripped.split()
                if len(parts) >= 2:
                    try:
                        type_id = int(parts[0])
                        mass = float(parts[1])
                        masses[type_id] = mass
                    except ValueError:
                        pass
                continue

            # Parse Atoms section (full style: id mol type charge x y z)
            if current_section == "Atoms":
                parts = line_stripped.split()
                if len(parts) >= 7:
                    try:
                        atoms.append(
                            DataFileAtom(
                                atom_id=int(parts[0]),
                                mol_id=int(parts[1]),
                                atom_type=int(parts[2]),
                                charge=float(parts[3]),
                                x=float(parts[4]),
                                y=float(parts[5]),
                                z=float(parts[6]),
                            )
                        )
                    except (ValueError, IndexError):
                        logger.warning(f"Failed to parse atom line {i}: {line_stripped}")
                continue

            # Parse Bonds section (bond_id bond_type atom1_id atom2_id)
            if current_section == "Bonds":
                parts = line_stripped.split()
                if len(parts) >= 4:
                    try:
                        bonds.append(
                            DataFileBond(
                                bond_id=int(parts[0]),
                                bond_type=int(parts[1]),
                                atom1_id=int(parts[2]),
                                atom2_id=int(parts[3]),
                            )
                        )
                    except (ValueError, IndexError):
                        logger.warning(f"Failed to parse bond line {i}: {line_stripped}")
                continue

            # Parse Angles section
            if current_section == "Angles":
                parts = line_stripped.split()
                if len(parts) >= 5:
                    try:
                        angles.append(
                            DataFileAngle(
                                angle_id=int(parts[0]),
                                angle_type=int(parts[1]),
                                atom1_id=int(parts[2]),
                                atom2_id=int(parts[3]),
                                atom3_id=int(parts[4]),
                            )
                        )
                    except (ValueError, IndexError):
                        logger.warning(f"Failed to parse angle line {i}: {line_stripped}")
                continue

            # Parse Dihedrals section
            if current_section == "Dihedrals":
                parts = line_stripped.split()
                if len(parts) >= 6:
                    try:
                        dihedrals.append(
                            DataFileDihedral(
                                dihedral_id=int(parts[0]),
                                dihedral_type=int(parts[1]),
                                atom1_id=int(parts[2]),
                                atom2_id=int(parts[3]),
                                atom3_id=int(parts[4]),
                                atom4_id=int(parts[5]),
                            )
                        )
                    except (ValueError, IndexError):
                        logger.warning(f"Failed to parse dihedral line {i}: {line_stripped}")
                continue

            # Parse Impropers section
            if current_section == "Impropers":
                parts = line_stripped.split()
                if len(parts) >= 6:
                    try:
                        impropers.append(
                            DataFileImproper(
                                improper_id=int(parts[0]),
                                improper_type=int(parts[1]),
                                atom1_id=int(parts[2]),
                                atom2_id=int(parts[3]),
                                atom3_id=int(parts[4]),
                                atom4_id=int(parts[5]),
                            )
                        )
                    except (ValueError, IndexError):
                        logger.warning(f"Failed to parse improper line {i}: {line_stripped}")
                continue

        # Flush any remaining coeff section
        _flush_coeff()

        if not atoms:
            raise ParserError(
                code=ErrorCode.PARSER_ERROR,
                message="No atoms found in data file",
                file_path=file_path,
            )

        return DataFileInfo(
            atoms=atoms,
            bonds=bonds,
            box_bounds=tuple(box_bounds),  # type: ignore
            n_atoms=len(atoms),
            n_bonds=len(bonds),
            n_atom_types=n_atom_types,
            masses=masses,
            angles=angles or None,
            dihedrals=dihedrals or None,
            impropers=impropers or None,
            n_bond_types=n_bond_types,
            n_angle_types=n_angle_types,
            n_dihedral_types=n_dihedral_types,
            n_improper_types=n_improper_types,
            raw_coeff_sections=raw_coeff_sections or None,
        )

    def data_to_xyz(
        self,
        data_file: Path,
        type_map: dict[str, str],
    ) -> tuple[str, tuple[float, float, float]]:
        """
        Convert LAMMPS data file to XYZ format string.

        Args:
            data_file: Path to LAMMPS data file
            type_map: Mapping of type ID to element symbol

        Returns:
            Tuple of (XYZ string, box dimensions)
        """
        info = self.parse(data_file)
        return self.info_to_xyz(info, type_map, comment="Initial structure (t=0)")

    def info_to_xyz(
        self,
        info: DataFileInfo,
        type_map: dict[str, str],
        comment: str = "Structure",
    ) -> tuple[str, tuple[float, float, float]]:
        """Convert parsed DataFileInfo to XYZ format string."""

        lines = [
            str(info.n_atoms),
            comment,
        ]

        for atom in info.atoms:
            element = type_map.get(str(atom.atom_type), "X")
            lines.append(f"{element} {atom.x:.6f} {atom.y:.6f} {atom.z:.6f}")

        # Calculate box dimensions
        xlo, xhi, ylo, yhi, zlo, zhi = info.box_bounds
        box_size = (xhi - xlo, yhi - ylo, zhi - zlo)

        return "\n".join(lines), box_size

    def estimate_elements_from_masses(
        self,
        data_file: Path,
    ) -> dict[str, str]:
        """
        Estimate element symbols from atom masses.

        Fallback method when type_map.json is not available.

        Args:
            data_file: Path to LAMMPS data file

        Returns:
            Mapping of type ID to element symbol
        """
        info = self.parse(data_file)
        return self.estimate_elements_from_info(info)

    def estimate_elements_from_info(
        self,
        info: DataFileInfo,
    ) -> dict[str, str]:
        """Estimate element symbols from atom masses using parsed DataFileInfo."""
        type_map: dict[str, str] = {}

        for type_id, mass in info.masses.items():
            # Find closest matching element
            best_element = "X"
            best_diff = float("inf")

            for element, elem_mass in ATOMIC_WEIGHTS.items():
                diff = abs(mass - elem_mass)
                if diff < best_diff:
                    best_diff = diff
                    best_element = element

            # Only assign if within 0.5 g/mol tolerance
            if best_diff < 0.5:
                type_map[str(type_id)] = best_element
            else:
                type_map[str(type_id)] = "X"
                logger.warning(f"Unknown mass {mass} for type {type_id}, using 'X'")

        return type_map


# Export
__all__ = [
    "DataParser",
    "DataFileInfo",
    "DataFileAtom",
    "DataFileBond",
    "DataFileAngle",
    "DataFileDihedral",
    "DataFileImproper",
]
