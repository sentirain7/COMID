"""Running-job progress and stage tracking logic."""

from datetime import datetime

from common.logging import get_logger
from contracts.errors import ErrorCode, OrchestrationError
from features.common import run_in_session
from features.dashboard.timing import compute_pipeline_elapsed_seconds

from .progress import (
    compute_total_steps_with_overrides,
    format_elapsed_eta,
    get_stage_info_with_overrides,
)
from .thermo import parse_stage_marker, parse_thermo_tail

logger = get_logger("features.jobs.running")


def _resolve_current_step(process_step: int | None, parsed_step: int) -> int:
    """Prefer tracked process step when available and parser value is missing/stale."""
    if process_step is None:
        return parsed_step
    try:
        tracked = int(process_step)
    except (TypeError, ValueError):
        return parsed_step
    if tracked < 0:
        return parsed_step
    if parsed_step <= 0:
        return tracked
    return max(tracked, parsed_step)


def _resolve_total_steps_and_stage(
    tier: str,
    current_step: int,
    db_total_steps: int | None,
    overrides,
    has_equilibration: bool = False,
    compiled_plan: dict | None = None,
    stage_marker: tuple[int, str] | None = None,
) -> tuple[int, dict]:
    if compiled_plan:
        total_steps = compute_total_steps_with_overrides(
            tier,
            overrides or [],
            dt_fs=1.0,
            has_equilibration=has_equilibration,
            compiled_plan=compiled_plan,
        )
    elif db_total_steps is not None:
        total_steps = db_total_steps
    else:
        total_steps = compute_total_steps_with_overrides(
            tier, overrides or [], dt_fs=1.0, has_equilibration=has_equilibration
        )

    stage_info = get_stage_info_with_overrides(
        tier,
        current_step,
        overrides,
        dt_fs=1.0,
        has_equilibration=has_equilibration,
        compiled_plan=compiled_plan,
        stage_marker=stage_marker,
    )

    return total_steps, stage_info


def _build_running_payload(
    *,
    job_id: str,
    exp_id: str,
    tier: str,
    gpu_id,
    current_step: int,
    total_steps: int,
    temperature: float | None,
    pressure: float | None,
    density: float | None,
    energy: float | None,
    thermo_data: list[dict],
    elapsed_seconds: float,
    stage_info: dict,
    telemetry_age_sec: float | None = None,
    source: str = "unknown",
    pipeline_elapsed_seconds: float | None = None,
    build_progress_percent: float | None = None,
) -> dict:
    elapsed_str, eta_str = format_elapsed_eta(current_step, total_steps, elapsed_seconds)
    return {
        "job_id": job_id,
        "exp_id": exp_id,
        "tier": tier,
        "gpu_id": gpu_id,
        "current_step": current_step,
        "total_steps": total_steps,
        "progress": round(current_step / total_steps * 100, 1) if total_steps > 0 else 0,
        "temperature": temperature,
        "pressure": pressure,
        "density": density,
        "energy": energy,
        "elapsed": elapsed_str,
        "eta": eta_str,
        "thermo_data": thermo_data,
        "current_stage": stage_info["current_stage"],
        "stage_type": stage_info["stage_type"],
        "stage_index": stage_info["stage_index"],
        "total_stages": stage_info["total_stages"],
        "stage_progress": f"{stage_info['stage_index']}/{stage_info['total_stages']}",
        "stage_step": stage_info["stage_step"],
        "stage_total_steps": stage_info["stage_total_steps"],
        "stage_percent": stage_info["stage_percent"],
        "telemetry_age_sec": telemetry_age_sec,
        "telemetry_stale": telemetry_age_sec is not None and telemetry_age_sec > 60,
        "source": source,
        "pipeline_elapsed_seconds": pipeline_elapsed_seconds,
        "build_progress_percent": build_progress_percent,
    }


def _resolve_telemetry_value(db_value: float | None, parsed_value: float | None) -> float | None:
    """Prefer DB heartbeat telemetry when available."""
    return db_value if db_value is not None else parsed_value


def _calc_elapsed_seconds(*start_times) -> float:
    """Return elapsed seconds from the first valid start timestamp."""
    for start_time in start_times:
        if start_time is None:
            continue
        try:
            now = (
                datetime.now(start_time.tzinfo)
                if getattr(start_time, "tzinfo", None) is not None
                else datetime.utcnow()
            )
            return max((now - start_time).total_seconds(), 0.0)
        except Exception:
            continue
    return 0.0


