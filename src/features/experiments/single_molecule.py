"""Single-molecule E_intra batch submission.

Submits one experiment per temperature for a selected molecule.
Each experiment runs minimize + NVT in vacuum to compute PE_total = E_intra.
Uses SubmissionFacade for canonical DB-first lifecycle (exp_id, experiment_molecules,
celery_task_id, duplicate blocking).
"""

from __future__ import annotations

from common.logging import get_logger
from common.seed import generate_seed
from contracts.policies.forcefield import get_ff_display_label, get_ff_version
from contracts.schemas import SubmissionSource

logger = get_logger("features.experiments.single_molecule")


def _make_single_molecule_exp_id(
    mol_id: str,
    temperature_k: float,
    ff_type: str,
    atom_count: int,
    seed: int,
    method: str = "single_molecule_vacuum",
) -> str:
    """Create the dashboard-visible single-molecule experiment id.

    PR 2 (Method 1a SSOT): ``method`` is folded into the hash so Method 1
    and Method 1a runs of the same (mol, temp, ff, atoms, seed) tuple
    produce distinct exp_ids and can co-exist in the experiment table.
    Method 1 (default) preserves the legacy hash for backward compatibility.
    """
    import hashlib

    temp_token = f"{int(round(float(temperature_k)))}K"
    if method == "single_molecule_vacuum":
        # Legacy hash (no method suffix) — preserves existing exp_ids.
        hash_input = f"SM_{mol_id}_{temperature_k}_{ff_type}_{atom_count}_{seed}"
    else:
        hash_input = f"SM_{mol_id}_{temperature_k}_{ff_type}_{atom_count}_{seed}_{method}"
    hash6 = hashlib.md5(hash_input.encode()).hexdigest()[:6]
    return f"SM_{mol_id}_{temp_token}_{hash6}"


# Terminal statuses that can be deleted for force_recompute
_FORCE_DELETABLE_STATUSES = {"completed", "failed", "cancelled", "timeout"}


def _handle_force_recompute_cleanup(
    exp_id: str,
    mol_id: str,
    temp: float,
    ff_type_str: str,
    method: str = "single_molecule_vacuum",
) -> None:
    """Handle cleanup for force_recompute=True.

    Deletes existing terminal experiments and E_intra cache entries for the
    *specific* method only.  PR 2 (Codex peer-review): force_recompute must
    not nuke other methods' rows since the new 5-column UC explicitly allows
    them to coexist.

    Raises exception if experiment is in active state (cannot delete running jobs).
    """
    from database.connection import session_scope
    from database.repositories.e_intra_repo import EIntraRepository
    from database.repositories.experiment_repo import ExperimentRepository
    from features.experiments.experiment_lifecycle import _delete_deferred_files, _delete_one

    deferred_file_deletions: list[str] = []
    with session_scope() as session:
        repo = ExperimentRepository(session)
        existing = repo.get_by_id(exp_id)

        if existing:
            status = str(existing.status or "").lower()
            if status in _FORCE_DELETABLE_STATUSES:
                # Delete using lifecycle cascade for full cleanup
                result = _delete_one(session, exp_id)
                if result.get("success"):
                    deferred_file_deletions.extend(result.get("deferred_files", []))
                    logger.info(
                        "force_recompute: deleted existing experiment %s (status=%s)",
                        exp_id,
                        status,
                    )
                else:
                    from contracts.errors import ContractError, ErrorCode

                    raise ContractError(
                        ErrorCode.INVALID_REQUEST,
                        f"Cannot force recompute: failed to delete existing experiment {exp_id}",
                        {"exp_id": exp_id, "reason": result.get("reason")},
                    )
            elif status in {"pending", "queued", "building", "ready", "running", "analyzing"}:
                # Cannot delete active experiment
                from contracts.errors import ContractError, ErrorCode

                raise ContractError(
                    ErrorCode.INVALID_REQUEST,
                    f"Cannot force recompute: experiment {exp_id} is active (status={status})",
                    {"exp_id": exp_id, "status": status},
                )

        # Delete the existing E_intra cache entry for this method only.
        # PR 2 (Codex peer-review): the 5-column UC permits co-existence of
        # Method 1 / 1a / 2 rows; force_recompute must isolate cleanup to
        # the targeted method.
        try:
            e_intra_repo = EIntraRepository(session)
            from contracts.policies.forcefield import get_ff_display_label, get_ff_version
            from contracts.schema_enums import coerce_e_intra_method
            from contracts.schemas import EIntraKey

            ff_name = get_ff_display_label(ff_type_str)
            ff_version = get_ff_version(ff_type_str)

            method_enum = coerce_e_intra_method(method)
            key = EIntraKey(
                mol_id=mol_id,
                ff_name=ff_name,
                ff_version=ff_version,
                temperature_K=temp,
                method=method_enum,
            )
            if e_intra_repo.exists(key) and e_intra_repo.delete(key):
                logger.info(
                    "force_recompute: deleted E_intra cache for %s @ %.0fK [%s]",
                    mol_id,
                    temp,
                    method_enum.value,
                )
            else:
                logger.debug(
                    "force_recompute: no E_intra cache entry for %s @ %.0fK [%s]",
                    mol_id,
                    temp,
                    method_enum.value,
                )
        except Exception as exc:
            logger.warning("force_recompute: failed to delete E_intra cache: %s", exc)

        session.commit()
    _delete_deferred_files(deferred_file_deletions)


