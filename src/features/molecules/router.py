"""Molecule and composition routes."""

from datetime import UTC

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from . import service as molecules_service


class AdminGenerateSelectedRequest(BaseModel):
    """Request body for ``POST /artifacts/admin/generate-selected``."""

    mol_ids: list[str] = Field(..., min_length=1)
    profile: str = "baseline"
    force: bool = False  # v00.99.63: True → regenerate even if artifact is complete


router = APIRouter()


def _validate_e_intra_method(value: str | None) -> str | None:
    """Reject unknown method tags at the REST boundary (PR 2 Codex Round 5)."""
    if value is None:
        return None
    from contracts.schema_enums import EIntraMethod, normalize_e_intra_method

    try:
        return normalize_e_intra_method(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown e_intra_method='{value}'. Allowed: {[m.value for m in EIntraMethod]}"
            ),
        ) from exc


@router.get("/molecules", tags=["Molecules"])
async def list_molecules(
    sara_type: str | None = None,
    aging_state: str | None = None,
    temperature_code: str | None = None,
    limit: int = 100,
    offset: int = 0,
    e_intra_method: str | None = None,
):
    """List molecules with optional E_intra coverage method override.

    PR 2 (Codex Round 5): ``e_intra_method`` lets the client request a
    specific Method 1 / 1a / 2 coverage view; default is Method 1 baseline.
    """
    method = _validate_e_intra_method(e_intra_method)
    return await molecules_service.list_molecules(
        sara_type=sara_type,
        aging_state=aging_state,
        temperature_code=temperature_code,
        limit=limit,
        offset=offset,
        e_intra_method=method,
    )


@router.get("/binder-types", tags=["Composition"])
async def list_binder_types():
    return await molecules_service.list_binder_types()


@router.get("/binder-types/{binder_type}/composition", tags=["Composition"])
async def get_binder_composition(
    binder_type: str,
    size: str = "X1",
    aging: str = "non_aging",
    temp_code: str = "0293",
):
    return await molecules_service.get_binder_composition(
        binder_type=binder_type,
        size=size,
        aging=aging,
        temp_code=temp_code,
    )


@router.get("/additives", tags=["Composition"])
async def list_additives():
    return await molecules_service.list_additives()


@router.get("/molecules/{mol_id}/structure", tags=["Molecules"])
async def get_molecule_structure(mol_id: str):
    return await molecules_service.get_molecule_structure(mol_id)


@router.get("/e_intra/{mol_id}", tags=["E_intra"])
async def get_e_intra(
    mol_id: str,
    ff_name: str | None = None,
    ff_version: str | None = None,
    e_intra_method: str | None = None,
):
    """Get E_intra values for a molecule.

    Args:
        mol_id: Molecule identifier.
        ff_name: Force field name. Defaults to canonical GAFF2 (resolved by repository).
        ff_version: Force field version. Defaults to canonical version from registry.
        e_intra_method: PR 2 (Codex Round 5) — E_intra method tag.  Allowed
            values are ``EIntraMethod`` strings.  Defaults to Method 1 baseline.

    Returns:
        E_intra data with resolved FF parameters and coverage information.
    """
    method = _validate_e_intra_method(e_intra_method)
    return await molecules_service.get_e_intra(
        mol_id,
        ff_name=ff_name,
        ff_version=ff_version,
        e_intra_method=method,
    )


# ---------------------------------------------------------------------------
# GAFF2 Artifact Generation
# ---------------------------------------------------------------------------


