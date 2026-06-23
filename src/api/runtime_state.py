"""Runtime state for API process-level services."""

_process_tracker = None
_recovery_service = None


def set_recovery_components(process_tracker, recovery_service) -> None:
    """Set process-tracker and recovery-service singletons."""
    global _process_tracker, _recovery_service
    _process_tracker = process_tracker
    _recovery_service = recovery_service


def clear_recovery_components() -> None:
    """Clear runtime recovery singletons during shutdown."""
    global _process_tracker, _recovery_service
    _process_tracker = None
    _recovery_service = None


def get_process_tracker():
    """Get the global ProcessTracker instance."""
    return _process_tracker


def get_recovery_service():
    """Get the global ProcessRecoveryService instance."""
    return _recovery_service
