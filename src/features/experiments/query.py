"""Experiment query and lifecycle operations."""

from api.utils.time_utils import to_utc_iso
from common.logging import get_logger
from contracts.errors import (
    ContractError,
    DatabaseError,
    ErrorCode,
    ParserError,
)
from contracts.policies.forcefield import get_ff_display_label
from features.common import run_in_session, run_in_session_commit
from features.dashboard.timing import compute_pipeline_elapsed_seconds
from features.experiments.e_intra_method import resolve_experiment_e_intra_method

# Re-export lifecycle operations (backward compatibility)
from features.experiments.experiment_lifecycle import (  # noqa: F401
    _GPU_IMMEDIATE_RELEASE_STATUSES,
    CANCELABLE_STATUSES,
    DELETABLE_STATUSES,
    _cancel_one,
    _delete_one,
    batch_cancel_experiments,
    batch_delete_experiments,
    batch_retry_experiments,
    cancel_experiment,
    delete_experiment,
    retry_experiment,
)

# Re-export search operations (backward compatibility)
from features.experiments.experiment_search import (  # noqa: F401
    calculate_composition_from_library,
    count_experiments_by_status,
    find_similar_experiments,
    find_similar_experiments_batch,
    list_experiments_paginated,
    search_by_composition,
)

logger = get_logger("features.experiments.query")


def _parse_box_from_data_file(path: str | None) -> tuple[float, float, float] | None:
    """Parse box dimensions (lx, ly, lz) from LAMMPS data file header.

    Delegates to features.common.box_dims (SSOT for cross-feature reuse).
    """
    from features.common.box_dims import parse_box_from_data_file

    return parse_box_from_data_file(path)


def _get_box_dims(exp) -> tuple[float | None, float | None, float | None]:
    """Get box dimensions from model, lazy-populating from data file if needed."""
    box_lx = getattr(exp, "box_lx", None)
    box_ly = getattr(exp, "box_ly", None)
    box_lz = getattr(exp, "box_lz", None)
    if box_lx is not None and box_ly is not None and box_lz is not None:
        return (box_lx, box_ly, box_lz)
    # Lazy populate from data file
    dims = _parse_box_from_data_file(getattr(exp, "data_file_path", None))
    if dims:
        try:
            exp.box_lx, exp.box_ly, exp.box_lz = dims
        except Exception:
            pass
        return dims
    return (None, None, None)


def _get_additive_short_names(session) -> dict[str, str]:
    """Return {mol_id: short_name} for all active additives."""
    try:
        from database.repositories.additive_repo import AdditiveRepository

        repo = AdditiveRepository(session)
        rows = repo.list_active()
        return {r.mol_id: getattr(r, "short_name", None) or r.name for r in rows}
    except Exception:
        return {}


def _resolve_experiment_catalog_labels(exp) -> dict[str, str]:
    """Resolve binder/size/aging/additive labels for UI and analytics from SSOT fields."""
    from features.common.labels import resolve_experiment_catalog_labels

    return resolve_experiment_catalog_labels(exp)


def _raise_experiment_not_found(exp_id: str) -> None:
    raise DatabaseError(
        ErrorCode.RECORD_NOT_FOUND,
        f"Experiment {exp_id} not found",
        {"exp_id": exp_id},
    )


