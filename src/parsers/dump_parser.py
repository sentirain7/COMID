"""
LAMMPS dump file parser.

Parses LAMMPS trajectory dump files in various formats.
"""

import io
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from common.logging import get_logger

logger = get_logger("parsers.dump_parser")


@dataclass
class DumpFrame:
    """A single frame from a dump file."""

    timestep: int
    n_atoms: int
    box_bounds: list[tuple[float, float]]
    columns: list[str]
    atoms: list[dict]


class DumpParser:
    """
    Parser for LAMMPS dump files.

    Supports standard LAMMPS dump format (custom dump format).
    """

    def __init__(self):
        """Initialize dump parser."""
        pass

    def parse(self, dump_file: Path) -> list[DumpFrame]:
        """
        Parse entire dump file.

        Args:
            dump_file: Path to dump file

        Returns:
            List of DumpFrame objects
        """
        return list(self.parse_frames(dump_file))

    def parse_frames(self, dump_file: Path) -> Iterator[DumpFrame]:
        """
        Parse dump file frame by frame (generator).

        Args:
            dump_file: Path to dump file

        Yields:
            DumpFrame for each timestep
        """
        dump_file = Path(dump_file)

        if not dump_file.exists():
            logger.error(f"Dump file not found: {dump_file}")
            return

        with open(dump_file) as f:
            while True:
                frame = self._parse_single_frame(f)
                if frame is None:
                    break
                yield frame

    def _parse_single_frame(self, f) -> DumpFrame | None:
        """Parse a single frame from file handle."""
        # Read TIMESTEP
        line = f.readline()
        if not line:
            return None

        if "ITEM: TIMESTEP" not in line:
            # Try to find next timestep
            while line and "ITEM: TIMESTEP" not in line:
                line = f.readline()
            if not line:
                return None

        timestep = int(f.readline().strip())

        # Read NUMBER OF ATOMS
        line = f.readline()
        if "ITEM: NUMBER OF ATOMS" not in line:
            return None
        n_atoms = int(f.readline().strip())

        # Read BOX BOUNDS
        line = f.readline()
        if "ITEM: BOX BOUNDS" not in line:
            return None

        box_bounds = []
        for _ in range(3):
            bounds = f.readline().strip().split()
            box_bounds.append((float(bounds[0]), float(bounds[1])))

        # Read ATOMS header
        line = f.readline()
        if "ITEM: ATOMS" not in line:
            return None

        # Extract column names
        columns = line.replace("ITEM: ATOMS", "").strip().split()

        # Read atom data
        atoms = []
        for _ in range(n_atoms):
            atom_line = f.readline().strip()
            values = atom_line.split()
            atom = {}
            for col, val in zip(columns, values, strict=False):
                try:
                    if col in ("id", "type", "mol"):
                        atom[col] = int(val)
                    else:
                        atom[col] = float(val)
                except ValueError:
                    atom[col] = val
            atoms.append(atom)

        return DumpFrame(
            timestep=timestep,
            n_atoms=n_atoms,
            box_bounds=box_bounds,
            columns=columns,
            atoms=atoms,
        )

    def get_positions(self, frame: DumpFrame) -> list[tuple[float, float, float]]:
        """Extract atom positions from frame."""
        positions = []
        for atom in frame.atoms:
            x = atom.get("x", atom.get("xu", 0.0))
            y = atom.get("y", atom.get("yu", 0.0))
            z = atom.get("z", atom.get("zu", 0.0))
            positions.append((x, y, z))
        return positions

    def get_velocities(self, frame: DumpFrame) -> list[tuple[float, float, float]]:
        """Extract atom velocities from frame."""
        velocities = []
        for atom in frame.atoms:
            vx = atom.get("vx", 0.0)
            vy = atom.get("vy", 0.0)
            vz = atom.get("vz", 0.0)
            velocities.append((vx, vy, vz))
        return velocities

    def get_types(self, frame: DumpFrame) -> list[int]:
        """Extract atom types from frame."""
        return [atom.get("type", 0) for atom in frame.atoms]

    def get_box_dimensions(self, frame: DumpFrame) -> tuple[float, float, float]:
        """Get box dimensions from frame."""
        lx = frame.box_bounds[0][1] - frame.box_bounds[0][0]
        ly = frame.box_bounds[1][1] - frame.box_bounds[1][0]
        lz = frame.box_bounds[2][1] - frame.box_bounds[2][0]
        return (lx, ly, lz)

    def get_box_volume(self, frame: DumpFrame) -> float:
        """Get box volume from frame."""
        lx, ly, lz = self.get_box_dimensions(frame)
        return lx * ly * lz

    def parse_last_frame(self, dump_file: Path) -> DumpFrame | None:
        """
        Parse only the last frame from a dump file.

        Args:
            dump_file: Path to dump file

        Returns:
            Last DumpFrame or None
        """
        dump_file = Path(dump_file)
        if not dump_file.exists():
            logger.error(f"Dump file not found: {dump_file}")
            return None

        marker = b"ITEM: TIMESTEP"
        marker_offset = self._find_last_marker_offset(dump_file, marker)
        if marker_offset is None:
            logger.warning(f"No TIMESTEP marker found in dump file: {dump_file}")
            return None

        with open(dump_file, "rb") as raw:
            raw.seek(marker_offset)
            # Keep existing text parser path while seeking by byte offset.
            with io.TextIOWrapper(raw, encoding="utf-8", errors="replace") as text_stream:
                return self._parse_single_frame(text_stream)

    def _find_last_marker_offset(self, dump_file: Path, marker: bytes) -> int | None:
        """Find byte offset of last marker in file using reverse chunk scan."""
        marker_len = len(marker)
        if marker_len == 0:
            return None

        with open(dump_file, "rb") as f:
            f.seek(0, 2)
            file_size = f.tell()
            if file_size == 0:
                return None

            chunk_size = 1024 * 1024
            overlap = marker_len - 1
            pos = file_size
            tail = b""

            while pos > 0:
                read_size = min(chunk_size, pos)
                pos -= read_size
                f.seek(pos)
                chunk = f.read(read_size)

                data = chunk + tail
                idx = data.rfind(marker)
                if idx != -1:
                    return pos + idx

                tail = data[:overlap] if overlap > 0 else b""

        return None

    def count_frames(self, dump_file: Path) -> int:
        """Count number of frames in dump file."""
        count = 0
        for _ in self.parse_frames(dump_file):
            count += 1
        return count

    def get_sorted_positions(
        self,
        frame: DumpFrame,
        prefer_unwrapped: bool = True,
    ) -> tuple[np.ndarray, bool]:
        """Get positions sorted by atom ID for consistent cross-frame ordering.

        Args:
            frame: Parsed dump frame.
            prefer_unwrapped: If True, prefer xu/yu/zu over x/y/z.

        Returns:
            Tuple of (positions (N, 3), used_unwrapped).
        """
        has_unwrapped = all(k in frame.columns for k in ("xu", "yu", "zu"))
        use_unwrapped = prefer_unwrapped and has_unwrapped

        if use_unwrapped:
            xk, yk, zk = "xu", "yu", "zu"
        else:
            xk, yk, zk = "x", "y", "z"
            # Fallback to xs/ys/zs if x/y/z absent
            if "x" not in frame.columns and "xs" in frame.columns:
                xk, yk, zk = "xs", "ys", "zs"

        # Sort atoms by id for consistent ordering
        atoms = sorted(frame.atoms, key=lambda a: a.get("id", 0))

        n = len(atoms)
        pos = np.empty((n, 3), dtype=np.float64)
        for i, atom in enumerate(atoms):
            pos[i, 0] = atom.get(xk, 0.0)
            pos[i, 1] = atom.get(yk, 0.0)
            pos[i, 2] = atom.get(zk, 0.0)

        return pos, use_unwrapped

    def get_positions_array(self, frame: DumpFrame) -> np.ndarray:
        """Extract atom positions as numpy (N, 3) array.

        Args:
            frame: Parsed dump frame.

        Returns:
            Positions array of shape (n_atoms, 3).
        """
        n = frame.n_atoms
        pos = np.empty((n, 3), dtype=np.float64)
        for i, atom in enumerate(frame.atoms):
            pos[i, 0] = atom.get("x", atom.get("xu", 0.0))
            pos[i, 1] = atom.get("y", atom.get("yu", 0.0))
            pos[i, 2] = atom.get("z", atom.get("zu", 0.0))
        return pos

    def make_molecules_whole(
        self,
        frame: DumpFrame,
        bond_pairs: list[list[int]],
    ) -> None:
        """Unwrap molecules in-place so bonded atoms are contiguous.

        Uses wrapped coordinates as base and BFS per connected component
        to shift bonded neighbours via minimum-image convention.  This
        keeps every molecule intact while preventing atoms from drifting
        outside the simulation box.

        Args:
            frame: Parsed dump frame (atoms modified in-place).
            bond_pairs: List of [idx_i, idx_j] index pairs (0-based).
        """
        atoms = frame.atoms
        n = len(atoms)
        if n == 0 or not bond_pairs:
            return

        box = self.get_box_dimensions(frame)
        if box is None:
            return
        lx, ly, lz = box.get("lx", 0.0), box.get("ly", 0.0), box.get("lz", 0.0)
        if lx <= 0 or ly <= 0 or lz <= 0:
            return

        # Build adjacency list
        adj: list[list[int]] = [[] for _ in range(n)]
        for pair in bond_pairs:
            i, j = pair[0], pair[1]
            if 0 <= i < n and 0 <= j < n:
                adj[i].append(j)
                adj[j].append(i)

        # Determine coordinate keys (prefer wrapped)
        xk = "x" if "x" in frame.columns else "xu"
        yk = "y" if "y" in frame.columns else "yu"
        zk = "z" if "z" in frame.columns else "zu"

        visited = [False] * n
        for start in range(n):
            if visited[start] or not adj[start]:
                continue
            visited[start] = True
            queue = deque([start])
            while queue:
                curr = queue.popleft()
                cx = atoms[curr].get(xk, 0.0)
                cy = atoms[curr].get(yk, 0.0)
                cz = atoms[curr].get(zk, 0.0)
                for nb in adj[curr]:
                    if visited[nb]:
                        continue
                    visited[nb] = True
                    nx = atoms[nb].get(xk, 0.0)
                    ny = atoms[nb].get(yk, 0.0)
                    nz = atoms[nb].get(zk, 0.0)
                    # Minimum-image shift
                    dx = nx - cx
                    dy = ny - cy
                    dz = nz - cz
                    atoms[nb][xk] = cx + dx - round(dx / lx) * lx
                    atoms[nb][yk] = cy + dy - round(dy / ly) * ly
                    atoms[nb][zk] = cz + dz - round(dz / lz) * lz
                    queue.append(nb)

    def frame_to_xyz(
        self,
        frame: DumpFrame,
        type_map: dict[str, str],
    ) -> str:
        """
        Convert DumpFrame to XYZ format string.

        Args:
            frame: Parsed dump frame (from parse_last_frame)
            type_map: Mapping of type ID to element symbol, e.g., {"1": "C", "2": "H"}

        Returns:
            XYZ format string compatible with 3Dmol.js
        """
        lines = [
            str(frame.n_atoms),
            f"Timestep {frame.timestep}",
        ]

        for atom in frame.atoms:
            atom_type = str(atom.get("type", 1))
            element = type_map.get(atom_type, "X")  # "X" for unknown

            x = atom.get("x", atom.get("xu", 0.0))
            y = atom.get("y", atom.get("yu", 0.0))
            z = atom.get("z", atom.get("zu", 0.0))

            lines.append(f"{element} {x:.6f} {y:.6f} {z:.6f}")

        return "\n".join(lines)
