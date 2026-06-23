"""
Task runner helpers: core simulation execution, pipeline creation, artifact management.

Extracted from tasks.py — NO functional changes, only code organization.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

try:
    from celery.exceptions import SoftTimeLimitExceeded
except Exception:  # pragma: no cover - fallback for non-Celery test envs

    class SoftTimeLimitExceeded(Exception):
        """Fallback used when Celery is unavailable in lightweight test envs."""


from common.logging import get_logger
from contracts.policies.forcefield import get_ff_display_label, get_ff_version
from contracts.schemas import (
    BuildRequest,
    ProtocolRequest,
    RunTier,
)
from orchestrator.exp_id_helper import generate_exp_id_from_material
from orchestrator.task_common import (
    TaskResult,
    get_experiment_work_dir,
    run_in_task_session,
    run_in_task_session_commit,
)
from orchestrator.task_maintenance import (
    _acquire_exp_lock,
    _get_experiment_lifecycle_by_task_id,
    _is_duplicate_active_execution,
    _mark_experiment_ready_with_artifact,
    _release_exp_lock,
    _trigger_ready_scheduler,
    _update_experiment_status_by_task_id,
)

if TYPE_CHECKING:
    from orchestrator.layer_pipeline import LayerPipelineRunner
    from orchestrator.pipeline import Pipeline

logger = get_logger("orchestrator.tasks")


def _get_e_intra_adapter(session, *, temperature_tolerance_k=None):  # type: ignore[no-untyped-def]
    """Create a DB-backed E_intra adapter compatible with EIntraStore interface.

    The CED calculator calls ``e_intra_store.get(key)`` which returns
    ``EIntraValue | None``.  ``EIntraRepository.get_value()`` has the
    same signature, so we wrap it in a lightweight adapter.

    Args:
        session: DB session.
        temperature_tolerance_k: Temperature tolerance for DB lookup.
            ``0.0`` for exact-only, ``None`` for DB default (5K policy).
    """
    try:
        from database.repositories.e_intra_repo import EIntraRepository

        repo = EIntraRepository(session)
        tol_k = temperature_tolerance_k

        class _DBAdapter:
            """Adapter: EIntraRepository → EIntraStore interface for CED."""

            def get(self, key):  # type: ignore[no-untyped-def]
                return repo.get_value(key, temperature_tolerance_k=tol_k)

            def list_keys(self):  # type: ignore[no-untyped-def]
                return []  # DB adapter does not need list_keys

        return _DBAdapter()
    except Exception as exc:
        logger.warning("Failed to create E_intra DB adapter: %s", exc)
        return None


def make_metrics_calculator(session=None, *, ced_coverage_mode="exact_required"):  # type: ignore[no-untyped-def]
    """Create a MetricsCalculator with DB-backed E_intra adapter.

    Use this factory everywhere a MetricsCalculator is needed to ensure
    consistent exact-temperature CED lookup.  Avoids creating bare
    calculators that silently fall back to PE/V approximation.

    Args:
        session: DB session.
        ced_coverage_mode: CED coverage mode. ``"exact_required"`` (default)
            uses ``temperature_tolerance_k=0.0`` for exact-only DB lookup.
            ``"allow_tolerance"`` and ``"allow_missing_pe_over_v"`` use DB
            default tolerance (5K policy).
    """
    from metrics.array_storage import ArrayStorage
    from metrics.calculator import MetricsCalculator

    tol_k = 0.0 if ced_coverage_mode == "exact_required" else None
    adapter = _get_e_intra_adapter(session, temperature_tolerance_k=tol_k) if session else None
    return MetricsCalculator(
        array_storage=ArrayStorage(),
        e_intra_store=adapter,
        ced_coverage_mode=ced_coverage_mode,
    )


def restore_run_result_metadata(run_result, exp_id: str, session=None):  # type: ignore[no-untyped-def]
    """Restore CED lookup metadata on a bare LAMMPSRunResult from DB.

    Use this in reanalysis/scan/admin paths where run_result is constructed
    without pipeline context.  Populates mol_counts, force_field, ff_version,
    temperature_K, and persisted E_intra method metadata from the
    experiments + experiment_molecules tables.
    """
    if not exp_id or not session:
        return
    try:
        from database.models import ExperimentModel
        from database.models.experiment import ExperimentMoleculeModel
        from database.models.molecule import MoleculeModel

        exp = session.query(ExperimentModel).filter_by(exp_id=exp_id).first()
        if exp is None:
            return

        run_result.temperature_K = exp.temperature_K or 298.0
        run_result.force_field = get_ff_display_label(exp.ff_type or "bulk_ff_gaff2")
        run_result.ff_version = get_ff_version(exp.ff_type or "bulk_ff_gaff2")
        run_result.study_type = exp.study_type or "bulk"
        exp_meta = getattr(exp, "metadata_json", None) or {}
        from contracts.schema_enums import normalize_e_intra_method

        run_result.e_intra_method = normalize_e_intra_method(
            exp_meta.get("e_intra_method") or getattr(run_result, "e_intra_method", None)
        )
        if exp_meta.get("vacuum_cutoff_a") is not None:
            run_result.vacuum_cutoff_a = exp_meta.get("vacuum_cutoff_a")
        ced_meta = (exp_meta.get("ced_provenance") or {}) if isinstance(exp_meta, dict) else {}
        meta_by_layer = ced_meta.get("mol_counts_by_layer") or {}
        if isinstance(meta_by_layer, dict):
            run_result.mol_counts_by_layer = {
                str(layer_label): {
                    str(mol_id): int(count)
                    for mol_id, count in (mol_counts or {}).items()
                    if str(mol_id).strip() and int(count) > 0
                }
                for layer_label, mol_counts in meta_by_layer.items()
                if str(layer_label).strip() and isinstance(mol_counts, dict)
            }
        meta_volumes = ced_meta.get("layer_volumes_A3") or {}
        if isinstance(meta_volumes, dict):
            run_result.layer_volumes_A3 = {
                str(layer_label): float(volume)
                for layer_label, volume in meta_volumes.items()
                if str(layer_label).strip() and float(volume) > 0.0
            }
        meta_labels = ced_meta.get("layer_labels") or []
        if isinstance(meta_labels, list):
            run_result.layer_labels = [str(label) for label in meta_labels if str(label).strip()]

        # Restore mol_counts from experiment_molecules
        mol_rows = (
            session.query(ExperimentMoleculeModel.molecule_id, ExperimentMoleculeModel.count)
            .filter(ExperimentMoleculeModel.experiment_id == exp.id)
            .all()
        )
        if mol_rows:
            mol_ids = {r.molecule_id: r.count for r in mol_rows}
            # Resolve molecule_id (int FK) → mol_id (string)
            id_to_mol = {}
            for mid in mol_ids:
                mol = session.query(MoleculeModel).filter_by(id=mid).first()
                if mol:
                    id_to_mol[mol.mol_id] = mol_ids[mid]
            run_result.mol_counts = id_to_mol
    except Exception as exc:
        logger.warning("Failed to restore run_result metadata for %s: %s", exp_id, exc)


def _get_pipeline(
    task_id: str | None = None,
    work_dir: Path | None = None,
    ff_name: str | None = None,
    exp_id: str | None = None,
    *,
    allocate_gpu: bool = True,
    preallocated_gpu_id: int | None = None,
    run_tier: RunTier | None = None,
    actual_atom_count: int | None = None,
) -> tuple[Pipeline, int | None]:
    """
    Lazy import of pipeline to avoid circular imports.

    Args:
        task_id: Celery task ID for GPU allocation tracking
        work_dir: Working directory for structure builder (permanent storage)
        ff_name: Force-field registry key for topology generation
        exp_id: Experiment ID for GPU allocation (fallback when celery_task_id not found)
        run_tier: Run tier for determining target_atoms (GPU thread scaling fallback)
        actual_atom_count: Actual atom count from build result (preferred for GPU thread scaling)

    Returns:
        Tuple of (Pipeline instance, allocated GPU ID or None)

    Raises:
        OrchestrationError: If no GPU is available
    """
    from builder.structure_builder import StructureBuilder
    from config.settings import get_settings
    from contracts.errors import ErrorCode, OrchestrationError
    from database.connection import get_session
    from database.repositories.experiment_repo import ExperimentRepository
    from database.repositories.metric_repo import MetricRepository
    from orchestrator.celery_job_manager import CeleryJobManager
    from orchestrator.lammps_runner import (
        LAMMPSConfig,
        LAMMPSRunner,
        calculate_threads_per_job,
    )
    from orchestrator.pipeline import Pipeline
    from orchestrator.process_tracker import ProcessTracker
    from protocols.lammps_input import LAMMPSInputGenerator

    # Get LAMMPS settings from config
    app_settings = get_settings()

    # Probe LAMMPS binary capabilities (lazy cached per worker process)
    from orchestrator.lammps_probe import get_lammps_caps

    try:
        lammps_caps = get_lammps_caps(
            app_settings.lammps.executable, mpi_command=app_settings.lammps.mpi_command
        )
        logger.info(
            f"LAMMPS caps: accel_mode={lammps_caps.accel_mode}, "
            f"kokkos={lammps_caps.kokkos_backend}, gpu={lammps_caps.gpu_detected}"
        )
    except Exception as e:
        logger.warning(f"LAMMPS probing failed: {e}, using defaults")
        lammps_caps = None

    # GPU allocation using GPUService (Single Source of Truth)
    # GPUService.initialize() reads settings.json for selected_gpus — no need to read it here.
    from monitoring.gpu_collector import detect_system_gpus
    from orchestrator.gpu_service import get_gpu_service

    gpu_service = get_gpu_service()
    gpu_service.initialize()  # Idempotent, loads selected_gpus from settings.json

    # Validate selected_gpus against detected GPUs (prevent ghost GPUs)
    # Policy: Trust settings.json selected_gpus even if detect fails (nvidia-smi may be temporarily unavailable)
    try:
        detected = detect_system_gpus()
        detected_ids = [g["gpu_id"] for g in detected] if detected else []

        if detected_ids:
            # Validate only if detection succeeded - remove GPUs not in detected list
            gpu_service.validate_selected_gpus(detected_ids)
        # If detect fails but selected_gpus is configured, trust settings.json
        # This prevents false negatives when nvidia-smi is temporarily unavailable
    except Exception as e:
        logger.warning(f"GPU detection failed: {e}, trusting settings.json selected_gpus")
        detected_ids = []

    # Determine gpu_enabled from GPUService selected_gpus or detection
    # If caps probe determined CPU-only mode, skip GPU allocation to avoid
    # occupying a GPU slot that won't actually be used.
    has_selected_gpus = len(gpu_service.selected_gpus) > 0
    has_detected_gpus = len(detected_ids) > 0
    gpu_possible = has_selected_gpus or has_detected_gpus
    caps_needs_gpu = lammps_caps is None or lammps_caps.accel_mode.value == "kokkos_gpu"
    gpu_enabled = (
        gpu_possible and caps_needs_gpu and (allocate_gpu or preallocated_gpu_id is not None)
    )
    if gpu_enabled:
        logger.info(
            f"GPU mode enabled: selected={gpu_service.selected_gpus}, detected={detected_ids}"
        )
    else:
        logger.info("GPU allocation disabled for this phase, running in CPU mode")

    if preallocated_gpu_id is not None:
        gpu_id = preallocated_gpu_id
    else:
        # Allocate GPU using GPUService (ensures 1 GPU per job, DB-based)
        # Use allocate_gpu() with exp_id for fallback when celery_task_id not found
        gpu_id = gpu_service.allocate_gpu(job_id=task_id, exp_id=exp_id) if gpu_enabled else None

    if gpu_enabled and allocate_gpu and gpu_id is None:
        raise OrchestrationError(
            code=ErrorCode.GPU_NOT_AVAILABLE,
            message="No GPU available for simulation, task will be retried",
        )

    # Calculate threads per job based on system CPU cores, GPU count, accel mode, and atom count
    # This ensures optimal CPU utilization without over-subscription
    # GPU thread scaling (v00.97.00): larger systems need more CPU threads for data prep
    selected_gpu_count = len(gpu_service.selected_gpus) or 1
    accel_mode = lammps_caps.accel_mode.value if lammps_caps else None

    # Use actual_atom_count if provided (most accurate), otherwise fall back to tier policy
    # This ensures GPU thread scaling works correctly even when run_tier is not passed
    if actual_atom_count is not None:
        effective_atom_count = actual_atom_count
    else:
        from contracts.policies.tier import DEFAULT_TIER_POLICY

        effective_tier = run_tier if run_tier is not None else RunTier.SCREENING
        tier_config = DEFAULT_TIER_POLICY.get_tier_config(effective_tier)
        effective_atom_count = tier_config.target_atoms

    # Per-job thread count is capped by co-location density (slots_per_gpu) so
    # N co-located jobs don't oversubscribe host cores (v01.05.56 C). Mode-aware:
    # MPS = policy N per whole GPU; MIG/none = 1 per device (a MIG instance/whole
    # GPU runs a single job), so selected_gpu_count x slots_per_gpu = the real
    # concurrent-job count in every mode.
    from contracts.policies.budget import DEFAULT_JOB_BUDGETING_POLICY
    from monitoring.gpu_collector import resolve_sharing_mode

    slots_per_gpu = (
        max(1, int(DEFAULT_JOB_BUDGETING_POLICY.max_concurrent_jobs_per_gpu))
        if resolve_sharing_mode() == "mps"
        else 1
    )
    num_threads = calculate_threads_per_job(
        selected_gpu_count,
        accel_mode=accel_mode,
        target_atoms=effective_atom_count,
        slots_per_gpu=slots_per_gpu,
    )

    # Single-rank GPU runs (kokkos_gpu, 1 MPI rank) drop the `mpirun -np 1`
    # wrapper: it adds only OpenMPI env that trips a (non-fatal) KOKKOS binding
    # warning and pins all OpenMP threads to one core, hurting co-located
    # throughput. Running lmp directly keeps the full CPU mask and KOKKOS GPU
    # init / device selection intact (v01.05.56 C). CPU/MPI modes keep the launcher.
    mpi_executable = "" if accel_mode == "kokkos_gpu" else app_settings.lammps.mpi_command

    # Create LAMMPS config with executable from settings
    lammps_config = LAMMPSConfig(
        executable=app_settings.lammps.executable,
        mpi_executable=mpi_executable,
        num_procs=app_settings.lammps.default_num_procs,
        num_threads=num_threads,
        gpu_enabled=gpu_enabled,
        gpu_id=gpu_id if gpu_id is not None else 0,
        accel_mode=lammps_caps.accel_mode.value if lammps_caps else None,
    )
    logger.info(
        f"LAMMPS config: gpu_enabled={gpu_enabled}, gpu_id={gpu_id}, "
        f"accel_mode={lammps_config.accel_mode}, "
        f"num_threads={num_threads} (cpus={os.cpu_count()}, gpus={selected_gpu_count})"
    )

    # Create ProcessTracker for real-time monitoring
    process_tracker = ProcessTracker()

    # Initialize MoleculeDB with aging library (combined config: binder + single + additives)
    from builder.molecule_db_loader import create_molecule_db

    molecule_db = create_molecule_db(allow_mock=True)
    logger.info(f"Loaded molecule library, {molecule_db.count()} molecules")

    # Create StructureBuilder with initialized MoleculeDB and permanent work directory
    builder_ff_name = ff_name or "gaff2"
    builder = (
        StructureBuilder(molecule_db=molecule_db, work_dir=work_dir, ff_name=builder_ff_name)
        if work_dir
        else StructureBuilder(molecule_db=molecule_db, ff_name=builder_ff_name)
    )

    session = get_session()
    job_manager = CeleryJobManager(gpu_tracker=gpu_service)
    pipeline = Pipeline(
        builder=builder,
        protocol=LAMMPSInputGenerator(caps=lammps_caps),
        calculator=make_metrics_calculator(session),
        repository=ExperimentRepository(session),
        runner=LAMMPSRunner(config=lammps_config, process_tracker=process_tracker),
        metric_repository=MetricRepository(session),
        job_manager=job_manager,
    )
    return pipeline, gpu_id


def _validate_prepared_run_owner(
    exp_id: str,
    task_id: str,
    gpu_id: int,
    dispatch_attempt_id: str | None = None,
) -> tuple[bool, str]:
    """
    Validate that this run_prepared_simulation task is the active owner.

    Returns:
        (ok, reason). When ok is False, caller must no-op and exit.
    """
    try:
        from sqlalchemy import or_

        from database.models import ExperimentModel
        from database.repositories.experiment_repo import ExperimentRepository

        def _op(session):
            repo = ExperimentRepository(session)
            exp = repo.get_by_id(exp_id)
            if exp is None:
                return False, "experiment_missing"

            status = str(exp.status or "").lower()
            if status in {"completed", "failed", "cancelled", "timeout"}:
                return False, f"terminal_status:{status}"

            if dispatch_attempt_id:
                metadata = dict(getattr(exp, "metadata_json", None) or {})
                expected_dispatch_id = str(metadata.get("dispatch_attempt_id") or "").strip()
                if not expected_dispatch_id:
                    return False, (
                        "dispatch_missing:"
                        f"task_id={task_id}, dispatch_attempt_id={dispatch_attempt_id}"
                    )
                if expected_dispatch_id != str(dispatch_attempt_id).strip():
                    return False, (
                        "dispatch_mismatch:"
                        f"expected={expected_dispatch_id}, got={dispatch_attempt_id}"
                    )
            else:
                # Backward compatibility for tasks dispatched before dispatch token rollout.
                active_attempt_id = str(exp.active_attempt_id or "").strip()
                if active_attempt_id and active_attempt_id != task_id:
                    return False, (
                        f"attempt_mismatch:active_attempt_id={active_attempt_id}, task_id={task_id}"
                    )

            allocated_gpu = getattr(exp, "gpu_id_allocated", None)
            if allocated_gpu is not None and int(allocated_gpu) != int(gpu_id):
                return False, f"gpu_mismatch:db={allocated_gpu}, task_gpu={gpu_id}"

            # Atomic ownership claim — closes the TOCTOU between this read-side
            # validation and the ready->running transition. Concurrent/duplicate
            # dispatches of the same exp_id (e.g. overlapping scheduler ticks
            # during post-restart churn) all reach here; this conditional UPDATE
            # lets exactly ONE win. A task wins if the experiment is still
            # `ready` (fresh claim) or already owned by this task_id (idempotent
            # retry). Losers get rowcount 0 -> skipped + GPU released. The single
            # UPDATE serializes (SQLite write lock / row match), so it is
            # race-free without depending on active_attempt_id dispatch timing.
            claimed = (
                session.query(ExperimentModel)
                .filter(
                    ExperimentModel.exp_id == exp_id,
                    ~ExperimentModel.status.in_(
                        ["completed", "failed", "cancelled", "timeout"]
                    ),
                    or_(
                        ExperimentModel.status == "ready",
                        ExperimentModel.active_attempt_id == task_id,
                    ),
                )
                .update(
                    {
                        "status": "running",
                        "active_attempt_id": task_id,
                        "updated_at": datetime.utcnow(),
                    },
                    synchronize_session=False,
                )
            )
            if claimed == 1:
                return True, "ok"
            return False, f"duplicate_claim:task_id={task_id}"

        return run_in_task_session_commit(_op)
    except Exception as exc:
        return False, f"validation_error:{exc}"


def _clear_dispatch_attempt_id(exp_id: str, dispatch_attempt_id: str | None = None) -> None:
    """Best-effort clear of dispatch token."""
    try:
        from database.repositories.experiment_repo import ExperimentRepository

        def _op(session):
            repo = ExperimentRepository(session)
            repo.clear_dispatch_attempt_id(
                exp_id=exp_id,
                expected_dispatch_attempt_id=dispatch_attempt_id if dispatch_attempt_id else None,
            )

        run_in_task_session_commit(_op)
    except Exception as exc:
        logger.debug("Failed to clear dispatch token for %s: %s", exp_id, exc)


def _load_prepared_artifact(exp_id: str) -> dict | None:
    """Load prepared artifact payload for ready->running phase."""
    try:
        from database.repositories.experiment_repo import ExperimentRepository

        def _op(session):
            repo = ExperimentRepository(session)
            exp = repo.get_by_id(exp_id)
            if exp is None:
                return None
            return dict(getattr(exp, "prepared_artifact_json", None) or {})

        return run_in_task_session(_op)
    except Exception as e:
        logger.warning("Failed to load prepared artifact for %s: %s", exp_id, e)
        return None


def _get_layer_pipeline(
    task_id: str | None = None,
    exp_id: str | None = None,
    actual_atom_count: int | None = None,
    run_tier: str | None = None,
) -> tuple[LayerPipelineRunner, int | None]:
    """Create LayerPipelineRunner with real dependencies.

    Mirrors _get_pipeline() pattern but uses LayerBuilder instead of
    StructureBuilder, and LayerPipelineRunner instead of Pipeline.

    Args:
        task_id: Celery task ID for GPU allocation tracking.
        exp_id: Experiment ID for GPU allocation (fallback when celery_task_id not found).
        actual_atom_count: Actual atom count from build result (preferred for GPU thread scaling).
        run_tier: Run tier for GPU thread scaling fallback (when actual_atom_count not available).

    Returns:
        Tuple of (LayerPipelineRunner instance, allocated GPU ID or None).
    """
    from orchestrator.task_layer import get_layer_pipeline

    return get_layer_pipeline(
        task_id=task_id,
        exp_id=exp_id,
        actual_atom_count=actual_atom_count,
        run_tier=run_tier,
    )


def _run_tier_simulation(
    task,
    tier: RunTier,
    composition: dict[str, float],
    temperature_K: float,
    target_atoms: int,
    seed: int,
    material_id: str,
    stage_duration_overrides: list | None = None,
    property_calculations: dict | None = None,
    exp_id: str | None = None,
    build_request: BuildRequest | None = None,
    protocol_request: ProtocolRequest | None = None,
    # Phase 5.1: additive metadata propagation
    additive_type: str | None = None,
    additive_wt: float = 0.0,
    additive_mol_id: str | None = None,
    deferred_gpu_allocation: bool = False,
) -> dict:
    """
    Common logic for tier-based simulations.

    Used by run_screening_simulation, run_confirm_simulation,
    run_viscosity_simulation, and run_simulation (Celery wrapper).

    NOTE: SoftTimeLimitExceeded is NOT handled here. Only viscosity has
    time_limit decorator, so it handles the exception in its wrapper.
    run_simulation also catches it after delegation.

    Args:
        task: Celery bound task (self)
        tier: RunTier enum (SCREENING, CONFIRM, VISCOSITY)
        composition: SARA composition (wt%) - used only if build_request is None
        temperature_K: Temperature in Kelvin - used only if protocol_request is None
        target_atoms: Target atom count - used only if build_request is None
        seed: Random seed - used only if build_request is None
        material_id: Material identifier
        stage_duration_overrides: Optional stage duration overrides
        property_calculations: Optional property calculation settings
        exp_id: Pre-generated experiment ID (generated if None)
        build_request: Pre-created BuildRequest (avoids re-creation if provided)
        protocol_request: Pre-created ProtocolRequest (avoids re-creation if provided)

    Returns:
        TaskResult.to_dict()
    """
    start_time = datetime.now(UTC)
    task_id = task.request.id
    gpu_id = None
    lock_exp_id: str | None = None

    logger.info(f"Task {task_id}: Starting {tier.value} simulation for {material_id}")

    # Set STARTED state for Celery to track
    task.update_state(state="STARTED", meta={"status": "starting", "material_id": material_id})

    # Update experiment status to 'building' only on first attempt
    # Avoid overwriting 'running' status on GPU-not-available retries
    if task.request.retries == 0:
        _update_experiment_status_by_task_id(task_id, "building")

    try:
        # Update to RUNNING state
        task.update_state(state="RUNNING", meta={"status": "building_structure"})

        # Use provided requests or create new ones (avoids redundant re-creation)
        if build_request is None or protocol_request is None:
            from orchestrator.request_factory import create_build_request, create_protocol_request

            if build_request is None:
                build_request = create_build_request(
                    composition=composition,
                    target_atoms=target_atoms,
                    seed=seed,
                    tier=tier,
                )

            if protocol_request is None:
                protocol_request = create_protocol_request(
                    tier=tier,
                    temperature_K=temperature_K,
                )

        # Use provided exp_id or generate one for permanent work directory
        if exp_id is None:
            exp_id = generate_exp_id_from_material(
                material_id=material_id,
                temperature_k=temperature_K,
                ff_type=protocol_request.ff_type.value,
                atom_count=target_atoms,
                seed=seed,
            )

        # Defensive guard: stale queued retries must not re-run completed experiments.
        lifecycle_exp_id, lifecycle_status, lifecycle_completed = (
            _get_experiment_lifecycle_by_task_id(task_id)
        )
        if lifecycle_completed or lifecycle_status == "completed":
            logger.warning(
                f"Task {task_id}: stale execution skipped "
                f"(status={lifecycle_status}, completed_at={lifecycle_completed}, exp_id={lifecycle_exp_id})"
            )
            return TaskResult(
                success=True,
                exp_id=lifecycle_exp_id or exp_id,
                duration_seconds=(datetime.now(UTC) - start_time).total_seconds(),
            ).to_dict()

        # Idempotency: block duplicate active execution for same exp_id.
        if _is_duplicate_active_execution(exp_id, task_id):
            from contracts.errors import ErrorCode, OrchestrationError

            raise OrchestrationError(
                code=ErrorCode.DUPLICATE_EXECUTION_BLOCKED,
                message=f"Duplicate execution blocked for exp_id={exp_id}",
            )

        if not _acquire_exp_lock(exp_id, task_id):
            from contracts.errors import ErrorCode, OrchestrationError

            raise OrchestrationError(
                code=ErrorCode.DUPLICATE_EXECUTION_BLOCKED,
                message=f"Experiment lock already held for exp_id={exp_id}",
            )
        lock_exp_id = exp_id

        # Create per-attempt work directory to prevent log/result collisions.
        work_dir = get_experiment_work_dir(exp_id, attempt_tag=task_id)
        logger.info(f"Task {task_id}: Work directory -> {work_dir}")

        if deferred_gpu_allocation:
            _update_experiment_status_by_task_id(task_id, "building")
            # Build/preparation phase only (CPU), then move to ready queue.
            # Note: allocate_gpu=False means GPU thread scaling doesn't apply here,
            # but we pass run_tier for consistency (actual_atom_count will be known
            # after build, passed to execute_ready_experiment later).
            pipeline, _ = _get_pipeline(
                task_id,
                work_dir=work_dir,
                ff_name=protocol_request.ff_type.value,
                exp_id=exp_id,
                allocate_gpu=False,
                run_tier=tier,
            )
            prepared_payload = pipeline.build_only(
                build_request=build_request,
                protocol_request=protocol_request,
                material_id=material_id,
                exp_id=exp_id,
                stage_duration_overrides=stage_duration_overrides,
            )
            marked_ready = _mark_experiment_ready_with_artifact(
                task_id=task_id,
                exp_id=exp_id,
                prepared_payload=prepared_payload,
                property_calculations=property_calculations,
                additive_type=additive_type,
                additive_wt=additive_wt,
                additive_mol_id=additive_mol_id,
            )
            if not marked_ready:
                raise RuntimeError(f"Failed to store build artifact for exp_id={exp_id}")
            _trigger_ready_scheduler(max_submissions=10)
            return TaskResult(
                success=True,
                exp_id=exp_id,
                metrics={"phase": "build_complete"},
                duration_seconds=(datetime.now(UTC) - start_time).total_seconds(),
            ).to_dict()

        # Legacy immediate path: allocate GPU and run in one task.
        # Pass run_tier for GPU thread scaling (target_atoms from tier policy)
        pipeline, gpu_id = _get_pipeline(
            task_id,
            work_dir=work_dir,
            ff_name=protocol_request.ff_type.value,
            exp_id=exp_id,
            run_tier=tier,
        )

        # Wire optional coarse-grained builder progress into task meta state.
        builder_obj = getattr(pipeline, "builder", None)
        if builder_obj is not None and hasattr(builder_obj, "set_progress_callback"):

            def _on_build_progress(status_text: str, label: str | None = None) -> None:
                # Prefer the fine-grained label when provided so Celery backend
                # consumers (e.g. legacy task-state listeners) receive the
                # same sub-phase message the dashboard shows. Fall back to the
                # coarse status code for backward compatibility.
                task.update_state(state="RUNNING", meta={"status": label or status_text})

            builder_obj.set_progress_callback(_on_build_progress)

        exp_id = pipeline.run(
            build_request,
            protocol_request,
            material_id,
            exp_id=exp_id,
            stage_duration_overrides=stage_duration_overrides,
            property_calculations=property_calculations,
            additive_type=additive_type,
            additive_wt=additive_wt,
            additive_mol_id=additive_mol_id,
        )

        duration = (datetime.now(UTC) - start_time).total_seconds()
        logger.info(f"Task {task_id}: Completed successfully -> {exp_id}")

        # Update experiment status to 'completed' in DB
        _update_experiment_status_by_task_id(task_id, "completed")

        return TaskResult(
            success=True,
            exp_id=exp_id,
            duration_seconds=duration,
        ).to_dict()

    except SoftTimeLimitExceeded:
        # Re-raise to let caller (e.g., run_viscosity_simulation) handle it
        # Only viscosity tasks have time_limit decorator, so only they need
        # to catch this exception with E4003 error code
        raise

    except Exception as e:
        from contracts.errors import ErrorCode, OrchestrationError
        from contracts.policies.failure import DEFAULT_FAILURE_POLICY

        error_msg = str(e)

        # GPU_NOT_AVAILABLE: use dedicated retry policy from failure.py (SSOT)
        if isinstance(e, OrchestrationError) and e.code == ErrorCode.GPU_NOT_AVAILABLE:
            exp_state_exp_id, exp_state, has_completed_at = _get_experiment_lifecycle_by_task_id(
                task_id
            )
            if has_completed_at or exp_state in {"completed", "failed", "cancelled", "timeout"}:
                logger.warning(
                    f"Task {task_id}: skipping GPU retry because experiment is terminal "
                    f"(status={exp_state}, completed_at={has_completed_at}, exp_id={exp_state_exp_id})"
                )
                if exp_state == "completed":
                    return TaskResult(
                        success=True,
                        exp_id=exp_state_exp_id or exp_id,
                        duration_seconds=(datetime.now(UTC) - start_time).total_seconds(),
                    ).to_dict()
                return TaskResult(
                    success=False,
                    exp_id=exp_state_exp_id or exp_id,
                    error=f"Experiment already in terminal state: {exp_state}",
                    duration_seconds=(datetime.now(UTC) - start_time).total_seconds(),
                ).to_dict()

            max_retries = DEFAULT_FAILURE_POLICY.gpu_not_available_max_retries
            delay = DEFAULT_FAILURE_POLICY.gpu_not_available_retry_delay_seconds

            if task.request.retries < max_retries:
                logger.info(
                    f"Task {task_id}: GPU not available, "
                    f"retry {task.request.retries + 1}/{max_retries} in {delay}s"
                )
                raise task.retry(exc=e, countdown=delay, max_retries=max_retries) from e
            else:
                # Max retries exceeded - mark as timeout (not simulation failure)
                wait_hours = max_retries * delay // 3600
                logger.error(
                    f"Task {task_id}: GPU not available after {max_retries} retries ({wait_hours}h)"
                )
                _update_experiment_status_by_task_id(
                    task_id,
                    "timeout",
                    error_code="E8002",
                    error_message=f"GPU not available after {max_retries} retries ({wait_hours}h)",
                )
                return TaskResult(
                    success=False,
                    error=error_msg,
                    duration_seconds=(datetime.now(UTC) - start_time).total_seconds(),
                ).to_dict()

        # Duplicate execution must not be retried.
        if isinstance(e, OrchestrationError) and e.code == ErrorCode.DUPLICATE_EXECUTION_BLOCKED:
            logger.warning(f"Task {task_id}: {e}")
            _update_experiment_status_by_task_id(
                task_id,
                "failed",
                error_code=ErrorCode.DUPLICATE_EXECUTION_BLOCKED.value,
                error_message=str(e),
            )
            return TaskResult(
                success=False,
                exp_id=exp_id,
                error=str(e),
                duration_seconds=(datetime.now(UTC) - start_time).total_seconds(),
            ).to_dict()

        # Other exceptions: use default retry logic
        logger.error(f"Task {task_id}: Failed - {error_msg}")

        if task.request.retries < task.max_retries:
            logger.info(f"Task {task_id}: Retrying (attempt {task.request.retries + 1})")
            raise task.retry(exc=e) from e

        _update_experiment_status_by_task_id(
            task_id, "failed", error_code="E4001", error_message=error_msg
        )

        return TaskResult(
            success=False,
            error=error_msg,
            duration_seconds=(datetime.now(UTC) - start_time).total_seconds(),
        ).to_dict()

    finally:
        # Always release GPU after task completes
        if gpu_id is not None:
            from orchestrator.gpu_service import get_gpu_service

            get_gpu_service().release(gpu_id, task_id=task_id, exp_id=exp_id)
        if lock_exp_id is not None:
            _release_exp_lock(lock_exp_id, task_id)


# ------------------------------------------------------------------
# Restart-from-checkpoint helpers
# ------------------------------------------------------------------


def prepare_restart_artifact(
    exp_id: str,
    restart_point: object,
) -> bool:
    """Prepare a restart artifact and transition experiment to *ready*.

    Reuses the existing ``prepared_artifact_json → ready →
    run_prepared_simulation`` pipeline.  The new artifact's
    ``protocol_result.input_script_path`` points to the generated
    ``in.restart.lammps`` in a fresh attempt directory.

    Args:
        exp_id: Experiment to restart.
        restart_point: Discovered restart position (``RestartPoint``).

    Returns:
        True if the artifact was persisted and status set to *ready*.
    """
    try:
        import uuid

        from database.connection import session_scope
        from database.repositories.experiment_repo import ExperimentRepository
        from orchestrator.task_common import get_experiment_work_dir

        # Phase 1: Read experiment state and reset terminal status to pending
        # so the subsequent ready transition is valid (failed→pending→ready).
        with session_scope() as session:
            repo = ExperimentRepository(session)
            exp = repo.get_by_id(exp_id)
            if exp is None:
                logger.warning("prepare_restart_artifact: experiment %s not found", exp_id)
                return False

            artifact = exp.prepared_artifact_json
            if not artifact:
                logger.warning("prepare_restart_artifact: no prepared artifact for %s", exp_id)
                return False

            # Reset terminal status → pending (allowed by state machine SSOT).
            if exp.status in ("failed", "cancelled", "timeout"):
                repo.update_status(exp_id, "pending")
                exp.error_code = None
                exp.error_message = None
                session.commit()

            compiled_plan = (exp.metadata_json or {}).get("compiled_execution_plan")
            if not compiled_plan:
                logger.warning("prepare_restart_artifact: no compiled plan for %s", exp_id)
                return False

        # Phase 2: Generate restart script (no DB session needed).
        attempt_tag = f"restart-{uuid.uuid4().hex[:8]}"
        new_work_dir = get_experiment_work_dir(exp_id, attempt_tag=attempt_tag)

        from contracts.schemas import ProtocolRequest
        from protocols.lammps_input import LAMMPSInputGenerator

        protocol_request = ProtocolRequest.model_validate(artifact["protocol_request"])
        original_data_file = None
        if artifact.get("protocol_result", {}).get("input_script_path"):
            candidate = (
                Path(artifact["protocol_result"]["input_script_path"]).parent / "data.lammps"
            )
            if candidate.is_file():
                original_data_file = candidate

        # Recover stage duration overrides from original artifact.
        stage_duration_overrides = None
        raw_overrides = artifact.get("stage_duration_overrides")
        if raw_overrides:
            from protocols.duration_adjuster import StageDurationOverride

            stage_duration_overrides = [StageDurationOverride(**o) for o in raw_overrides]

        generator = LAMMPSInputGenerator()
        restart_script_path = new_work_dir / "in.restart.lammps"
        restart_result = generator.generate_restart_script(
            request=protocol_request,
            restart_file=restart_point.restart_file,
            remaining_stage_indices=restart_point.remaining_stage_indices,
            output_path=restart_script_path,
            original_data_file=original_data_file,
            stage_duration_overrides=stage_duration_overrides,
        )

        # Replace the full protocol_result with the restart result
        # so that estimated_steps and protocol_hash reflect the
        # remaining stages (progress/ETA accuracy).
        updated_artifact = dict(artifact)
        updated_artifact["protocol_result"] = restart_result.model_dump()
        updated_artifact["restart_context"] = {
            "source_attempt_dir": str(restart_point.source_attempt_dir),
            "restart_file": str(restart_point.restart_file),
            "resume_from_stage_index": restart_point.completed_stage_index + 1,
            "resume_from_stage_name": (
                compiled_plan["stages"][restart_point.completed_stage_index + 1]["stage_key"]
                if restart_point.completed_stage_index + 1 < len(compiled_plan["stages"])
                else "unknown"
            ),
        }

        # Phase 3: Mark ready via canonical helper (owns its own session).
        from orchestrator.task_maintenance import _mark_experiment_ready_with_artifact

        marked = _mark_experiment_ready_with_artifact(
            task_id=attempt_tag,
            exp_id=exp_id,
            prepared_payload=updated_artifact,
            property_calculations=artifact.get("property_calculations"),
            additive_type=(artifact.get("additive") or {}).get("type"),
            additive_wt=(artifact.get("additive") or {}).get("wt", 0.0),
            additive_mol_id=(artifact.get("additive") or {}).get("mol_id"),
        )
        if not marked:
            logger.warning("prepare_restart_artifact: failed to mark %s ready", exp_id)
            return False

        _trigger_ready_scheduler(max_submissions=5)
        logger.info(
            "prepare_restart_artifact: %s queued for restart from stage %s",
            exp_id,
            restart_point.completed_stage_name,
        )
        return True

    except Exception as e:
        logger.error("prepare_restart_artifact failed for %s: %s", exp_id, e, exc_info=True)
        return False