async def get_experiment(exp_id: str) -> dict:
    """Get experiment details by ID."""
    from database.repositories.experiment_repo import ExperimentRepository

    try:

        def _query(session):
            repo = ExperimentRepository(session)
            exp = repo.get_by_id(exp_id)
            if not exp:
                _raise_experiment_not_found(exp_id)

            mol_counts = {}
            mol_details = {}
            total_mass = 0.0
            exp_mols = repo.get_experiment_molecules(exp_id)

            # Build additive short_name lookup for consistent display
            additive_names = _get_additive_short_names(session)

            for exp_mol, mol in exp_mols:
                mol_counts[mol.mol_id] = exp_mol.count
                mw = mol.molecular_weight or 0.0
                weight = exp_mol.count * mw
                total_mass += weight
                detail = {
                    "count": exp_mol.count,
                    "molecular_weight": mw,
                    "weight": weight,
                    "sara_type": mol.sara_type,
                }
                if mol.mol_id in additive_names:
                    detail["short_name"] = additive_names[mol.mol_id]
                mol_details[mol.mol_id] = detail

            metrics_dict = None
            if hasattr(exp, "metrics") and exp.metrics:
                metrics_dict = {m.metric_name: m.value for m in exp.metrics}

            box_lx, box_ly, box_lz = _get_box_dims(exp)
            labels = _resolve_experiment_catalog_labels(exp)
            (
                e_intra_method,
                e_intra_method_origin,
                e_intra_method_resolved_from,
            ) = resolve_experiment_e_intra_method(exp)
            dump_files: list[str] = []
            lammps_result = exp.lammps_result_json or {}
            result_dump_files = lammps_result.get("dump_files")
            if isinstance(result_dump_files, list):
                dump_files.extend(str(path) for path in result_dump_files if path)
            elif result_dump_files:
                dump_files.append(str(result_dump_files))
            if exp.dump_file_path and exp.dump_file_path not in dump_files:
                dump_files.insert(0, exp.dump_file_path)

            return {
                "exp_id": exp.exp_id,
                "status": exp.status or "pending",
                "run_tier": exp.run_tier or "screening",
                "ff_type": exp.ff_type or "bulk_ff_gaff2",
                "force_field_type": get_ff_display_label(exp.ff_type or "bulk_ff_gaff2"),
                "study_type": getattr(exp, "study_type", None) or "bulk",
                "additive_mol_id": getattr(exp, "additive_mol_id", None),
                "e_intra_method": e_intra_method,
                "e_intra_method_origin": e_intra_method_origin,
                "e_intra_method_resolved_from": e_intra_method_resolved_from,
                "e_intra_method_source": e_intra_method_origin,
                "temperature_k": exp.temperature_K,
                "pressure_atm": exp.pressure_atm,
                "target_atoms": exp.target_atoms,
                "actual_atoms": exp.actual_atoms,
                "seed": exp.seed,
                "composition": {
                    "asphaltene": exp.comp_asphaltene_wt,
                    "resin": exp.comp_resin_wt,
                    "aromatic": exp.comp_aromatic_wt,
                    "saturate": exp.comp_saturate_wt,
                },
                "mol_counts": mol_counts if mol_counts else None,
                "mol_details": mol_details if mol_details else None,
                "total_mass": total_mass if total_mass > 0 else None,
                "data_file_path": exp.data_file_path,
                "log_file_path": exp.log_file_path,
                "dump_files": dump_files,
                "error_code": exp.error_code,
                "error_message": exp.error_message,
                "metrics": metrics_dict,
                "wall_time_seconds": getattr(exp, "wall_time_seconds", None),
                "box_lx": box_lx,
                "box_ly": box_ly,
                "box_lz": box_lz,
                **labels,
                "created_at": to_utc_iso(exp.created_at),
                "completed_at": to_utc_iso(exp.completed_at),
            }

        return run_in_session_commit(_query)
    except ContractError:
        raise
    except Exception as exc:
        logger.error(f"Failed to get experiment {exp_id}: {exc}")
        raise DatabaseError(
            ErrorCode.DATABASE_ERROR,
            "Internal server error",
            {"exp_id": exp_id},
        ) from exc


