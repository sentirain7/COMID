"""Layer-simulation task helpers."""

from __future__ import annotations

import os

from common.logging import get_logger

logger = get_logger("orchestrator.task_layer")


def get_layer_pipeline(
    task_id: str | None = None,
    exp_id: str | None = None,
    run_tier: str | None = None,
    actual_atom_count: int | None = None,
):
    """Create LayerPipelineRunner with real dependencies.

    Args:
        task_id: Celery task ID for GPU allocation tracking.
        exp_id: Experiment ID for GPU allocation (fallback when celery_task_id not found).
        run_tier: Run tier for determining target_atoms (GPU thread scaling fallback).
        actual_atom_count: Actual atom count from build result (preferred for GPU thread scaling).

    Returns:
        Tuple of (LayerPipelineRunner instance, allocated GPU ID or None).
    """
    from builder.layer_builder import LayerBuilder
    from config.settings import get_settings
    from contracts.errors import ErrorCode, OrchestrationError
    from database.connection import get_session
    from database.repositories.experiment_repo import ExperimentRepository
    from database.repositories.metric_repo import MetricRepository
    from orchestrator.lammps_runner import (
        LAMMPSConfig,
        LAMMPSRunner,
        calculate_threads_per_job,
    )
    from orchestrator.layer_pipeline import LayerPipelineRunner
    from orchestrator.process_tracker import ProcessTracker
    from orchestrator.task_runners import make_metrics_calculator
    from protocols.lammps_input import LAMMPSInputGenerator

    app_settings = get_settings()

    # Probe LAMMPS binary capabilities (lazy cached per worker process)
    from orchestrator.lammps_probe import get_lammps_caps

    try:
        lammps_caps = get_lammps_caps(
            app_settings.lammps.executable, mpi_command=app_settings.lammps.mpi_command
        )
    except Exception as e:
        logger.warning(f"LAMMPS probing failed: {e}, using defaults")
        lammps_caps = None

    from monitoring.gpu_collector import detect_system_gpus
    from orchestrator.gpu_service import get_gpu_service

    gpu_service = get_gpu_service()
    gpu_service.initialize()

    try:
        detected = detect_system_gpus()
        detected_ids = [g["gpu_id"] for g in detected] if detected else []
        if detected_ids:
            gpu_service.validate_selected_gpus(detected_ids)
    except Exception as e:
        logger.warning(f"GPU detection failed: {e}, trusting settings.json")
        detected_ids = []

    has_selected_gpus = len(gpu_service.selected_gpus) > 0
    has_detected_gpus = len(detected_ids) > 0
    # If caps probe determined CPU-only mode, skip GPU allocation
    caps_needs_gpu = lammps_caps is None or lammps_caps.accel_mode.value == "kokkos_gpu"
    gpu_enabled = (has_selected_gpus or has_detected_gpus) and caps_needs_gpu

    gpu_id = gpu_service.allocate_gpu(job_id=task_id, exp_id=exp_id) if gpu_enabled else None
    if gpu_enabled and gpu_id is None:
        raise OrchestrationError(
            code=ErrorCode.GPU_NOT_AVAILABLE,
            message="No GPU available for layer simulation",
        )

    # Calculate threads per job based on system CPU cores, GPU count, accel mode, and atom count
    # GPU thread scaling (v00.97.00): larger systems need more CPU threads for data prep
    selected_gpu_count = len(gpu_service.selected_gpus) or 1
    accel_mode = lammps_caps.accel_mode.value if lammps_caps else None

    # Use actual_atom_count if provided (most accurate), otherwise fall back to tier policy
    # This ensures GPU thread scaling works correctly even when run_tier is not passed
    if actual_atom_count is not None:
        effective_atom_count = actual_atom_count
    else:
        from contracts.policies.tier import DEFAULT_TIER_POLICY, RunTier

        try:
            if run_tier is not None:
                tier_enum = RunTier(run_tier) if isinstance(run_tier, str) else run_tier
            else:
                tier_enum = RunTier.SCREENING
            tier_config = DEFAULT_TIER_POLICY.get_tier_config(tier_enum)
            effective_atom_count = tier_config.target_atoms
        except (ValueError, KeyError):
            logger.warning(f"Unknown run_tier: {run_tier}, using screening default")
            tier_config = DEFAULT_TIER_POLICY.get_tier_config(RunTier.SCREENING)
            effective_atom_count = tier_config.target_atoms

    # Co-location-aware threads + drop mpirun wrapper for single-rank GPU runs
    # (v01.05.56 C — same as the bulk path in task_runners; layered/interface
    # jobs co-locate via MPS too, so they need the same oversubscription guard).
    # Mode-aware slots: MPS = policy N; MIG/none = 1 per device.
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
    mpi_executable = "" if accel_mode == "kokkos_gpu" else app_settings.lammps.mpi_command

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
        f"num_threads={num_threads} (cpus={os.cpu_count()}, gpus={selected_gpu_count})"
    )

    process_tracker = ProcessTracker()
    session = get_session()

    runner = LayerPipelineRunner(
        layer_builder=LayerBuilder(),
        protocol=LAMMPSInputGenerator(caps=lammps_caps),
        calculator=make_metrics_calculator(session),
        repository=ExperimentRepository(session),
        runner=LAMMPSRunner(config=lammps_config, process_tracker=process_tracker),
        metric_repository=MetricRepository(session),
    )
    return runner, gpu_id