async def submit_single_molecule_batch(request) -> dict:  # type: ignore[no-untyped-def]
    """Submit single-molecule E_intra experiments for multiple temperatures.

    Uses SubmissionFacade.submit_experiment() for each temperature to ensure
    canonical experiment lifecycle (DB stub, experiment_molecules, task tracking).

    When force_recompute=True:
    - Deletes existing terminal experiments (completed/failed/cancelled/timeout)
    - Skips active experiments with warning (cannot delete running experiments)
    - Deletes existing E_intra cache entries
    """
    from api.deps import get_job_manager, get_molecule_db
    from config.dashboard_settings import resolve_submission_e_intra_method
    from contracts.schemas import FFType, RunTier, StudyType
    from database.connection import session_scope
    from database.repositories.e_intra_repo import EIntraRepository
    from orchestrator.request_factory import create_build_request, create_protocol_request
    from orchestrator.submission_facade import SubmissionFacade

    mol_id = request.selected_mol_id
    temperatures = request.temperatures_k
    seed_base = request.seed or generate_seed()
    force = request.force_recompute

    # Server-side FF resolution — ignore client ff_type, use SSOT from MoleculeDB
    from features.molecules.catalog import resolve_ff_hint

    ff_resolved = resolve_ff_hint(mol_id)
    ff_type_str = ff_resolved["submit_ff_type"]  # Always "bulk_ff_gaff2" in current pipeline

    # Fail-closed: reject blocked molecules before any work
    if not ff_resolved["is_submittable"]:
        reason = ff_resolved["blocked_reason"] or "Molecule not submittable"
        return {
            "mol_id": mol_id,
            "total": len(temperatures),
            "submitted": 0,
            "skipped_existing": 0,
            "failed": len(temperatures),
            "items": [
                {"temperature_K": t, "status": "failed", "exp_id": None, "error": reason}
                for t in temperatures
            ],
            "resolved_ff_hint": ff_resolved["ff_hint"],
            "resolved_ff_display_label": ff_resolved["ff_display_label"],
        }

    # Validate mol_id exists in MoleculeDB
    mol_db = get_molecule_db()
    mol_spec = mol_db.get(mol_id)
    if mol_spec is None:
        return {
            "mol_id": mol_id,
            "total": len(temperatures),
            "submitted": 0,
            "skipped_existing": 0,
            "failed": len(temperatures),
            "items": [
                {
                    "temperature_K": t,
                    "status": "failed",
                    "exp_id": None,
                    "error": f"Molecule {mol_id} not found in MoleculeDB",
                }
                for t in temperatures
            ],
            "resolved_ff_hint": ff_resolved["ff_hint"],
            "resolved_ff_display_label": ff_resolved["ff_display_label"],
        }

    # Real atom count from MoleculeSpec (single molecule has only ~10-100 atoms)
    mol_atom_count = int(mol_spec.atom_count or 100)

    items: list[dict] = []
    submitted = 0
    skipped = 0
    failed = 0

    # Resolve the active E_intra method once for the whole batch so it flows
    # uniformly into duplicate-check, exp_id hash, force-recompute cleanup,
    # ProtocolRequest, and submission metadata_json.
    active_method = resolve_submission_e_intra_method(getattr(request, "e_intra_method", None))

    # Check existing E_intra + active experiments to avoid duplicates
    skip_temps: set[float] = set()
    if not force:
        try:
            with session_scope() as session:
                e_intra_repo = EIntraRepository(session)
                ff_name = get_ff_display_label(ff_type_str)

                for temp in temperatures:
                    from contracts.schemas import EIntraKey

                    key = EIntraKey(
                        mol_id=mol_id,
                        ff_name=ff_name,
                        ff_version=get_ff_version(ff_type_str),
                        temperature_K=temp,
                        method=active_method,
                    )
                    if e_intra_repo.exists(key):
                        skip_temps.add(temp)
                        continue

                    # Check if identical single-molecule experiment is already active.
                    # PR 2: ``study_type`` alone is not enough — Method 1 and
                    # Method 1a both share study_type=single_molecule_vacuum,
                    # so we additionally require the active job's
                    # ``metadata_json["e_intra_method"]`` to match the active
                    # method.  Legacy rows without that key are treated as
                    # Method 1 (single_molecule_vacuum).
                    from database.models import ExperimentModel

                    candidates = (
                        session.query(ExperimentModel)
                        .filter(
                            ExperimentModel.additive_mol_id == mol_id,
                            ExperimentModel.temperature_K == temp,
                            ExperimentModel.study_type == "single_molecule_vacuum",
                            ExperimentModel.status.in_(
                                ["pending", "queued", "building", "ready", "running"]
                            ),
                        )
                        .all()
                    )
                    active_match = None
                    for cand in candidates:
                        meta = getattr(cand, "metadata_json", None) or {}
                        from contracts.schema_enums import normalize_e_intra_method

                        cand_method = normalize_e_intra_method(
                            meta.get("e_intra_method", "single_molecule_vacuum")
                        )
                        if cand_method == active_method.value:
                            active_match = cand
                            break
                    if active_match:
                        skip_temps.add(temp)
        except Exception as exc:
            logger.warning("Failed to check existing E_intra/experiments: %s", exc)

    job_manager = get_job_manager()

    for temp in temperatures:
        force_cleanup_completed = False
        if temp in skip_temps:
            items.append(
                {"temperature_K": temp, "status": "skipped_existing", "exp_id": None, "error": None}
            )
            skipped += 1
            continue

        try:
            # Generate canonical exp_id for single molecule first.
            # Format: SM_{mol_id}_{temperature}K_{hash6}
            # PR 2: ``method`` is folded into the hash so Method 1 and 1a
            # produce distinct exp_ids; legacy Method 1 keeps its hash shape.
            exp_id = _make_single_molecule_exp_id(
                mol_id=mol_id,
                temperature_k=temp,
                ff_type=ff_type_str,
                atom_count=mol_atom_count,
                seed=seed_base,
                method=active_method.value,
            )

            # Force recompute: delete existing experiment and E_intra cache
            # for this specific method (PR 2: not all methods).
            if force:
                _handle_force_recompute_cleanup(
                    exp_id=exp_id,
                    mol_id=mol_id,
                    temp=temp,
                    ff_type_str=ff_type_str,
                    method=active_method.value,
                )
                force_cleanup_completed = True

            # Direct composition: single molecule, count=1
            composition = {mol_id: 1.0}

            build_request = create_build_request(
                composition=composition,
                composition_mode="mol_count",
                seed=seed_base,
                tier=RunTier.SCREENING,
                initial_density=0.01,  # Very low density for large vacuum box
                target_atoms=mol_atom_count,  # Single molecule: ~10-100 atoms, not 100k
            )

            protocol_request = create_protocol_request(
                tier=RunTier.SCREENING,
                ff_type=FFType(ff_type_str),
                temperature_K=temp,
                pressure_atm=1.0,
                study_type=StudyType.SINGLE_MOLECULE_VACUUM,
                e_intra_method=active_method.value,
                skip_stage_keys=["npt_production"],  # vacuum: minimize + NVT only
            )

            # Use SubmissionFacade for canonical DB-first lifecycle
            job_id, celery_task_id = SubmissionFacade.submit_experiment(
                job_manager=job_manager,
                exp_id=exp_id,
                run_tier=RunTier.SCREENING.value,
                ff_type=ff_type_str,
                target_atoms=mol_atom_count,
                temperature_k=temp,
                pressure_atm=1.0,
                seed=seed_base,
                comp_asphaltene_wt=0.0,
                comp_resin_wt=0.0,
                comp_aromatic_wt=0.0,
                comp_saturate_wt=0.0,
                build_request=build_request,
                protocol_request=protocol_request,
                material_id=f"single_mol_{mol_id}",
                additive_type=mol_id,
                additive_wt=0.0,
                additive_mol_id=mol_id,
                metadata_json={
                    "source": SubmissionSource.SINGLE_MOLECULE.value,
                    "study_type": "single_molecule_vacuum",
                    "e_intra_method": active_method.value,
                },
            )

            items.append(
                {"temperature_K": temp, "status": "submitted", "exp_id": exp_id, "error": None}
            )
            submitted += 1

        except Exception as exc:
            logger.error(
                "Failed to submit single-molecule %s @ %.0fK: %s",
                mol_id,
                temp,
                exc,
                exc_info=True,
            )
            items.append(
                {
                    "temperature_K": temp,
                    "status": "failed",
                    "exp_id": None,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "force_recompute_cleanup_completed": force_cleanup_completed if force else None,
                }
            )
            failed += 1

    return {
        "mol_id": mol_id,
        "total": len(temperatures),
        "submitted": submitted,
        "skipped_existing": skipped,
        "failed": failed,
        "items": items,
        "resolved_ff_hint": ff_resolved["ff_hint"],
        "resolved_ff_display_label": ff_resolved["ff_display_label"],
    }
