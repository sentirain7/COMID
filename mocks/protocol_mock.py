"""
Mock protocol generator for testing.

Implements IProtocolGenerator interface with mock data.
"""

import sys

sys.path.insert(0, "src")

from common.hashing import compute_protocol_hash
from contracts.interfaces import IProtocolGenerator
from contracts.policies.stabilization import DEFAULT_STABILIZATION_CHAIN
from contracts.schemas import ProtocolRequest, ProtocolResult


class MockProtocolGenerator(IProtocolGenerator):
    """Mock implementation of protocol generator."""

    def __init__(self, fail_on_call: int = -1):
        """
        Initialize mock protocol generator.

        Args:
            fail_on_call: Fail on this call number (-1 = never fail)
        """
        self.call_count = 0
        self.fail_on_call = fail_on_call
        self.generate_history: list[ProtocolRequest] = []
        self.stabilization_chain = DEFAULT_STABILIZATION_CHAIN

    def generate(self, request: ProtocolRequest, **kwargs) -> ProtocolResult:
        """
        Mock protocol generation.

        Args:
            request: Protocol request
            **kwargs: Additional keyword arguments (e.g. stage_duration_overrides)

        Returns:
            Mock protocol result
        """
        self.call_count += 1
        self.generate_history.append(request)

        if self.fail_on_call == self.call_count:
            raise RuntimeError("Mock protocol generator failure")

        tier = request.run_tier.value
        chain_steps = self.stabilization_chain.get_step_names(tier)
        protocol_hash = self.get_protocol_hash(tier)

        # Estimate steps based on tier
        estimated_steps = self.stabilization_chain.get_estimated_steps(tier, dt_fs=1.0)

        return ProtocolResult(
            input_script_path=f"/mock/experiments/in.{tier}.lammps",
            expected_outputs=[
                f"log.{tier}.lammps",
                f"dump.{tier}.lammpstrj",
                f"restart.{tier}.lammps",
            ],
            estimated_steps=estimated_steps,
            protocol_hash=protocol_hash,
            stabilization_chain=chain_steps,
        )

    def get_protocol_hash(self, tier: str) -> str:
        """Get protocol hash for tier."""
        chain = self.stabilization_chain.get_chain(tier)
        chain_dicts = [step.model_dump() for step in chain]
        return compute_protocol_hash(
            tier=tier,
            stabilization_steps=chain_dicts,
            ff_type="bulk_ff",
            temperature_k=298.0,
            pressure_atm=1.0,
        )

    def get_stabilization_chain(self, tier: str) -> list[str]:
        """Get stabilization step names."""
        return self.stabilization_chain.get_step_names(tier)

    def reset(self) -> None:
        """Reset mock state."""
        self.call_count = 0
        self.generate_history.clear()
