"""
Process Tracker Service.

Manages persistence and recovery of LAMMPS process information across
server restarts. Tracks PIDs, heartbeats, and process state to enable
recovery of orphaned simulations.
"""

import socket
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import psutil

from common.logging import get_logger
from common.pathing import get_project_root
from contracts.policies.recovery import (
    DEFAULT_RECOVERY_POLICY,
    ProcessRecoveryPolicy,
)
from contracts.schemas import (
    ProcessInfo,
    ProcessState,
    RecoveryAction,
    RecoveryCandidate,
)

logger = get_logger("orchestrator.process_tracker")


class ProcessRegistrationConflict(RuntimeError):
    """A run cannot be registered because another run already owns this slot.

    Raised when a process registration would create a duplicate/conflicting lmp
    for an experiment — a live lmp is already registered for the exp on this
    host (different PID), or the passed GPU disagrees with the DB allocation
    SSOT. The caller (lammps_runner) MUST treat this as FATAL: kill the
    just-launched process and abort, so a duplicate lmp never survives. This is
    the last-line backstop behind the dispatcher single-flight lock and the
    atomic ready->running claim.
    """


def _is_live_lmp(pid: int) -> bool:
    """Best-effort: is ``pid`` a currently-alive LAMMPS process?

    Confirms the PID is alive AND looks like lmp/lammps, so a recycled PID does
    not cause a false conflict. Returns False on any uncertainty (fail-open:
    never block a legitimate run on a guess).
    """
    try:
        if not psutil.pid_exists(int(pid)):
            return False
        proc = psutil.Process(int(pid))
        name = (proc.name() or "").lower()
        if "lmp" in name or "lammps" in name:
            return True
        cmdline = " ".join(proc.cmdline() or []).lower()
        return "lmp" in cmdline or "lammps" in cmdline
    except Exception:
        return False


