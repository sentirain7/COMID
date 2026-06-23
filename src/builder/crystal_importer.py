"""Crystal import adapters.

Currently supports CIF import via optional pymatgen dependency.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from contracts.errors import ContractError, ErrorCode


def load_cif_unit_cell(cif_path: Path) -> dict[str, Any]:
    """
    Load a CIF file and return a CrystalBuilder-compatible unit-cell payload.

    Returns:
        Dict with keys: a, b, c, alpha, beta, gamma, atoms
        where atoms is [(element, frac_x, frac_y, frac_z), ...].
    """
    if not cif_path.exists():
        raise ContractError(
            ErrorCode.STRUCTURE_NOT_FOUND,
            f"CIF file not found: {cif_path}",
            {"cif_path": str(cif_path)},
        )

    try:
        from pymatgen.core import Structure
    except Exception as exc:
        raise ContractError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "CIF import requires optional dependency 'pymatgen'. Install with: pip install pymatgen",
            {"cif_path": str(cif_path)},
        ) from exc

    try:
        structure = Structure.from_file(str(cif_path))
    except Exception as exc:
        raise ContractError(
            ErrorCode.PARSER_ERROR,
            "Failed to parse CIF file",
            {"cif_path": str(cif_path), "reason": str(exc)},
        ) from exc

    if len(structure.sites) == 0:
        raise ContractError(
            ErrorCode.PARSER_ERROR,
            "CIF contains no atomic sites",
            {"cif_path": str(cif_path)},
        )

    lattice = structure.lattice
    atoms: list[tuple[str, float, float, float]] = []
    for site in structure.sites:
        specie = str(site.specie)
        symbol = "".join(ch for ch in specie if ch.isalpha()) or specie
        fx, fy, fz = site.frac_coords
        atoms.append((symbol, float(fx), float(fy), float(fz)))

    return {
        "a": float(lattice.a),
        "b": float(lattice.b),
        "c": float(lattice.c),
        "alpha": float(lattice.alpha),
        "beta": float(lattice.beta),
        "gamma": float(lattice.gamma),
        "atoms": atoms,
    }
