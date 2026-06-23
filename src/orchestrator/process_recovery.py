"""
Process Recovery Service.

Handles recovery of orphaned LAMMPS processes and experiments.
Called during API server startup and on user request.
"""

from datetime import datetime
from pathlib import Path

import psutil

from common.logging import get_logger
from contracts.policies.recovery import (
    DEFAULT_RECOVERY_POLICY,
    ProcessRecoveryPolicy,
)
from contracts.schemas import (
    ProcessState,
    RecoveryAction,
    RecoveryCandidate,
    RecoveryResult,
)
from orchestrator.process_tracker import ProcessTracker

logger = get_logger("orchestrator.process_recovery")


class ProcessRecoveryService:
    """
    Service for recovering orphaned LAMMPS processes.

    Called during:
    - API server startup (lifespan hook)
    - Periodic health check task
    - User-initiated recovery request
    """

    def __init__(
        self,
        process_tracker: ProcessTracker,
        policy: ProcessRecoveryPolicy | None = None,
    ) -> None:
        """
        Initialize recovery service.

        Args:
            process_tracker: ProcessTracker instance
            policy: Recovery policy (defaults to DEFAULT_RECOVERY_POLICY)
        """
        self.tracker = process_tracker
        self._policy = policy or DEFAULT_RECOVERY_POLICY

    def check_for_recovery_needed(self) -> list[RecoveryCandidate]:
        """
        Check if any processes need recovery.

        Returns:
            List of candidates with recommended actions
        """
        return self.tracker.detect_orphaned_processes()

    def needs_recovery_dialog(self) -> bool:
        """
        Quick check if recovery dialog should be shown.

        Returns:
            True if there are candidates needing recovery
        """
        candidates = self.check_for_recovery_needed()
        return len(candidates) > 0

    def execute_recovery(
        self,
        exp_id: str,
        action: RecoveryAction,
    ) -> RecoveryResult:
        """
        Execute a recovery action.

        Args:
            exp_id: Experiment ID
            action: Recovery action to take

        Returns:
            Result with success status and details
        """
        logger.info(f"Executing recovery action {action.value} for {exp_id}")

        try:
            if action == RecoveryAction.RESUME:
                return self._execute_resume(exp_id)
            elif action == RecoveryAction.RECOVER_RESULTS:
                return self._execute_recover_results(exp_id)
            elif action == RecoveryAction.RESTART:
                return self._execute_restart(exp_id)
            elif action == RecoveryAction.ABANDON:
                return self._execute_abandon(exp_id)
            elif action == RecoveryAction.IGNORE:
                return self._execute_ignore(exp_id)
            else:
                return RecoveryResult(
                    success=False,
                    action=action,
                    exp_id=exp_id,
                    message="Unknown action",
                    error=f"Unhandled action: {action.value}",
                )
        except Exception as e:
            logger.error(f"Recovery action {action.value} failed for {exp_id}: {e}")
            return RecoveryResult(
                success=False,
                action=action,
                exp_id=exp_id,
                message="Recovery failed",
                error=str(e),
            )

    def execute_all_recommended(self) -> list[RecoveryResult]:
        """
        Execute recommended action for all candidates.

        Returns:
            List of recovery results
        """
        candidates = self.check_for_recovery_needed()
        results = []

        for candidate in candidates:
            result = self.execute_recovery(
                candidate.exp_id,
                candidate.recommended_action,
            )
            results.append(result)

        return results

    def _execute_resume(self, exp_id: str) -> RecoveryResult:
        """
        Resume monitoring a running/stale process.

        Re-registers the process with the current server instance.
        """
        from database.connection import session_scope
        from database.models import ExperimentModel, ProcessInfoModel

        try:
            with session_scope() as session:
                process_info = session.query(ProcessInfoModel).filter_by(exp_id=exp_id).first()

                if not process_info:
                    return RecoveryResult(
                        success=False,
                        action=RecoveryAction.RESUME,
                        exp_id=exp_id,
                        message="Process info not found",
                        error="No process tracking record in database",
                    )

                # Verify process is still running
                state = self.tracker.detect_process_state(
                    exp_id,
                    process_info.pid,
                    process_info.hostname,
                )

                if state not in (ProcessState.RUNNING, ProcessState.STALE):
                    return RecoveryResult(
                        success=False,
                        action=RecoveryAction.RESUME,
                        exp_id=exp_id,
                        message="Process no longer running",
                        error=f"Process state: {state.value}",
                    )

                # Update server instance and heartbeat
                process_info.server_instance_id = self.tracker.server_instance_id
                process_info.last_heartbeat = datetime.utcnow()

                experiment = session.query(ExperimentModel).filter_by(exp_id=exp_id).first()
                if experiment:
                    experiment.last_heartbeat_at = datetime.utcnow()
                    experiment.recovery_status = "resumed"

                session.commit()

                logger.info(f"Resumed monitoring process for {exp_id}")
                return RecoveryResult(
                    success=True,
                    action=RecoveryAction.RESUME,
                    exp_id=exp_id,
                    message="Process monitoring resumed successfully",
                )

        except Exception as e:
            logger.error(f"Failed to resume {exp_id}: {e}")
            return RecoveryResult(
                success=False,
                action=RecoveryAction.RESUME,
                exp_id=exp_id,
                message="Failed to resume",
                error=str(e),
            )

    def _execute_recover_results(self, exp_id: str) -> RecoveryResult:
        """
        Parse partial results and mark experiment as completed with partial data.
        """
        from database.connection import session_scope
        from database.models import ExperimentModel, ProcessInfoModel
        from database.repositories.experiment_repo import ExperimentRepository

        try:
            with session_scope() as session:
                experiment = session.query(ExperimentModel).filter_by(exp_id=exp_id).first()

                if not experiment:
                    return RecoveryResult(
                        success=False,
                        action=RecoveryAction.RECOVER_RESULTS,
                        exp_id=exp_id,
                        message="Experiment not found",
                        error="No experiment record in database",
                    )

                # Get working directory
                working_dir = experiment.lammps_working_dir
                if not working_dir or not Path(working_dir).exists():
                    return RecoveryResult(
                        success=False,
                        action=RecoveryAction.RECOVER_RESULTS,
                        exp_id=exp_id,
                        message="Working directory not found",
                        error=f"Directory not found: {working_dir}",
                    )

                # Try to parse log file and extract metrics
                log_file = Path(working_dir) / "log.lammps"
                metrics_recovered = False

                if log_file.exists():
                    try:
                        from parsers.log_parser import LogParser

                        parser = LogParser()
                        thermo = parser.parse_thermo(log_file)

                        if thermo:
                            # Calculate final metrics from available data
                            final_density = thermo[-1].get("density", 0.0)
                            metrics_recovered = True

                            logger.info(
                                f"Recovered partial results for {exp_id}: density={final_density}"
                            )
                    except Exception as e:
                        logger.warning(f"Failed to parse log for {exp_id}: {e}")

                # Update experiment status
                repo = ExperimentRepository(session)
                repo.update_status(exp_id, "completed" if metrics_recovered else "failed")
                experiment.completed_at = datetime.utcnow()
                experiment.recovery_status = "results_recovered"
                experiment.error_message = (
                    None if metrics_recovered else "Partial recovery - no metrics extracted"
                )

                # Clean up process info
                process_info = session.query(ProcessInfoModel).filter_by(exp_id=exp_id).first()
                if process_info:
                    session.delete(process_info)

                session.commit()
                self.tracker.unregister_process(exp_id)

                return RecoveryResult(
                    success=True,
                    action=RecoveryAction.RECOVER_RESULTS,
                    exp_id=exp_id,
                    message=(
                        "Partial results recovered successfully"
                        if metrics_recovered
                        else "Recovery completed but no metrics extracted"
                    ),
                )

        except Exception as e:
            logger.error(f"Failed to recover results for {exp_id}: {e}")
            return RecoveryResult(
                success=False,
                action=RecoveryAction.RECOVER_RESULTS,
                exp_id=exp_id,
                message="Failed to recover results",
                error=str(e),
            )

    def _execute_restart(self, exp_id: str) -> RecoveryResult:
        """
        Terminate existing process (if any) and queue for restart.

        This method:
        1. Terminates any running LAMMPS process
        2. Releases allocated GPU
        3. Resets experiment status to pending
        4. Creates a new Celery task to re-run the simulation
        """
        from database.connection import session_scope
        from database.models import ExperimentModel, ProcessInfoModel
        from database.repositories.experiment_repo import ExperimentRepository

        try:
            new_task_id = None

            with session_scope() as session:
                process_info = session.query(ProcessInfoModel).filter_by(exp_id=exp_id).first()

                # Try to kill existing process
                if process_info:
                    if process_info.hostname == self.tracker.hostname:
                        self._terminate_process(process_info.pid)
                    session.delete(process_info)

                experiment = session.query(ExperimentModel).filter_by(exp_id=exp_id).first()

                if experiment:
                    repo = ExperimentRepository(session)
                    # IMPORTANT: Save GPU ID before resetting (bug fix)
                    gpu_id_to_release = experiment.gpu_id_allocated

                    # Reset to pending for restart
                    repo.update_status(exp_id, "pending")
                    experiment.lammps_pid = None
                    experiment.lammps_hostname = None
                    experiment.lammps_start_time = None
                    experiment.last_heartbeat_at = None
                    experiment.recovery_status = "requeued"
                    experiment.error_message = None
                    experiment.retry_count = (experiment.retry_count or 0) + 1

                    # Release GPU if was allocated
                    if gpu_id_to_release is not None:
                        self._release_gpu(gpu_id_to_release, exp_id=exp_id)

                    # --- Checkpoint-first restart (v1) ---
                    # Try to resume from the last completed stage's restart
                    # file before falling back to a full fresh rerun.
                    checkpoint_resumed = False
                    if experiment.data_file_path and experiment.prepared_artifact_json:
                        checkpoint_resumed = self._try_checkpoint_restart(experiment, repo)

                    if not checkpoint_resumed and experiment.data_file_path:
                        # Fallback: fresh rerun from scratch (seed change)
                        new_task_id = self._submit_restart_task(experiment)
                        if new_task_id:
                            repo.update_celery_task_id(exp_id, new_task_id)
                            logger.info(f"Created new Celery task {new_task_id} for {exp_id}")

                session.commit()
                self.tracker.unregister_process(exp_id)

                if checkpoint_resumed:
                    message = "Experiment queued for checkpoint restart (ready)"
                elif new_task_id:
                    message = f"Experiment restarted with task {new_task_id}"
                else:
                    message = "Experiment queued for restart"

                logger.info(f"Experiment {exp_id} queued for restart")
                return RecoveryResult(
                    success=True,
                    action=RecoveryAction.RESTART,
                    exp_id=exp_id,
                    message=message,
                )

        except Exception as e:
            logger.error(f"Failed to restart {exp_id}: {e}")
            return RecoveryResult(
                success=False,
                action=RecoveryAction.RESTART,
                exp_id=exp_id,
                message="Failed to restart",
                error=str(e),
            )

    def _execute_abandon(self, exp_id: str) -> RecoveryResult:
        """
        Mark experiment as failed and clean up resources.
        """
        from database.connection import session_scope
        from database.models import ExperimentModel, ProcessInfoModel
        from database.repositories.experiment_repo import ExperimentRepository

        try:
            with session_scope() as session:
                process_info = session.query(ProcessInfoModel).filter_by(exp_id=exp_id).first()

                # Try to kill existing process
                if process_info:
                    if process_info.hostname == self.tracker.hostname:
                        self._terminate_process(process_info.pid)
                    session.delete(process_info)

                experiment = session.query(ExperimentModel).filter_by(exp_id=exp_id).first()

                if experiment:
                    repo = ExperimentRepository(session)
                    gpu_id = experiment.gpu_id_allocated
                    repo.update_status(exp_id, "failed")
                    experiment.completed_at = datetime.utcnow()
                    experiment.error_message = "Abandoned during recovery"
                    experiment.recovery_status = "abandoned"
                    experiment.lammps_pid = None
                    experiment.lammps_hostname = None

                    # Release GPU
                    if gpu_id is not None:
                        self._release_gpu(gpu_id, exp_id=exp_id)

                session.commit()
                self.tracker.unregister_process(exp_id)

                logger.info(f"Experiment {exp_id} abandoned")
                return RecoveryResult(
                    success=True,
                    action=RecoveryAction.ABANDON,
                    exp_id=exp_id,
                    message="Experiment marked as failed and resources released",
                )

        except Exception as e:
            logger.error(f"Failed to abandon {exp_id}: {e}")
            return RecoveryResult(
                success=False,
                action=RecoveryAction.ABANDON,
                exp_id=exp_id,
                message="Failed to abandon",
                error=str(e),
            )

    def _execute_ignore(self, exp_id: str) -> RecoveryResult:
        """
        Mark as ignored for manual handling.
        """
        from database.connection import session_scope
        from database.models import ExperimentModel

        try:
            with session_scope() as session:
                experiment = session.query(ExperimentModel).filter_by(exp_id=exp_id).first()

                if experiment:
                    experiment.recovery_status = "ignored"

                session.commit()

                logger.info(f"Experiment {exp_id} marked as ignored")
                return RecoveryResult(
                    success=True,
                    action=RecoveryAction.IGNORE,
                    exp_id=exp_id,
                    message="Experiment marked for manual handling",
                )

        except Exception as e:
            logger.error(f"Failed to ignore {exp_id}: {e}")
            return RecoveryResult(
                success=False,
                action=RecoveryAction.IGNORE,
                exp_id=exp_id,
                message="Failed to mark as ignored",
                error=str(e),
            )

    def _try_checkpoint_restart(self, experiment, repo) -> bool:
        """Attempt to prepare a restart artifact from checkpoint files.

        Returns True if a checkpoint was found and the experiment was
        successfully transitioned to *ready* state for the run scheduler.
        """
        try:
            from pathlib import Path

            from orchestrator.task_common import get_experiment_work_dir
            from protocols.restart_discovery import discover_restart_point

            compiled_plan = (experiment.metadata_json or {}).get("compiled_execution_plan")
            if not compiled_plan:
                return False

            # Build candidate dirs (priority: active attempt, celery task, newest)
            base_dir = get_experiment_work_dir(experiment.exp_id)
            candidate_dirs: list[Path] = []

            if experiment.active_attempt_id:
                d = base_dir / f"attempt_{experiment.active_attempt_id}"
                if d.is_dir():
                    candidate_dirs.append(d)
            if (
                experiment.celery_task_id
                and experiment.celery_task_id != experiment.active_attempt_id
            ):
                d = base_dir / f"attempt_{experiment.celery_task_id}"
                if d.is_dir():
                    candidate_dirs.append(d)
            # Add any other attempt dirs sorted newest first
            for d in sorted(
                base_dir.glob("attempt_*"), key=lambda p: p.stat().st_mtime, reverse=True
            ):
                if d not in candidate_dirs:
                    candidate_dirs.append(d)

            # Also check compositions/{binder}/{additive}/{exp_id}/input/
            # where LAMMPS actually writes restart files during execution.
            from common.pathing import get_experiment_path

            compositions_input = get_experiment_path(experiment.exp_id, "input")
            if compositions_input.is_dir() and compositions_input not in candidate_dirs:
                candidate_dirs.append(compositions_input)

            if not candidate_dirs:
                return False

            restart_point = discover_restart_point(experiment.exp_id, compiled_plan, candidate_dirs)
            if restart_point is None:
                return False

            from orchestrator.task_runners import prepare_restart_artifact

            return prepare_restart_artifact(experiment.exp_id, restart_point)

        except Exception as e:
            logger.warning("Checkpoint restart attempt failed for %s: %s", experiment.exp_id, e)
            return False

    def _submit_restart_task(self, experiment) -> str | None:
        """
        Submit a new Celery task to restart a simulation.

        Args:
            experiment: ExperimentModel instance with required fields

        Returns:
            New Celery task ID, or None if failed
        """
        try:
            from common.seed import generate_seed
            from contracts.schemas import FFType, RunTier
            from orchestrator.request_factory import create_build_request, create_protocol_request
            from orchestrator.tasks import run_simulation

            # Reconstruct build request from experiment data
            composition = {
                "asphaltene": experiment.comp_asphaltene_wt or 0.0,
                "resin": experiment.comp_resin_wt or 0.0,
                "aromatic": experiment.comp_aromatic_wt or 0.0,
                "saturate": experiment.comp_saturate_wt or 0.0,
            }

            run_tier = RunTier(experiment.run_tier or "screening")
            ff_type = FFType(experiment.ff_type or "bulk_ff_gaff2")

            build_request = create_build_request(
                composition=composition,
                target_atoms=experiment.target_atoms,
                seed=generate_seed(experiment.seed),
                tier=run_tier,
            )

            protocol_request = create_protocol_request(
                tier=run_tier,
                ff_type=ff_type,
                temperature_K=experiment.temperature_K or 298.0,
                pressure_atm=experiment.pressure_atm or 1.0,
                data_file_path=experiment.data_file_path or "",
            )

            # Extract material_id from exp_id
            from common.pathing import exp_id_to_material_id

            material_id = (
                exp_id_to_material_id(experiment.exp_id)
                if "_" in experiment.exp_id
                else "restarted"
            )

            # Submit task
            task = run_simulation.delay(
                build_request_dict=build_request.model_dump(),
                protocol_request_dict=protocol_request.model_dump(),
                material_id=material_id,
                exp_id=experiment.exp_id,
            )

            logger.info(f"Submitted restart task {task.id} for {experiment.exp_id}")
            return task.id

        except Exception as e:
            logger.error(f"Failed to submit restart task for {experiment.exp_id}: {e}")
            return None

    def _terminate_process(self, pid: int) -> bool:
        """
        Terminate a process by PID.

        Args:
            pid: Process ID

        Returns:
            True if terminated successfully
        """
        try:
            process = psutil.Process(pid)
            # Try graceful termination first
            process.terminate()
            try:
                process.wait(timeout=5)
            except psutil.TimeoutExpired:
                # Force kill
                process.kill()
            logger.info(f"Terminated process {pid}")
            return True
        except psutil.NoSuchProcess:
            return True  # Already terminated
        except Exception as e:
            logger.error(f"Failed to terminate process {pid}: {e}")
            return False

    def _release_gpu(self, gpu_id: int | None, exp_id: str | None = None) -> bool:
        """
        Release an allocated GPU.

        Args:
            gpu_id: GPU ID to release
            exp_id: Experiment ID owning the GPU allocation
        """
        if gpu_id is None:
            return True

        try:
            from api.deps import get_gpu_resource_tracker

            tracker = get_gpu_resource_tracker()
            released = bool(tracker.release_gpu(gpu_id, exp_id=exp_id))
            if released:
                logger.info(f"Released GPU {gpu_id}")
            else:
                logger.warning(
                    "GPU release failed for gpu_id=%s exp_id=%s (SSOT guard preserved DB state)",
                    gpu_id,
                    exp_id,
                )
            return released
        except Exception as e:
            logger.warning(f"Failed to release GPU {gpu_id}: {e}")
            return False

    def restore_gpu_state_from_db(self) -> int:
        """
        Restore GPU allocations from database on startup.

        Returns:
            Number of GPUs restored
        """
        from database.connection import session_scope
        from database.models import ExperimentModel
        from database.repositories.experiment_repo import ExperimentRepository

        restored = 0

        try:
            from api.deps import get_gpu_resource_tracker

            tracker = get_gpu_resource_tracker()

            with session_scope() as session:
                repo = ExperimentRepository(session)
                running_experiments = (
                    session.query(ExperimentModel)
                    .filter(
                        ExperimentModel.status == "running",
                        ExperimentModel.gpu_id_allocated.isnot(None),
                    )
                    .all()
                )

                for exp in running_experiments:
                    # Verify process is still running
                    if exp.lammps_pid and exp.lammps_hostname == self.tracker.hostname:
                        state = self.tracker.detect_process_state(
                            exp.exp_id,
                            exp.lammps_pid,
                            exp.lammps_hostname,
                        )

                        if state in (ProcessState.RUNNING, ProcessState.STALE):
                            # Use restore_allocation with proper exp_id and job_id
                            success = tracker.restore_allocation(
                                gpu_id=exp.gpu_id_allocated,
                                job_id=exp.celery_task_id,
                                exp_id=exp.exp_id,
                            )
                            if success:
                                restored += 1
                                logger.info(
                                    f"Restored GPU {exp.gpu_id_allocated} allocation "
                                    f"for {exp.exp_id}"
                                )
                        else:
                            # Process not running - mark experiment as failed
                            if exp.gpu_id_allocated is not None:
                                self._release_gpu(exp.gpu_id_allocated, exp_id=exp.exp_id)
                            repo.update_status(exp.exp_id, "failed")
                            exp.error_message = "Process terminated unexpectedly"
                            session.commit()
                            logger.info(f"Marked stale experiment {exp.exp_id} as failed")

            if restored > 0:
                logger.info(f"Restored {restored} GPU allocations from database")

        except Exception as e:
            logger.error(f"Failed to restore GPU state: {e}")

        return restored
