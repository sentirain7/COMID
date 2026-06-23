"""GPU domain types for orchestrator service."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class GPUStatus(StrEnum):
    """GPU status enum."""

    AVAILABLE = "available"
    BUSY = "busy"
    RESERVED = "reserved"
    ERROR = "error"
    OFFLINE = "offline"


@dataclass
class GPUInfo:
    """GPU information in in-memory cache."""

    gpu_id: int
    name: str = "Unknown"
    status: GPUStatus = GPUStatus.AVAILABLE
    current_task_id: str | None = None
    current_exp_id: str | None = None
    memory_used_gb: float = 0.0
    memory_total_gb: float = 0.0
    utilization_pct: float = 0.0
    temperature_c: float = 0.0
    allocated_at: datetime | None = None
    last_updated: datetime | None = None
    # Hardware identity + eligibility (from enumerate_compute_devices). uuid is
    # the routing SSOT; eligible=False marks a sub-threshold GPU (e.g. RTX 3050)
    # that is still shown/selectable but gets a reduced per-device slot cap.
    uuid: str | None = None
    eligible: bool = True
    kind: str = "whole_gpu"
    # Per-device job slots (mode-aware: MPS N, MIG instance 1, sub-threshold 1).
    # 0 = unknown (callers fall back to the policy value).
    slots: int = 0
    # 다중잡(N슬롯) 동시 할당 목록 — [{"task_id": ..., "exp_id": ...}, ...].
    # current_task_id/current_exp_id는 첫 항목의 호환 별칭으로 유지(표시·구버전).
    active_jobs: list[dict] = field(default_factory=list)

    @property
    def current_job_id(self) -> str | None:
        """GPUResourceTracker compatibility alias for current_task_id."""
        return self.current_task_id

    @current_job_id.setter
    def current_job_id(self, value: str | None) -> None:
        self.current_task_id = value

    @property
    def utilization_percent(self) -> float:
        """GPUResourceTracker compatibility alias for utilization_pct."""
        return self.utilization_pct

    @utilization_percent.setter
    def utilization_percent(self, value: float) -> None:
        self.utilization_pct = value

    @property
    def memory_free_gb(self) -> float:
        """GPUResourceTracker compatibility helper."""
        return self.memory_total_gb - self.memory_used_gb

    @property
    def is_available(self) -> bool:
        """GPUResourceTracker compatibility helper."""
        return self.status == GPUStatus.AVAILABLE

    def set_jobs(self, jobs: list[dict]) -> None:
        """Replace the active job list and keep compat aliases in sync."""
        self.active_jobs = list(jobs)
        first = self.active_jobs[0] if self.active_jobs else {}
        self.current_task_id = first.get("task_id")
        self.current_exp_id = first.get("exp_id")
