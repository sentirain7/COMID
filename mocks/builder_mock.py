"""
Mock structure builder for testing.

Implements IStructureBuilder interface with mock data.
"""

import sys

sys.path.insert(0, "src")

from common.hashing import compute_composition_hash
from contracts.interfaces import IStructureBuilder
from contracts.schemas import BuildRequest, BuildResult


class MockBuilder(IStructureBuilder):
    """Mock implementation of structure builder."""

    def __init__(self, fail_on_call: int = -1):
        """
        Initialize mock builder.

        Args:
            fail_on_call: Fail on this call number (-1 = never fail)
        """
        self.call_count = 0
        self.fail_on_call = fail_on_call
        self.build_history: list[BuildRequest] = []

    def build(self, request: BuildRequest) -> BuildResult:
        """
        Mock structure building.

        Args:
            request: Build request

        Returns:
            Mock build result
        """
        self.call_count += 1
        self.build_history.append(request)

        if self.fail_on_call == self.call_count:
            raise RuntimeError("Mock builder failure: Lost atoms during packing")

        # Calculate mock "actual" composition (small random variation)
        # Keep L1 error under 1.0 wt% (max 0.2% per component for 4 components)
        actual_comp = {}
        for key, value in request.composition.items():
            # Add small variation (-0.2% to +0.2%)
            variation = (hash(f"{key}{request.seed}") % 100 - 50) / 250.0
            actual_comp[key] = value + variation

        # Normalize to 100%
        total = sum(actual_comp.values())
        actual_comp = {k: v * 100.0 / total for k, v in actual_comp.items()}

        # Calculate L1 error (should be < 1.0)
        error_l1 = sum(
            abs(request.composition[k] - actual_comp.get(k, 0)) for k in request.composition
        )

        # Generate topology hash
        topo_hash = compute_composition_hash(
            request.composition, request.target_atoms, request.seed
        )

        # Calculate actual atoms (within tolerance)
        atom_variation = (hash(f"atoms{request.seed}") % 100 - 50) / 1000.0
        actual_atoms = int(request.target_atoms * (1 + atom_variation))

        return BuildResult(
            data_file_path=f"/mock/experiments/exp_{request.seed}/input/data.lammps",
            actual_atoms=actual_atoms,
            actual_density=request.initial_density * (1 + atom_variation / 10),
            topology_hash=topo_hash,
            packmol_version="mock-20.14.0",
            actual_composition_wt=actual_comp,
            composition_error_l1=error_l1,
            target_composition_wt=request.composition,
            min_distance_violation_count=0,
            initial_pe_per_atom=-5.5,
            stability_flag=None,
        )

    def validate_packing(self, data_file_path: str) -> dict:
        """Mock packing validation."""
        return {
            "valid": True,
            "min_distance_violations": 0,
            "overlap_atoms": [],
        }

    def reset(self) -> None:
        """Reset mock state."""
        self.call_count = 0
        self.build_history.clear()