@router.delete("/artifacts/{mol_id}", tags=["Artifacts"])
async def delete_artifact_endpoint(mol_id: str, force: bool = False):
    """Delete a GAFF2 artifact and reset YAML status to blocked_placeholder.

    Args:
        mol_id: Molecule ID to delete artifact for.
        force: When True, delete even if source_id is shared by multiple consumers.
    """
    import re

    if not re.fullmatch(r"[A-Za-z0-9_ \-]+", mol_id):
        raise HTTPException(status_code=400, detail="Invalid mol_id format")

    from features.molecules.artifact_service import (
        delete_artifact,
        resolve_artifact_target,
    )

    target = resolve_artifact_target(mol_id)
    try:
        deleted = delete_artifact(mol_id, ff_assignment=target.ff_assignment, force=force)
    except (ValueError, PermissionError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        # Shared source_id → refuse without force=True (operator-level action).
        raise HTTPException(status_code=409, detail=str(e)) from e
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Artifact not found: {mol_id}")
    return {
        "status": "deleted",
        "mol_id": mol_id,
        "source_id": target.source_id,
    }


@router.delete("/e_intra/{mol_id}", tags=["E_intra"])
async def delete_e_intra_endpoint(
    mol_id: str,
    e_intra_method: str | None = None,
    all_methods: bool = False,
) -> dict:
    """Delete E_intra values for a molecule.

    PR 2 (Codex Round 6): explicit, method-scoped deletion is the safe
    default — Method 1 and Method 1a rows now coexist under the 5-column
    UC, so a blanket "delete all" can no longer be the implicit behaviour.

    Behaviour:
    - ``e_intra_method`` set → delete only that method's rows for this molecule.
    - ``all_methods=true`` → delete every method's rows (legacy behaviour).
    - Both unset → 400 Bad Request (forces an explicit choice).
    """
    import re

    if not re.fullmatch(r"[A-Za-z0-9_ \-]+", mol_id):
        raise HTTPException(status_code=400, detail="Invalid mol_id format")

    if not e_intra_method and not all_methods:
        raise HTTPException(
            status_code=400,
            detail=(
                "Specify either e_intra_method=<tag> for a method-scoped delete "
                "or all_methods=true to wipe every method (legacy behaviour). "
                "Both unset is rejected to prevent accidental cross-method deletion."
            ),
        )

    method_str = _validate_e_intra_method(e_intra_method)

    from contracts.policies.forcefield import get_ff_display_label, get_ff_version
    from database.connection import session_scope
    from database.repositories.e_intra_repo import EIntraRepository

    with session_scope() as session:
        repo = EIntraRepository(session)
        if all_methods:
            count = repo.delete_all_by_mol_id(mol_id)
        else:
            count = repo.delete_by_mol_id(
                mol_id,
                ff_name=get_ff_display_label("bulk_ff_gaff2"),
                ff_version=get_ff_version("bulk_ff_gaff2"),
                method=method_str,
            )
        session.commit()

    if count == 0:
        raise HTTPException(status_code=404, detail=f"No E_intra data found for {mol_id}")
    return {
        "status": "deleted",
        "mol_id": mol_id,
        "deleted_count": count,
        "method": method_str if not all_methods else None,
        "all_methods": all_methods,
    }


@router.post("/artifacts/admin/reset-batch", tags=["Artifacts (admin)"])
async def reset_batch():
    """Force-reset a stuck batch slot (running=true after abnormal termination)."""
    from features.molecules.artifact_service import release_batch_slot

    release_batch_slot()
    return {"status": "reset", "message": "Batch slot released."}


@router.get("/artifacts/status", tags=["Artifacts"])
async def get_artifact_status():
    """Get GAFF2 artifact generation status for all organic molecules."""
    from features.molecules.artifact_service import (
        check_ambertools_available,
        get_pending_molecules,
    )

    molecules = get_pending_molecules()
    total = len(molecules)
    complete = sum(1 for m in molecules if m["is_complete"])
    pending = total - complete

    return {
        "total": total,
        "complete": complete,
        "pending": pending,
        "ambertools_available": check_ambertools_available(),
        "molecules": molecules,
    }


@router.post("/artifacts/generate/{mol_id}", tags=["Artifacts"])
async def generate_artifact_endpoint(
    mol_id: str,
    background_tasks: BackgroundTasks,
):
    """Generate GAFF2 artifact for a single molecule."""
    from pathlib import Path

    from features.molecules.artifact_service import (
        check_ambertools_available,
        generate_gaff2_artifact,
        get_pending_molecules,
        resolve_artifact_target,
        validate_artifact,
    )

    if not check_ambertools_available():
        raise HTTPException(
            status_code=503,
            detail="AmberTools not available. Run: conda activate asphalt_env",
        )

    # Find molecule info
    molecules = get_pending_molecules()
    mol_info = next((m for m in molecules if m["mol_id"] == mol_id), None)
    if not mol_info:
        raise HTTPException(
            status_code=404,
            detail=f"Molecule {mol_id} not found in organic catalog",
        )

    if mol_info.get("is_passthrough"):
        raise HTTPException(
            status_code=409,
            detail=(
                f"{mol_id} uses organic_gaff2_passthrough parameterization; "
                "use the admin FF Parameters page instead."
            ),
        )

    mol_path = Path(mol_info["mol_path"])
    if not mol_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"MOL file not found: {mol_path.name}",
        )

    from features.molecules.admin_status import AdminStatusStore
    from features.molecules.artifact_service import (
        ARTIFACT_DIR,
        source_generation_lock,
    )
    from features.molecules.exceptions import ArtifactGenerationError

    target = resolve_artifact_target(mol_id)
    store = AdminStatusStore(ARTIFACT_DIR)
    # Single critical section: artifact write + sidecar write are atomic
    # from any reader's perspective. Same lock primitive that the runtime
    # auto-generation path and the admin endpoint use.
    try:
        with source_generation_lock(target.source_id):
            try:
                artifact = generate_gaff2_artifact(
                    mol_path=mol_path,
                    mol_id=mol_id,
                    smiles=mol_info.get("smiles", ""),
                    formal_charge=mol_info.get("formal_charge", 0),
                    ff_assignment=target.ff_assignment,
                )
            except ArtifactGenerationError as e:
                try:
                    from features.molecules.admin_status import (
                        recommended_action_for_failure,
                    )

                    store.record_failure(
                        target.source_id,
                        e,
                        consumer_ids=target.consumer_ids,
                        generation_profile="baseline",
                        recommended_action=recommended_action_for_failure(e.failure_code.value),
                    )
                except Exception:
                    pass
                raise HTTPException(
                    status_code=409 if e.failure_code.value == "passthrough_unsupported" else 500,
                    detail={
                        "message": e.message,
                        "failure_code": e.failure_code.value,
                        "stage": e.stage,
                    },
                ) from e
            validation = validate_artifact(artifact)
            try:
                store.record_success(
                    target.source_id,
                    consumer_ids=target.consumer_ids,
                    generation_profile="baseline",
                    generator=artifact.get("generator", "antechamber_am1bcc"),
                )
            except Exception:
                pass
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Generation failed: {str(e)[:300]}",
        ) from e

    # Invalidate the runtime cache so subsequent builds pick up the fresh file.
    try:
        from forcefield.organic_curated_artifact import clear_artifact_cache

        clear_artifact_cache()
    except ImportError:
        pass

    return {
        "status": "completed",
        "mol_id": mol_id,
        "source_id": target.source_id,
        "atoms": len(artifact["atoms"]),
        "bond_types": len(artifact["bond_types"]),
        "angle_types": len(artifact["angle_types"]),
        "dihedral_types": len(artifact["dihedral_types"]),
        "improper_types": len(artifact["improper_types"]),
        "charge_sum": artifact.get("charge_sum", 0),
        "validation": validation,
    }


