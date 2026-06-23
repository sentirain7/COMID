"""
Packing validator for checking structure quality.

Validates molecular packing quality including minimum distances,
overlaps, and initial energy estimates.
"""

import math
from dataclasses import dataclass
from pathlib import Path

from common.logging import get_logger
from contracts.schemas import FailureCategory

logger = get_logger("builder.packing_validator")


@dataclass
class ValidationResult:
    """Result of packing validation."""

    valid: bool
    min_distance: float
    min_distance_violations: int
    overlap_pairs: list[tuple[int, int]]
    estimated_pe_per_atom: float
    stability_flag: str | None = None
    message: str = ""


class PackingValidator:
    """
    Validator for molecular packing quality.

    Checks for overlaps, minimum distances, and estimates
    initial potential energy to detect problematic structures.
    """

    def __init__(
        self,
        min_distance: float = 1.5,
        max_pe_per_atom: float = 100.0,
    ):
        """
        Initialize validator.

        Args:
            min_distance: Minimum allowed distance between atoms (Angstrom)
            max_pe_per_atom: Maximum PE/atom before flagging (kcal/mol/atom)
        """
        self.min_distance = min_distance
        self.max_pe_per_atom = max_pe_per_atom

    def validate(self, data_file: Path) -> ValidationResult:
        """
        Validate packing quality of LAMMPS data file.

        Args:
            data_file: Path to LAMMPS data file

        Returns:
            ValidationResult with quality metrics
        """
        # Read atom positions
        atoms = self._read_atoms(data_file)

        if not atoms:
            return ValidationResult(
                valid=False,
                min_distance=0.0,
                min_distance_violations=0,
                overlap_pairs=[],
                estimated_pe_per_atom=0.0,
                stability_flag=FailureCategory.PACKING_OVERLAP_SUSPECTED.value,
                message="No atoms found in data file",
            )

        # Inter-molecular minimum distances (intra-molecular bonds excluded).
        min_dist, violations, overlaps = self._check_distances(atoms)
        pe_per_atom = self._estimate_pe(atoms, min_dist)

        # 어떤 분자간 원자쌍이든 임계(=0.9×tolerance) 미만이면 결함(겹침/관통).
        # 정상 패킹은 모든 분자간 쌍이 tolerance 이상이라 위반 0. 결함은 0.6~1.1 Å.
        valid = violations == 0
        stability_flag = (
            None if valid else FailureCategory.PACKING_OVERLAP_SUSPECTED.value
        )
        if valid:
            message = "Packing OK"
        else:
            message = (
                f"{violations} inter-molecular distance violation(s) "
                f"(min {min_dist:.3f} Å < {self.min_distance:.2f} Å)"
            )

        # inf(분자간 쌍 없음 — 단일분자/희박)는 직렬화·다운스트림 안전 위해 유한값으로.
        reported_min = min_dist if math.isfinite(min_dist) else 999.0

        return ValidationResult(
            valid=valid,
            min_distance=reported_min,
            min_distance_violations=violations,
            overlap_pairs=overlaps[:10],
            estimated_pe_per_atom=pe_per_atom,
            stability_flag=stability_flag,
            message=message,
        )

    def _read_atoms(
        self, data_file: Path
    ) -> list[tuple[int, int, float, float, float]]:
        """Read atom id, molecule id, and position from a LAMMPS data file.

        The ``mol_id`` (column 2 of ``atom_style full``) is preserved so that
        validation can check **inter-molecular** distances only — intra-molecular
        bonded atoms (C–H ~1.1 Å, C–C ~1.5 Å) are normal and must not be
        counted as overlaps (the historical bug that made every structure
        report invalid).
        """
        atoms = []
        in_atoms_section = False
        found_first_atom = False

        for line in data_file.read_text().split("\n"):
            line = line.strip()

            if line.startswith("Atoms"):
                in_atoms_section = True
                continue

            if in_atoms_section:
                if not line:
                    if found_first_atom:
                        break
                    continue

                if line.startswith("Bonds") or line.startswith("Velocities"):
                    break

                parts = line.split()
                if len(parts) >= 7:  # atom_id mol_id type charge x y z
                    try:
                        atom_id = int(parts[0])
                        mol_id = int(parts[1])
                        x = float(parts[4])
                        y = float(parts[5])
                        z = float(parts[6])
                        atoms.append((atom_id, mol_id, x, y, z))
                        found_first_atom = True
                    except (ValueError, IndexError):
                        continue

        return atoms

    def _check_distances(
        self,
        atoms: list[tuple[int, int, float, float, float]],
    ) -> tuple[float, int, list[tuple[int, int]]]:
        """Check **inter-molecular** minimum atom distances (KDTree).

        Only pairs of atoms belonging to *different* molecules are checked —
        intra-molecular bonded distances are physical and excluded. This is a
        molecule-agnostic, tuning-free re-verification of Packmol's own
        ``tolerance`` guarantee: a converged pack has no inter-molecular pair
        below ``tolerance``, while overlaps/threading sit at 0.6–1.1 Å.

        Returns:
            Tuple of (min_inter_distance, violation_count, overlap_pairs).
            ``min_inter_distance`` is ``inf`` when there are no inter-molecular
            pairs (e.g. a single-molecule system) — trivially valid.
        """
        import numpy as np
        from scipy.spatial import cKDTree

        if len(atoms) < 2:
            return float("inf"), 0, []

        ids = np.array([a[0] for a in atoms])
        mol_ids = np.array([a[1] for a in atoms])
        coords = np.array([(a[2], a[3], a[4]) for a in atoms], dtype=float)

        tree = cKDTree(coords)
        # 후보쌍을 tolerance 반경에서만 질의(전수 O(N²) 회피). 위반은 이 안에만 존재.
        pairs = tree.query_pairs(self.min_distance, output_type="ndarray")
        min_inter = float("inf")
        violations = 0
        overlaps: list[tuple[int, int]] = []
        if len(pairs):
            inter_mask = mol_ids[pairs[:, 0]] != mol_ids[pairs[:, 1]]
            inter = pairs[inter_mask]
            if len(inter):
                d = np.linalg.norm(coords[inter[:, 0]] - coords[inter[:, 1]], axis=1)
                min_inter = float(d.min())
                violations = int(len(inter))
                for i, j in inter[:100]:
                    overlaps.append((int(ids[i]), int(ids[j])))
        return min_inter, violations, overlaps

    def _estimate_pe(
        self,
        atoms: list[tuple[int, int, float, float, float]],
        min_dist: float,
    ) -> float:
        """
        Estimate potential energy per atom from the closest inter-molecular gap.

        Uses simple LJ-like approximation for overlap detection (informational
        ``estimated_pe_per_atom`` field; no longer a gating signal).
        """
        if min_dist > 3.0:
            # Normal distances, low PE
            return -5.0

        if min_dist < 0.5:
            # Severe overlap
            return 1000.0

        if min_dist < 1.0:
            # Significant overlap
            return 100.0

        if min_dist < 1.5:
            # Minor overlap
            return 10.0

        # Slight compression
        return -3.0

    def quick_check(self, data_file: Path) -> bool:
        """
        Quick validity check without detailed metrics.

        Args:
            data_file: Path to LAMMPS data file

        Returns:
            True if structure passes basic checks
        """
        result = self.validate(data_file)
        return result.valid
