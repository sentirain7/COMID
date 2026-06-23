"""Parse box dimensions from LAMMPS data file — read-only utility."""

from __future__ import annotations

from pathlib import Path


def parse_box_from_data_file(path: str | None) -> tuple[float, float, float] | None:
    """Parse box dimensions (lx, ly, lz) from LAMMPS data file header.

    Args:
        path: Path to LAMMPS data file (absolute or relative).

    Returns:
        Tuple (lx, ly, lz) in Angstrom, or None if file missing/unparseable.
    """
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    try:
        xlo = xhi = ylo = yhi = zlo = zhi = 0.0
        with p.open() as f:
            for line in f:
                if "xlo xhi" in line:
                    parts = line.split()
                    xlo, xhi = float(parts[0]), float(parts[1])
                elif "ylo yhi" in line:
                    parts = line.split()
                    ylo, yhi = float(parts[0]), float(parts[1])
                elif "zlo zhi" in line:
                    parts = line.split()
                    zlo, zhi = float(parts[0]), float(parts[1])
                    break  # z bounds are always last
        lx, ly, lz = xhi - xlo, yhi - ylo, zhi - zlo
        if lx > 0 and ly > 0 and lz > 0:
            return (lx, ly, lz)
    except Exception:
        pass
    return None