@router.get("/artifacts/batch-progress", tags=["Artifacts"])
async def get_batch_progress_endpoint():
    """Get batch artifact generation progress."""
    from features.molecules.artifact_service import get_batch_progress

    return get_batch_progress()


@router.post("/artifacts/cancel-batch", tags=["Artifacts"])
async def cancel_batch_endpoint(force: bool = False):
    """Cancel running batch generation.

    Args:
        force: When True, performs comprehensive cleanup:
            - Removes ALL ``.*.generating.lock`` files (regardless of age)
            - Releases the batch slot immediately

            When False (default), sets cancel flag for running workers.
            In-flight molecules will complete; pending ones are skipped.

    Returns:
        Status and cleanup counts.

    Note:
        ``force=True`` is a destructive operation intended for stuck
        batches where the process has already terminated. The UI should
        confirm with the operator before calling.
    """
    if force:
        from features.molecules.artifact_service import force_cleanup_batch

        result = force_cleanup_batch()
        return {
            "status": "force_cancelled",
            "message": f"Forced cleanup: {result['locks_removed']} locks removed.",
            **result,
        }

    from features.molecules.artifact_service import cancel_batch

    cancelled = cancel_batch()
    if not cancelled:
        return {
            "status": "no_batch_running",
            "message": "No batch generation is currently running.",
        }
    return {
        "status": "cancelling",
        "message": "Cancellation requested. Current molecule(s) will finish, then batch stops.",
    }


@router.post("/artifacts/generate-all", tags=["Artifacts"])
async def generate_all_artifacts(
    background_tasks: BackgroundTasks,
    max_workers: int | None = None,
):
    """Generate GAFF2 artifacts for all pending organic molecules (async batch).

    Uses parallel ProcessPoolExecutor (sqm is single-threaded CPU-bound).
    Returns 202 Accepted immediately; generation runs in background.
    Poll GET /artifacts/batch-progress to track progress.

    v00.99.43: acquires the global batch slot synchronously so a
    concurrent admin batch is rejected with 409 instead of racing.

    Args:
        max_workers: Max parallel processes. None = auto (cpu_count - 4).
    """
    from features.molecules.artifact_service import (
        acquire_batch_slot,
        check_ambertools_available,
        get_batch_progress,
        get_pending_molecules,
    )

    if not check_ambertools_available():
        raise HTTPException(status_code=503, detail="AmberTools not available")

    molecules = get_pending_molecules()
    pending = [m for m in molecules if not m["is_complete"]]

    if not pending:
        return {"status": "nothing_to_do", "total": 0, "pending": 0}

    if not acquire_batch_slot("public", "baseline"):
        snapshot = get_batch_progress()
        raise HTTPException(
            status_code=409,
            detail={
                "message": "another batch is already running",
                "batch_kind": snapshot.get("batch_kind"),
                "generation_profile": snapshot.get("generation_profile"),
                "started_at": snapshot.get("started_at"),
            },
        )

    background_tasks.add_task(
        _run_batch_generation,
        pending,
        max_workers,
        "public",
        "baseline",
    )

    from starlette.responses import JSONResponse

    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "total": len(pending),
            "batch_kind": "public",
            "generation_profile": "baseline",
            "message": f"Batch generation started for {len(pending)} molecules (parallel). Poll GET /artifacts/batch-progress for progress.",
        },
    )


# ---------------------------------------------------------------------------
# Ionic Artifact Generation
# ---------------------------------------------------------------------------