def _collect_running_from_manager(job) -> dict:
    from database.models import ProcessInfoModel
    from database.repositories.experiment_repo import ExperimentRepository

    db_exp_id = None
    db_gpu_id = None
    db_total_steps = None
    db_current_step = None
    log_file_path = None
    db_last_heartbeat = None
    db_temperature = None
    db_pressure = None
    db_density = None
    db_energy = None
    db_lammps_start_time = None
    process_started_at = None
    metadata_json = None
    db_status = None
    db_wall_time_seconds = None
    db_completed_at = None
    db_updated_at = None

    def _load(session):
        nonlocal \
            db_exp_id, \
            db_gpu_id, \
            db_total_steps, \
            db_current_step, \
            log_file_path, \
            db_last_heartbeat, \
            db_temperature, \
            db_pressure, \
            db_density, \
            db_energy, \
            db_lammps_start_time, \
            process_started_at, \
            metadata_json, \
            db_status, \
            db_wall_time_seconds, \
            db_completed_at, \
            db_updated_at
        repo = ExperimentRepository(session)
        exp = None

        if hasattr(job, "task_id") and job.task_id:
            exp = repo.get_by_celery_task_id(job.task_id)
        if not exp and job.result_exp_id:
            exp = repo.get_by_id(job.result_exp_id)

        if exp:
            db_exp_id = exp.exp_id
            db_gpu_id = getattr(exp, "gpu_id_allocated", None)
            log_file_path = exp.log_file_path
            db_last_heartbeat = getattr(exp, "last_heartbeat_at", None)
            db_lammps_start_time = getattr(exp, "lammps_start_time", None)
            metadata_json = getattr(exp, "metadata_json", None)
            db_status = getattr(exp, "status", None)
            db_wall_time_seconds = getattr(exp, "wall_time_seconds", None)
            db_completed_at = getattr(exp, "completed_at", None)
            db_updated_at = getattr(exp, "updated_at", None)

            process_info = session.query(ProcessInfoModel).filter_by(exp_id=exp.exp_id).first()
            if process_info:
                if process_info.total_steps is not None:
                    db_total_steps = process_info.total_steps
                if process_info.current_step is not None:
                    db_current_step = process_info.current_step
                process_started_at = process_info.started_at
                db_temperature = process_info.temperature
                db_pressure = process_info.pressure
                db_density = process_info.density
                db_energy = process_info.energy

    run_in_session(_load)

    (
        thermo_data,
        current_step,
        parsed_temperature,
        parsed_pressure,
        parsed_density,
        parsed_energy,
    ) = parse_thermo_tail(log_file_path)
    temperature = _resolve_telemetry_value(db_temperature, parsed_temperature)
    pressure = _resolve_telemetry_value(db_pressure, parsed_pressure)
    density = _resolve_telemetry_value(db_density, parsed_density)
    energy = _resolve_telemetry_value(db_energy, parsed_energy)
    current_step = _resolve_current_step(db_current_step, current_step)

    from .chain_resolver import has_injected_equilibration, resolve_chain_key

    chain_key = resolve_chain_key(
        protocol_request=job.protocol_request,
        metadata_json=metadata_json,
    )
    eq_injected = has_injected_equilibration(
        protocol_request=job.protocol_request,
        metadata_json=metadata_json,
    )
    tier = job.protocol_request.run_tier.value
    compiled_plan = (
        metadata_json.get("compiled_execution_plan") if isinstance(metadata_json, dict) else None
    )
    stage_marker = parse_stage_marker(log_file_path)
    total_steps, stage_info = _resolve_total_steps_and_stage(
        tier=chain_key,
        current_step=current_step,
        db_total_steps=db_total_steps,
        overrides=job.stage_duration_overrides,
        has_equilibration=eq_injected,
        compiled_plan=compiled_plan,
        stage_marker=stage_marker,
    )
    current_step = stage_info.get("adjusted_step", current_step)

    elapsed_seconds = _calc_elapsed_seconds(
        db_lammps_start_time,
        process_started_at,
        job.started_at,
    )
    telemetry_age_sec = (
        (datetime.utcnow() - db_last_heartbeat).total_seconds() if db_last_heartbeat else None
    )
    actual_exp_id = job.result_exp_id or db_exp_id or f"pending_{job.job_id}"

    pipeline_elapsed = compute_pipeline_elapsed_seconds(
        status=db_status or "running",
        metadata_json=metadata_json if isinstance(metadata_json, dict) else None,
        lammps_start_time=db_lammps_start_time,
        wall_time_seconds=db_wall_time_seconds,
        completed_at=db_completed_at,
        updated_at=db_updated_at,
    )
    build_percent = None
    if isinstance(metadata_json, dict):
        raw_percent = metadata_json.get("build_progress_percent")
        if raw_percent is not None:
            try:
                build_percent = float(raw_percent)
            except (TypeError, ValueError):
                build_percent = None

    return _build_running_payload(
        job_id=job.job_id,
        exp_id=actual_exp_id,
        tier=tier,
        gpu_id=db_gpu_id,
        current_step=current_step,
        total_steps=total_steps,
        temperature=temperature,
        pressure=pressure,
        density=density,
        energy=energy,
        thermo_data=thermo_data,
        elapsed_seconds=elapsed_seconds,
        stage_info=stage_info,
        telemetry_age_sec=telemetry_age_sec,
        source="manager",
        pipeline_elapsed_seconds=pipeline_elapsed,
        build_progress_percent=build_percent,
    )


