"""
Composition calculator for converting wt% to molecule counts.

Handles the conversion from target weight percentages to actual
molecule numbers while minimizing composition error.
"""

from dataclasses import dataclass

from contracts.policies.composition import DEFAULT_COMPOSITION_CONSTRAINTS, CompositionConstraints
from contracts.schemas import CompositionResult, MoleculeInfo


@dataclass
class MoleculeAllocation:
    """Allocation result for a single molecule type."""

    mol_id: str
    category: str
    target_wt_pct: float
    count: int
    actual_mass: float  # g/mol total
    actual_wt_pct: float
    atoms: int


class CompositionCalculator:
    """
    Calculator for converting wt% composition to molecule counts.

    Implements optimization to minimize L1 composition error while
    meeting target atom count constraints.
    """

    def __init__(self, constraints: CompositionConstraints | None = None):
        """
        Initialize calculator with constraints.

        Args:
            constraints: Composition constraints (uses default if None)
        """
        self.constraints = constraints or DEFAULT_COMPOSITION_CONSTRAINTS

    def calculate(
        self,
        target_wt: dict[str, float],
        molecules: dict[str, MoleculeInfo],
        target_atoms: int,
        tolerance: float = 0.10,
    ) -> CompositionResult:
        """
        Calculate molecule counts from target wt% composition.

        Args:
            target_wt: Target composition by category (wt%)
            molecules: Available molecules by category
            target_atoms: Target total atom count
            tolerance: Allowed deviation from target atoms

        Returns:
            CompositionResult with molecule counts and error metrics
        """
        # Normalize target composition
        target_wt = self._normalize_composition(target_wt)

        # Initial calculation
        mol_counts, total_mass = self._initial_allocation(target_wt, molecules, target_atoms)

        # Calculate actual wt%
        actual_wt = self._calculate_actual_wt(mol_counts, molecules, total_mass)

        # Calculate error
        error_l1 = self._calculate_l1_error(target_wt, actual_wt)

        # If error exceeds threshold, optimize
        if error_l1 > self.constraints.composition_error_threshold_l1:
            mol_counts, total_mass = self._optimize_allocation(
                target_wt, molecules, target_atoms, tolerance
            )
            actual_wt = self._calculate_actual_wt(mol_counts, molecules, total_mass)
            error_l1 = self._calculate_l1_error(target_wt, actual_wt)

        # Calculate total atoms
        total_atoms = sum(mol_counts[cat] * molecules[cat].atom_count for cat in mol_counts)

        return CompositionResult(
            mol_counts=mol_counts,
            actual_wt=actual_wt,
            target_wt=target_wt,
            error_l1=error_l1,
            total_atoms=total_atoms,
            total_mass=total_mass,
        )

    def _normalize_composition(self, composition: dict[str, float]) -> dict[str, float]:
        """Normalize composition to sum to 100%."""
        total = sum(composition.values())
        if abs(total - 100.0) < 0.01:
            return composition.copy()
        return {k: v * 100.0 / total for k, v in composition.items()}

    def _initial_allocation(
        self,
        target_wt: dict[str, float],
        molecules: dict[str, MoleculeInfo],
        target_atoms: int,
    ) -> tuple[dict[str, int], float]:
        """
        Perform initial molecule allocation.

        Uses weighted average molecular weight to estimate total mass,
        then allocates molecules proportionally.
        """
        # Calculate weighted average atoms per mass unit
        total_wt = sum(target_wt.values())
        avg_atoms_per_mass = 0.0

        for cat, wt_pct in target_wt.items():
            if cat not in molecules:
                continue
            mol = molecules[cat]
            # atoms per g/mol
            atoms_per_mass = mol.atom_count / mol.molecular_weight
            avg_atoms_per_mass += (wt_pct / total_wt) * atoms_per_mass

        if avg_atoms_per_mass == 0:
            raise ValueError("No valid molecules for composition")

        # Estimate total mass needed for target atoms
        estimated_total_mass = target_atoms / avg_atoms_per_mass

        # Allocate molecules
        mol_counts = {}
        actual_total_mass = 0.0

        for cat, wt_pct in target_wt.items():
            if cat not in molecules:
                mol_counts[cat] = 0
                continue

            mol = molecules[cat]
            target_mass = estimated_total_mass * (wt_pct / 100.0)
            count = max(1, round(target_mass / mol.molecular_weight))
            mol_counts[cat] = count
            actual_total_mass += count * mol.molecular_weight

        return mol_counts, actual_total_mass

    def _optimize_allocation(
        self,
        target_wt: dict[str, float],
        molecules: dict[str, MoleculeInfo],
        target_atoms: int,
        tolerance: float,
    ) -> tuple[dict[str, int], float]:
        """
        Optimize molecule allocation to minimize composition error.

        Uses iterative adjustment to find better allocation within
        atom count tolerance.
        """
        min_atoms = int(target_atoms * (1 - tolerance))
        max_atoms = int(target_atoms * (1 + tolerance))

        best_counts = None
        best_error = float("inf")
        best_mass = 0.0

        # Try different total atom targets
        for atom_target in range(min_atoms, max_atoms + 1, max(1, (max_atoms - min_atoms) // 20)):
            counts, mass = self._initial_allocation(target_wt, molecules, atom_target)
            actual_wt = self._calculate_actual_wt(counts, molecules, mass)
            error = self._calculate_l1_error(target_wt, actual_wt)

            if error < best_error:
                best_error = error
                best_counts = counts
                best_mass = mass

        # Fine-tune by adjusting individual counts
        if best_counts:
            best_counts, best_mass = self._fine_tune_allocation(
                best_counts, target_wt, molecules, min_atoms, max_atoms
            )

        return best_counts or {}, best_mass

    def _fine_tune_allocation(
        self,
        counts: dict[str, int],
        target_wt: dict[str, float],
        molecules: dict[str, MoleculeInfo],
        min_atoms: int,
        max_atoms: int,
    ) -> tuple[dict[str, int], float]:
        """Fine-tune allocation by adjusting individual molecule counts."""
        best_counts = counts.copy()
        best_mass = sum(
            best_counts[cat] * molecules[cat].molecular_weight
            for cat in best_counts
            if cat in molecules
        )
        best_error = self._calculate_l1_error(
            target_wt, self._calculate_actual_wt(best_counts, molecules, best_mass)
        )

        # Try adjusting each category ±1
        improved = True
        max_iterations = 50
        iteration = 0

        while improved and iteration < max_iterations:
            improved = False
            iteration += 1

            for cat in counts:
                if cat not in molecules:
                    continue

                for delta in [-1, 1]:
                    test_counts = best_counts.copy()
                    test_counts[cat] = max(1, test_counts[cat] + delta)

                    # Check atom count bounds
                    total_atoms = sum(
                        test_counts[c] * molecules[c].atom_count
                        for c in test_counts
                        if c in molecules
                    )
                    if total_atoms < min_atoms or total_atoms > max_atoms:
                        continue

                    test_mass = sum(
                        test_counts[c] * molecules[c].molecular_weight
                        for c in test_counts
                        if c in molecules
                    )
                    test_wt = self._calculate_actual_wt(test_counts, molecules, test_mass)
                    test_error = self._calculate_l1_error(target_wt, test_wt)

                    if test_error < best_error:
                        best_counts = test_counts
                        best_mass = test_mass
                        best_error = test_error
                        improved = True

        return best_counts, best_mass

    def _calculate_actual_wt(
        self,
        mol_counts: dict[str, int],
        molecules: dict[str, MoleculeInfo],
        total_mass: float,
    ) -> dict[str, float]:
        """Calculate actual wt% from molecule counts."""
        if total_mass == 0:
            return dict.fromkeys(mol_counts, 0.0)

        actual_wt = {}
        for cat, count in mol_counts.items():
            if cat in molecules:
                mass = count * molecules[cat].molecular_weight
                actual_wt[cat] = (mass / total_mass) * 100.0
            else:
                actual_wt[cat] = 0.0

        return actual_wt

    def _calculate_l1_error(
        self,
        target_wt: dict[str, float],
        actual_wt: dict[str, float],
    ) -> float:
        """Calculate L1 error between target and actual compositions."""
        error = 0.0
        all_cats = set(target_wt.keys()) | set(actual_wt.keys())

        for cat in all_cats:
            target = target_wt.get(cat, 0.0)
            actual = actual_wt.get(cat, 0.0)
            error += abs(target - actual)

        return error

    def get_detailed_allocation(
        self,
        result: CompositionResult,
        molecules: dict[str, MoleculeInfo],
    ) -> list[MoleculeAllocation]:
        """
        Get detailed allocation information.

        Args:
            result: Composition calculation result
            molecules: Molecule info dictionary

        Returns:
            List of detailed allocations
        """
        allocations = []

        for cat, count in result.mol_counts.items():
            if cat in molecules:
                mol = molecules[cat]
                mass = count * mol.molecular_weight
                allocations.append(
                    MoleculeAllocation(
                        mol_id=mol.mol_id,
                        category=cat,
                        target_wt_pct=result.target_wt.get(cat, 0.0),
                        count=count,
                        actual_mass=mass,
                        actual_wt_pct=result.actual_wt.get(cat, 0.0),
                        atoms=count * mol.atom_count,
                    )
                )

        return allocations