@router.post("/artifacts/generate-ionic/{mol_id}", tags=["Artifacts"])
async def generate_ionic_artifact_endpoint(mol_id: str):
    """Generate ionic artifact (Joung-Cheatham/Li-Merz parameters)."""
    from features.molecules.ionic_artifact_service import (
        generate_ionic_artifact,
        get_supported_ionic_molecules,
        validate_ionic_artifact,
    )

    supported = get_supported_ionic_molecules()
    if mol_id not in supported:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported ionic molecule: {mol_id}. Supported: {', '.join(supported)}",
        )

    try:
        artifact = generate_ionic_artifact(mol_id)
        validation = validate_ionic_artifact(artifact)
        return {
            "status": "completed",
            "mol_id": mol_id,
            "ff_family": "ionic_jc_tip3p",
            "atoms": len(artifact["atoms"]),
            "charge_sum": artifact.get("charge_sum", 0),
            "validation": validation,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Generation failed: {str(e)[:300]}",
        ) from e


@router.post("/artifacts/generate-all-ionic", tags=["Artifacts"])
async def generate_all_ionic_artifacts():
    """Generate artifacts for all supported ionic molecules."""
    from features.molecules.ionic_artifact_service import (
        generate_ionic_artifact,
        get_supported_ionic_molecules,
        validate_ionic_artifact,
    )

    supported = get_supported_ionic_molecules()
    results: dict = {"total": len(supported), "success": 0, "failed": 0, "details": []}

    for mol_id in supported:
        try:
            artifact = generate_ionic_artifact(mol_id)
            validation = validate_ionic_artifact(artifact)
            results["success"] += 1
            results["details"].append(
                {
                    "mol_id": mol_id,
                    "status": "completed",
                    "atoms": len(artifact["atoms"]),
                    "valid": validation["valid"],
                }
            )
        except Exception as e:
            results["failed"] += 1
            results["details"].append(
                {
                    "mol_id": mol_id,
                    "status": "error",
                    "error": str(e)[:200],
                }
            )

    return results


def _run_batch_generation(
    pending: list[dict],
    max_workers: int | None = None,
    batch_kind: str = "public",
    generation_profile: str = "baseline",
) -> None:
    """Background task: generate artifacts in parallel across CPU cores.

    The HTTP layer has already called ``acquire_batch_slot`` so we pass
    ``slot_already_acquired=True`` and just forward the metadata. The
    slot is released by ``run_parallel_batch`` itself (try/finally).

    Args:
        pending: List of molecule dicts from get_pending_molecules().
        max_workers: Max parallel processes. None = auto-detect.
        batch_kind: ``"public"`` or ``"admin"`` (already on progress dict).
        generation_profile: ``"baseline"`` or ``"sqm_robust"``.
    """
    from features.molecules.artifact_service import run_parallel_batch

    run_parallel_batch(
        pending,
        max_workers=max_workers,
        batch_kind=batch_kind,
        generation_profile=generation_profile,
        slot_already_acquired=True,
    )


# ---------------------------------------------------------------------------
# Phase 5 (v00.99.41) — Admin control plane
#
# All admin endpoints below sit behind the ``ASPHALT_ANTECHAMBER_ADMIN``
# environment guard, mirroring the precedent set by the ionic Wave 3
# activation flag (``ASPHALT_IONIC_ROUTE_ACTIVATED``). The capabilities
# endpoint is intentionally NOT guarded so the frontend can always
# discover whether the admin surface is enabled (and render the FF
# Parameters page accordingly).
# ---------------------------------------------------------------------------


_ADMIN_PROFILES: tuple[str, ...] = ("baseline", "sqm_robust")

# Admin gate removed (v00.99.45) — all FF Parameters endpoints always accessible.
# _admin_enabled() and _require_admin() removed.


@router.get("/artifacts/admin/capabilities", tags=["Artifacts (admin)"])
async def admin_capabilities():
    """Always-200 capability probe for the FF Parameters page.

    Returned shape::

        {
            "enabled": bool,
            "ambertools_available": bool,
            "rdkit_available": bool,
            "profiles": ["baseline", "sqm_robust"]
        }

    When admin is disabled, the underlying ``ambertools_available`` and
    ``rdkit_available`` flags are reported as ``False`` so an unauth'd
    caller cannot use this endpoint to probe the host's tool inventory.
    """
    # Always enabled — admin gate removed (v00.99.45)
    from features.molecules.artifact_service import check_ambertools_available

    ambertools_available = check_ambertools_available()
    rdkit_available = False
    try:
        import rdkit  # noqa: F401

        rdkit_available = True
    except Exception:
        rdkit_available = False

    return {
        "enabled": True,
        "ambertools_available": ambertools_available,
        "rdkit_available": rdkit_available,
        "profiles": list(_ADMIN_PROFILES),
    }