async def list_experiments(
    status: str | None = None,
    tier: str | None = None,
    limit: int = 100,
    exclude_layered: bool = False,
    study_type: str | None = None,
    additive_mol_id: str | None = None,
    temperature_min: float | None = None,
    temperature_max: float | None = None,
    additive_type: str | None = None,
    e_intra_method: str | None = None,
) -> dict:
    """List experiments with optional filters.

    Args:
        status: Filter by experiment status.
        tier: Filter by run tier.
        limit: Maximum number of experiments to return.
        exclude_layered: If True, exclude experiments that have layered
            lineage (LayeredExperimentSourceModel entries).
        study_type: Filter by study type (exact match, e.g.
            ``"bulk"``, ``"single_molecule_vacuum"``).
        additive_mol_id: Filter by additive molecule ID (exact match).
        temperature_min: Minimum temperature (K) for range filter.
        temperature_max: Maximum temperature (K) for range filter.
        additive_type: Filter by additive type (exact match).
        e_intra_method: Filter by resolved E_intra method provenance.
    """
    from datetime import datetime, timedelta

    from contracts.schema_enums import normalize_e_intra_method

    try:
        from database.models import ExperimentModel

        def _query(session):
            # Build ORM base query with all filters applied at DB level
            # so that filtered_total_count and limit are accurate.
            base = session.query(ExperimentModel)

            if status:
                base = base.filter(ExperimentModel.status == status)
            if tier:
                base = base.filter(ExperimentModel.run_tier == tier)
            if exclude_layered:
                from database.models.structure import LayeredExperimentSourceModel

                layered_ids = session.query(LayeredExperimentSourceModel.exp_id).distinct()
                base = base.filter(~ExperimentModel.exp_id.in_(layered_ids))
            if study_type:
                from sqlalchemy import or_

                if study_type == "bulk":
                    # Legacy rows may have NULL study_type — treat as bulk.
                    base = base.filter(
                        or_(
                            ExperimentModel.study_type == "bulk",
                            ExperimentModel.study_type.is_(None),
                        )
                    )
                else:
                    base = base.filter(ExperimentModel.study_type == study_type)
            if additive_mol_id:
                base = base.filter(ExperimentModel.additive_mol_id == additive_mol_id)
            if temperature_min is not None:
                base = base.filter(ExperimentModel.temperature_K >= temperature_min)
            if temperature_max is not None:
                base = base.filter(ExperimentModel.temperature_K <= temperature_max)
            if additive_type:
                base = base.filter(ExperimentModel.additive_type == additive_type)

            method_filter = normalize_e_intra_method(e_intra_method) if e_intra_method else None

            if method_filter:
                db_experiments = base.order_by(ExperimentModel.created_at.desc()).all()
            else:
                filtered_total_count = base.count()
                db_experiments = base.order_by(ExperimentModel.created_at.desc()).limit(limit).all()

            now = datetime.utcnow()
            session_start = now - timedelta(hours=1)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

            experiments = []
            for exp in db_experiments:
                data_age = "historical"
                if exp.created_at:
                    if exp.created_at > session_start:
                        data_age = "current_session"
                    elif exp.created_at > today_start:
                        data_age = "today"

                metrics_dict = None
                if hasattr(exp, "metrics") and exp.metrics:
                    metrics_dict = {m.metric_name: m.value for m in exp.metrics}

                box_lx, box_ly, box_lz = _get_box_dims(exp)
                labels = _resolve_experiment_catalog_labels(exp)
                (
                    resolved_e_intra_method,
                    e_intra_method_origin,
                    e_intra_method_resolved_from,
                ) = resolve_experiment_e_intra_method(exp)
                if method_filter and resolved_e_intra_method != method_filter:
                    continue
                exp_meta = getattr(exp, "metadata_json", None)
                pipeline_elapsed = compute_pipeline_elapsed_seconds(
                    status=getattr(exp, "status", None),
                    metadata_json=exp_meta if isinstance(exp_meta, dict) else None,
                    lammps_start_time=getattr(exp, "lammps_start_time", None),
                    wall_time_seconds=getattr(exp, "wall_time_seconds", None),
                    completed_at=getattr(exp, "completed_at", None),
                    updated_at=getattr(exp, "updated_at", None),
                )

                experiments.append(
                    {
                        "exp_id": exp.exp_id,
                        "status": exp.status,
                        "run_tier": exp.run_tier,
                        "ff_type": exp.ff_type,
                        "study_type": getattr(exp, "study_type", None) or "bulk",
                        "additive_mol_id": getattr(exp, "additive_mol_id", None),
                        "e_intra_method": resolved_e_intra_method,
                        "e_intra_method_origin": e_intra_method_origin,
                        "e_intra_method_resolved_from": e_intra_method_resolved_from,
                        "e_intra_method_source": e_intra_method_origin,
                        "temperature_k": getattr(exp, "temperature_K", None),
                        "target_atoms": getattr(exp, "target_atoms", None),
                        "created_at": to_utc_iso(exp.created_at),
                        "started_at": to_utc_iso(getattr(exp, "lammps_start_time", None)),
                        "completed_at": to_utc_iso(exp.completed_at),
                        "wall_time_seconds": getattr(exp, "wall_time_seconds", None),
                        "pipeline_elapsed_seconds": pipeline_elapsed,
                        "error_message": exp.error_message,
                        "metrics": metrics_dict,
                        "data_age": data_age,
                        "gpu_id_allocated": getattr(exp, "gpu_id_allocated", None),
                        "box_lx": box_lx,
                        "box_ly": box_ly,
                        "box_lz": box_lz,
                        **labels,
                    }
                )

            if method_filter:
                filtered_total_count = len(experiments)
                experiments = experiments[:limit]

            # Keep global total_count for dashboard/header use.
            total_count = session.query(ExperimentModel).count()

            return {
                "experiments": experiments,
                "total": len(experiments),
                "filtered_total_count": filtered_total_count,
                "total_count": total_count,
                "limit": limit,
            }

        return run_in_session_commit(_query)

    except ImportError:
        return {
            "experiments": [],
            "total": 0,
            "filtered_total_count": 0,
            "total_count": 0,
            "limit": limit,
        }


