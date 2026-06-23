"""Scan database service — orchestrates scanning and DB import."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from common.logging import get_logger
from common.pathing import BINDER_ABBREV_REVERSE, parse_exp_id
from database.connection import session_scope
from database.models import ExperimentModel

from .scanner import ScannedExperiment, scan_experiment_directories

logger = get_logger("features.scan_database.service")


def _detect_e_intra_method_from_input(input_file_path: str | None) -> str:
    """Detect E_intra method tag from a LAMMPS input file's pair_style line.

    PR 2 (Codex Round 6): delegates to
    ``protocols.e_intra_method_detect.detect_e_intra_method_from_input`` so
    non-API workers (pipeline) can use the detector without importing the
    FastAPI router subtree.  Kept here as a thin alias for any callers that
    already imported this name.
    """
    from protocols.e_intra_method_detect import detect_e_intra_method_from_input

    return detect_e_intra_method_from_input(input_file_path)


# Binder-specific default SARA compositions (wt%)
# Order: (asphaltene, resin, aromatic, saturate)
_BINDER_COMPOSITIONS: dict[str, tuple[float, float, float, float]] = {
    "AAA1": (20.0, 30.0, 35.0, 15.0),
    "AAK1": (17.0, 38.0, 33.0, 12.0),
    "AAM1": (12.0, 37.0, 35.0, 16.0),
}

# Compatibility levels that are importable
_IMPORTABLE = {"compatible", "compatible_incomplete"}
_FORCE_IMPORTABLE = {"compatible", "compatible_incomplete", "protocol_mismatch"}
# Never importable even with force
_NEVER_IMPORTABLE = {"hash_unverifiable", "no_metadata", "empty"}


def scan(database_dir: Path | None = None) -> list[ScannedExperiment]:
    """Scan filesystem and annotate with DB presence.

    Args:
        database_dir: Override database directory path.

    Returns:
        List of ScannedExperiment with already_in_db populated.
    """
    experiments = scan_experiment_directories(database_dir)

    # Check which are already in DB
    try:
        with session_scope() as session:
            existing_ids = {row[0] for row in session.query(ExperimentModel.exp_id).all()}

        for exp in experiments:
            exp.already_in_db = exp.exp_id in existing_ids
    except Exception as exc:
        logger.warning(f"Failed to check existing experiments in DB: {exc}")

    return experiments


def import_experiments(
    exp_ids: list[str],
    force_import: bool = False,
    database_dir: Path | None = None,
) -> dict:
    """Import selected experiments into the DB.

    Args:
        exp_ids: List of experiment IDs to import.
        force_import: If True, allow protocol_mismatch imports.
        database_dir: Override database directory path.

    Returns:
        Dict with imported/failed counts and per-experiment results.
    """
    # First scan to get metadata
    all_experiments = scan_experiment_directories(database_dir)
    exp_map = {e.exp_id: e for e in all_experiments}

    allowed = _FORCE_IMPORTABLE if force_import else _IMPORTABLE
    imported = 0
    failed = 0
    results: list[dict] = []

    with session_scope() as session:
        # Get already-imported IDs
        existing_ids = {row[0] for row in session.query(ExperimentModel.exp_id).all()}

        for exp_id in exp_ids:
            exp = exp_map.get(exp_id)
            if exp is None:
                results.append(
                    {
                        "exp_id": exp_id,
                        "status": "error",
                        "reason": "Not found in filesystem scan",
                    }
                )
                failed += 1
                continue

            if exp.exp_id in existing_ids:
                results.append(
                    {
                        "exp_id": exp_id,
                        "status": "skipped",
                        "reason": "Already in database",
                    }
                )
                continue

            if exp.compatibility in _NEVER_IMPORTABLE:
                results.append(
                    {
                        "exp_id": exp_id,
                        "status": "rejected",
                        "reason": f"Cannot import: {exp.compatibility} — {exp.compatibility_reason}",
                    }
                )
                failed += 1
                continue

            if exp.compatibility not in allowed:
                results.append(
                    {
                        "exp_id": exp_id,
                        "status": "rejected",
                        "reason": (
                            f"Compatibility '{exp.compatibility}' not allowed "
                            f"(force_import={force_import})"
                        ),
                    }
                )
                failed += 1
                continue

            try:
                nested = session.begin_nested()
                model = _create_experiment_model(exp)
                session.add(model)
                session.flush()  # detect constraint violations early
                nested.commit()
                existing_ids.add(exp_id)

                # SM experiments: experiment_molecules is mandatory
                sm_partial = False
                if exp.study_type == "single_molecule_vacuum" and exp.additive_mol_id:
                    try:
                        from database.repositories.experiment_repo import ExperimentRepository

                        exp_repo = ExperimentRepository(session)
                        exp_repo.upsert_experiment_molecules(exp.exp_id, {exp.additive_mol_id: 1})
                    except Exception as mol_exc:
                        sm_partial = True
                        logger.error(
                            "SM experiment_molecules FAILED for %s: %s",
                            exp_id,
                            mol_exc,
                        )

                # Compute and store metrics only for completed runs
                n_metrics = 0
                e_intra_ok = True
                if exp.lammps_completed:
                    n_metrics, e_intra_ok = _compute_metrics_for_imported(exp, session)
                    # For non-SM, e_intra_ok is irrelevant
                    if exp.study_type != "single_molecule_vacuum":
                        e_intra_ok = True

                # Determine result status for SM experiments
                is_sm = exp.study_type == "single_molecule_vacuum"
                if sm_partial or (is_sm and exp.lammps_completed and not e_intra_ok):
                    # Mark DB row as import_partial so Dynamics/analysis queries skip it
                    try:
                        model.status = "import_partial"
                        session.flush()
                    except Exception:
                        pass
                    failed += 1
                    fail_reason = "molecule linkage failed" if sm_partial else "E_intra not stored"
                    results.append(
                        {
                            "exp_id": exp_id,
                            "status": "partial",
                            "reason": f"Experiment saved as import_partial: {fail_reason}",
                        }
                    )
                else:
                    imported += 1
                    reason = f"Imported as {model.status}"
                    if n_metrics > 0:
                        reason += f" ({n_metrics} metrics computed)"
                    if (exp.study_type or "").startswith("layer"):
                        reason += " (lineage unavailable — re-submit to restore)"
                    results.append(
                        {
                            "exp_id": exp_id,
                            "status": "imported",
                            "reason": reason,
                        }
                    )
            except Exception as exc:
                nested.rollback()
                logger.error(f"Failed to import {exp_id}: {exc}")
                results.append(
                    {
                        "exp_id": exp_id,
                        "status": "error",
                        "reason": str(exc),
                    }
                )
                failed += 1

    return {
        "imported": imported,
        "failed": failed,
        "results": results,
    }


# Directories that must never be deleted via scan-database API
_PROTECTED_DIRS = {"amorphous_cells"}

# Characters that indicate path traversal or invalid exp_id
_INVALID_PATH_CHARS = {"/", "\\", "\0"}


def _validate_exp_id_for_delete(exp_id: str) -> str | None:
    """Validate exp_id is safe for filesystem deletion.

    Returns:
        Error reason string if invalid, None if valid.
    """
    if not exp_id or not exp_id.strip():
        return "Empty experiment ID"
    if exp_id in (".", ".."):
        return "Invalid path token"
    if any(c in exp_id for c in _INVALID_PATH_CHARS):
        return "Path separators or null bytes not allowed in experiment ID"
    if exp_id in _PROTECTED_DIRS:
        return f"'{exp_id}' is a protected directory"
    return None


def delete_experiment_dirs(
    exp_ids: list[str],
    database_dir: Path | None = None,
) -> dict:
    """Delete experiment directories from the filesystem.

    Only deletes directories that:
    - Have a valid exp_id (no path traversal tokens)
    - Are not protected (e.g. amorphous_cells)
    - Are not already imported into the DB
    - Exist as direct children of the database/ directory

    Args:
        exp_ids: List of experiment IDs (directory names) to delete.
        database_dir: Override database directory path.

    Returns:
        Dict with deleted/failed counts and per-experiment results.
    """
    import shutil

    from .scanner import _get_database_dir

    db_dir = database_dir or _get_database_dir()
    deleted = 0
    failed = 0
    results: list[dict] = []

    # Check which exp_ids are already in DB — refuse to delete those
    db_exp_ids: set[str] = set()
    try:
        with session_scope() as session:
            db_exp_ids = {row[0] for row in session.query(ExperimentModel.exp_id).all()}
    except Exception as exc:
        logger.warning(f"Failed to query DB for delete safety check: {exc}")

    for exp_id in exp_ids:
        # 1. Validate exp_id format
        err = _validate_exp_id_for_delete(exp_id)
        if err:
            results.append({"exp_id": exp_id, "status": "rejected", "reason": err})
            failed += 1
            continue

        # 2. Refuse if already in DB
        if exp_id in db_exp_ids:
            results.append(
                {
                    "exp_id": exp_id,
                    "status": "rejected",
                    "reason": "Experiment is imported in DB — delete via Experiments page instead",
                }
            )
            failed += 1
            continue

        # 3. Check directory exists
        exp_dir = db_dir / exp_id
        if not exp_dir.exists():
            results.append({"exp_id": exp_id, "status": "error", "reason": "Directory not found"})
            failed += 1
            continue

        if not exp_dir.is_dir():
            results.append({"exp_id": exp_id, "status": "error", "reason": "Not a directory"})
            failed += 1
            continue

        # 4. Must be a direct child of database/ (no symlink escape)
        try:
            resolved = exp_dir.resolve()
            resolved.relative_to(db_dir.resolve())
            # Ensure it's a direct child, not a deeper path
            if resolved.parent != db_dir.resolve():
                raise ValueError("Not a direct child")
        except ValueError:
            results.append(
                {"exp_id": exp_id, "status": "error", "reason": "Path outside database directory"}
            )
            failed += 1
            continue

        # 5. Perform deletion
        try:
            shutil.rmtree(exp_dir)
            deleted += 1
            results.append({"exp_id": exp_id, "status": "deleted", "reason": "Directory removed"})
            logger.info(f"Deleted experiment directory: {exp_dir}")
        except Exception as exc:
            failed += 1
            results.append({"exp_id": exp_id, "status": "error", "reason": str(exc)})
            logger.error(f"Failed to delete {exp_dir}: {exc}")

    return {"deleted": deleted, "failed": failed, "results": results}


def _compute_metrics_for_imported(exp: ScannedExperiment, session: object) -> tuple[int, bool]:
    """Compute and store metrics from imported experiment's log.lammps.

    Args:
        exp: Scanned experiment with log_file_path.
        session: Active DB session.

    Returns:
        Tuple of (n_metrics_stored, e_intra_stored).
    """
    if not exp.log_file_path or not Path(exp.log_file_path).exists():
        return 0, False
    try:
        from contracts.schemas import LAMMPSRunResult
        from database.repositories.metric_repo import MetricRepository
        from orchestrator.task_runners import make_metrics_calculator, restore_run_result_metadata

        run_result = LAMMPSRunResult(
            success=True,
            log_file=exp.log_file_path,
            dump_files=[exp.dump_file_path] if exp.dump_file_path else [],
            wall_time_seconds=0.0,
            exit_code=0,
            exp_id=exp.exp_id,
        )
        restore_run_result_metadata(run_result, exp.exp_id, session)
        calculator = make_metrics_calculator(session)
        metric_results = calculator.calculate(run_result)
        for m in metric_results:
            m.exp_id = exp.exp_id
        repo = MetricRepository(session)
        n_saved = repo.save_batch(metric_results)

        # Store E_intra for single-molecule experiments (PR 2: method-aware).
        e_intra_stored = False
        if exp.study_type == "single_molecule_vacuum" and exp.additive_mol_id:
            try:
                from features.common.e_intra_helper import store_e_intra_from_metrics

                method_tag = _detect_e_intra_method_from_input(exp.input_file_path)
                e_intra_stored = store_e_intra_from_metrics(
                    mol_id=exp.additive_mol_id,
                    metrics=metric_results,
                    ff_type=exp.ff_type or "bulk_ff_gaff2",
                    temperature_k=exp.temperature_k or 298.0,
                    exp_id=exp.exp_id,
                    session=session,
                    method=method_tag,
                )
                if not e_intra_stored:
                    logger.error(
                        "E_intra FAILED for SM %s: no potential_energy metric",
                        exp.exp_id,
                    )
            except Exception as ei_exc:
                logger.error("E_intra storage FAILED for %s: %s", exp.exp_id, ei_exc)

        return n_saved, e_intra_stored
    except Exception as exc:
        logger.warning(f"Metric computation failed for {exp.exp_id}: {exc}")
        return 0, False


def _create_experiment_model(exp: ScannedExperiment) -> ExperimentModel:
    """Create ORM model from scanned experiment data.

    Args:
        exp: Scanned experiment metadata.

    Returns:
        ExperimentModel instance (not yet committed).
    """
    now = datetime.now(UTC)

    # Box dimensions
    box_lx = exp.box_dims[0] if exp.box_dims and len(exp.box_dims) >= 1 else None
    box_ly = exp.box_dims[1] if exp.box_dims and len(exp.box_dims) >= 2 else None
    box_lz = exp.box_dims[2] if exp.box_dims and len(exp.box_dims) >= 3 else None

    # P2: Resolve binder type and composition from exp_id
    parsed = parse_exp_id(exp.exp_id)
    binder_abbrev = str(parsed.get("binder_type") or "").strip()
    binder_full = BINDER_ABBREV_REVERSE.get(binder_abbrev, binder_abbrev)
    default_comp = _BINDER_COMPOSITIONS.get(binder_full, (0.0, 0.0, 0.0, 0.0))
    metadata_json = {
        "imported": True,
        "scan_version": "v00.95.53",
        "compatibility": exp.compatibility,
        "attempt_dir": exp.attempt_dir,
        "binder_type": binder_full,
        "aging_state": str(parsed.get("aging_state") or "non_aging"),
        "structure_size": str(parsed.get("structure_size") or "X1"),
    }
    if exp.study_type == "single_molecule_vacuum":
        method_tag = _detect_e_intra_method_from_input(exp.input_file_path)
        if method_tag:
            metadata_json["e_intra_method"] = method_tag
            metadata_json["e_intra_method_origin"] = "scan_import"

    return ExperimentModel(
        exp_id=exp.exp_id,
        status="completed" if exp.lammps_completed else "imported_incomplete",
        run_tier=exp.tier or "screening",
        ff_type=exp.ff_type or "bulk_ff_gaff2",
        study_type=exp.study_type or "bulk",
        additive_mol_id=exp.additive_mol_id or None,
        temperature_K=exp.temperature_k or 298.0,
        pressure_atm=exp.pressure_atm or 1.0,
        # Composition — resolve from binder type
        comp_asphaltene_wt=default_comp[0],
        comp_resin_wt=default_comp[1],
        comp_aromatic_wt=default_comp[2],
        comp_saturate_wt=default_comp[3],
        # Build info
        actual_atoms=exp.total_atoms,
        seed=exp.seed,
        topology_hash=exp.topology_hash,
        protocol_hash=exp.protocol_hash_found,
        # Paths
        data_file_path=exp.data_file_path,
        input_file_path=exp.input_file_path,
        log_file_path=exp.log_file_path,
        dump_file_path=exp.dump_file_path,
        # Box
        box_lx=box_lx,
        box_ly=box_ly,
        box_lz=box_lz,
        # Timestamps
        created_at=now,
        completed_at=now if exp.lammps_completed else None,
        # P3: Enriched metadata
        metadata_json=metadata_json,
    )
