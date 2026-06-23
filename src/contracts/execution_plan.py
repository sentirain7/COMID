"""Compiled execution plan models for canonical stage/progress handling."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CompiledStage(BaseModel):
    """Resolved stage information used for execution preview and progress tracking."""

    stage_key: str
    type: str
    duration_ps: float | None = None
    duration_steps: int | None = None
    expected_steps: int = Field(0, ge=0)
    cumulative_steps: int = Field(0, ge=0)
    parameters: dict = Field(default_factory=dict)
    display_name: str | None = None
    short_name: str | None = None
    color: str | None = None


class CompiledExecutionPlan(BaseModel):
    """Immutable execution plan derived from a request plus validated overrides."""

    chain_key: str
    base_tier: str
    stages: list[CompiledStage] = Field(default_factory=list)
    total_steps: int = Field(0, ge=0)
    total_duration_ps: float = Field(0.0, ge=0)
    dt_fs: float = Field(1.0, gt=0)
    compiled_at: str
    plan_hash: str
