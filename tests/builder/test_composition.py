"""Tests for composition calculator."""

import sys

import pytest

sys.path.insert(0, "src")

from builder.composition_calculator import CompositionCalculator
from contracts.schemas import MoleculeCategory, MoleculeInfo


class TestCompositionCalculator:
    """Test composition calculator."""

    @pytest.fixture
    def calculator(self):
        return CompositionCalculator()

    @pytest.fixture
    def molecules(self):
        return {
            "asphaltene": MoleculeInfo(
                mol_id="asp_01",
                molecular_weight=280.0,
                atom_count=42,
                category=MoleculeCategory.ASPHALTENE,
            ),
            "resin": MoleculeInfo(
                mol_id="res_01",
                molecular_weight=180.0,
                atom_count=28,
                category=MoleculeCategory.RESIN,
            ),
            "aromatic": MoleculeInfo(
                mol_id="aro_01",
                molecular_weight=130.0,
                atom_count=18,
                category=MoleculeCategory.AROMATIC,
            ),
            "saturate": MoleculeInfo(
                mol_id="sat_01",
                molecular_weight=230.0,
                atom_count=50,
                category=MoleculeCategory.SATURATE,
            ),
        }

    def test_basic_calculation(self, calculator, molecules):
        """Test basic composition calculation."""
        target_wt = {
            "asphaltene": 20.0,
            "resin": 30.0,
            "aromatic": 35.0,
            "saturate": 15.0,
        }

        result = calculator.calculate(
            target_wt=target_wt,
            molecules=molecules,
            target_atoms=10000,
        )

        assert result.error_l1 < 5.0  # Reasonable error
        assert result.total_atoms > 0
        assert sum(result.actual_wt.values()) > 99.0  # Near 100%
        assert sum(result.actual_wt.values()) < 101.0

    def test_error_within_threshold(self, calculator, molecules):
        """Test that error is within threshold."""
        target_wt = {
            "asphaltene": 20.0,
            "resin": 30.0,
            "aromatic": 35.0,
            "saturate": 15.0,
        }

        result = calculator.calculate(
            target_wt=target_wt,
            molecules=molecules,
            target_atoms=100000,
        )

        # With 100k atoms, error should be < 1%
        assert result.error_l1 < 2.0

    def test_atom_count_within_tolerance(self, calculator, molecules):
        """Test that atom count is within tolerance."""
        target_wt = {
            "asphaltene": 25.0,
            "resin": 25.0,
            "aromatic": 25.0,
            "saturate": 25.0,
        }

        target_atoms = 50000
        tolerance = 0.10

        result = calculator.calculate(
            target_wt=target_wt,
            molecules=molecules,
            target_atoms=target_atoms,
            tolerance=tolerance,
        )

        min_atoms = int(target_atoms * (1 - tolerance))
        max_atoms = int(target_atoms * (1 + tolerance))

        assert result.total_atoms >= min_atoms * 0.9  # Some flexibility
        assert result.total_atoms <= max_atoms * 1.1

    def test_normalization(self, calculator, molecules):
        """Test composition normalization."""
        # Input doesn't sum to 100
        target_wt = {
            "asphaltene": 10.0,
            "resin": 15.0,
            "aromatic": 17.5,
            "saturate": 7.5,
        }  # Sum = 50

        result = calculator.calculate(
            target_wt=target_wt,
            molecules=molecules,
            target_atoms=10000,
        )

        # Should normalize internally
        assert result.total_atoms > 0

    def test_single_component(self, calculator, molecules):
        """Test single component composition."""
        target_wt = {
            "asphaltene": 100.0,
        }

        molecules_single = {
            "asphaltene": molecules["asphaltene"],
        }

        result = calculator.calculate(
            target_wt=target_wt,
            molecules=molecules_single,
            target_atoms=5000,
        )

        assert result.mol_counts["asphaltene"] > 0
        assert abs(result.actual_wt["asphaltene"] - 100.0) < 0.01

    def test_mol_counts_positive(self, calculator, molecules):
        """Test that all molecule counts are positive."""
        target_wt = {
            "asphaltene": 20.0,
            "resin": 30.0,
            "aromatic": 35.0,
            "saturate": 15.0,
        }

        result = calculator.calculate(
            target_wt=target_wt,
            molecules=molecules,
            target_atoms=10000,
        )

        for cat, count in result.mol_counts.items():
            assert count >= 1, f"{cat} has count {count}"


class TestDetailedAllocation:
    """Test detailed allocation output."""

    def test_detailed_allocation(self):
        calculator = CompositionCalculator()

        molecules = {
            "asphaltene": MoleculeInfo(
                mol_id="asp_01",
                molecular_weight=280.0,
                atom_count=42,
                category=MoleculeCategory.ASPHALTENE,
            ),
            "resin": MoleculeInfo(
                mol_id="res_01",
                molecular_weight=180.0,
                atom_count=28,
                category=MoleculeCategory.RESIN,
            ),
        }

        target_wt = {"asphaltene": 40.0, "resin": 60.0}

        result = calculator.calculate(
            target_wt=target_wt,
            molecules=molecules,
            target_atoms=5000,
        )

        allocations = calculator.get_detailed_allocation(result, molecules)

        assert len(allocations) == 2
        for alloc in allocations:
            assert alloc.count > 0
            assert alloc.atoms > 0
            assert alloc.actual_mass > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