@router.get("/artifacts/admin/status", tags=["Artifacts (admin)"])
async def admin_status():
    """Source-centric admin status (env-guarded).

    One row per ``source_id`` joining the catalog inventory with the
    persisted ``.admin_status/`` sidecars. Includes consumer_ids so
    operators can see which mol_ids share a source_id (e.g., CNT +
    Graphene → carbon_sp2_passthrough_v1).
    """

    from features.molecules.admin_status import AdminStatusStore
    from features.molecules.artifact_service import (
        ARTIFACT_DIR,
        dedupe_by_source_id,
        get_pending_molecules,
    )

    store = AdminStatusStore(ARTIFACT_DIR)
    pending = [m for m in get_pending_molecules() if m.get("artifact_type") == "organic"]
    unique, conflicts = dedupe_by_source_id(pending)

    rows: list[dict] = []
    for row in unique:
        sid = row.get("source_id") or row["mol_id"]
        sidecar = store.get(sid)
        # Real-time filesystem check computed from is_passthrough / is_complete /
        # has_artifact. Same classifier used by `get_pending_molecules`, so two
        # endpoints stay SSOT-consistent (previously sidecar could override
        # a real "complete" artifact with a stale "pending" value).
        if row.get("is_passthrough"):
            artifact_status = "passthrough"
        elif row.get("is_complete"):
            artifact_status = "complete"
        elif row.get("has_artifact"):
            artifact_status = "incomplete"
        else:
            artifact_status = "pending"

        # Sidecar carries failure details (stage/stderr/failure_code) that must
        # survive across restarts, but its recorded `artifact_status` CAN go
        # stale when the artifact file changes without a fresh generation pass
        # (e.g. out-of-band tool run, manual repair, or successful retry whose
        # sidecar wasn't rewritten). Only trust the sidecar status in states
        # where filesystem evidence is insufficient — i.e. when we have no
        # complete artifact AND sidecar records a terminal "failed" state.
        if (
            sidecar is not None
            and artifact_status != "complete"
            and artifact_status != "passthrough"
        ):
            effective_status = sidecar.artifact_status or artifact_status
        else:
            effective_status = artifact_status

        rows.append(
            {
                "source_id": sid,
                "primary_mol_id": row["mol_id"],
                "consumer_ids": list(row.get("consumer_ids") or [row["mol_id"]]),
                "artifact_status": effective_status,
                "has_artifact": row.get("has_artifact", False),
                "is_complete": row.get("is_complete", False),
                "validation": row.get("validation"),
                "is_passthrough": row.get("is_passthrough", False),
                "parameterization_mode": row.get("parameterization_mode"),
                "failure_code": sidecar.failure_code if sidecar else None,
                "stage": sidecar.stage if sidecar else "",
                "stderr_excerpt": sidecar.stderr_excerpt if sidecar else "",
                "recommended_action": (sidecar.recommended_action if sidecar else ""),
                "generation_profile": (sidecar.generation_profile if sidecar else ""),
                "generator": (sidecar.generator if sidecar else ""),
                "preflight": sidecar.preflight if sidecar else None,
                "last_attempt_at": sidecar.last_attempt_at if sidecar else None,
                "last_success_at": sidecar.last_success_at if sidecar else None,
                "atom_count": row.get("atom_count", 0),
                "catalog": row.get("catalog"),
            }
        )
    return {
        "rows": rows,
        "conflicts": [
            {
                "mol_id": c["mol_id"],
                "source_id": c.get("source_id"),
                "conflict_with": c.get("conflict_with"),
            }
            for c in conflicts
        ],
    }