async def get_experiment_thermo(exp_id: str) -> dict:
    """Get thermo data from experiment log file."""
    try:
        from database.repositories.experiment_repo import ExperimentRepository
        from parsers.log_parser import LogParser

        def _query(session):
            repo = ExperimentRepository(session)
            exp = repo.get_by_id(exp_id)
            if not exp:
                _raise_experiment_not_found(exp_id)
            if not exp.log_file_path:
                raise DatabaseError(
                    ErrorCode.RECORD_NOT_FOUND,
                    "Log file path not available",
                    {"exp_id": exp_id},
                )

            parser = LogParser()
            result = parser.parse(exp.log_file_path)
            if not result or not result.thermo_data:
                raise ParserError(
                    ErrorCode.THERMO_EXTRACT_FAILED,
                    "No thermo data in log file",
                    details={"exp_id": exp_id, "log_file_path": exp.log_file_path},
                )
            return result.thermo_data

        return run_in_session(_query)

    except ContractError:
        raise
    except Exception as exc:
        logger.error(f"Failed to get thermo data for {exp_id}: {exc}")
        raise ParserError(
            ErrorCode.LOG_PARSE_FAILED,
            str(exc),
            details={"exp_id": exp_id},
        ) from exc


async def get_experiment_filter_options() -> dict:
    """Return distinct filter values for client-side dropdowns."""
    try:
        from sqlalchemy import func

        from database.models import ExperimentModel

        def _query(session):
            additive_types = sorted(
                r[0]
                for r in session.query(ExperimentModel.additive_type)
                .filter(ExperimentModel.additive_type.isnot(None))
                .distinct()
                .all()
                if r[0]
            )
            temp_range = session.query(
                func.min(ExperimentModel.temperature_K),
                func.max(ExperimentModel.temperature_K),
            ).one()
            tiers = sorted(
                r[0] for r in session.query(ExperimentModel.run_tier).distinct().all() if r[0]
            )
            return {
                "additive_types": additive_types,
                "temperature_min": float(temp_range[0]) if temp_range[0] else None,
                "temperature_max": float(temp_range[1]) if temp_range[1] else None,
                "tiers": tiers,
            }

        return run_in_session(_query)
    except Exception as exc:
        logger.error(f"Failed to get filter options: {exc}")
        return {"additive_types": [], "temperature_min": None, "temperature_max": None, "tiers": []}