class ProcessTracker:
    """
    Tracks LAMMPS processes across server restarts.

    Provides:
    - Process registration/unregistration
    - Heartbeat updates
    - State detection (running, stale, orphaned, terminated)
    - Recovery candidate identification
    - PID file management
    """

    def __init__(
        self,
        policy: ProcessRecoveryPolicy | None = None,
    ) -> None:
        """
        Initialize process tracker.

        Args:
            policy: Recovery policy to use (defaults to DEFAULT_RECOVERY_POLICY)
        """
        self._policy = policy or DEFAULT_RECOVERY_POLICY
        self._hostname = socket.gethostname()
        self._server_instance_id = self._generate_instance_id()

        # Ensure PID directory exists
        self._pid_dir = get_project_root() / self._policy.pid_directory
        self._pid_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            f"ProcessTracker initialized on {self._hostname}, "
            f"instance_id={self._server_instance_id}"
        )

    def _generate_instance_id(self) -> str:
        """Generate unique server instance ID."""
        return uuid.uuid4().hex[: self._policy.server_instance_id_length]

    @property
    def hostname(self) -> str:
        """Get current hostname."""
        return self._hostname

    @property
    def server_instance_id(self) -> str:
        """Get current server instance ID."""
        return self._server_instance_id

    def register_process(
        self,
        exp_id: str,
        pid: int,
        hostname: str,
        working_dir: str,
        gpu_id: int | None = None,
        total_steps: int | None = None,
    ) -> None:
        """
        Register a new LAMMPS process.

        Args:
            exp_id: Experiment ID
            pid: OS process ID
            hostname: Machine hostname
            working_dir: Working directory path
            gpu_id: Allocated GPU ID
            total_steps: Total simulation steps
        """
        from database.connection import session_scope
        from database.models import ExperimentModel, ProcessInfoModel

        now = datetime.utcnow()

        # Write PID file
        pid_file = self._get_pid_file_path(exp_id)
        self._write_pid_file(pid_file, pid, hostname, working_dir)

        # Update database
        try:
            with session_scope() as session:
                from database.repositories.experiment_repo import ExperimentRepository

                # Create or update ProcessInfo record
                process_info = session.query(ProcessInfoModel).filter_by(exp_id=exp_id).first()

                # Live-duplicate backstop: if a DIFFERENT lmp for this exp is
                # already registered and still alive on this host, refuse — two
                # concurrent lmp for one experiment (the duplicate-lmp bug) must
                # not both survive registration. Confirmed-live-lmp only, so a
                # recycled PID never blocks a legitimate run.
                if (
                    process_info is not None
                    and process_info.pid
                    and int(process_info.pid) != int(pid)
                    and str(process_info.hostname or "") == str(hostname or "")
                    and _is_live_lmp(int(process_info.pid))
                ):
                    raise ProcessRegistrationConflict(
                        f"Process registration blocked for {exp_id}: a live lmp "
                        f"PID {process_info.pid} is already registered on "
                        f"{hostname} (new PID {pid}) — duplicate run rejected"
                    )

                if process_info:
                    process_info.pid = pid
                    process_info.hostname = hostname
                    process_info.working_dir = working_dir
                    process_info.gpu_id = gpu_id
                    process_info.started_at = now
                    process_info.last_heartbeat = now
                    process_info.total_steps = total_steps
                    process_info.server_instance_id = self._server_instance_id
                else:
                    process_info = ProcessInfoModel(
                        exp_id=exp_id,
                        pid=pid,
                        hostname=hostname,
                        working_dir=working_dir,
                        gpu_id=gpu_id,
                        started_at=now,
                        last_heartbeat=now,
                        total_steps=total_steps,
                        server_instance_id=self._server_instance_id,
                    )
                    session.add(process_info)

                # Update experiment record
                experiment = session.query(ExperimentModel).filter_by(exp_id=exp_id).first()
                if experiment:
                    experiment.lammps_pid = pid
                    experiment.lammps_hostname = hostname
                    experiment.lammps_start_time = now
                    experiment.lammps_working_dir = working_dir
                    # GPU allocation SSOT is GPUService.allocate_gpu().
                    # ProcessTracker must not overwrite gpu_id_allocated directly.
                    if gpu_id is not None:
                        allocated_gpu = getattr(experiment, "gpu_id_allocated", None)
                        if allocated_gpu is None:
                            raise ProcessRegistrationConflict(
                                f"Process registration blocked for {exp_id}: "
                                f"GPU {gpu_id} provided but DB allocation is empty"
                            )
                        if int(allocated_gpu) != int(gpu_id):
                            raise ProcessRegistrationConflict(
                                f"Process registration blocked for {exp_id}: "
                                f"GPU mismatch (db={allocated_gpu}, passed={gpu_id})"
                            )
                    experiment.last_heartbeat_at = now
                    # Best-effort status transition to "running".
                    # Must not block process registration / heartbeat if
                    # the current status does not allow this transition
                    # (e.g. building → running is blocked by state machine).
                    try:
                        ExperimentRepository(session).update_status(
                            exp_id,
                            "running",
                            attempt_id=getattr(experiment, "active_attempt_id", None)
                            or getattr(experiment, "celery_task_id", None),
                        )
                    except Exception as status_exc:
                        logger.debug(
                            "register_process: status transition to running skipped for %s: %s",
                            exp_id,
                            status_exc,
                        )
                    # Set log_file_path for real-time monitoring
                    if working_dir:
                        from pathlib import Path

                        log_path = Path(working_dir) / "log.lammps"
                        experiment.log_file_path = str(log_path)

                session.commit()
                logger.info(
                    f"Registered process: exp_id={exp_id}, pid={pid}, host={hostname}, gpu={gpu_id}"
                )
        except Exception as e:
            logger.error(f"Failed to register process {exp_id}: {e}")
            raise

    def unregister_process(self, exp_id: str) -> None:
        """
        Unregister a completed/failed process.

        Args:
            exp_id: Experiment ID
        """
        from database.connection import session_scope
        from database.models import ProcessInfoModel

        # Remove PID file
        pid_file = self._get_pid_file_path(exp_id)
        self._remove_pid_file(pid_file)

        # Remove from database
        try:
            with session_scope() as session:
                process_info = session.query(ProcessInfoModel).filter_by(exp_id=exp_id).first()
                if process_info:
                    session.delete(process_info)
                    session.commit()
                    logger.info(f"Unregistered process: exp_id={exp_id}")
        except Exception as e:
            logger.error(f"Failed to unregister process {exp_id}: {e}")

    def update_heartbeat(
        self,
        exp_id: str,
        current_step: int | None = None,
        pid: int | None = None,
        temperature: float | None = None,
        pressure: float | None = None,
        density: float | None = None,
        energy: float | None = None,
    ) -> None:
        """
        Update process heartbeat.

        Args:
            exp_id: Experiment ID
            current_step: Current simulation step (optional)
            pid: Process ID to guard against stale heartbeat updates
            temperature: Latest temperature from runtime log (optional)
            pressure: Latest pressure from runtime log (optional)
            density: Latest density from runtime log (optional)
            energy: Latest potential energy from runtime log (optional)
        """
        from database.connection import session_scope
        from database.models import ExperimentModel, ProcessInfoModel

        now = datetime.utcnow()

        try:
            with session_scope() as session:
                process_info = session.query(ProcessInfoModel).filter_by(exp_id=exp_id).first()
                if process_info:
                    if pid is not None and process_info.pid != pid:
                        # Ignore stale heartbeat from a superseded process.
                        return
                    process_info.last_heartbeat = now
                    if current_step is not None:
                        process_info.current_step = current_step
                    process_info.temperature = temperature
                    process_info.pressure = pressure
                    process_info.density = density
                    process_info.energy = energy

                experiment = session.query(ExperimentModel).filter_by(exp_id=exp_id).first()
                if experiment:
                    experiment.last_heartbeat_at = now

                session.commit()
        except Exception as e:
            logger.warning(f"Failed to update heartbeat for {exp_id}: {e}")

    def get_process_info(self, exp_id: str) -> ProcessInfo | None:
        """
        Get process info for an experiment.

        Args:
            exp_id: Experiment ID

        Returns:
            ProcessInfo if found, None otherwise
        """
        from database.connection import session_scope
        from database.models import ProcessInfoModel

        try:
            with session_scope() as session:
                record = session.query(ProcessInfoModel).filter_by(exp_id=exp_id).first()
                if record:
                    return ProcessInfo(
                        exp_id=record.exp_id,
                        pid=record.pid,
                        hostname=record.hostname,
                        working_dir=record.working_dir,
                        gpu_id=record.gpu_id,
                        started_at=record.started_at,
                        last_heartbeat=record.last_heartbeat,
                        current_step=record.current_step,
                        total_steps=record.total_steps,
                        temperature=record.temperature,
                        pressure=record.pressure,
                        density=record.density,
                        energy=record.energy,
                    )
        except Exception as e:
            logger.error(f"Failed to get process info for {exp_id}: {e}")
        return None

    def detect_process_state(
        self,
        exp_id: str,
        pid: int,
        hostname: str,
    ) -> ProcessState:
        """
        Detect the current state of a process.

        Args:
            exp_id: Experiment ID
            pid: Process ID
            hostname: Expected hostname

        Returns:
            Detected ProcessState
        """
        # Check if this is a remote host
        if hostname != self._hostname:
            logger.debug(f"Process {exp_id} on remote host {hostname}")
            return ProcessState.UNKNOWN

        # Check if process exists
        try:
            process = psutil.Process(pid)
            if process.is_running():
                # Check if it's actually LAMMPS
                cmdline = " ".join(process.cmdline())
                if "lmp" in cmdline.lower() or "lammps" in cmdline.lower():
                    return ProcessState.RUNNING
                else:
                    # PID reused by different process
                    return ProcessState.TERMINATED
            else:
                return ProcessState.TERMINATED
        except psutil.NoSuchProcess:
            return ProcessState.TERMINATED
        except psutil.AccessDenied:
            # Cannot access process - assume it's running
            logger.warning(f"Access denied for PID {pid}")
            return ProcessState.UNKNOWN
        except Exception as e:
            logger.error(f"Error checking process {pid}: {e}")
            return ProcessState.UNKNOWN

    def detect_orphaned_processes(self) -> list[RecoveryCandidate]:
        """
        Detect processes that need recovery.

        Scans for:
        - PID files without matching DB records (orphaned)
        - DB records with stale heartbeats
        - Running experiments with terminated processes

        Returns:
            List of recovery candidates
        """
        from database.connection import session_scope
        from database.models import ExperimentModel, ProcessInfoModel

        candidates = []
        now = datetime.utcnow()
        stale_threshold = now - timedelta(minutes=self._policy.stale_threshold_minutes)
        now - timedelta(minutes=self._policy.heartbeat_timeout_minutes)

        try:
            with session_scope() as session:
                # Find running experiments with process info
                running_experiments = (
                    session.query(ExperimentModel).filter(ExperimentModel.status == "running").all()
                )

                for exp in running_experiments:
                    process_info = (
                        session.query(ProcessInfoModel).filter_by(exp_id=exp.exp_id).first()
                    )

                    if not process_info:
                        # Running experiment with no process info - likely orphaned
                        candidates.append(self._create_orphaned_candidate(exp))
                        continue

                    # Check process state
                    state = self.detect_process_state(
                        exp.exp_id,
                        process_info.pid,
                        process_info.hostname,
                    )

                    # Check for stale heartbeat
                    if state == ProcessState.RUNNING:
                        if (
                            process_info.last_heartbeat
                            and process_info.last_heartbeat < stale_threshold
                        ):
                            state = ProcessState.STALE

                    # Calculate progress
                    progress = 0.0
                    if (
                        process_info.current_step
                        and process_info.total_steps
                        and process_info.total_steps > 0
                    ):
                        progress = (process_info.current_step / process_info.total_steps) * 100.0

                    # Only add candidates that need recovery
                    if state in (
                        ProcessState.STALE,
                        ProcessState.ORPHANED,
                        ProcessState.TERMINATED,
                    ):
                        candidate = self._create_recovery_candidate(
                            exp_id=exp.exp_id,
                            pid=process_info.pid,
                            hostname=process_info.hostname,
                            state=state,
                            db_status=exp.status,
                            last_seen=process_info.last_heartbeat,
                            progress=progress,
                            gpu_id=process_info.gpu_id,
                            working_dir=process_info.working_dir,
                        )
                        candidates.append(candidate)

        except Exception as e:
            logger.error(f"Failed to detect orphaned processes: {e}")

        # Also scan PID files
        candidates.extend(self._scan_pid_files())

        return candidates

    def _create_recovery_candidate(
        self,
        exp_id: str,
        pid: int,
        hostname: str,
        state: ProcessState,
        db_status: str,
        last_seen: datetime | None,
        progress: float,
        gpu_id: int | None,
        working_dir: str,
    ) -> RecoveryCandidate:
        """Create a recovery candidate from process info."""
        available_actions = [
            RecoveryAction(a) for a in self._policy.get_available_actions(state.value)
        ]
        recommended = RecoveryAction(self._policy.get_recommended_action(state.value, progress))
        reason = self._get_recommendation_reason(state, progress)

        return RecoveryCandidate(
            exp_id=exp_id,
            pid=pid,
            hostname=hostname,
            state=state,
            db_status=db_status,
            last_seen=last_seen,
            progress_percent=progress if progress > 0 else None,
            gpu_id=gpu_id,
            working_dir=working_dir,
            available_actions=available_actions,
            recommended_action=recommended,
            reason=reason,
        )

    def _create_orphaned_candidate(self, exp) -> RecoveryCandidate:
        """Create a candidate for orphaned experiment."""
        return RecoveryCandidate(
            exp_id=exp.exp_id,
            pid=exp.lammps_pid or 0,
            hostname=exp.lammps_hostname or self._hostname,
            state=ProcessState.ORPHANED,
            db_status=exp.status,
            last_seen=exp.last_heartbeat_at,
            progress_percent=None,
            gpu_id=exp.gpu_id_allocated,
            working_dir=exp.lammps_working_dir or "",
            available_actions=[RecoveryAction.ABANDON, RecoveryAction.IGNORE],
            recommended_action=RecoveryAction.ABANDON,
            reason="No process tracking info found for running experiment",
        )

    def _get_recommendation_reason(
        self,
        state: ProcessState,
        progress: float,
    ) -> str:
        """Get human-readable reason for recommendation."""
        if state == ProcessState.RUNNING:
            return "Process is running normally"
        elif state == ProcessState.STALE:
            if progress > 50:
                return f"Stale heartbeat but {progress:.1f}% complete - resume recommended"
            else:
                return f"Stale heartbeat and only {progress:.1f}% complete - restart recommended"
        elif state == ProcessState.TERMINATED:
            if progress >= self._policy.min_progress_for_result_recovery:
                return f"Process terminated at {progress:.1f}% - partial results can be recovered"
            else:
                return f"Process terminated at {progress:.1f}% - restart recommended"
        elif state == ProcessState.ORPHANED:
            return "Process not found - likely crashed or killed"
        else:
            return "Unknown state - manual review recommended"

    def _get_pid_file_path(self, exp_id: str) -> Path:
        """Get PID file path for experiment."""
        filename = self._policy.pid_file_pattern.format(exp_id=exp_id)
        return self._pid_dir / filename

    def _write_pid_file(
        self,
        pid_file: Path,
        pid: int,
        hostname: str,
        working_dir: str,
    ) -> None:
        """Write PID file."""
        try:
            content = f"{pid}\n{hostname}\n{working_dir}\n{self._server_instance_id}\n"
            pid_file.write_text(content)
            logger.debug(f"Wrote PID file: {pid_file}")
        except Exception as e:
            logger.error(f"Failed to write PID file {pid_file}: {e}")

    def _remove_pid_file(self, pid_file: Path) -> None:
        """Remove PID file."""
        try:
            if pid_file.exists():
                pid_file.unlink()
                logger.debug(f"Removed PID file: {pid_file}")
        except Exception as e:
            logger.error(f"Failed to remove PID file {pid_file}: {e}")

    def _scan_pid_files(self) -> list[RecoveryCandidate]:
        """Scan PID files for orphaned processes."""
        from database.connection import session_scope
        from database.models import ProcessInfoModel

        candidates = []

        try:
            for pid_file in self._pid_dir.glob(".lammps.*.pid"):
                try:
                    content = pid_file.read_text().strip().split("\n")
                    if len(content) >= 3:
                        pid = int(content[0])
                        hostname = content[1]
                        working_dir = content[2]

                        # Extract exp_id from filename
                        exp_id = pid_file.stem.replace(".lammps.", "").replace(".pid", "")

                        # Check if in database
                        with session_scope() as session:
                            db_record = (
                                session.query(ProcessInfoModel).filter_by(exp_id=exp_id).first()
                            )
                            if not db_record:
                                # Orphaned PID file
                                self.detect_process_state(exp_id, pid, hostname)
                                candidate = self._create_recovery_candidate(
                                    exp_id=exp_id,
                                    pid=pid,
                                    hostname=hostname,
                                    state=ProcessState.ORPHANED,
                                    db_status="unknown",
                                    last_seen=None,
                                    progress=0.0,
                                    gpu_id=None,
                                    working_dir=working_dir,
                                )
                                candidates.append(candidate)
                except Exception as e:
                    logger.warning(f"Failed to parse PID file {pid_file}: {e}")
        except Exception as e:
            logger.error(f"Failed to scan PID files: {e}")

        return candidates

    def cleanup_stale_records(self) -> int:
        """
        Clean up stale process records.

        Returns:
            Number of records cleaned up
        """
        from database.connection import session_scope
        from database.models import ProcessInfoModel

        cleaned = 0
        timeout = datetime.utcnow() - timedelta(minutes=self._policy.heartbeat_timeout_minutes * 2)

        try:
            with session_scope() as session:
                stale_records = (
                    session.query(ProcessInfoModel)
                    .filter(ProcessInfoModel.last_heartbeat < timeout)
                    .all()
                )

                for record in stale_records:
                    # Verify process is not running
                    state = self.detect_process_state(record.exp_id, record.pid, record.hostname)
                    if state == ProcessState.TERMINATED:
                        session.delete(record)
                        self._remove_pid_file(self._get_pid_file_path(record.exp_id))
                        cleaned += 1

                session.commit()
                if cleaned > 0:
                    logger.info(f"Cleaned up {cleaned} stale process records")
        except Exception as e:
            logger.error(f"Failed to cleanup stale records: {e}")

        return cleaned
