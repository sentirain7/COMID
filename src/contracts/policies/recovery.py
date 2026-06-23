"""
Process recovery policy - SSOT for LAMMPS process persistence and recovery.

Defines constants and rules for tracking LAMMPS processes across restarts
and recovering from orphaned/stale states.
"""

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class ProcessRecoveryPolicy:
    """
    Policy for LAMMPS process tracking and recovery.

    This policy defines timeouts, thresholds, and decision rules
    for detecting and recovering orphaned LAMMPS processes.
    """

    # Heartbeat configuration
    heartbeat_interval_seconds: int = 30
    heartbeat_timeout_minutes: int = 30

    # Auto-recovery settings
    auto_recovery_max_retries: int = 2
    min_progress_for_result_recovery: float = 30.0  # percent

    # PID file configuration
    pid_file_pattern: str = ".lammps.{exp_id}.pid"
    pid_directory: str = ".pids"

    # Process scanning
    process_scan_interval_seconds: int = 60
    stale_threshold_minutes: int = 5

    # Orphan ready-allocation recovery grace window.
    # A status=ready row that holds a GPU allocation but is younger than this is
    # NOT reclaimed. The celery inspect() snapshot used by orphan recovery can
    # MISS a freshly-dispatched-but-not-yet-active task under load (prefetch=1 +
    # acks_late); without a grace window, recovery would release that task's GPU
    # and re-trigger the dispatcher, causing re-dispatch churn (and re-issuing a
    # new dispatch token each round). Mirrors the v01.06.09 queued-job grace fix.
    orphan_ready_grace_seconds: int = 90

    # Server instance tracking
    server_instance_id_length: int = 8

    # Checkpoint configuration for periodic restart file writing
    # This enables recovery from long-running simulations that crash mid-run
    checkpoint_interval_ps: int = 100  # Write checkpoint every 100 ps
    checkpoint_interval_steps: int = 100000  # Equivalent in steps (dt=1.0fs)
    enable_periodic_checkpoint: bool = True  # Enable periodic checkpointing

    def should_auto_resume(self, state: str, progress: float) -> bool:
        """
        Determine if a process should be automatically resumed.

        Args:
            state: Current process state
            progress: Simulation progress percentage

        Returns:
            True if automatic resume is recommended
        """
        return state == "stale" and progress > 50.0

    def should_recover_results(self, state: str, progress: float) -> bool:
        """
        Determine if partial results should be recovered.

        Args:
            state: Current process state
            progress: Simulation progress percentage

        Returns:
            True if result recovery is recommended
        """
        return state == "terminated" and progress >= self.min_progress_for_result_recovery

    def get_recommended_action(self, state: str, progress: float) -> str:
        """
        Get recommended recovery action for a given state.

        Args:
            state: Current process state
            progress: Simulation progress percentage

        Returns:
            Recommended RecoveryAction value
        """
        if state == "running":
            return "resume"
        elif state == "stale":
            if progress > 50.0:
                return "resume"
            else:
                return "restart"
        elif state == "terminated":
            if progress >= self.min_progress_for_result_recovery:
                return "recover"
            else:
                return "restart"
        elif state == "orphaned":
            return "abandon"
        else:
            return "ignore"

    def get_available_actions(self, state: str) -> list[str]:
        """
        Get list of valid actions for a given state.

        Args:
            state: Current process state

        Returns:
            List of valid RecoveryAction values
        """
        if state == "running":
            return ["resume", "restart", "abandon"]
        elif state == "stale":
            return ["resume", "restart", "abandon"]
        elif state == "terminated":
            return ["recover", "restart", "abandon"]
        elif state == "orphaned":
            return ["abandon", "ignore"]
        else:
            return ["ignore"]


# Default policy instance
DEFAULT_RECOVERY_POLICY: Final[ProcessRecoveryPolicy] = ProcessRecoveryPolicy()