def _collect_running_from_db_exp(exp, session) -> dict:
    from database.models import ProcessInfoModel

    process_info = session.query(ProcessInfoModel).filter_by(exp_id=exp.exp_id).first()
    db_total_steps = (
        process_info.total_steps if process_info and process_info.total_steps is not None else None
    )
    db_current_step = (
        process_info.current_step
        if process_info and process_info.current_step is not None
        else None
    )
    db_temperature = process_info.temperature if process_info else None
    db_pressure = process_info.pressure if process_info else None
    db_density = process_info.density if process_info else None
    db_energy = process_info.energy if process_info else None

    (
        thermo_data,
        current_step,
        parsed_temperature,
        parsed_pressure,
        parsed_density,
        parsed_energy,
    ) = parse_thermo_tail(exp.log_file_path)
    temperature = _resolve_telemetry_value(db_temperature, parsed_temperature)
    pressure = _resolve_telemetry_value(db_pressure, parsed_pressure)
    density = _resolve_telemetry_value(db_density, parsed_density)
    energy = _resolve_telemetry_value(db_energy, parsed_energy)
    current_step = _resolve_current_step(db_current_step, current_step)

    from .chain_resolver import has_injected_equilibration, resolve_chain_key

    tier = exp.run_tier or "screening"
    metadata = getattr(exp, "metadata_json", None)
    chain_key = resolve_chain_key(run_tier=tier, metadata_json=metadata)
    eq_injected = has_injected_equilibration(metadata_json=metadata)
    compiled_plan = metadata.get("compiled_execution_plan") if isinstance(metadata, dict) else None

    db_overrides = getattr(exp, "stage_duration_overrides", None)
    override_objs = None
    if db_overrides:
        from protocols.duration_adjuster import StageDurationOverride

        override_objs = [StageDurationOverride(**o) for o in db_overrides]

    stage_marker = parse_stage_marker(exp.log_file_path)
    try:
        total_steps, stage_info = _resolve_total_steps_and_stage(
            tier=chain_key,
            current_step=current_step,
            db_total_steps=db_total_steps,
            overrides=override_objs,
            has_equilibration=eq_injected,
            compiled_plan=compiled_plan,
            stage_marker=stage_marker,
        )
        current_step = stage_info.get("adjusted_step", current_step)
    except ValueError:
        total_steps = 1000000
        stage_info = {
            "current_stage": "unknown",
            "stage_type": "unknown",
            "stage_index": 1,
            "total_stages": 1,
            "stage_step": current_step,
            "stage_total_steps": total_steps,
            "stage_percent": round(current_step / total_steps * 100, 1) if total_steps > 0 else 0,
        }

    elapsed_seconds = _calc_elapsed_seconds(
        getattr(exp, "lammps_start_time", None),
        process_info.started_at if process_info else None,
        exp.created_at,
    )
    telemetry_age_sec = (
        (datetime.utcnow() - exp.last_heartbeat_at).total_seconds()
        if exp.last_heartbeat_at
        else None
    )

    pipeline_elapsed = compute_pipeline_elapsed_seconds(
        status=getattr(exp, "status", None) or "running",
        metadata_json=metadata if isinstance(metadata, dict) else None,
        lammps_start_time=getattr(exp, "lammps_start_time", None),
        wall_time_seconds=getattr(exp, "wall_time_seconds", None),
        completed_at=getattr(exp, "completed_at", None),
        updated_at=getattr(exp, "updated_at", None),
    )
    build_percent = None
    if isinstance(metadata, dict):
        raw_percent = metadata.get("build_progress_percent")
        if raw_percent is not None:
            try:
                build_percent = float(raw_percent)
            except (TypeError, ValueError):
                build_percent = None

    return _build_running_payload(
        job_id=exp.exp_id[:8],
        exp_id=exp.exp_id,
        tier=tier,
        gpu_id=getattr(exp, "gpu_id_allocated", None),
        current_step=current_step,
        total_steps=total_steps,
        temperature=temperature,
        pressure=pressure,
        density=density,
        energy=energy,
        thermo_data=thermo_data,
        elapsed_seconds=elapsed_seconds,
        stage_info=stage_info,
        telemetry_age_sec=telemetry_age_sec,
        source="db",
        pipeline_elapsed_seconds=pipeline_elapsed,
        build_progress_percent=build_percent,
    )


