"""Dependency policy for chained job submission."""

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class DependencyPolicy:
    """Central policy for dependency graph and scheduler behavior."""

    enforce_acyclic_graph: bool = True
    auto_submit_when_ready: bool = True
    max_dependents_per_parent: int = 32
    allowed_parent_terminal_states: tuple[str, ...] = ("completed",)
    blocked_parent_states: tuple[str, ...] = ("failed", "cancelled", "timeout")


DEFAULT_DEPENDENCY_POLICY: Final[DependencyPolicy] = DependencyPolicy()
