"""Artifact runtime orchestration -- build-time auto-generation + fail-closed.

Policy (post v00.99.30):
- Preview/list API treats missing artifacts as warnings, never blocks submit.
- Build pipeline calls ``ensure_organic_artifact`` which auto-generates a
  curated GAFF2 artifact when absent (single-writer via fcntl lock) and
  raises if generation fails or produces an incomplete artifact.

Design principles:
- YAML is never modified (authoring SSOT stays read-only).
- The artifact loader (organic_curated_artifact.py) stays pure: all side
  effects (generation, cache invalidation) live here.
- fcntl advisory lock keeps the writer single across concurrent build
  workers on the same machine / mounted filesystem.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from common.logging import get_logger

logger = get_logger("molecules.artifact_runtime")

# Stale lock threshold: 6 hours.
# - Large molecules (200+ atoms): AM1-BCC can take 1-2 hours
# - System load: can extend this further
# - Large batch jobs (500+ molecules): need ample headroom
# Locks older than this are considered orphaned from crashed processes.
_STALE_LOCK_THRESHOLD_SECONDS = 21600


def _cleanup_stale_locks(artifact_dir: Path) -> int:
    """Remove stale .generating.lock files from the artifact directory.

    fcntl advisory locks are released when the process terminates, but the
    lock files themselves may remain if the process crashes or is killed.
    These orphaned files are harmless (new processes can still acquire locks)
    but clutter the directory.

    Args:
        artifact_dir: Directory containing artifact files and lock files.

    Returns:
        Number of stale lock files removed.
    """
    if not artifact_dir.exists():
        return 0

    now = time.time()
    removed = 0

    for lock_file in artifact_dir.glob(".*.generating.lock"):
        try:
            mtime = lock_file.stat().st_mtime
            age_seconds = now - mtime
            if age_seconds > _STALE_LOCK_THRESHOLD_SECONDS:
                lock_file.unlink(missing_ok=True)
                logger.debug(
                    "Removed stale lock file (age %.1f hours): %s",
                    age_seconds / 3600,
                    lock_file.name,
                )
                removed += 1
        except OSError:
            # File may have been removed by another process
            pass

    if removed > 0:
        logger.info("Cleaned up %d stale lock file(s) in %s", removed, artifact_dir)

    return removed


def is_artifact_ready(
    mol_id: str,
    ff_assignment: dict,
    ff_family: str = "organic_gaff2",
) -> tuple[bool, str]:
    """Check whether a complete GAFF2 artifact already exists for this molecule.

    This is the observe-only counterpart of :func:`ensure_organic_artifact` and
    is safe to call from preview endpoints: it performs only the cheap
    existence + completeness check (the same `fast path` used at the top of
    ``ensure_organic_artifact``) and never invokes AM1-BCC generation.

    Args:
        mol_id: Molecule ID (variant or base).
        ff_assignment: The molecule's ``ff_assignment`` dict from YAML.
        ff_family: Force field family (currently only ``"organic_gaff2"``).

    Returns:
        ``(True, source_id)`` if the artifact exists and passes the
        completeness check; ``(False, source_id)`` otherwise.
    """
    from features.molecules.artifact_service import (
        _is_artifact_complete,
        get_artifact_path,
        resolve_artifact_source_id,
    )

    _ = ff_family  # currently only organic_gaff2 is supported

    source_id = resolve_artifact_source_id(mol_id, ff_assignment)
    artifact_path = get_artifact_path(mol_id, ff_assignment)
    ready = artifact_path.exists() and _is_artifact_complete(artifact_path)
    return ready, source_id


def _should_skip_to_fragment(store, source_id: str) -> bool:
    """Return True iff prior admin-status history shows this molecule needs
    fragment_fallback (logic ②, failure-history skip).

    AM1 SCF (non-)convergence is deterministic for a fixed structure, so a
    molecule that previously needed fragment_fallback will need it again.
    Verdict:
      1. previously resolved via fragment_fallback (``generation_profile``), or
      2. previously exhausted AM1 SCF (``sqm_timeout`` / ``sqm_nonconverged``)
         at the sqm_robust profile.
    """
    from contracts.policies.ff_generation import DEFAULT_FF_GENERATION_POLICY

    try:
        sidecar = store.get(source_id)
    except Exception:
        return False
    if sidecar is None:
        return False
    if sidecar.generation_profile == "fragment_fallback":
        return True
    return (
        sidecar.generation_profile == "sqm_robust"
        and sidecar.failure_code in DEFAULT_FF_GENERATION_POLICY.scf_failure_codes
    )


def _should_prescreen_to_fragment(mol_path: Path) -> bool:
    """Return True iff the molecule is large enough that AM1-BCC is impractical,
    so it should skip baseline+sqm_robust and go straight to fragment_fallback on
    the FIRST encounter (efficiency layer, v01.06.20).

    Deliberately **size-only**: ring-density / "fused aromatic" heuristics are
    NOT used because they mis-route convergent systems (flat graphene converges
    while curved CNT of the same size does not — the discriminator is geometry,
    not 2-D topology, which RDKit cannot see reliably). The threshold sits above
    the largest molecule that converges in this project, so a known-good FF is
    never degraded; genuinely non-convergent same-size structures (e.g. CNT) are
    still caught by the zero-false-positive failure-history skip on re-encounter.

    Only neutral CHONS molecules (which fragment_fallback can actually handle)
    are routed; anything else falls through to the normal chain / fail-closed.
    """
    from contracts.policies.ff_generation import DEFAULT_FF_GENERATION_POLICY

    policy = DEFAULT_FF_GENERATION_POLICY
    if not policy.prescreen_to_fragment_enabled:
        return False
    try:
        from rdkit import Chem

        from forcefield.fragment_fallback import _ALLOWED_ELEMENTS

        mol = Chem.MolFromMolFile(str(mol_path), removeHs=False)
        if mol is None or mol.GetNumAtoms() <= policy.prescreen_max_atoms:
            return False
        elements = {a.GetSymbol() for a in mol.GetAtoms()}
        return elements.issubset(_ALLOWED_ELEMENTS) and Chem.GetFormalCharge(mol) == 0
    except Exception:
        return False


def ensure_organic_artifact(
    mol_id: str,
    mol_path: Path,
    ff_assignment: dict,
    ff_family: str = "organic_gaff2",
    *,
    progress_callback: Callable[[str, str], None] | None = None,
) -> str:
    """Ensure a complete GAFF2 artifact exists for this molecule.

    Fast path: existing + complete artifact returns immediately.

    Slow path: acquires an fcntl LOCK_EX on a per-source_id lock file, then
    double-checks, invokes :func:`generate_gaff2_artifact`, and re-verifies
    completeness. The lock keeps concurrent build workers from racing on
    the same artifact.

    Args:
        mol_id: Molecule ID (variant or base, e.g. ``"U-SA-Squalane-0293"``
            or ``"Methanol"``).
        mol_path: Path to the MOL/MOL2 file used for AM1-BCC parameterization.
        ff_assignment: The molecule's ``ff_assignment`` dict from YAML.
        ff_family: Force field family (currently only ``"organic_gaff2"``).
        progress_callback: Optional ``(code, label)`` callback forwarded to
            :func:`generate_gaff2_artifact` on the slow path. Not invoked on
            the fast path (artifact already complete).

    Returns:
        The resolved ``source_id`` for use with ``load_artifact``.

    Raises:
        ArtifactMissingError: If generation is required but ``mol_path`` does
            not exist.
        ArtifactIncompleteError: If generation fails or the generated
            artifact is still incomplete (missing LJ params / bonded terms /
            charge sum mismatch).
    """
    from features.molecules.artifact_service import (
        _is_artifact_complete,
        generate_gaff2_artifact,
        get_artifact_path,
        resolve_artifact_source_id,
    )
    from forcefield.organic_curated_artifact import (
        ArtifactIncompleteError,
        ArtifactMissingError,
        clear_artifact_cache,
    )

    _ = ff_family  # currently only organic_gaff2 is supported

    source_id = resolve_artifact_source_id(mol_id, ff_assignment)
    artifact_path = get_artifact_path(mol_id, ff_assignment)

    # Fast path: existing complete artifact.
    if artifact_path.exists() and _is_artifact_complete(artifact_path):
        return source_id

    # Stale artifact — log the rejection BEFORE acquiring the lock so it is
    # visible even if another worker wins the race and regenerates first.
    if artifact_path.exists():
        logger.warning(
            "Existing curated artifact rejected: charge mismatch or incomplete"
            " LJ/bonded terms — regenerating: %s",
            source_id,
        )

    # v00.99.42: shared source_generation_lock helper so admin/public/batch
    # and runtime auto-generation use the same fcntl scope keyed on
    # source_id. Sidecar writes (when the worker triggers them) live in the
    # same critical section.
    from features.molecules.admin_status import AdminStatusStore
    from features.molecules.artifact_service import (
        ARTIFACT_DIR as _ARTIFACT_DIR,
    )
    from features.molecules.artifact_service import (
        source_generation_lock,
    )
    from features.molecules.exceptions import (
        ArtifactGenerationError as _ArtifactGenerationError,
    )

    store = AdminStatusStore(_ARTIFACT_DIR)
    with source_generation_lock(source_id, artifact_dir=artifact_path.parent):
        # Double-check after acquiring the lock; another worker may have
        # already regenerated.
        if artifact_path.exists() and _is_artifact_complete(artifact_path):
            return source_id

        if not mol_path.exists():
            raise ArtifactMissingError(
                f"Curated artifact auto-generation failed for '{source_id}':"
                f" MOL file not found at {mol_path}. Expected artifact"
                f" path: {artifact_path}"
            )

        # Route straight to fragment_fallback (skipping baseline+sqm_robust) when
        # either efficiency-layer condition holds:
        #   ② Failure-history skip — this exact molecule previously needed
        #      fragment_fallback or exhausted AM1 SCF at sqm_robust. SCF
        #      (non-)convergence is deterministic for a fixed structure, so the
        #      doomed baseline+sqm_robust attempts are wasted (zero false positive).
        #   ③ Size pre-screen — the molecule is larger than the policy threshold,
        #      where AM1-BCC is impractical (size-only; see _should_prescreen_to_fragment).
        # Either way the outcome (fragment FF) is unchanged; falls through to the
        # normal chain if the fast attempt fails (stale verdict / mis-screen).
        from contracts.policies.ff_generation import DEFAULT_FF_GENERATION_POLICY

        _route_fragment_first = (
            DEFAULT_FF_GENERATION_POLICY.skip_to_fragment_on_prior_scf_failure
            and _should_skip_to_fragment(store, source_id)
        ) or _should_prescreen_to_fragment(mol_path)
        if _route_fragment_first:
            try:
                generate_gaff2_artifact(
                    mol_path=mol_path,
                    mol_id=source_id,
                    smiles=(ff_assignment.get("canonical_smiles") or ""),
                    formal_charge=int(ff_assignment.get("formal_charge") or 0),
                    progress_callback=progress_callback,
                    generation_profile="fragment_fallback",
                )
                if artifact_path.exists() and _is_artifact_complete(artifact_path):
                    try:
                        store.record_success(
                            source_id,
                            consumer_ids=[source_id],
                            generation_profile="fragment_fallback",
                            generator="fragment_fallback_gaff2",
                        )
                    except Exception:
                        logger.exception("admin sidecar record_success failed for %s", source_id)
                    clear_artifact_cache()
                    logger.warning(
                        "Skipped baseline/sqm_robust for %s (prior SCF non-convergence) "
                        "→ fragment_fallback",
                        source_id,
                    )
                    return source_id
            except Exception as _skip_exc:
                logger.warning(
                    "skip-to-fragment failed for %s (%s); running full "
                    "baseline→sqm_robust→fragment chain",
                    source_id,
                    _skip_exc,
                )

        logger.info("Auto-generating GAFF2 artifact for %s", source_id)
        _effective_profile = "baseline"  # Track which profile succeeded
        try:
            generate_gaff2_artifact(
                mol_path=mol_path,
                mol_id=source_id,
                smiles=(ff_assignment.get("canonical_smiles") or ""),
                formal_charge=int(ff_assignment.get("formal_charge") or 0),
                progress_callback=progress_callback,
            )
        except (ArtifactMissingError, ArtifactIncompleteError):
            raise
        except _ArtifactGenerationError as exc:
            try:
                store.record_failure(
                    source_id,
                    exc,
                    consumer_ids=[source_id],
                    generation_profile="baseline",
                )
            except Exception:
                logger.exception("admin sidecar record_failure failed for %s", source_id)

            # Auto-retry with sqm_robust if failure is retryable
            if exc.retryable:
                logger.warning(
                    "Baseline failed for %s [%s/%s], auto-retrying with sqm_robust",
                    source_id,
                    exc.stage,
                    exc.failure_code.value,
                )
                try:
                    generate_gaff2_artifact(
                        mol_path=mol_path,
                        mol_id=source_id,
                        smiles=(ff_assignment.get("canonical_smiles") or ""),
                        formal_charge=int(ff_assignment.get("formal_charge") or 0),
                        progress_callback=progress_callback,
                        generation_profile="sqm_robust",
                    )
                    _effective_profile = "sqm_robust"
                except _ArtifactGenerationError as retry_exc:
                    try:
                        store.record_failure(
                            source_id,
                            retry_exc,
                            consumer_ids=[source_id],
                            generation_profile="sqm_robust",
                        )
                    except Exception:
                        pass
                    # 3rd tier: fragment fallback (RDKit fragment typing, no
                    # SCF) for neutral CHONS molecules where AM1 won't converge.
                    # The generator gates applicability internally; the result
                    # is governed research_only (gaff2_fragment_fallback_v1).
                    logger.warning(
                        "sqm_robust failed for %s [%s]; attempting fragment_fallback",
                        source_id,
                        retry_exc.failure_code.value,
                    )
                    try:
                        generate_gaff2_artifact(
                            mol_path=mol_path,
                            mol_id=source_id,
                            smiles=(ff_assignment.get("canonical_smiles") or ""),
                            formal_charge=int(ff_assignment.get("formal_charge") or 0),
                            progress_callback=progress_callback,
                            generation_profile="fragment_fallback",
                        )
                        _effective_profile = "fragment_fallback"
                        logger.warning(
                            "Recovered '%s' via fragment_fallback (research_only governance)",
                            source_id,
                        )
                    except _ArtifactGenerationError as frag_exc:
                        try:
                            store.record_failure(
                                source_id,
                                frag_exc,
                                consumer_ids=[source_id],
                                generation_profile="fragment_fallback",
                            )
                        except Exception:
                            pass
                        raise ArtifactIncompleteError(
                            f"Auto-generation of '{source_id}' failed: "
                            f"baseline [{exc.failure_code.value}] → "
                            f"sqm_robust [{retry_exc.failure_code.value}] → "
                            f"fragment_fallback [{frag_exc.failure_code.value}]"
                        ) from frag_exc
                    except Exception as frag_exc:
                        raise ArtifactIncompleteError(
                            f"fragment_fallback for '{source_id}' failed: "
                            f"{type(frag_exc).__name__}: {frag_exc}"
                        ) from frag_exc
                except Exception as retry_exc:
                    raise ArtifactIncompleteError(
                        f"sqm_robust retry for '{source_id}' failed: "
                        f"{type(retry_exc).__name__}: {retry_exc}"
                    ) from retry_exc
            else:
                raise ArtifactIncompleteError(
                    f"Auto-generation of curated artifact for '{source_id}'"
                    f" failed [{exc.stage}/{exc.failure_code.value}]: {exc.message}"
                ) from exc
        except Exception as exc:
            raise ArtifactIncompleteError(
                f"Auto-generation of curated artifact for '{source_id}'"
                f" failed: {type(exc).__name__}: {exc}"
            ) from exc

        if not artifact_path.exists() or not _is_artifact_complete(artifact_path):
            # Record completeness failure in sidecar for diagnostics
            try:
                from features.molecules.exceptions import (
                    ArtifactFailureCode as _AFC,
                )

                store.record_failure(
                    source_id,
                    _ArtifactGenerationError(
                        stage="completeness_check",
                        failure_code=_AFC.PARMED_FAILED,
                        message="Artifact generated but incomplete (missing LJ/bonded)",
                    ),
                    consumer_ids=[source_id],
                    generation_profile=_effective_profile,
                )
            except Exception:
                pass
            raise ArtifactIncompleteError(
                f"Auto-generated curated artifact for '{source_id}' is"
                f" incomplete (missing LJ params or bonded terms)."
                f" Path: {artifact_path}"
            )

        try:
            # Record the generator that actually produced the artifact so the
            # failure-history skip (logic ②) and governance downgrade can read
            # it back: fragment_fallback profile → fragment_fallback_gaff2,
            # otherwise antechamber/AM1-BCC.
            _generator = (
                "fragment_fallback_gaff2"
                if _effective_profile == "fragment_fallback"
                else "antechamber_am1bcc"
            )
            store.record_success(
                source_id,
                consumer_ids=[source_id],
                generation_profile=_effective_profile,
                generator=_generator,
            )
        except Exception:
            logger.exception("admin sidecar record_success failed for %s", source_id)
        clear_artifact_cache()
        logger.info(
            "Auto-generated GAFF2 artifact: %s (profile=%s)",
            source_id,
            _effective_profile,
        )

    return source_id


def cleanup_stale_artifact_locks(
    artifact_dir: Path | str | None = None,
    threshold_hours: float = 6.0,
) -> int:
    """Manually clean up stale lock files from artifact directories.

    Convenience function for manual cleanup or scheduled maintenance tasks.

    Args:
        artifact_dir: Directory to clean. If None, uses the default organic_gaff2
            artifact directory.
        threshold_hours: Lock files older than this are considered stale.
            Default is 6 hours (matches _STALE_LOCK_THRESHOLD_SECONDS).

    Returns:
        Number of stale lock files removed.
    """
    # v00.99.42 reinforcement: delegate to the canonical helper in
    # artifact_service so the lock-cleanup policy stays in one place.
    # ``artifact_dir=None`` means "use the default organic_gaff2 dir"
    # (ARTIFACT_DIR in artifact_service).
    global _STALE_LOCK_THRESHOLD_SECONDS

    from features.molecules import artifact_service as _svc

    target_dir = Path(artifact_dir) if artifact_dir is not None else _svc.ARTIFACT_DIR

    # Temporarily adjust threshold for custom cleanup. Both this module's
    # threshold and the service-side threshold are bumped so the helper
    # observes the requested age window.
    original_local = _STALE_LOCK_THRESHOLD_SECONDS
    original_svc = _svc._STALE_LOCK_THRESHOLD_SECONDS
    try:
        _STALE_LOCK_THRESHOLD_SECONDS = int(threshold_hours * 3600)
        _svc._STALE_LOCK_THRESHOLD_SECONDS = int(threshold_hours * 3600)
        return _svc.cleanup_stale_generation_locks(target_dir)
    finally:
        _STALE_LOCK_THRESHOLD_SECONDS = original_local
        _svc._STALE_LOCK_THRESHOLD_SECONDS = original_svc
