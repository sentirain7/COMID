"""
Property-based binder design policy — SSOT for budget guardrails.

Controls iteration limits, candidate counts, simulation approval gates,
and wall-time caps for the property design closed-loop workflow.
"""

from pydantic import BaseModel, Field


class PropertyDesignPolicy(BaseModel):
    """Budget and safety guardrails for property-based binder design."""

    max_candidates_per_search: int = Field(
        5, description="Maximum candidates returned per search round"
    )
    max_simulation_candidates: int = Field(
        3, description="Maximum candidates submitted for simulation per iteration"
    )
    max_wall_time_hours_per_candidate: float = Field(
        24.0, description="Wall-time cap per candidate simulation (hours)"
    )
    max_concurrent_design_jobs: int = Field(
        2, description="Maximum concurrent design simulation jobs"
    )
    max_iterations: int = Field(5, description="Maximum additive swap iterations before stopping")
    require_user_approval_before_sim: bool = Field(
        True, description="Gate: require user approval before queuing simulations"
    )
    auto_promote_to_confirm: bool = Field(
        False, description="Auto-promote screening results to confirm tier"
    )


DEFAULT_PROPERTY_DESIGN_POLICY = PropertyDesignPolicy()