async def get_running_jobs() -> dict:
    from api.deps import get_job_manager
    from orchestrator.celery_job_manager import CeleryJobStatus

    jobs = []
    seen_exp_ids: set[str] = set()
    try:
        job_manager = get_job_manager()
    except RuntimeError as exc:
        logger.warning(f"Job manager unavailable: {exc}")
        raise OrchestrationError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "Infrastructure degraded. Running jobs data unavailable.",
            {"reason": str(exc)},
        ) from exc

    try:
        running_jobs = job_manager.list_jobs(status=CeleryJobStatus.RUNNING)
        for job in running_jobs:
            try:
                job_data = _collect_running_from_manager(job)
                jobs.append(job_data)
                exp_id = job_data.get("exp_id")
                if exp_id:
                    seen_exp_ids.add(exp_id)
            except Exception as exc:
                logger.debug(f"Failed to parse thermo/progress for job {job.job_id}: {exc}")
    except Exception as exc:
        logger.warning(f"Failed to get running jobs from job manager: {exc}")

    try:
        from database.repositories.experiment_repo import ExperimentRepository

        def _collect_from_db(session):
            repo = ExperimentRepository(session)
            for exp in repo.get_by_status("running"):
                if exp.exp_id in seen_exp_ids:
                    continue
                jobs.append(_collect_running_from_db_exp(exp, session))
                seen_exp_ids.add(exp.exp_id)
            # Include building experiments with build_phase metadata
            for exp in repo.get_by_status("building"):
                if exp.exp_id in seen_exp_ids:
                    continue
                meta = exp.metadata_json or {}
                build_percent = meta.get("build_progress_percent")
                try:
                    build_percent = float(build_percent) if build_percent is not None else None
                except (TypeError, ValueError):
                    build_percent = None
                pipeline_elapsed = compute_pipeline_elapsed_seconds(
                    status="building",
                    metadata_json=meta if isinstance(meta, dict) else None,
                    lammps_start_time=getattr(exp, "lammps_start_time", None),
                    wall_time_seconds=getattr(exp, "wall_time_seconds", None),
                    completed_at=getattr(exp, "completed_at", None),
                    updated_at=getattr(exp, "updated_at", None),
                )
                jobs.append(
                    {
                        "job_id": f"build_{exp.exp_id[:8]}",
                        "exp_id": exp.exp_id,
                        "tier": getattr(exp, "run_tier", "screening"),
                        "gpu_id": None,
                        "status": "building",
                        "build_phase": meta.get("build_phase", "structure_build"),
                        "build_phase_label": meta.get("build_phase_label", "Building..."),
                        "progress": 0,
                        "current_step": 0,
                        "total_steps": 0,
                        "pipeline_elapsed_seconds": pipeline_elapsed,
                        "build_progress_percent": build_percent,
                    }
                )
                seen_exp_ids.add(exp.exp_id)
            return None

        run_in_session(_collect_from_db)
    except Exception as exc:
        logger.warning(f"Failed to get running experiments from DB: {exc}")

    return {"jobs": jobs, "count": len(jobs)}
