"""
Celery tasks for MD simulation workflow.

Defines async tasks for:
- Simulation execution (screening, confirm, viscosity)
- Metric calculation
- Job maintenance (cleanup, stall detection)

This is a thin facade: task registration only.
Implementation lives in task_runners.py and task_maintenance.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from celery import shared_task
from celery.exceptions import Retry, SoftTimeLimitExceeded

if TYPE_CHECKING:
    from pathlib import Path

    from contracts.schemas import GroupEnergySpec, StudyType

from common.logging import get_logger
from common.seed import generate_seed
from contracts.policies.tier import DEFAULT_TIER_POLICY
from contracts.schemas import (
    BuildRequest,
    ProtocolRequest,
    RunTier,
)
from orchestrator.task_common import (
    TaskResult,
    get_experiment_work_dir,
    run_in_task_session,
)
from orchestrator.task_maintenance import (
    _handle_completed_experiment_feedback,
    _trigger_ready_scheduler,
    _update_experiment_status_by_task_id,
)
from orchestrator.task_runners import (
    _clear_dispatch_attempt_id,
    _get_pipeline,
    _load_prepared_artifact,
    _run_tier_simulation,
    _validate_prepared_run_owner,
)

logger = get_logger("orchestrator.tasks")


@shared_task(
    bind=True,
    name="orchestrator.tasks.run_simulation",
    max_retries=2,
    default_retry_delay=60,
)
def run_simulation(
    self,
    build_request_dict: dict,
    protocol_request_dict: dict,
    material_id: str = "default_binder",
    stage_duration_overrides_dict: list[dict] | None = None,
    property_calculations: dict | None = None,
    exp_id: str | None = None,
    # Phase 5.1: additive metadata propagation
    additive_type: str | None = None,
    additive_wt: float = 0.0,
    additive_mol_id: str | None = None,
) -> dict:
    """
    Celery wrapper: deserialize dicts -> delegate to _run_tier_simulation.

    Args:
        build_request_dict: BuildRequest as dictionary
        protocol_request_dict: ProtocolRequest as dictionary
        material_id: Material identifier
        stage_duration_overrides_dict: Optional list of stage duration overrides (serialized)
        property_calculations: Optional property calculation settings
        exp_id: Pre-generated experiment ID for API-Celery sync (generated if None)
        additive_type: Additive type identifier (Phase 5.1)
        additive_wt: Additive weight percent (Phase 5.1)
        additive_mol_id: Additive molecule ID (Phase 5.1)

    Returns:
        TaskResult as dictionary
    """
    start_time = datetime.now(UTC)
    task_id = self.request.id

    # Deserialize requests
    build_request = BuildRequest(**build_request_dict)
    protocol_request = ProtocolRequest(**protocol_request_dict)

    # Deserialize stage duration overrides if provided
    stage_duration_overrides = None
    if stage_duration_overrides_dict:
        from protocols.duration_adjuster import StageDurationOverride

        stage_duration_overrides = [
            StageDurationOverride(**o) for o in stage_duration_overrides_dict
        ]
        logger.info(
            f"Task {task_id}: Stage duration overrides: "
            f"{[(o.stage_name, o.duration_ps or o.duration_steps) for o in stage_duration_overrides]}"
        )

    try:
        # Pass pre-created requests to avoid redundant re-creation
        return _run_tier_simulation(
            task=self,
            tier=protocol_request.run_tier,
            composition=build_request.composition,
            temperature_K=protocol_request.temperature_K,
            target_atoms=build_request.target_atoms,
            seed=build_request.seed,
            material_id=material_id,
            stage_duration_overrides=stage_duration_overrides,
            property_calculations=property_calculations,
            exp_id=exp_id,
            build_request=build_request,
            protocol_request=protocol_request,
            additive_type=additive_type,
            additive_wt=additive_wt,
            additive_mol_id=additive_mol_id,
            deferred_gpu_allocation=True,
        )
    except SoftTimeLimitExceeded:
        logger.error(f"Task {task_id}: Soft time limit exceeded")
        _update_experiment_status_by_task_id(
            task_id, "failed", error_code="E4003", error_message="Task exceeded soft time limit"
        )
        return TaskResult(
            success=False,
            error="Task exceeded soft time limit",
            duration_seconds=(datetime.now(UTC) - start_time).total_seconds(),
        ).to_dict()
    except Retry:
        # Explicit retry from _run_tier_simulation() must propagate to Celery.
        raise
    except Exception as e:
        logger.error(f"Task {task_id}: Unhandled wrapper error - {e}")
        _update_experiment_status_by_task_id(
            task_id, "failed", error_code="E4001", error_message=str(e)
        )
        return TaskResult(
            success=False,
            error=str(e),
            duration_seconds=(datetime.now(UTC) - start_time).total_seconds(),
        ).to_dict()


@shared_task(
    bind=True,
    name="orchestrator.tasks.run_screening_simulation",
    queue="simulation.screening",
    max_retries=2,
    default_retry_delay=60,
)
def run_screening_simulation(
    self,
    composition: dict[str, float],
    temperature_K: float = 298.0,
    target_atoms: int = DEFAULT_TIER_POLICY.get_target_atoms("screening"),
    seed: int | None = None,
    material_id: str = "default_binder",
    exp_id: str | None = None,
) -> dict:
    """
    Run a screening tier simulation.

    Args:
        composition: SARA composition (wt%)
        temperature_K: Temperature in Kelvin
        target_atoms: Target atom count (from tier policy)
        seed: Random seed
        material_id: Material identifier
        exp_id: Pre-generated experiment ID for GPU allocation

    Returns:
        TaskResult as dictionary
    """
    return _run_tier_simulation(
        task=self,
        tier=RunTier.SCREENING,
        composition=composition,
        temperature_K=temperature_K,
        target_atoms=target_atoms,
        seed=generate_seed(seed),
        material_id=material_id,
        exp_id=exp_id,
    )


@shared_task(
    bind=True,
    name="orchestrator.tasks.run_confirm_simulation",
    queue="simulation.confirm",
    max_retries=2,
    default_retry_delay=60,
)
def run_confirm_simulation(
    self,
    composition: dict[str, float],
    temperature_K: float = 298.0,
    target_atoms: int = DEFAULT_TIER_POLICY.get_target_atoms("confirm"),
    seed: int | None = None,
    material_id: str = "default_binder",
    exp_id: str | None = None,
) -> dict:
    """
    Run a confirm tier simulation.

    Args:
        composition: SARA composition (wt%)
        temperature_K: Temperature in Kelvin
        target_atoms: Target atom count (from tier policy)
        seed: Random seed
        material_id: Material identifier
        exp_id: Pre-generated experiment ID for GPU allocation

    Returns:
        TaskResult as dictionary
    """
    return _run_tier_simulation(
        task=self,
        tier=RunTier.CONFIRM,
        composition=composition,
        temperature_K=temperature_K,
        target_atoms=target_atoms,
        seed=generate_seed(seed),
        material_id=material_id,
        exp_id=exp_id,
    )


@shared_task(
    bind=True,
    name="orchestrator.tasks.run_viscosity_simulation",
    queue="simulation.viscosity",
    time_limit=172800,  # 48 hours for viscosity
    soft_time_limit=169200,  # 47 hours
    max_retries=2,
    default_retry_delay=120,
)
def run_viscosity_simulation(
    self,
    composition: dict[str, float],
    temperature_K: float = 298.0,
    target_atoms: int = DEFAULT_TIER_POLICY.get_target_atoms("viscosity"),
    seed: int | None = None,
    material_id: str = "default_binder",
    exp_id: str | None = None,
) -> dict:
    """
    Run a viscosity tier simulation with extended time limits.

    This wrapper handles SoftTimeLimitExceeded separately because only
    viscosity tasks have time_limit/soft_time_limit decorators.

    Args:
        composition: SARA composition (wt%)
        temperature_K: Temperature in Kelvin
        target_atoms: Target atom count (from tier policy)
        seed: Random seed
        material_id: Material identifier
        exp_id: Pre-generated experiment ID for GPU allocation

    Returns:
        TaskResult as dictionary
    """
    start_time = datetime.now(UTC)
    task_id = self.request.id

    try:
        return _run_tier_simulation(
            task=self,
            tier=RunTier.VISCOSITY,
            composition=composition,
            temperature_K=temperature_K,
            target_atoms=target_atoms,
            seed=generate_seed(seed),
            material_id=material_id,
            exp_id=exp_id,
        )
    except SoftTimeLimitExceeded:
        # Viscosity-specific: soft time limit exceeded handling
        logger.error(f"Task {task_id}: Soft time limit exceeded")
        _update_experiment_status_by_task_id(
            task_id,
            "failed",
            error_code="E4003",
            error_message="Viscosity simulation exceeded time limit",
        )
        return TaskResult(
            success=False,
            error="Task exceeded soft time limit",
            duration_seconds=(datetime.now(UTC) - start_time).total_seconds(),
        ).to_dict()


@shared_task(
    bind=True,
    name="orchestrator.tasks.calculate_metrics",
    queue="metrics",
)
def calculate_metrics(
    self,
    exp_id: str,
    log_file: str,
    dump_files: list[str],
) -> dict:
    """
    Calculate metrics from simulation output.

    This task is used for recalculating metrics or calculating
    additional metrics after simulation completion.

    Args:
        exp_id: Experiment ID
        log_file: Path to LAMMPS log file
        dump_files: List of dump file paths

    Returns:
        Dictionary with calculated metrics
    """
    logger.info(f"Calculating metrics for {exp_id}")

    try:
        from contracts.schemas import LAMMPSRunResult
        from parsers.log_parser import LogParser

        # Parse log file
        parser = LogParser()
        _thermo_data = parser.parse(log_file)  # noqa: F841

        # Create run result
        run_result = LAMMPSRunResult(
            success=True,
            log_file=log_file,
            dump_files=dump_files,
            wall_time_seconds=0.0,
            exit_code=0,
        )

        # Restore CED lookup metadata from DB and calculate metrics
        from database.connection import get_session as _get_calc_session
        from orchestrator.task_runners import make_metrics_calculator, restore_run_result_metadata

        _calc_session = _get_calc_session()
        try:
            restore_run_result_metadata(run_result, exp_id, _calc_session)
            calculator = make_metrics_calculator(_calc_session)
            metrics = calculator.calculate(run_result)
        finally:
            _calc_session.close()

        return {
            "success": True,
            "exp_id": exp_id,
            "metrics": {m.metric_name: m.value for m in metrics if m.value is not None},
        }

    except Exception as e:
        logger.error(f"Metric calculation failed for {exp_id}: {e}")
        return {
            "success": False,
            "exp_id": exp_id,
            "error": str(e),
        }


@shared_task(
    bind=True,
    name="orchestrator.tasks.priority_simulation",
    queue="priority",
)
def priority_simulation(
    self,
    build_request_dict: dict,
    protocol_request_dict: dict,
    material_id: str = "default_binder",
) -> dict:
    """
    Run a high-priority simulation.

    This task uses the priority queue for urgent simulations.

    Args:
        build_request_dict: BuildRequest as dictionary
        protocol_request_dict: ProtocolRequest as dictionary
        material_id: Material identifier

    Returns:
        TaskResult as dictionary
    """
    return run_simulation(
        build_request_dict,
        protocol_request_dict,
        material_id,
    )


@shared_task(name="orchestrator.tasks.cleanup_old_jobs")
def cleanup_old_jobs(older_than_hours: int = 24) -> dict:
    """
    Clean up old completed/failed jobs from result backend.

    Args:
        older_than_hours: Remove results older than this

    Returns:
        Cleanup statistics
    """
    from orchestrator.maintenance import MaintenanceService

    return run_in_task_session(
        lambda session: MaintenanceService(session).cleanup_old_jobs(older_than_hours)
    )


@shared_task(name="orchestrator.tasks.check_stalled_jobs")
def check_stalled_jobs(stall_timeout_minutes: int = 60) -> dict:
    """
    Check for stalled jobs and handle them.

    Args:
        stall_timeout_minutes: Time in minutes after which a job is considered stalled

    Returns:
        Stall check statistics
    """
    from orchestrator.celery_app import celery_app as _celery_app
    from orchestrator.maintenance import MaintenanceService

    return run_in_task_session(
        lambda session: MaintenanceService(session).check_stalled_jobs(
            stall_timeout_minutes=stall_timeout_minutes,
            celery_app=_celery_app,
        )
    )


@shared_task(
    bind=True,
    name="orchestrator.tasks.batch_simulation",
)
def batch_simulation(
    self,
    compositions: list[dict[str, float]],
    temperature_K: float = 298.0,
    target_atoms: int = DEFAULT_TIER_POLICY.get_target_atoms("screening"),
    run_tier: str = "screening",
) -> dict:
    """
    Submit a batch of simulations.

    Args:
        compositions: List of SARA compositions
        temperature_K: Temperature in Kelvin
        target_atoms: Target atom count
        run_tier: Run tier name

    Returns:
        Batch submission result with task IDs
    """
    from celery import group

    from orchestrator.task_registry import get_task_for_tier

    task_func = get_task_for_tier(run_tier)
    tasks = []

    for i, comp in enumerate(compositions):
        task = task_func.s(
            composition=comp,
            temperature_K=temperature_K,
            target_atoms=target_atoms,
            seed=i + 1,
            material_id=f"batch_{i:04d}",
        )
        tasks.append(task)

    # Create and execute group
    job = group(tasks)
    result = job.apply_async()

    logger.info(f"Batch submitted: {len(compositions)} simulations")

    return {
        "batch_id": result.id,
        "task_count": len(compositions),
        "run_tier": run_tier,
    }


@shared_task(name="orchestrator.tasks.cleanup_orphaned_tasks")
def cleanup_orphaned_tasks() -> dict:
    """
    Clean up orphaned tasks from Redis queue.

    Finds tasks in Celery queues that have no corresponding experiment
    in the database and revokes them.

    Returns:
        Cleanup statistics including count of orphaned tasks revoked
    """
    from orchestrator.celery_app import celery_app
    from orchestrator.maintenance import MaintenanceService

    return run_in_task_session(
        lambda session: MaintenanceService(session).cleanup_orphaned_tasks(celery_app)
    )


@shared_task(name="orchestrator.tasks.sync_job_status")
def sync_job_status() -> dict:
    """
    Synchronize job status between Celery and database.

    This task inspects actual Celery worker state and updates
    experiment records in the database to match reality.

    Fixes issues where:
    - Jobs show as 'pending' but are actually running
    - Jobs show as 'running' but have completed
    - started_at timestamps are missing

    Returns:
        Sync statistics
    """
    from orchestrator.celery_app import celery_app
    from orchestrator.maintenance import MaintenanceService

    return run_in_task_session(
        lambda session: MaintenanceService(session).sync_job_status(celery_app)
    )


@shared_task(name="orchestrator.tasks.reconcile_unprocessed_completions")
def reconcile_unprocessed_completions(limit: int = 20) -> dict[str, int]:
    """Reconcile completed experiments that still lack feedback processing."""
    from orchestrator.maintenance import MaintenanceService

    exp_ids = run_in_task_session(
        lambda session: MaintenanceService(session).reconcile_unprocessed_completions(
            limit=max(1, int(limit))
        )
    )
    processed = 0
    for exp_id in exp_ids:
        if _handle_completed_experiment_feedback(exp_id):
            processed += 1
    return {"scanned": len(exp_ids), "processed": processed}


@shared_task(name="orchestrator.tasks.reconcile_dependency_chains")
def reconcile_dependency_chains(max_submissions: int = 10) -> dict:
    """
    Reconcile dependency graph and submit READY downstream jobs.

    Runs in two phases:
    1) blocked/ready edges reconciliation by upstream terminal status + budget
    2) READY edge submission (bounded)
    """
    try:
        from orchestrator.celery_job_manager import CeleryJobManager
        from orchestrator.dependency_scheduler import DependencyScheduler
        from orchestrator.gpu_service import get_gpu_service

        scheduler = DependencyScheduler(CeleryJobManager(gpu_tracker=get_gpu_service()))
        reconcile = scheduler.reconcile_all()
        submit = scheduler.submit_ready(max_submissions=max_submissions)
        return {
            "status": "ok",
            "reconcile": reconcile,
            "submit": submit,
        }
    except Exception as exc:
        logger.error("Dependency reconcile task failed: %s", exc)
        return {"status": "error", "error": str(exc)}


@shared_task(name="orchestrator.tasks.schedule_ready_experiments")
def schedule_ready_experiments(max_submissions: int = 10) -> dict:
    """Schedule ready experiments onto available GPUs."""
    try:
        from orchestrator.celery_app import celery_app
        from orchestrator.gpu_service import get_gpu_service
        from orchestrator.run_scheduler import RunScheduler

        scheduler = RunScheduler(gpu_service=get_gpu_service(), celery_app=celery_app)
        result = scheduler.schedule_ready_experiments(max_submissions=max_submissions)
        return {"status": "ok", **result}
    except Exception as exc:
        logger.error("Ready scheduler failed: %s", exc)
        return {"status": "error", "error": str(exc)}


@shared_task(name="orchestrator.tasks.refresh_gpu_inventory")
def refresh_gpu_inventory() -> dict:
    """Real-time GPU pool refresh so repaired/added GPUs become usable without a
    restart, and removed ones are marked OFFLINE.

    Runs on the gpu@ pool (default queue) — the same process whose GPUService the
    scheduler allocates from — so a GPU that comes back online after repair is
    picked up within one beat interval. Non-destructive: never disturbs in-flight
    allocations (see GPUService.refresh_inventory).
    """
    try:
        from config.dashboard_settings import get_selected_gpus
        from monitoring.gpu_collector import enumerate_compute_devices
        from orchestrator.gpu_service import get_gpu_service

        gpu_service = get_gpu_service()
        gpu_service.initialize()
        devices = enumerate_compute_devices() or []
        eligible = [d for d in devices if d.get("eligible")]
        # auto_mode: settings.json selected_gpus empty => selection follows live
        # detection (so newly-repaired GPUs are auto-included).
        auto_mode = not (get_selected_gpus() or [])
        result = gpu_service.refresh_inventory(eligible, auto_mode=auto_mode)
        return {"status": "ok", **result}
    except Exception as exc:
        logger.error("refresh_gpu_inventory failed: %s", exc)
        return {"status": "error", "error": str(exc)}


@shared_task(name="orchestrator.tasks.recover_orphan_ready_allocations")
def recover_orphan_ready_allocations(limit: int = 200) -> dict:
    """
    Recover stuck rows: status=ready with gpu_id_allocated but no active Celery task.
    """
    try:
        from datetime import timedelta

        from contracts.policies.recovery import DEFAULT_RECOVERY_POLICY
        from database.connection import session_scope
        from database.models import ExperimentModel
        from orchestrator.celery_app import celery_app
        from orchestrator.gpu_service import get_gpu_service

        inspect = celery_app.control.inspect(timeout=1.0)
        active = inspect.active() or {}
        reserved = inspect.reserved() or {}
        scheduled = inspect.scheduled() or {}

        alive_task_ids: set[str] = set()
        for collection in (active, reserved):
            for tasks in collection.values():
                for task in tasks or []:
                    tid = str(task.get("id") or "").strip()
                    if tid:
                        alive_task_ids.add(tid)
        for tasks in scheduled.values():
            for entry in tasks or []:
                req = (entry or {}).get("request", {})
                tid = str(req.get("id") or "").strip()
                if tid:
                    alive_task_ids.add(tid)

        # Grace window: do not reclaim rows that were just dispatched. A
        # freshly-dispatched-but-not-yet-active run task can be invisible in the
        # inspect() snapshot under load; releasing its GPU here would re-trigger
        # the dispatcher and cause re-dispatch churn.
        grace_s = int(getattr(DEFAULT_RECOVERY_POLICY, "orphan_ready_grace_seconds", 90))
        cutoff = datetime.utcnow() - timedelta(seconds=grace_s)

        released = 0
        scanned = 0
        with session_scope() as session:
            rows = (
                session.query(ExperimentModel)
                .filter(
                    ExperimentModel.status == "ready",
                    ExperimentModel.gpu_id_allocated.isnot(None),
                    ExperimentModel.lammps_pid.is_(None),
                    ExperimentModel.updated_at < cutoff,
                )
                .order_by(ExperimentModel.updated_at.asc())
                .limit(int(limit))
                .all()
            )
            scanned = len(rows)
            for exp in rows:
                task_id = str(exp.celery_task_id or "").strip()
                if task_id and task_id in alive_task_ids:
                    continue
                gpu_id = int(exp.gpu_id_allocated)
                get_gpu_service().release(gpu_id, task_id=task_id or None, exp_id=exp.exp_id)
                released += 1

        if released > 0:
            _trigger_ready_scheduler(max_submissions=10)
        return {"status": "ok", "scanned": scanned, "released": released}
    except Exception as exc:
        logger.error("Orphan ready-allocation recovery failed: %s", exc)
        return {"status": "error", "error": str(exc)}


@shared_task(name="orchestrator.tasks.cleanup_stale_exp_locks")
def cleanup_stale_exp_locks(max_keys: int = 500) -> dict:
    """Cleanup stale Redis exp_lock:* keys left after terminal/delete paths."""
    try:
        from orchestrator.exp_lock_manager import cleanup_stale_exp_locks as _cleanup

        result = _cleanup(max_keys=max_keys)
        return {"status": "ok", **result}
    except Exception as exc:
        logger.error("Stale exp_lock cleanup failed: %s", exc)
        return {"status": "error", "error": str(exc)}


@shared_task(
    bind=True,
    name="orchestrator.tasks.run_prepared_simulation",
    queue="simulation.gpu",
    max_retries=2,
    default_retry_delay=60,
)
def run_prepared_simulation(
    self,
    exp_id: str,
    gpu_id: int,
    dispatch_attempt_id: str | None = None,
) -> dict:
    """Execute prepared simulation (ready -> running).

    gpu_id may be -1 when LammpsCaps determined CPU-only mode, in which case
    no GPU slot was allocated by the scheduler.
    """
    start_time = datetime.now(UTC)
    task_id = self.request.id
    allocated_gpu_id: int | None = int(gpu_id) if int(gpu_id) >= 0 else None
    try:
        is_owner, reason = _validate_prepared_run_owner(
            exp_id,
            task_id,
            int(gpu_id),
            str(dispatch_attempt_id).strip() if dispatch_attempt_id else None,
        )
        if not is_owner:
            logger.warning(
                "Skipping stale/duplicate prepared run for %s (task_id=%s, reason=%s)",
                exp_id,
                task_id,
                reason,
            )
            # Release only in safe, recoverable skip paths.
            if allocated_gpu_id is not None and (
                reason.startswith("terminal_status:")
                or reason.startswith("dispatch_missing:")
                or reason.startswith("gpu_mismatch:")
                or reason.startswith("validation_error:")
                or reason.startswith("duplicate_claim:")
            ):
                from orchestrator.gpu_service import get_gpu_service

                get_gpu_service().release(allocated_gpu_id, task_id=task_id, exp_id=exp_id)
                if reason.startswith("dispatch_missing:"):
                    _clear_dispatch_attempt_id(exp_id)
                allocated_gpu_id = None
                _trigger_ready_scheduler(max_submissions=10)
            return TaskResult(
                success=True,
                exp_id=exp_id,
                metrics={"phase": "skipped", "reason": reason},
                duration_seconds=(datetime.now(UTC) - start_time).total_seconds(),
            ).to_dict()

        _clear_dispatch_attempt_id(
            exp_id,
            str(dispatch_attempt_id).strip() if dispatch_attempt_id else None,
        )
        _update_experiment_status_by_task_id(task_id, "running")
        artifact = _load_prepared_artifact(exp_id)
        if not artifact:
            raise RuntimeError(f"Prepared artifact missing for exp_id={exp_id}")

        protocol_request = ProtocolRequest.model_validate(artifact["protocol_request"])
        property_calculations = artifact.get("property_calculations")
        additive = artifact.get("additive") or {}

        # Extract actual atom count from build_result for GPU thread scaling (v00.97.00)
        build_result_data = artifact.get("build_result", {})
        actual_atom_count = build_result_data.get("actual_atoms")

        work_dir = get_experiment_work_dir(exp_id, attempt_tag=task_id)
        pipeline, _ = _get_pipeline(
            task_id=task_id,
            work_dir=work_dir,
            ff_name=protocol_request.ff_type.value,
            exp_id=exp_id,
            allocate_gpu=False,
            preallocated_gpu_id=allocated_gpu_id,
            actual_atom_count=actual_atom_count,
        )
        pipeline.execute_with_gpu(
            exp_id=exp_id,
            prepared_payload=artifact,
            property_calculations=property_calculations
            if isinstance(property_calculations, dict)
            else None,
            additive_type=additive.get("type"),
            additive_wt=float(additive.get("wt") or 0.0),
            additive_mol_id=additive.get("mol_id"),
        )
        _update_experiment_status_by_task_id(task_id, "completed")
        return TaskResult(
            success=True,
            exp_id=exp_id,
            duration_seconds=(datetime.now(UTC) - start_time).total_seconds(),
        ).to_dict()
    except Retry:
        raise
    except Exception as exc:
        _update_experiment_status_by_task_id(
            task_id,
            "failed",
            error_code="E4001",
            error_message=str(exc),
        )
        return TaskResult(
            success=False,
            exp_id=exp_id,
            error=str(exc),
            duration_seconds=(datetime.now(UTC) - start_time).total_seconds(),
        ).to_dict()
    finally:
        if allocated_gpu_id is not None:
            from orchestrator.gpu_service import get_gpu_service

            get_gpu_service().release(allocated_gpu_id, task_id=task_id, exp_id=exp_id)
            _trigger_ready_scheduler(max_submissions=10)


# =============================================================================
# Phase 4.3: Layer/Tensile simulation task
# =============================================================================


@shared_task(
    bind=True,
    name="orchestrator.tasks.run_layer_simulation",
    queue="simulation.layer",
    max_retries=2,
    default_retry_delay=60,
)
def run_layer_simulation(
    self,
    layer_spec_dict: dict,
    protocol_request_dict: dict,
    material_id: str = "default_layer",
    exp_id: str | None = None,
) -> dict:
    """Deprecated shim — returns standard failure response.

    The legacy LayerBuilder/LayerPipelineRunner path is no longer used.
    All layered structure simulations go through the canonical path:
    ``features.layered_structures.service.submit_layered_structure()``
    which builds prebuilt data via ``_write_combined_lammps_data()``
    and submits to ``run_simulation`` (generic pipeline).

    This shim ensures the placeholder data writer is never executed.

    Returns:
        TaskResult(success=False) with deprecation guidance.
    """
    logger.warning(
        "Deprecated run_layer_simulation called. exp_id=%s, material=%s. "
        "Use features.layered_structures.service.submit_layered_structure().",
        exp_id,
        material_id,
    )
    return TaskResult(
        success=False,
        exp_id=exp_id,
        error=(
            "run_layer_simulation is deprecated. "
            "Use features.layered_structures.service.submit_layered_structure() "
            "which provides full topology via the canonical layered writer."
        ),
    ).to_dict()


# =============================================================================
# Phase 5.1: Additive DOE Batch Job Binder Cell task
# =============================================================================


@shared_task(
    bind=True,
    name="orchestrator.tasks.run_additive_batch_job_binder_cell",
    queue="batch_job_binder_cell",
)
def run_additive_batch_job_binder_cell(self, batch_job_spec_dict: dict) -> dict:
    """Run an additive DOE batch Binder Cell job.

    Deserializes BatchJobBinderCellSpec from dict, creates AdditiveBatchJobBinderCellRunner,
    and submits all DOE jobs.

    Args:
        batch_job_spec_dict: BatchJobBinderCellSpec fields as dictionary.

    Returns:
        BatchJobBinderCellResult as dictionary.
    """
    from database.repositories.experiment_repo import ExperimentRepository
    from orchestrator.batch_job_binder_cell import (
        AdditiveBatchJobBinderCellRunner,
        BatchJobBinderCellSpec,
    )
    from orchestrator.celery_job_manager import CeleryJobManager
    from orchestrator.gpu_service import get_gpu_service

    task_id = self.request.id
    logger.info(f"Task {task_id}: Starting additive batch Binder Cell job")

    try:
        spec = BatchJobBinderCellSpec(**batch_job_spec_dict)

        def _submit(session):
            experiment_repo = ExperimentRepository(session)
            job_manager = CeleryJobManager(gpu_tracker=get_gpu_service())
            runner = AdditiveBatchJobBinderCellRunner(
                experiment_repo=experiment_repo,
                job_manager=job_manager,
            )
            return runner.submit(spec)

        result = run_in_task_session(_submit)

        return {
            "success": True,
            "batch_job_id": result.batch_job_id,
            "total": result.total,
            "submitted": result.submitted,
            "duplicates": result.duplicates,
            "errors": result.errors,
        }

    except Exception as e:
        logger.error(f"Task {task_id}: Additive batch Binder Cell job failed - {e}")
        return {
            "success": False,
            "error": str(e),
        }


@shared_task(
    name="orchestrator.tasks.ml_continuous_learning_check",
    queue="default",
)
def ml_continuous_learning_check() -> dict:
    """Run periodic continuous-learning check and optional retraining.

    PR 2 (Codex Round 5): the loop auto-inherits the champion's CED label
    method (``training_config_json["e_intra_method"]``) so periodic Celery
    retraining stays on the deployed champion's label contract instead of
    silently reverting to Method 1 baseline.
    """
    from api.deps import _resolve_champion_e_intra_method
    from orchestrator.continuous_loop import ContinuousLearningLoop

    def _run(session):
        # Critical path (Codex Round 7): periodic retraining must not
        # silently drift back to Method 1 baseline if the registry query
        # fails — re-raise instead.
        method = _resolve_champion_e_intra_method(session, strict=True)
        return ContinuousLearningLoop(session, e_intra_method=method).run_check()

    return run_in_task_session(_run)


@shared_task(
    bind=True,
    name="orchestrator.tasks.run_cpu_rerun_einter",
    max_retries=1,
    soft_time_limit=86400,
    queue="analysis.cpu",
)
def run_cpu_rerun_einter(
    self,
    exp_id: str,
    job_id: str,
    metrics: list[str] | None = None,
) -> dict:
    """CPU-only rerun for precise E_inter calculation.

    GPU 본 계산 완료 후 호출. kspace yes로 장거리 쿨롱 포함.
    실패해도 parent experiment는 completed 유지.

    Args:
        exp_id: Experiment ID
        job_id: Analysis job ID
        metrics: List of metrics to compute

    Returns:
        Task result dictionary
    """
    from pathlib import Path

    from common.hashing import compute_content_hash
    from contracts.schemas import GroupEnergySpec, ProtocolResult, StudyType
    from database.connection import session_scope
    from database.models import AnalysisJobModel, ExperimentModel
    from protocols.cpu_rerun_generator import DEFAULT_CPU_RERUN_GENERATOR

    task_id = self.request.id
    start_time = datetime.now(UTC)

    def _update_job_status(
        status: str, error_message: str | None = None, result_json: dict | None = None
    ) -> None:
        """Update analysis job status in DB."""
        with session_scope() as session:
            job = (
                session.query(AnalysisJobModel)
                .filter(AnalysisJobModel.analysis_job_id == job_id)
                .first()
            )
            if job:
                job.status = status
                if error_message:
                    job.error_message = error_message
                if result_json:
                    job.result_json = result_json
                if status == "running":
                    job.started_at = datetime.now(UTC)
                    job.celery_task_id = task_id
                elif status in ("completed", "failed"):
                    job.completed_at = datetime.now(UTC)
                    job.wall_time_seconds = (datetime.now(UTC) - start_time).total_seconds()

    try:
        _update_job_status("running")
        logger.info(f"Starting CPU rerun for exp_id={exp_id}, job_id={job_id}")

        # 1. Load experiment data with proper path resolution
        with session_scope() as session:
            exp = session.query(ExperimentModel).filter(ExperimentModel.exp_id == exp_id).first()
            if not exp:
                raise RuntimeError(f"Experiment {exp_id} not found")
            if exp.status != "completed":
                raise RuntimeError(f"Experiment not completed: {exp.status}")

            lammps_result = exp.lammps_result_json or {}
            study_type_str = exp.study_type or "bulk"
            study_type = (
                StudyType(study_type_str) if study_type_str in StudyType else StudyType.BULK
            )
            ff_type = exp.ff_type or "bulk_ff_gaff2"
            if ff_type != "bulk_ff_gaff2":
                raise RuntimeError(
                    f"CPU rerun E_inter v1 supports only bulk_ff_gaff2, got {ff_type}"
                )
            temperature_K = exp.temperature_K or 298.0

            # Get group_energy_spec from lammps_result
            group_spec_data = lammps_result.get("group_energy_spec")
            if not group_spec_data:
                raise RuntimeError("No group_energy_spec found in experiment")

            group_energy_spec = GroupEnergySpec.model_validate(group_spec_data)

            # Path resolution priority: lammps_working_dir > input_file_path.parent > data_file_path.parent
            work_dir: Path | None = None
            if exp.lammps_working_dir:
                work_dir = Path(exp.lammps_working_dir)
            elif exp.input_file_path:
                work_dir = Path(exp.input_file_path).parent
            elif exp.data_file_path:
                work_dir = Path(exp.data_file_path).parent

            if work_dir is None or not work_dir.exists():
                from common.pathing import get_experiment_path

                work_dir = get_experiment_path(exp_id)

            # Data file resolution
            data_file: Path | None = None
            if exp.data_file_path:
                data_file = Path(exp.data_file_path)
            if data_file is None or not data_file.exists():
                data_file = work_dir / "data.lammps"

            if not data_file.exists():
                raise FileNotFoundError(f"Data file not found: {data_file}")

            # Trajectory file resolution from lammps_result_json.dump_files
            dump_files = lammps_result.get("dump_files", [])
            trajectory_file: Path | None = None

            # Priority: npt_production > npt_equilibration > viscosity_nemd
            priority_patterns = ["npt_production", "npt_equilibration", "viscosity_nemd"]
            for pattern in priority_patterns:
                for dump_path in dump_files:
                    if pattern in str(dump_path):
                        candidate = Path(dump_path)
                        if candidate.exists():
                            trajectory_file = candidate
                            break
                if trajectory_file:
                    break

            # Fallback to first existing dump file
            if trajectory_file is None:
                for dump_path in dump_files:
                    candidate = Path(dump_path)
                    if candidate.exists():
                        trajectory_file = candidate
                        break

            # Ultimate fallback: check standard paths in work_dir
            if trajectory_file is None:
                for pattern in priority_patterns:
                    candidate = work_dir / f"dump_{pattern}.lammpstrj"
                    if candidate.exists():
                        trajectory_file = candidate
                        break

            if trajectory_file is None:
                raise FileNotFoundError(f"No trajectory file found for {exp_id}")

        # 2. Generate CPU rerun script (SSOT reuse)
        rerun_script = DEFAULT_CPU_RERUN_GENERATOR.generate(
            data_file=data_file,
            trajectory_file=trajectory_file,
            group_energy_spec=group_energy_spec,
            output_dir=work_dir,
            study_type=study_type,
            ff_config_key=ff_type,
        )
        logger.info(f"Generated CPU rerun script: {rerun_script}")

        # 3. Create ProtocolResult for LAMMPSRunner
        protocol_hash = compute_content_hash(
            {"type": "cpu_rerun_einter", "exp_id": exp_id, "job_id": job_id},
            length=8,
        )
        protocol_result = ProtocolResult(
            input_script_path=str(rerun_script),
            expected_outputs=["log.rerun_einter.lammps"],
            estimated_steps=1,  # rerun processes existing trajectory
            protocol_hash=f"cpu_rerun_einter:{protocol_hash}",
            stabilization_chain=["cpu_rerun_einter"],
        )

        # 4. Run CPU-only LAMMPS (no KOKKOS)
        from orchestrator.lammps_runner import LAMMPSConfig, LAMMPSRunner

        config = LAMMPSConfig(
            gpu_enabled=False,
            accel_mode="mpi_only",
            log_suffix=".rerun_einter.lammps",
            timeout_seconds=86400,
        )
        runner = LAMMPSRunner(config, work_dir=work_dir)
        result = runner.run(protocol_result, exp_id=exp_id)

        if not result.success:
            raise RuntimeError(f"CPU rerun failed: {result.error_message}")

        # 5. Parse rerun log and store precise metrics
        rerun_log_path = work_dir / "log.rerun_einter.lammps"
        if not rerun_log_path.exists():
            # Try alternate log file names
            for log_name in ["log.lammps.rerun_einter", "log.rerun_einter"]:
                alt_path = work_dir / log_name
                if alt_path.exists():
                    rerun_log_path = alt_path
                    break

        precise_metrics = _parse_and_store_precise_einter_metrics(
            exp_id=exp_id,
            job_id=job_id,
            rerun_log_path=rerun_log_path,
            group_energy_spec=group_energy_spec,
            study_type=study_type,
            temperature_K=temperature_K,
            trajectory_file=trajectory_file,
            namespace=ff_type,
        )

        # Fail if no precise metrics were stored (Finding #4)
        if not precise_metrics:
            raise RuntimeError("No precise E_inter metrics could be parsed or stored")

        logger.info(
            f"CPU rerun completed for exp_id={exp_id}, stored {len(precise_metrics)} metrics"
        )

        _update_job_status("completed", result_json={"metrics": precise_metrics})
        return {
            "status": "completed",
            "exp_id": exp_id,
            "job_id": job_id,
            "metrics": precise_metrics,
            "duration_seconds": (datetime.now(UTC) - start_time).total_seconds(),
        }

    except Exception as exc:
        logger.exception(f"CPU rerun failed for {exp_id}: {exc}")
        _update_job_status("failed", str(exc))
        # Parent experiment remains completed (failure isolation)
        return {
            "status": "failed",
            "exp_id": exp_id,
            "job_id": job_id,
            "error": str(exc),
        }


def _parse_and_store_precise_einter_metrics(
    exp_id: str,
    job_id: str,
    rerun_log_path: Path,
    group_energy_spec: GroupEnergySpec,
    study_type: StudyType,
    temperature_K: float,
    trajectory_file: Path,
    namespace: str = "bulk_ff_gaff2",
) -> list[str]:
    """Parse CPU rerun log and store precise E_inter metrics.

    Preserves existing short-range metrics as *_short_range and upserts
    precise values as canonical metrics with proper provenance metadata.

    Uses MetricRepository.upsert() to ensure namespace is always set (Finding #3).
    Pair details stored in metadata_json.pair_energies rather than separate
    e_inter_pair_* metrics to match registry SSOT (Finding #7).

    Args:
        exp_id: Experiment ID
        job_id: Analysis job ID
        rerun_log_path: Path to CPU rerun log file
        group_energy_spec: Group energy specification
        study_type: Study type
        temperature_K: Temperature
        trajectory_file: Path to trajectory file
        namespace: Metric namespace (default: bulk_ff_gaff2)

    Returns:
        List of stored metric names

    Raises:
        RuntimeError: If log file not found or no metrics could be parsed
    """
    import numpy as np

    from database.connection import session_scope
    from database.repositories.metric_repo import MetricRepository
    from parsers.log_parser import LogParser

    stored_metrics: list[str] = []

    if not rerun_log_path.exists():
        raise RuntimeError(f"Rerun log not found: {rerun_log_path}")

    # Parse rerun log (Finding #2: use parse() not parse_log())
    parser = LogParser()
    parse_result = parser.parse(rerun_log_path)
    thermo_data = parse_result.thermo_data

    if not thermo_data:
        raise RuntimeError(f"No thermo data parsed from {rerun_log_path}")

    # Extract group/group compute values (c_gg_*)
    precise_values: dict[str, float] = {}
    for pair in group_energy_spec.pairs:
        col_name = f"c_gg_{pair.label}"
        if col_name in thermo_data:
            values = thermo_data[col_name]
            if values:
                # Take mean of all rerun frames
                precise_values[pair.label] = float(np.mean(values))

    if not precise_values:
        raise RuntimeError("No group/group energy values found in rerun log")

    # Calculate precise e_inter_total
    e_inter_total_precise = sum(precise_values.values())

    # Metadata for precise metrics (Finding #7: store pair details in metadata)
    precise_metadata = {
        "analysis_mode": "cpu_rerun_precise",
        "includes_long_range_kspace": True,
        "analysis_job_id": job_id,
        "source_dump_file": str(trajectory_file),
        "source_log_file": str(rerun_log_path),
        "pair_energies": precise_values,  # Store pair breakdown in metadata
    }

    with session_scope() as session:
        metric_repo = MetricRepository(session)

        # Check for existing e_inter_total to preserve as short_range
        from database.models import MetricModel

        existing_einter = (
            session.query(MetricModel)
            .filter(
                MetricModel.exp_id == exp_id,
                MetricModel.metric_name == "e_inter_total",
            )
            .first()
        )

        # Preserve existing short-range value in metadata (Codex #1: no separate metric)
        short_range_preserved = None
        if existing_einter and existing_einter.value is not None:
            existing_meta = existing_einter.metadata_json or {}
            if existing_meta.get("analysis_mode") != "cpu_rerun_precise":
                short_range_preserved = {
                    "value": existing_einter.value,
                    "preserved_at": datetime.now(UTC).isoformat(),
                    "original_metadata": existing_meta,
                }

        # Include short_range_value in precise metadata if preserved
        if short_range_preserved:
            precise_metadata["short_range_value"] = short_range_preserved

        # Upsert precise e_inter_total (Finding #3: use MetricRepository)
        metric_repo.upsert(
            exp_id=exp_id,
            metric_name="e_inter_total",
            value=e_inter_total_precise,
            unit="kcal/mol",
            namespace=namespace,
            metadata=precise_metadata,
        )
        stored_metrics.append("e_inter_total")

        session.commit()

    logger.info(f"Stored {len(stored_metrics)} precise E_inter metrics for {exp_id}")
    return stored_metrics
