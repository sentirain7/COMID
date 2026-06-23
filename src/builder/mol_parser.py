"""
MOL file parsing utilities.

Standalone functions for parsing MDL MOL V2000/V3000 files into topology objects.
"""

from pathlib import Path

from common.constants import ATOMIC_WEIGHTS

from .mol_types import MolAtom, MolBond, MolTopology


def parse_mol_topology(mol_path: Path, mol_id: str = "") -> MolTopology | None:
    """
    Parse complete topology from MDL MOL V2000 file.

    Args:
        mol_path: Path to MOL file
        mol_id: Molecule identifier

    Returns:
        MolTopology with atoms, bonds, angles, and dihedrals
    """
    try:
        with open(mol_path) as f:
            lines = f.readlines()
    except Exception:
        return None

    if len(lines) < 5:
        return None

    # Parse counts line (line 4, index 3)
    # MDL MOL V2000 uses fixed-width fields: positions 0-2 = atom count, 3-5 = bond count
    # Do NOT strip() - it removes leading spaces needed for correct column parsing
    # Example: " 97101  0..." -> atoms=97 (cols 0-2), bonds=101 (cols 3-5)
    counts_line = lines[3]

    # Check for V3000 format
    if "V3000" in counts_line:
        return _parse_mol_v3000(lines, mol_id or mol_path.stem)

    # Parse V2000 format
    parts = counts_line.split()
    if not parts:
        return None

    try:
        # First 3 chars = atom count, next 3 = bond count
        atom_count = int(counts_line[:3].strip())
        bond_count = int(counts_line[3:6].strip())
    except ValueError:
        return None

    atoms: list[MolAtom] = []
    bonds: list[MolBond] = []
    molecular_weight = 0.0

    # Parse atom block (lines 5 to 4+atom_count)
    for i in range(4, 4 + atom_count):
        if i >= len(lines):
            break
        line = lines[i]
        parts = line.split()
        if len(parts) < 4:
            continue

        try:
            x = float(parts[0])
            y = float(parts[1])
            z = float(parts[2])
            element = parts[3].strip()

            atoms.append(MolAtom(index=len(atoms) + 1, x=x, y=y, z=z, element=element, charge=0.0))
            molecular_weight += ATOMIC_WEIGHTS.get(element, 12.0)
        except (ValueError, IndexError):
            continue

    # Parse bond block (lines after atom block)
    # V2000 bond format is fixed-width: 111222tttsssxxxrrrccc
    # First 3 chars = atom1, next 3 = atom2, next 3 = bond type
    bond_start = 4 + atom_count
    for i in range(bond_start, bond_start + bond_count):
        if i >= len(lines):
            break
        line = lines[i]
        if line.strip().startswith("M "):  # End of bond block
            break
        if len(line) < 9:
            continue

        try:
            # Fixed-width parsing (3 chars each)
            atom1 = int(line[0:3].strip())
            atom2 = int(line[3:6].strip())
            order = int(line[6:9].strip())

            bonds.append(MolBond(atom1=atom1, atom2=atom2, order=order))
        except (ValueError, IndexError):
            continue

    # Parse optional V2000 charge property lines:
    # M  CHG  n atom1 charge1 atom2 charge2 ...
    # Note: This is formal charge metadata, not partial charge.
    charge_map: dict[int, float] = {}
    for i in range(bond_start + bond_count, len(lines)):
        line = lines[i].strip()
        if line == "M  END":
            break
        if not line.startswith("M  CHG"):
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            n_pairs = int(parts[2])
        except (ValueError, IndexError):
            continue

        # Be defensive for malformed lines.
        available_pairs = max(0, (len(parts) - 3) // 2)
        n_pairs = min(n_pairs, available_pairs)
        for p in range(n_pairs):
            idx_pos = 3 + 2 * p
            chg_pos = idx_pos + 1
            try:
                atom_idx = int(parts[idx_pos])
                formal_charge = float(parts[chg_pos])
            except (ValueError, IndexError):
                continue
            charge_map[atom_idx] = formal_charge

    if charge_map:
        for atom in atoms:
            if atom.index in charge_map:
                atom.charge = charge_map[atom.index]
                atom.charge_defined = True

    return MolTopology(
        mol_id=mol_id or mol_path.stem,
        atoms=atoms,
        bonds=bonds,
        molecular_weight=round(molecular_weight, 2),
    )


def _parse_mol_v3000(lines: list[str], mol_id: str) -> MolTopology | None:
    """Parse V3000 format MOL file."""
    atoms: list[MolAtom] = []
    bonds: list[MolBond] = []
    molecular_weight = 0.0

    in_atom_block = False
    in_bond_block = False

    for raw_line in lines:
        line = raw_line.strip()

        if line.startswith("M  V30 BEGIN ATOM"):
            in_atom_block = True
            in_bond_block = False
            continue
        if line.startswith("M  V30 END ATOM"):
            in_atom_block = False
            continue
        if line.startswith("M  V30 BEGIN BOND"):
            in_bond_block = True
            in_atom_block = False
            continue
        if line.startswith("M  V30 END BOND"):
            in_bond_block = False
            continue

        if not line.startswith("M  V30 "):
            continue

        payload = line[len("M  V30 ") :].strip()
        if in_atom_block:
            # Atom format: idx element x y z aamap [props...]
            parts = payload.split()
            if len(parts) < 6:
                continue
            try:
                idx = int(parts[0])
                element = parts[1]
                x = float(parts[2])
                y = float(parts[3])
                z = float(parts[4])
                charge = 0.0
                charge_defined = False
                for token in parts[6:]:
                    if token.startswith("CHG="):
                        charge = float(token.split("=", 1)[1])
                        charge_defined = True
                        break
                atoms.append(
                    MolAtom(
                        index=idx,
                        x=x,
                        y=y,
                        z=z,
                        element=element,
                        charge=charge,
                        charge_defined=charge_defined,
                    )
                )
                molecular_weight += ATOMIC_WEIGHTS.get(element, 12.0)
            except (ValueError, IndexError):
                continue

        elif in_bond_block:
            # Bond format: idx order atom1 atom2 [props...]
            parts = payload.split()
            if len(parts) < 4:
                continue
            try:
                order = int(parts[1])
                atom1 = int(parts[2])
                atom2 = int(parts[3])
                bonds.append(MolBond(atom1=atom1, atom2=atom2, order=order))
            except (ValueError, IndexError):
                continue

    if not atoms:
        return None

    atoms.sort(key=lambda atom: atom.index)
    return MolTopology(
        mol_id=mol_id or "unknown_molecule",
        atoms=atoms,
        bonds=bonds,
        molecular_weight=round(molecular_weight, 2),
    )


def _parse_mol_file(mol_path: Path) -> tuple[int, float]:
    """
    Parse MDL MOL V2000 file to extract atom count and estimate molecular weight.

    Args:
        mol_path: Path to MOL file

    Returns:
        Tuple of (atom_count, estimated_molecular_weight)
    """
    topology = parse_mol_topology(mol_path)
    if topology:
        return topology.n_atoms, topology.molecular_weight
    return 0, 0.0


def _parse_mol_file_legacy(mol_path: Path) -> tuple[int, float]:
    """Legacy parser for backwards compatibility."""
    atom_count = 0
    molecular_weight = 0.0

    with open(mol_path) as f:
        lines = f.readlines()

    if len(lines) < 5:
        return 0, 0.0

    counts_line = lines[3].strip()
    parts = counts_line.split()
    if not parts:
        return 0, 0.0

    try:
        atom_count = int(parts[0][:3])
    except ValueError:
        return 0, 0.0

    for i in range(4, 4 + atom_count):
        if i >= len(lines):
            break
        line = lines[i]
        parts = line.split()
        if len(parts) >= 4:
            element = parts[3]
            molecular_weight += ATOMIC_WEIGHTS.get(element, 12.0)

    return atom_count, round(molecular_weight, 2)
