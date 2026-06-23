"""
Experiment status transition policy (SSOT).
"""

from __future__ import annotations

from contracts.errors import ContractError, ErrorCode

# Allowed transitions for experiment lifecycle states.
ALLOWED_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"queued", "building", "ready", "running", "failed", "cancelled", "timeout"},
    "queued": {"pending", "building", "ready", "failed", "cancelled", "timeout"},
    "building": {"queued", "ready", "failed", "cancelled", "timeout"},
    "ready": {"queued", "running", "failed", "cancelled", "timeout"},
    "running": {"pending", "analyzing", "completed", "failed", "cancelled", "timeout"},
    "analyzing": {"completed", "failed", "cancelled", "timeout"},
    # Terminal states can be reset only through explicit requeue flows.
    "completed": {"pending", "queued"},
    "failed": {"pending", "queued"},
    "cancelled": {"pending", "queued"},
    "timeout": {"pending", "queued"},
}


def ensure_valid_experiment_transition(from_status: str, to_status: str) -> None:
    """
    Validate experiment status transition.

    Raises:
        ContractError: If transition is not allowed.
    """
    src = (from_status or "").lower().strip()
    dst = (to_status or "").lower().strip()

    if not src or not dst:
        raise ContractError(
            ErrorCode.INVALID_STATE_TRANSITION,
            "Experiment status transition requires both source and destination states",
            {"from_status": from_status, "to_status": to_status},
        )

    if src == dst:
        return

    allowed = ALLOWED_STATUS_TRANSITIONS.get(src, set())
    if dst not in allowed:
        raise ContractError(
            ErrorCode.INVALID_STATE_TRANSITION,
            f"Invalid experiment status transition: {src} -> {dst}",
            {"from_status": src, "to_status": dst, "allowed": sorted(allowed)},
        )