@router.post("/artifacts/admin/generate/{mol_id}", tags=["Artifacts (admin)"])
async def admin_generate(mol_id: str, profile: str = "baseline"):
    """Admin generate with optional ``sqm_robust`` profile (env-guarded).

    Routing/gating policy is delegated to
    :func:`features.molecules.artifact_service.validate_admin_generation_request`
    so the CLI (``scripts/generate_gaff2_artifact.py``) and this HTTP
    endpoint apply identical rules. The artifact write and the admin
    sidecar record_* call live inside the same
    :func:`source_generation_lock` scope so admin status reflects
    success/failure atomically.
    """

    from pathlib import Path

    from features.molecules.admin_status import AdminStatusStore
    from features.molecules.artifact_service import (
        ARTIFACT_DIR,
        AdminGenerationError,
        check_ambertools_available,
        generate_gaff2_artifact,
        get_pending_molecules,
        resolve_artifact_target,
        source_generation_lock,
        validate_admin_generation_request,
        validate_artifact,
    )
    from features.molecules.exceptions import ArtifactGenerationError

    target = resolve_artifact_target(mol_id)
    store = AdminStatusStore(ARTIFACT_DIR)
    try:
        validate_admin_generation_request(target, profile, store)
    except AdminGenerationError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail={"message": e.message, **e.detail},
        ) from e

    if not check_ambertools_available():
        raise HTTPException(status_code=503, detail="AmberTools not available")

    molecules = get_pending_molecules()
    # v00.99.63: match on mol_id or consumer_ids so temp_code-suffixed
    # mol_ids from the frontend resolve correctly.
    mol_info = next(
        (m for m in molecules if m["mol_id"] == mol_id or mol_id in (m.get("consumer_ids") or [])),
        None,
    )
    if not mol_info:
        raise HTTPException(status_code=404, detail=f"Molecule {mol_id} not found")

    mol_path = Path(mol_info["mol_path"])
    if not mol_path.exists():
        raise HTTPException(status_code=404, detail=f"MOL file not found: {mol_path.name}")

    try:
        with source_generation_lock(target.source_id):
            try:
                artifact = generate_gaff2_artifact(
                    mol_path=mol_path,
                    mol_id=mol_id,
                    smiles=mol_info.get("smiles", ""),
                    formal_charge=mol_info.get("formal_charge", 0),
                    ff_assignment=target.ff_assignment,
                    generation_profile=profile,
                )
            except ArtifactGenerationError as e:
                try:
                    from features.molecules.admin_status import (
                        recommended_action_for_failure,
                    )

                    store.record_failure(
                        target.source_id,
                        e,
                        consumer_ids=target.consumer_ids,
                        generation_profile=profile,
                        recommended_action=recommended_action_for_failure(e.failure_code.value),
                    )
                except Exception:
                    pass
                raise HTTPException(
                    status_code=500,
                    detail={
                        "message": e.message,
                        "failure_code": e.failure_code.value,
                        "stage": e.stage,
                        "generation_profile": profile,
                    },
                ) from e
            validation = validate_artifact(artifact)
            try:
                store.record_success(
                    target.source_id,
                    consumer_ids=target.consumer_ids,
                    generation_profile=profile,
                    generator=artifact.get("generator", "antechamber_am1bcc"),
                )
            except Exception:
                pass
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Generation failed: {str(e)[:300]}",
        ) from e

    try:
        from forcefield.organic_curated_artifact import clear_artifact_cache

        clear_artifact_cache()
    except ImportError:
        pass

    return {
        "status": "completed",
        "mol_id": mol_id,
        "source_id": target.source_id,
        "generation_profile": profile,
        "atoms": len(artifact["atoms"]),
        "validation": validation,
    }


@router.post("/artifacts/admin/diagnose/{mol_id}", tags=["Artifacts (admin)"])
async def admin_diagnose(mol_id: str):
    """RDKit preflight only — no AmberTools execution (env-guarded).

    Delegates to
    :func:`features.molecules.artifact_service.diagnose_artifact_target`
    so HTTP and CLI surfaces share identical preflight semantics.
    """

    from features.molecules.artifact_service import (
        diagnose_artifact_target,
        resolve_artifact_target,
    )

    target = resolve_artifact_target(mol_id)
    return diagnose_artifact_target(target)


@router.get("/artifacts/admin/batch-progress", tags=["Artifacts (admin)"])
async def admin_batch_progress():
    """Admin-side progress view (env-guarded).

    Returns the same payload as the public progress endpoint but is
    routed under ``/admin/`` so the FF Parameters page can use a
    dedicated react-query key (``['artifact-admin-batch-progress']``).
    The payload includes ``batch_kind`` / ``generation_profile`` /
    ``started_at`` so the UI can tell whether the running batch is its
    own (admin) or a public one.
    """

    from features.molecules.artifact_service import get_batch_progress

    return get_batch_progress()


