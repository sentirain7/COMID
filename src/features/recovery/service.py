"""Recovery feature service."""

from __future__ import annotations

from api.runtime_state import get_process_tracker, get_recovery_service
from api.schemas import ExecuteRecoveryRequest, RecoveryCheckResponse
from common.logging import get_logger
from contracts.errors import ContractError, ErrorCode, OrchestrationError
from contracts.schemas import RecoveryAction, RecoveryCandidate, RecoveryResult

logger = get_logger("features.recovery")


async def check_recovery_status() -> RecoveryCheckResponse:
    """Quick check if recovery dialog should be shown."""
    recovery_service = get_recovery_service()
    if recovery_service is None:
        return RecoveryCheckResponse(
            needs_recovery=False,
            candidate_count=0,
            message="Recovery service not initialized",
        )

    try:
        candidates = recovery_service.check_for_recovery_needed()
        needs_recovery = len(candidates) > 0
        return RecoveryCheckResponse(
            needs_recovery=needs_recovery,
            candidate_count=len(candidates),
            message=(
                f"Found {len(candidates)} candidate(s) for recovery"
                if needs_recovery
                else "No recovery needed"
            ),
        )
    except Exception as exc:
        logger.error(f"Recovery check failed: {exc}")
        return RecoveryCheckResponse(
            needs_recovery=False,
            candidate_count=0,
            message=f"Error checking recovery status: {str(exc)}",
        )


async def get_recovery_candidates() -> list[RecoveryCandidate]:
    """Get list of processes/experiments needing recovery."""
    recovery_service = get_recovery_service()
    if recovery_service is None:
        raise OrchestrationError(ErrorCode.SERVICE_UNAVAILABLE, "Recovery service not initialized")

    try:
        return recovery_service.check_for_recovery_needed()
    except Exception as exc:
        logger.error(f"Failed to get recovery candidates: {exc}")
        raise OrchestrationError(
            ErrorCode.ORCHESTRATION_ERROR,
            "Failed to get recovery candidates",
            {"reason": str(exc)},
        ) from exc


async def execute_recovery_action(request: ExecuteRecoveryRequest) -> RecoveryResult:
    """Execute a recovery action for a specific experiment."""
    recovery_service = get_recovery_service()
    if recovery_service is None:
        raise OrchestrationError(ErrorCode.SERVICE_UNAVAILABLE, "Recovery service not initialized")

    try:
        action = RecoveryAction(request.action)
    except ValueError as exc:
        valid_actions = [a.value for a in RecoveryAction]
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            f"Invalid action. Must be one of: {valid_actions}",
            {"action": request.action},
        ) from exc

    try:
        return recovery_service.execute_recovery(request.exp_id, action)
    except Exception as exc:
        logger.error(f"Recovery execution failed: {exc}")
        raise OrchestrationError(
            ErrorCode.ORCHESTRATION_ERROR,
            "Recovery execution failed",
            {"exp_id": request.exp_id, "reason": str(exc)},
        ) from exc


async def execute_all_recommended() -> list[RecoveryResult]:
    """Execute recommended recovery action for all candidates."""
    recovery_service = get_recovery_service()
    if recovery_service is None:
        raise OrchestrationError(ErrorCode.SERVICE_UNAVAILABLE, "Recovery service not initialized")

    try:
        return recovery_service.execute_all_recommended()
    except Exception as exc:
        logger.error(f"Batch recovery failed: {exc}")
        raise OrchestrationError(
            ErrorCode.ORCHESTRATION_ERROR,
            "Batch recovery failed",
            {"reason": str(exc)},
        ) from exc


async def cleanup_stale_records() -> dict[str, object]:
    """Clean up stale process records."""
    process_tracker = get_process_tracker()
    if process_tracker is None:
        raise OrchestrationError(ErrorCode.SERVICE_UNAVAILABLE, "Process tracker not initialized")

    try:
        cleaned = process_tracker.cleanup_stale_records()
        return {"cleaned": cleaned, "message": f"Cleaned up {cleaned} stale records"}
    except Exception as exc:
        logger.error(f"Cleanup failed: {exc}")
        raise OrchestrationError(
            ErrorCode.ORCHESTRATION_ERROR,
            "Cleanup failed",
            {"reason": str(exc)},
        ) from exc
