"""Unified experiment submission facade.

Ensures a consistent submit flow across single/batch/structure features:
1) Create queued experiment record first
2) Submit Celery job with fixed exp_id
3) Attach celery_task_id + active_attempt_id
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from common.logging import get_logger
from contracts.errors import ContractError, ErrorCode, OrchestrationError
from contracts.policies.budget import JobPriority
from contracts.policies.forcefield import get_ff_display_label, get_ff_version
from features.common import run_in_session_commit
from orchestrator.exp_id_helper import parse_material_id

if TYPE_CHECKING:
    from orchestrator.celery_job_manager import CeleryJobManager

logger = get_logger("orchestrator.submission_facade")


def _serialize_stage_overrides(
    stage_duration_overrides: list | None,
) -> list[dict[str, Any]] | None:
    if not stage_duration_overrides:
        return None
    serialized: list[dict[str, Any]] = []
    for item in stage_duration_overrides:
        if hasattr(item, "model_dump"):
            serialized.append(item.model_dump())
        elif isinstance(item, dict):
            serialized.append(item)
    return serialized or None


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _classify_submit_error(error_message: str) -> str:
    message = str(error_message or "")
    if "E8701" in message or "Duplicate execution blocked" in message:
        return ErrorCode.DUPLICATE_EXECUTION_BLOCKED.value
    return ErrorCode.ORCHESTRATION_ERROR.value


def _extract_molecule_counts_from_build_request(build_request) -> dict[str, int] | None:
    """Extract mol_id->count when build_request is in mol_count mode."""
    if build_request is None:
        return None

    composition_mode = str(getattr(build_request, "composition_mode", "wt_percent") or "wt_percent")
    if composition_mode != "mol_count":
        return None

    composition = getattr(build_request, "composition", None)
    if not isinstance(composition, dict):
        return None

    counts: dict[str, int] = {}
    for raw_mol_id, raw_count in composition.items():
        mol_id = str(raw_mol_id or "").strip()
        if not mol_id:
            continue
        try:
            count = int(round(float(raw_count)))
        except (TypeError, ValueError):
            continue
        if count <= 0:
            continue
        counts[mol_id] = count
    return counts or None


def _extract_additive_source_ids(
    additive_mol_id: str | None, additive_type: str | None
) -> list[str]:
    """Return additive IDs that may carry independent FF provenance."""
    candidate = str(additive_mol_id or "").strip()
    if candidate:
        return [candidate]
    candidate = str(additive_type or "").strip()
    return [candidate] if candidate else []


def _build_submission_metadata(base: dict[str, Any] | None, *, status: str) -> dict[str, Any]:
    meta = dict(base or {})
    source = str(meta.get("source") or "unknown")
    ctx = dict(meta.get("submission_context") or {})
    ctx.setdefault("submit_flow", "submission_facade")
    ctx.setdefault("submit_source", source)
    ctx["submit_status"] = status
    if status == "queued":
        ctx.setdefault("queued_at", _utc_now_iso())
    meta["submission_context"] = ctx
    return meta


def _extract_tensile_context(protocol_request) -> tuple[float | None, float | None]:
    """Extract tensile pull velocity / strain rate from protocol request when present."""
    tensile_spec = getattr(protocol_request, "tensile_spec", None)
    if tensile_spec is None or not getattr(tensile_spec, "enabled", False):
        return None, None

    pull_velocity = getattr(tensile_spec, "pull_velocity_A_per_fs", None)
    strain_rate = getattr(tensile_spec, "strain_rate_1_per_ps", None)
    return pull_velocity, strain_rate


class SubmissionFacade:
    """Facade for robust experiment submission with DB-first visibility."""

    @staticmethod
    def submit_experiment(
        *,
        job_manager: CeleryJobManager,
        exp_id: str,
        run_tier: str,
        ff_type: str,
        target_atoms: int,
        temperature_k: float,
        pressure_atm: float,
        seed: int,
        comp_asphaltene_wt: float,
        comp_resin_wt: float,
        comp_aromatic_wt: float,
        comp_saturate_wt: float,
        build_request,
        protocol_request,
        material_id: str,
        selected_gpus: list[int] | None = None,
        stage_duration_overrides: list | None = None,
        property_calculations: dict[str, Any] | None = None,
        additive_type: str | None = None,
        additive_wt: float = 0.0,
        additive_mol_id: str | None = None,
        metadata_json: dict[str, Any] | None = None,
        data_file_path: str | None = None,
        post_stub_hook: Callable[[Any, str], None] | None = None,
        priority: JobPriority = JobPriority.MEDIUM,
    ) -> tuple[str, str]:
        """
        Submit one experiment with DB-first lifecycle consistency.

        Args:
            priority: Job priority level (default MEDIUM).

        Returns:
            (job_id, celery_task_id)
        """
        overrides_json = _serialize_stage_overrides(stage_duration_overrides)

        def _create_stub(session) -> None:
            from database.repositories.experiment_repo import ExperimentRepository

            repo = ExperimentRepository(session)
            existing = repo.get_by_id(exp_id)
            if existing is not None:
                raise ContractError(
                    ErrorCode.DUPLICATE_RECORD,
                    f"Experiment already exists: {exp_id}",
                    {"exp_id": exp_id, "status": str(existing.status or "")},
                )

            # Derive study_type from protocol_request if available
            _study_type = "bulk"
            if protocol_request is not None and hasattr(protocol_request, "study_type"):
                _study_type = str(
                    protocol_request.study_type.value
                    if hasattr(protocol_request.study_type, "value")
                    else protocol_request.study_type
                )
            binder_type, structure_size, aging_state = parse_material_id(material_id)
            tensile_pull_velocity, tensile_strain_rate = _extract_tensile_context(protocol_request)

            # Build FF provenance from actual request/metadata
            from contracts.policies.forcefield import build_ff_provenance

            # Collect organic source provenance for generator-aware stack_id
            # Use _extract_molecule_counts_from_build_request() for correct SSOT
            _facade_org_sources = None
            try:
                from forcefield.eligibility import collect_organic_source_provenance

                # Extract mol_ids from build_request.composition (mol_count mode)
                mol_counts = _extract_molecule_counts_from_build_request(build_request)
                _mol_ids_f = list(mol_counts.keys()) if mol_counts else []
                _additive_ids_f = [
                    mid
                    for mid in _extract_additive_source_ids(additive_mol_id, additive_type)
                    if mid not in _mol_ids_f
                ]
                _facade_org_sources = (
                    collect_organic_source_provenance(_mol_ids_f, _additive_ids_f) or None
                )
            except Exception:
                pass

            prov = build_ff_provenance(
                study_type=_study_type,
                ff_type=ff_type,
                source_tag="submission_facade",
                metadata_json=metadata_json,
                build_request=build_request,
                organic_sources=_facade_org_sources,
            )
            _merged_meta = _build_submission_metadata(
                {**(metadata_json or {}), "ff_provenance": prov["metadata"]},
                status="queued",
            )

            repo.create(
                exp_id=exp_id,
                run_tier=run_tier,
                ff_type=ff_type,
                study_type=_study_type,
                material_id=material_id,
                binder_type=binder_type,
                structure_size=structure_size,
                aging_state=aging_state,
                force_field_name=get_ff_display_label(ff_type),
                force_field_version=get_ff_version(ff_type),
                comp_asphaltene_wt=comp_asphaltene_wt,
                comp_resin_wt=comp_resin_wt,
                comp_aromatic_wt=comp_aromatic_wt,
                comp_saturate_wt=comp_saturate_wt,
                target_atoms=target_atoms,
                temperature_K=temperature_k,
                pressure_atm=pressure_atm,
                seed=seed,
                status="queued",
                tensile_strain_rate_1_per_ps=tensile_strain_rate,
                tensile_pull_velocity_a_per_fs=tensile_pull_velocity,
                stage_duration_overrides=overrides_json,
                additive_type=additive_type,
                additive_wt=additive_wt,
                additive_mol_id=additive_mol_id,
                metadata_json=_merged_meta,
                data_file_path=data_file_path,
                conditions=prov["conditions"],
            )
            if post_stub_hook is not None:
                post_stub_hook(session, exp_id)

        run_in_session_commit(_create_stub)
        molecule_counts = _extract_molecule_counts_from_build_request(build_request)
        if molecule_counts:

            def _attach_molecules(session) -> None:
                from database.repositories.experiment_repo import ExperimentRepository

                repo = ExperimentRepository(session)
                repo.upsert_experiment_molecules(exp_id, molecule_counts)

            run_in_session_commit(_attach_molecules)

        try:
            job_id = job_manager.submit(
                build_request=build_request,
                protocol_request=protocol_request,
                material_id=material_id,
                selected_gpus=selected_gpus,
                stage_duration_overrides=stage_duration_overrides,
                property_calculations=property_calculations,
                exp_id=exp_id,
                additive_type=additive_type,
                additive_wt=additive_wt,
                additive_mol_id=additive_mol_id,
                priority=priority,
            )
        except Exception as exc:
            SubmissionFacade._mark_submit_failed(exp_id=exp_id, error_message=str(exc))
            raise OrchestrationError(
                ErrorCode.ORCHESTRATION_ERROR,
                "Failed to submit job",
                {"reason": str(exc), "exp_id": exp_id},
            ) from exc

        celery_task_id = job_manager.get_task_id(job_id)
        if not celery_task_id:
            try:
                job_manager.cancel_job(job_id)
            except Exception:
                pass
            SubmissionFacade._mark_submit_failed(
                exp_id=exp_id,
                error_message=f"Missing Celery task id for job {job_id}",
            )
            raise OrchestrationError(
                ErrorCode.ORCHESTRATION_ERROR,
                "Celery task id missing after submission",
                {"exp_id": exp_id, "job_id": job_id},
            )

        def _attach_task(session) -> None:
            from database.repositories.experiment_repo import ExperimentRepository

            repo = ExperimentRepository(session)
            updated = repo.update_celery_task_id(exp_id, celery_task_id)
            if updated is None:
                raise ContractError(
                    ErrorCode.RECORD_NOT_FOUND,
                    f"Experiment not found while attaching task id: {exp_id}",
                    {"exp_id": exp_id, "task_id": celery_task_id},
                )

        run_in_session_commit(_attach_task)
        return job_id, celery_task_id

    @staticmethod
    def _mark_submit_failed(*, exp_id: str, error_message: str) -> None:
        def _op(session) -> None:
            from database.repositories.experiment_repo import ExperimentRepository

            repo = ExperimentRepository(session)
            experiment = repo.get_by_id(exp_id)
            if experiment is None:
                return
            reason_code = _classify_submit_error(error_message)
            base_meta = dict(experiment.metadata_json or {})
            base_meta["submission_context"] = {
                **dict(base_meta.get("submission_context") or {}),
                "submit_flow": "submission_facade",
                "submit_source": str(base_meta.get("source") or "unknown"),
                "submit_status": "failed",
            }
            base_meta["submit_error"] = {
                "reason_code": reason_code,
                "message": str(error_message),
                "failed_at": _utc_now_iso(),
            }
            experiment.metadata_json = base_meta  # type: ignore[assignment]
            repo.update_status(
                exp_id=exp_id,
                status="failed",
                error_code=reason_code,
                error_message=error_message,
            )

        try:
            run_in_session_commit(_op)
        except Exception as exc:
            logger.warning(f"Failed to mark submit failure for {exp_id}: {exc}")
