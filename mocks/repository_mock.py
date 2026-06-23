"""
Mock experiment repository for testing.

Implements IExperimentRepository interface with in-memory storage.
"""

import sys

sys.path.insert(0, "src")


from contracts.interfaces import IExperimentRepository
from contracts.schemas import ExperimentRecord, ExperimentStatus


class MockExperimentRepository(IExperimentRepository):
    """Mock implementation of experiment repository with in-memory storage."""

    def __init__(self, fail_on_save: bool = False):
        """
        Initialize mock repository.

        Args:
            fail_on_save: If True, raise error on save
        """
        self.fail_on_save = fail_on_save
        self.experiments: dict[str, ExperimentRecord] = {}
        self.save_count = 0

    def save(self, record) -> str:
        """
        Save experiment record.

        Args:
            record: Experiment record to save (can be dict or Pydantic model)

        Returns:
            Experiment ID
        """
        self.save_count += 1

        if self.fail_on_save:
            raise RuntimeError("Mock repository save failure")

        # Handle both dict and Pydantic model (like real repository)
        if isinstance(record, dict):
            exp_id = record.get("exp_id")
            self.experiments[exp_id] = record
            return exp_id
        else:
            self.experiments[record.exp_id] = record
            return record.exp_id

    def get(self, exp_id: str) -> ExperimentRecord | None:
        """
        Get experiment by ID.

        Args:
            exp_id: Experiment ID

        Returns:
            Experiment record or None
        """
        return self.experiments.get(exp_id)

    def update_status(self, exp_id: str, status: str) -> None:
        """
        Update experiment status.

        Args:
            exp_id: Experiment ID
            status: New status
        """
        if exp_id in self.experiments:
            record = self.experiments[exp_id]
            # Create new record with updated status
            updated = record.model_copy(update={"status": ExperimentStatus(status)})
            self.experiments[exp_id] = updated

    def find_by_status(self, status: str) -> list[ExperimentRecord]:
        """
        Find experiments by status.

        Args:
            status: Status to filter by

        Returns:
            List of matching experiments
        """
        return [exp for exp in self.experiments.values() if exp.status.value == status]

    def find_by_tier(self, tier: str) -> list[ExperimentRecord]:
        """
        Find experiments by run tier.

        Args:
            tier: Tier to filter by

        Returns:
            List of matching experiments
        """
        return [exp for exp in self.experiments.values() if exp.run_tier.value == tier]

    def list_all(self) -> list[ExperimentRecord]:
        """List all experiments."""
        return list(self.experiments.values())

    def count(self) -> int:
        """Count total experiments."""
        return len(self.experiments)

    def clear(self) -> None:
        """Clear all experiments."""
        self.experiments.clear()
        self.save_count = 0

    def reset(self) -> None:
        """Reset mock state."""
        self.clear()
        self.fail_on_save = False
