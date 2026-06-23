"""
Celery job data types.

Extracted from celery_job_manager.py for reuse across orchestrator modules.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from contracts.policies.budget import JobPriority
from contracts.schemas import BuildRequest, ProtocolRequest

if TYPE_CHECKING:
    from protocols.duration_adjuster import StageDurationOverride


class CeleryJobStatus(StrEnum):
    """Job status mapping to Celery states (lowercase for frontend compatibility)."""

    PENDING = "pending"
    QUEUED = "queued"
    STARTED = "running"
    RUNNING = "running"
    SUCCESS = "completed"
    FAILURE = "failed"
    REVOKED = "cancelled"
    RETRY = "retry"


@dataclass
class CeleryJob:
    """Celery job representation."""

    job_id: str
    task_id: str  # Celery task ID
    build_request: BuildRequest
    protocol_request: ProtocolRequest
    material_id: str

    status: CeleryJobStatus = CeleryJobStatus.PENDING
    priority: JobPriority = JobPriority.MEDIUM
    queue: str = "simulation"
    gpu_id: int | None = None

    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    result_exp_id: str | None = None
    error_message: str | None = None
    retry_count: int = 0

    # Stage duration overrides (optional, from user input)
    stage_duration_overrides: list["StageDurationOverride"] | None = None


@dataclass
class CeleryJobStats:
    """Celery job queue statistics."""

    total_pending: int = 0
    total_running: int = 0
    total_completed: int = 0
    total_failed: int = 0

    active_workers: int = 0
    reserved_tasks: int = 0
    scheduled_tasks: int = 0

    jobs_by_tier: dict[str, int] = field(default_factory=dict)
    jobs_by_queue: dict[str, int] = field(default_factory=dict)
