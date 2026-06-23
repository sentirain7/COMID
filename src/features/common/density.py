"""Density calculation from atom masses and box dimensions."""

from __future__ import annotations

from common.units import AVOGADRO


def total_mass_from_types(atom_types: list[int], mass_by_type: dict[int, float]) -> float:
    """Compute total mass (g/mol) from atom type IDs and per-type masses.

    Args:
        atom_types: List of atom type IDs for each atom.
        mass_by_type: Mapping of atom type ID to mass (g/mol).

    Returns:
        Total mass in g/mol.
    """
    total = 0.0
    for atom_type in atom_types:
        total += float(mass_by_type.get(atom_type, 0.0))
    return total


def density_from_total_mass(
    total_mass_g_mol: float,
    box_size: tuple[float, float, float],
) -> float | None:
    """Compute density (g/cm3) from total mass (g/mol) and box dimensions (Angstrom).

    Args:
        total_mass_g_mol: Total mass in g/mol.
        box_size: Box dimensions (lx, ly, lz) in Angstrom.

    Returns:
        Density in g/cm3, or None if inputs are non-positive.
    """
    lx, ly, lz = box_size
    volume_a3 = lx * ly * lz
    if volume_a3 <= 0 or total_mass_g_mol <= 0:
        return None
    return total_mass_g_mol / AVOGADRO * 1e24 / volume_a3