@router.post("/artifacts/admin/generate-all", tags=["Artifacts (admin)"])
async def admin_generate_all(
    background_tasks: BackgroundTasks,
    profile: str = "baseline",
    max_workers: int | None = None,
    force: bool = False,
):
    """Admin batch generate with per-row policy gating (env-guarded).

    Order of operations (matches CLI batch helper):

    1. ``_require_admin`` → 404 if env=0.
    2. Fail fast on profile / AmberTools availability.
    3. ``get_pending_molecules`` filtered to organic + incomplete.
    4. ``dedupe_by_source_id`` first so per-row gating sees one canonical
       row per source_id (Codex insistence: source-centric eligibility).
    5. ``validate_admin_generation_request`` per row → eligible / skipped
       / conflicts split returned in the 202 response.
    6. ``acquire_batch_slot`` synchronously so a concurrent batch is
       rejected with 409 before BackgroundTasks queues anything.
    7. Schedule ``_run_batch_generation`` with ``batch_kind="admin"``.
    """

    from features.molecules.admin_status import AdminStatusStore
    from features.molecules.artifact_service import (
        ARTIFACT_DIR,
        AdminGenerationError,
        acquire_batch_slot,
        check_ambertools_available,
        dedupe_by_source_id,
        get_batch_progress,
        get_pending_molecules,
        resolve_artifact_target,
        validate_admin_generation_request,
    )

    if profile not in _ADMIN_PROFILES:
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"profile must be one of {list(_ADMIN_PROFILES)}",
                "received": profile,
            },
        )

    if not check_ambertools_available():
        raise HTTPException(status_code=503, detail="AmberTools not available")

    molecules = get_pending_molecules()
    pending = [
        m
        for m in molecules
        if m.get("artifact_type") == "organic" and (force or not m.get("is_complete"))
    ]

    # Step 4: dedupe FIRST so eligibility decisions match the source-centric
    # admin status table the FF Parameters page renders.
    unique, conflict_rows = dedupe_by_source_id(pending)
    conflicts_payload = [
        {
            "mol_id": row["mol_id"],
            "source_id": row.get("source_id"),
            "conflict_with": row.get("conflict_with"),
            "reason": "shared_source_id_conflict",
        }
        for row in conflict_rows
    ]

    # Step 5: per-row admin policy gating.
    store = AdminStatusStore(ARTIFACT_DIR)
    eligible: list[dict] = []
    skipped: list[dict] = []
    for row in unique:
        target = resolve_artifact_target(row["mol_id"])
        try:
            validate_admin_generation_request(target, profile, store)
        except AdminGenerationError as exc:
            skipped.append(
                {
                    "mol_id": row["mol_id"],
                    "source_id": target.source_id,
                    "status_code": exc.status_code,
                    "message": exc.message,
                }
            )
            continue
        row["generation_profile"] = profile
        eligible.append(row)

    if not eligible:
        return {
            "status": "nothing_eligible",
            "eligible_count": 0,
            "eligible_source_ids": [],
            "skipped": skipped,
            "conflicts": conflicts_payload,
            "batch_kind": "admin",
            "generation_profile": profile,
        }

    # Step 6: synchronous slot acquisition so we can return 409 atomically.
    if not acquire_batch_slot("admin", profile):
        snapshot = get_batch_progress()
        raise HTTPException(
            status_code=409,
            detail={
                "message": "another batch is already running",
                "batch_kind": snapshot.get("batch_kind"),
                "generation_profile": snapshot.get("generation_profile"),
                "started_at": snapshot.get("started_at"),
            },
        )

    background_tasks.add_task(
        _run_batch_generation,
        eligible,
        max_workers,
        "admin",
        profile,
    )

    from starlette.responses import JSONResponse

    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "eligible_count": len(eligible),
            "eligible_source_ids": [row["source_id"] for row in eligible],
            "skipped": skipped,
            "conflicts": conflicts_payload,
            "batch_kind": "admin",
            "generation_profile": profile,
            "message": f"Admin batch started for {len(eligible)} eligible source_ids "
            f"(profile={profile}). Poll GET /artifacts/admin/batch-progress.",
        },
    )


@router.post("/artifacts/admin/generate-selected", tags=["Artifacts (admin)"])
async def admin_generate_selected(
    payload: AdminGenerateSelectedRequest,
    background_tasks: BackgroundTasks,
    max_workers: int | None = None,
):
    """Admin batch generate for an explicit subset of mol_ids.

    Same pipeline as ``/admin/generate-all`` (dedupe → per-row gating →
    ``batch_kind='admin'`` slot) but filtered to the submitted ``mol_ids``
    so the operator can target a specific selection from the UI.
    Responses are polled via the existing ``GET /admin/batch-progress``.
    """

    from features.molecules.admin_status import AdminStatusStore
    from features.molecules.artifact_service import (
        ARTIFACT_DIR,
        AdminGenerationError,
        acquire_batch_slot,
        check_ambertools_available,
        dedupe_by_source_id,
        get_batch_progress,
        get_pending_molecules,
        resolve_artifact_target,
        validate_admin_generation_request,
    )

    profile = payload.profile
    force = payload.force
    if profile not in _ADMIN_PROFILES:
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"profile must be one of {list(_ADMIN_PROFILES)}",
                "received": profile,
            },
        )

    if not check_ambertools_available():
        raise HTTPException(status_code=503, detail="AmberTools not available")

    requested = set(payload.mol_ids)
    if not requested:
        raise HTTPException(status_code=400, detail="mol_ids must not be empty")

    molecules = get_pending_molecules()
    # v00.99.63: match on consumer_ids (not just mol_id) so frontend
    # mol_ids with temp_code suffixes (e.g. "U-RE-Thio-0293") resolve
    # to the pending row whose mol_id is "U-RE-Thio".
    # force=True bypasses the is_complete filter (regenerate existing).
    selected = [
        m
        for m in molecules
        if m.get("artifact_type") == "organic"
        and (force or not m.get("is_complete"))
        and any(cid in requested for cid in (m.get("consumer_ids") or [m.get("mol_id")]))
    ]

    # Surface unmatched mol_ids back to the operator.
    all_consumer_ids: set[str] = set()
    for m in selected:
        all_consumer_ids.update(m.get("consumer_ids") or [m["mol_id"]])
    unmatched = sorted(requested - all_consumer_ids)

    unique, conflict_rows = dedupe_by_source_id(selected)
    conflicts_payload = [
        {
            "mol_id": row["mol_id"],
            "source_id": row.get("source_id"),
            "conflict_with": row.get("conflict_with"),
            "reason": "shared_source_id_conflict",
        }
        for row in conflict_rows
    ]

    store = AdminStatusStore(ARTIFACT_DIR)
    eligible: list[dict] = []
    skipped: list[dict] = []
    for row in unique:
        target = resolve_artifact_target(row["mol_id"])
        try:
            validate_admin_generation_request(target, profile, store)
        except AdminGenerationError as exc:
            skipped.append(
                {
                    "mol_id": row["mol_id"],
                    "source_id": target.source_id,
                    "status_code": exc.status_code,
                    "message": exc.message,
                }
            )
            continue
        row["generation_profile"] = profile
        eligible.append(row)

    if not eligible:
        return {
            "status": "nothing_eligible",
            "eligible_count": 0,
            "eligible_source_ids": [],
            "skipped": skipped,
            "conflicts": conflicts_payload,
            "unmatched_mol_ids": unmatched,
            "batch_kind": "admin",
            "generation_profile": profile,
        }

    # Mark eligible molecules as "generating" in sidecar so the UI
    # reflects the in-progress state immediately after cache invalidation.
    for row in eligible:
        sid = row.get("source_id") or row["mol_id"]
        try:
            from features.molecules.admin_status import AdminStatus

            existing = store.get(sid)
            store.write(
                AdminStatus(
                    source_id=sid,
                    artifact_status="generating",
                    failure_code=existing.failure_code if existing else None,
                    stage="",
                    stderr_excerpt="",
                    recommended_action="",
                    generation_profile=profile,
                    consumer_ids=list(row.get("consumer_ids") or [row["mol_id"]]),
                    last_attempt_at=existing.last_attempt_at if existing else None,
                    last_success_at=existing.last_success_at if existing else None,
                )
            )
        except Exception:
            pass  # best-effort; sidecar will be overwritten on completion

    if not acquire_batch_slot("admin", profile):
        snapshot = get_batch_progress()
        raise HTTPException(
            status_code=409,
            detail={
                "message": "another batch is already running",
                "batch_kind": snapshot.get("batch_kind"),
                "generation_profile": snapshot.get("generation_profile"),
                "started_at": snapshot.get("started_at"),
            },
        )

    background_tasks.add_task(
        _run_batch_generation,
        eligible,
        max_workers,
        "admin",
        profile,
    )

    from starlette.responses import JSONResponse

    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "eligible_count": len(eligible),
            "eligible_source_ids": [row["source_id"] for row in eligible],
            "skipped": skipped,
            "conflicts": conflicts_payload,
            "unmatched_mol_ids": unmatched,
            "batch_kind": "admin",
            "generation_profile": profile,
            "message": f"Admin batch started for {len(eligible)} eligible source_ids "
            f"(profile={profile}). Poll GET /artifacts/admin/batch-progress.",
        },
    )


@router.post("/artifacts/admin/dump-stacks", tags=["Artifacts (admin)"])
async def admin_dump_stacks():
    """Dump Python thread stacks of the running API process.

    v00.99.94: diagnostics-only endpoint. Writes the current process's
    full set of thread tracebacks to a timestamped file under
    ``logs/stackdump_<utc_iso>.log`` using ``faulthandler.dump_traceback
    (all_threads=True)``. Returns the file path plus a list of direct
    child PIDs so the operator can fan out with
    ``py-spy dump --pid <pid>`` against worker subprocesses when a batch
    lifecycle hang recurs (see v00.99.93 rollback commit for the
    original incident).

    Admin gate removed in v00.99.45 so no additional guard is required.
    """
    import faulthandler
    import os
    import threading
    from datetime import datetime
    from pathlib import Path

    # logs/ already exists in repo root; write next to api.log.
    logs_dir = Path.cwd() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    captured_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    safe_ts = captured_at.replace(":", "-").replace("+", "_")
    dump_path = logs_dir / f"stackdump_{safe_ts}.log"

    try:
        with open(dump_path, "w") as fp:
            fp.write(f"# Stack dump captured at {captured_at}\n")
            fp.write(f"# pid={os.getpid()} thread_count={threading.active_count()}\n\n")
            faulthandler.dump_traceback(file=fp, all_threads=True)
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Failed to write stack dump file",
                "error": str(exc),
                "path": str(dump_path),
            },
        ) from exc

    # Collect direct child PIDs (ProcessPoolExecutor workers / Manager /
    # resource_tracker) so the operator can target them with py-spy.
    child_pids: list[int] = []
    try:
        proc_root = Path("/proc")
        my_pid = os.getpid()
        for entry in proc_root.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                status = (entry / "status").read_text()
            except OSError:
                continue
            for line in status.splitlines():
                if line.startswith("PPid:"):
                    if int(line.split()[1]) == my_pid:
                        child_pids.append(int(entry.name))
                    break
    except Exception:
        # /proc not available (non-Linux) or permissions — silently skip.
        pass

    return {
        "status": "ok",
        "path": str(dump_path),
        "captured_at": captured_at,
        "thread_count": threading.active_count(),
        "child_pids": sorted(child_pids),
    }
