"""Molecule catalog and composition operations."""

from api.schemas import AdditiveInfo, BinderCompositionDetailResponse
from common.molecule_id import AGING_CATEGORY_MAP, build_aging_mol_id, parse_molecule_id
from contracts.errors import ContractError, ErrorCode
from contracts.policies.binders import get_default_binder_config

# ─────────────────────────────────────────────────────────────────────────────
# Artifact readiness helpers (fail-closed policy v00.99.29)
# Uses shared helpers from artifact_service for path resolution consistency.
# ─────────────────────────────────────────────────────────────────────────────


def _get_organic_artifact_readiness(
    mol_id: str,
    ff_assignment: dict | None,
) -> dict:
    """Check artifact readiness for organic_curated_artifact route.

    Uses shared helpers from artifact_service for consistent path resolution.

    Returns:
        {
            "exists": bool,
            "complete": bool,
            "source_id": str,
            "blocked_reason": str | None,
        }
    """
    from features.molecules.artifact_service import (
        _is_artifact_complete,
        get_artifact_path,
        resolve_artifact_source_id,
    )

    source_id = resolve_artifact_source_id(mol_id, ff_assignment)
    art_path = get_artifact_path(mol_id, ff_assignment)

    if not art_path.exists():
        return {
            "exists": False,
            "complete": False,
            "source_id": source_id,
            "blocked_reason": f"Artifact not found for '{source_id}'.",
        }

    if not _is_artifact_complete(art_path):
        return {
            "exists": True,
            "complete": False,
            "source_id": source_id,
            "blocked_reason": f"Artifact incomplete for '{source_id}' (missing LJ params).",
        }

    return {
        "exists": True,
        "complete": True,
        "source_id": source_id,
        "blocked_reason": None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Aging artifact status helper (P1.5)
#
# SSOT functions used (Codex mandate — no lstrip/direct string manipulation):
# - common.molecule_id.build_aging_mol_id()
# - features.molecules.artifact_runtime.is_artifact_ready()
# - features.molecules.artifact_service.resolve_artifact_target()
# ─────────────────────────────────────────────────────────────────────────────


def _compute_aging_artifact_status(
    base_mol_id: str,
    available_aging: list[str] | None,
    temp_code: str = "0293",
) -> dict:
    """Compute artifact readiness for each aging variant.

    Uses SSOT functions only — no direct string manipulation (lstrip, f-string prefix).
    Codex mandate: variant-specific ff_assignment lookup, available_aging respect.

    Args:
        base_mol_id: Base molecule ID (e.g., "SA-Squalane"), NOT an aging variant.
        available_aging: List of supported aging states (e.g., ["non_aging"] for saturates,
            ["non_aging", "short_aging", "long_aging"] for asphaltenes). From YAML SSOT.
        temp_code: Temperature code (default: "0293").

    Returns:
        {
            "non_aging": {"ready": bool, "source_id": str, "consumer_ids": list, "status": str},
            "short_aging": {...},
            "long_aging": {...},
        }
    """
    from features.molecules.artifact_runtime import is_artifact_ready
    from features.molecules.artifact_service import resolve_artifact_target

    # SSOT: aging states from AGING_CATEGORY_MAP values (common.molecule_id)
    aging_states = list(AGING_CATEGORY_MAP.values())
    result = {}

    # Codex fix: Default to non_aging only if available_aging is None
    # Empty list means "no aging support" and should result in all not_applicable
    effective_available = ["non_aging"] if available_aging is None else available_aging

    for aging in aging_states:
        # Codex fix: Check available_aging SSOT first — unsupported states are not_applicable
        if aging not in effective_available:
            result[aging] = {
                "ready": None,
                "source_id": None,
                "consumer_ids": [],
                "status": "not_applicable",
            }
            continue

        try:
            # SSOT: build_aging_mol_id() — never use f"{prefix}{base_id}" or lstrip
            variant_id = build_aging_mol_id(base_mol_id, aging, temp_code)

            # Codex fix: resolve_artifact_target WITHOUT ff_assignment override
            # This forces YAML lookup for variant-specific ff_assignment
            target = resolve_artifact_target(variant_id)

            # Codex fix: Use target.ff_assignment (variant-specific, not base's)
            # This prevents U-AS-Thio's ff_assignment being used for S-AS-Thio
            ready, source_id = is_artifact_ready(variant_id, target.ff_assignment, "organic_gaff2")

            result[aging] = {
                "ready": ready,
                "source_id": source_id,
                "consumer_ids": target.consumer_ids,
                "status": "ready" if ready else "missing",
            }
        except ValueError:
            # base_mol_id is not a valid asphalt molecule (e.g., additive, inorganic)
            # or aging state not supported for this molecule type
            result[aging] = {
                "ready": None,
                "source_id": None,
                "consumer_ids": [],
                "status": "not_applicable",
            }

    return result


def resolve_ff_hint(mol_id: str) -> dict:
    """Resolve force-field hint for a molecule from MoleculeDB SSOT.

    Delegates the routing decision to ``forcefield.typing_router`` so the
    UI label, the precompute endpoint, and the structure builder all
    derive their FF strategy from the same SSOT and never drift apart.

    Preview/list fail-open policy (post v00.99.30): for the
    ``organic_curated_artifact`` route, a missing or incomplete artifact
    is reported as an ``artifact_warning`` (string) while ``is_submittable``
    stays ``True``. Build-time fail-closed is preserved by
    ``ensure_organic_artifact`` which regenerates the artifact and raises
    on failure.

    Authoring / runtime contract violations (missing ``source_id``,
    misconfigured route, router or DB exception) still result in
    ``is_submittable=False`` with a diagnostic ``blocked_reason``.

    Return-shape invariant: every return path yields a dict with the same
    keys — ``ff_hint, ff_display_label, parameterization_mode,
    submit_ff_type, is_submittable, blocked_reason, route, status,
    artifact_warning`` — so callers can rely on key presence.
    """
    from api.deps import get_molecule_db
    from forcefield.typing_router import TypingStrategy, resolve_typing_strategy

    result = {
        "ff_hint": "gaff2",
        "ff_display_label": "GAFF2",
        "parameterization_mode": None,
        "submit_ff_type": "bulk_ff_gaff2",
        "is_submittable": True,
        "blocked_reason": None,
        # Wave 0: surface the route/status SSOT fields so the frontend can
        # render richer badges without re-deriving them from ff_hint strings.
        "route": None,
        "status": None,
        # v00.99.30: runtime readiness signal for the organic curated
        # artifact. None when not applicable or artifact is complete;
        # string message when artifact is missing/incomplete (submit is
        # still allowed — build pipeline will regenerate).
        "artifact_warning": None,
    }

    try:
        db = get_molecule_db()

        additive_def = db.get_additive_definition(mol_id)
        ff_assignment = db.get_ff_assignment(mol_id)

        # Fail-closed: YAML load error blocks additives (router has no IO)
        if additive_def is not None:
            yaml_err = db.get_additives_load_error()
            if yaml_err:
                result["is_submittable"] = False
                result["blocked_reason"] = "Additives YAML failed to load"
                return result

        # Fail-closed: ff_assignment SSOT load error blocks every molecule
        ff_err = db.get_ff_assignment_load_error()
        if ff_err is not None:
            result["is_submittable"] = False
            result["blocked_reason"] = f"ff_assignment SSOT failed to load: {ff_err}"
            return result

        # Capture the raw mode for display before delegating to the router
        param = (additive_def or {}).get("parameterization") or {}
        result["parameterization_mode"] = param.get("mode")

        if ff_assignment is not None:
            result["route"] = ff_assignment.get("route")
            result["status"] = ff_assignment.get("status")

        decision = resolve_typing_strategy(mol_id, additive_def, ff_assignment)

        # ─── Fail-open: organic_curated_artifact route at preview/list ───
        # (v00.99.30) Artifact completeness is a runtime readiness signal,
        # not a submit gate. Build pipeline regenerates and fails closed
        # there if parameterization is impossible.
        route = ff_assignment.get("route") if ff_assignment else None

        if route == "organic_curated_artifact":
            # Phase 2 (v00.99.41): the typing router is the SSOT for routing
            # decisions, including passthrough fail-closed. Honour BLOCKED
            # before applying the fail-open auto-generate readiness so
            # passthrough entries (CNT/Graphene) cannot slip through as
            # warning-only submittable.
            if decision.strategy == TypingStrategy.BLOCKED:
                result["is_submittable"] = False
                result["blocked_reason"] = decision.blocked_reason
                if param.get("mode") == "organic_gaff2_passthrough":
                    result["ff_hint"] = "gaff2_passthrough"
                    result["ff_display_label"] = "GAFF2 (passthrough — admin only)"
                if result["status"] is None and decision.status:
                    result["status"] = decision.status
                return result

            _apply_organic_curated_readiness(result, mol_id, ff_assignment, route)
            _inject_preflight_gate(result, mol_id, ff_assignment)
            # Backfill status from the router decision when the ff_assignment
            # did not carry one explicitly. Keeps the explicit-route branch
            # return shape aligned with the strategy-fallback branch.
            if result["status"] is None and decision.status:
                result["status"] = decision.status
            return result

        if decision.strategy == TypingStrategy.BLOCKED:
            result["is_submittable"] = False
            result["blocked_reason"] = decision.blocked_reason
            # If the blocked entry was meant to be an inorganic profile,
            # preserve the INTERFACE label so the UI can warn accordingly.
            if param.get("mode") == "inorganic_profile" or result["route"] == "inorganic_profile":
                result["ff_hint"] = "interface_profile"
                result["ff_display_label"] = "INTERFACE (blocked)"
            elif result["route"] == "ionic_profile":
                result["ff_hint"] = "ionic_profile"
                result["ff_display_label"] = "Ionic (curating)"
            return result

        if decision.strategy == TypingStrategy.INORGANIC_PROFILE:
            result["ff_hint"] = "interface_profile"
            result["ff_display_label"] = "INTERFACE-derived inorganic"
        elif decision.strategy == TypingStrategy.WATER_MODEL:
            result["ff_hint"] = "water_model"
            result["ff_display_label"] = "Water (TIP3P)"
        elif decision.strategy == TypingStrategy.ORGANIC_CURATED_ARTIFACT:
            # Fallback for molecules without explicit route (legacy path).
            # Same fail-open policy as the explicit branch above.
            _apply_organic_curated_readiness(result, mol_id, ff_assignment, result["route"])
            _inject_preflight_gate(result, mol_id, ff_assignment)

        # Reflect the router decision's status if the ff_assignment did not
        # supply one (e.g., legacy additive_def path).
        if result["status"] is None and decision.status:
            result["status"] = decision.status

    except Exception as exc:
        # Fail-closed: never silently fall through to submittable=True. The
        # whole point of Wave 0 is to make routing failures visible. We log
        # via the standard logger so operators can debug, but the UI/CLI
        # caller must see a blocked result.
        from common.logging import get_logger

        logger = get_logger("features.molecules.catalog")
        logger.exception("resolve_ff_hint failed for mol_id=%s", mol_id)
        return {
            "ff_hint": "gaff2",
            "ff_display_label": "Unknown",
            "parameterization_mode": None,
            "submit_ff_type": "bulk_ff_gaff2",
            "is_submittable": False,
            "blocked_reason": (
                f"Force-field resolution failed for '{mol_id}': {type(exc).__name__}: {exc}"
            ),
            "route": None,
            "status": None,
            "artifact_warning": None,
        }

    return result


def _inject_preflight_gate(
    result: dict,
    mol_id: str,
    ff_assignment: dict | None,
) -> None:
    """Block submit if admin sidecar preflight verdict is ``manual_review``.

    Phase 5: wires the preflight verdict from the admin sidecar into the
    eligibility gate without touching typing_router.

    Only applies to ``organic_curated_artifact`` route and only when the
    molecule is still submittable after the artifact readiness check.
    Wrapped in try/except so failures never break hint resolution.
    """
    try:
        # Use result["route"] (already resolved by resolve_ff_hint) so both
        # explicit-route and fallback paths are covered.
        if result.get("route") != "organic_curated_artifact":
            return
        if not result.get("is_submittable"):
            return

        from features.molecules.admin_status import AdminStatusStore
        from features.molecules.artifact_service import (
            ARTIFACT_DIR,
            resolve_artifact_source_id,
        )

        source_id = resolve_artifact_source_id(mol_id, ff_assignment)
        store = AdminStatusStore(ARTIFACT_DIR)
        sidecar = store.get(source_id)
        if sidecar is None:
            return

        preflight = sidecar.preflight
        if not isinstance(preflight, dict):
            return
        if preflight.get("verdict") != "manual_review":
            return

        # Block submission with a summary of findings
        findings = preflight.get("findings") or preflight.get("reason") or "manual review required"
        result["is_submittable"] = False
        result["blocked_reason"] = f"Preflight verdict: manual_review — {findings}"
    except Exception:
        # Never let sidecar read failures break hint resolution
        pass


def _apply_organic_curated_readiness(
    result: dict,
    mol_id: str,
    ff_assignment: dict | None,
    route: str | None,
) -> None:
    """Apply strict organic curated artifact readiness to ``result`` in-place.

    Shared between the explicit-route branch and the strategy-fallback
    branch so both paths produce identical hint shapes.

    v00.99.96 policy shift — FAIL-CLOSED at preview/validate:
        The old "warning if build will regenerate" semantic (v00.99.30)
        coupled FF generation to the build path via
        ``ensure_organic_artifact``. Under v00.99.96 the build path is
        strict observe-only — it does NOT regenerate — so a missing /
        incomplete artifact must already surface as blocked at
        preview/validate time. Callers (frontend submit gate, batch
        validate) rely on ``is_submittable`` and ``ff_blocked_items``
        to route the operator to the canonical Molecules catalog for
        explicit generation.

        ``artifact_warning`` is still populated for display parity —
        older UI callers that only read this field get the same text,
        but the new contract is that ``is_submittable=False`` is the
        single source of truth for gating.
    """
    readiness = _get_organic_artifact_readiness(mol_id, ff_assignment)
    result["ff_hint"] = "gaff2"
    if route is not None:
        result["route"] = route
    if ff_assignment is not None and result["status"] is None:
        result["status"] = ff_assignment.get("status")
    if readiness["complete"]:
        result["is_submittable"] = True
        result["blocked_reason"] = None
        result["ff_display_label"] = "GAFF2"
        result["artifact_warning"] = None
    else:
        # v00.99.96: strict gate — artifact must be generated in the
        # canonical Molecules catalog before submit.
        result["is_submittable"] = False
        result["blocked_reason"] = (
            f"{readiness['blocked_reason']} Generate via Molecules catalog before submit."
        )
        result["ff_display_label"] = "GAFF2 (not generated)"
        result["artifact_warning"] = readiness["blocked_reason"]


def _safe_parse_molecule_id_rest(mol_id: str) -> tuple[str, str | None, str]:
    """Parse molecule ID safely, returning (aging_state, temp_code, base_id)."""
    try:
        parsed = parse_molecule_id(mol_id)
        aging = parsed.aging_category or "non_aging"
        return aging, parsed.temp_code, parsed.base_id
    except ValueError:
        return "non_aging", None, mol_id


async def list_molecules(
    sara_type: str | None = None,
    aging_state: str | None = None,
    temperature_code: str | None = None,
    limit: int = 100,
    offset: int = 0,
    e_intra_method: str | None = None,
) -> dict:
    from api.deps import get_molecule_db

    def _infer_source(structure_file: str | None, mol_id: str) -> str:
        raw = str(structure_file or "").strip()
        if raw:
            return raw.split("/")[0]
        if mol_id.startswith(("U-", "S-", "L-")):
            return "asphalt_binder"
        return "single_moles"

    db = get_molecule_db()
    all_mol_ids = db.list_all()

    # Build additive metadata lookup from DB for consistent display names
    additive_meta: dict[str, dict] = {}
    try:
        from database.repositories.additive_repo import AdditiveRepository
        from features.common import run_in_session_async

        def _load_additive_meta(session):
            repo = AdditiveRepository(session)
            rows = repo.list_active()
            return {
                r.mol_id: {
                    "short_name": getattr(r, "short_name", None),
                    "name": getattr(r, "name", None),
                }
                for r in rows
            }

        additive_meta = await run_in_session_async(_load_additive_meta)
    except Exception:
        pass

    # Build single_moles + additives category lookup from YAML
    _yaml_category_map: dict[str, str] = {}
    try:
        from pathlib import Path

        import yaml

        for yaml_name in ("single_moles.yaml", "additives.yaml"):
            yaml_path = Path("data/molecules") / yaml_name
            if yaml_path.exists():
                raw = yaml.safe_load(yaml_path.read_text())
                if yaml_name == "additives.yaml":
                    for add_id, add_def in (raw.get("additives") or {}).items():
                        if isinstance(add_def, dict) and add_def.get("category"):
                            _yaml_category_map[add_id] = str(add_def["category"])
                else:
                    for mol_def in raw.get("molecules") or []:
                        if mol_def.get("category"):
                            _yaml_category_map[mol_def["base_id"]] = str(mol_def["category"])
    except Exception:
        pass

    result = []
    for mol_id in all_mol_ids:
        spec = db.get(mol_id)
        if spec is None:
            continue

        if sara_type and spec.category.value != sara_type:
            continue

        if aging_state:
            mol_aging, _, _ = _safe_parse_molecule_id_rest(mol_id)
            if mol_aging != aging_state:
                continue

        if temperature_code:
            _, mol_temp, _ = _safe_parse_molecule_id_rest(mol_id)
            if mol_temp != temperature_code:
                continue

        parsed_aging, parsed_temp, parsed_base = _safe_parse_molecule_id_rest(mol_id)
        source = _infer_source(spec.structure_file, mol_id)
        is_asphalt = source == "asphalt_binder"
        # Resolve display_category from all sources
        _display_cat: str | None = None
        if is_asphalt:
            _display_cat = spec.category.value if spec.category else None
        elif mol_id in _yaml_category_map:
            _display_cat = _yaml_category_map[mol_id]
        elif parsed_base in _yaml_category_map:
            _display_cat = _yaml_category_map[parsed_base]

        entry = {
            "mol_id": mol_id,
            # Keep SARA tag only for asphalt binder molecules.
            "category": spec.category.value if is_asphalt else None,
            "display_category": _display_cat,
            "molecular_weight": spec.molecular_weight,
            "atom_count": spec.atom_count,
            "smiles": spec.smiles,
            "structure_file": spec.structure_file,
            "aging_state": parsed_aging if is_asphalt else None,
            "temperature_code": parsed_temp if is_asphalt else None,
            "base_id": parsed_base,
            "source": source,
        }
        if source == "additives" and mol_id in additive_meta:
            meta = additive_meta[mol_id]
            entry["short_name"] = meta.get("short_name")
            entry["name"] = meta.get("name") or mol_id
        result.append(entry)

    total = len(result)
    page = result[offset : offset + limit]

    # Enrich with FF hints (lightweight — no DB call, only MoleculeDB YAML lookup).
    # Wave 0: surface route/status from the ff_assignment SSOT so the frontend
    # can render badges directly from the list endpoint without round-tripping
    # to resolve_ff_hint per molecule.
    for entry in page:
        ff = resolve_ff_hint(entry["mol_id"])
        entry["ff_hint"] = ff["ff_hint"]
        entry["ff_display_label"] = ff["ff_display_label"]
        entry["parameterization_mode"] = ff["parameterization_mode"]
        entry["is_submittable"] = ff["is_submittable"]
        entry["blocked_reason"] = ff["blocked_reason"]
        entry["route"] = ff.get("route")
        entry["status"] = ff.get("status")
        entry["artifact_warning"] = ff.get("artifact_warning")

    # P1.5: Enrich with aging artifact status (observe-only, SSOT functions only)
    # Only compute for organic_curated_artifact molecules (asphalt binders).
    # Non-asphalt molecules get not_applicable status.
    for entry in page:
        route = entry.get("route")
        base_id = entry.get("base_id")
        temp_code = entry.get("temperature_code", "0293")

        if route == "organic_curated_artifact" and base_id:
            try:
                # Codex fix: Get available_aging from YAML SSOT (not ff_assignment)
                from features.molecules.artifact_service import get_available_aging

                available_aging = get_available_aging(base_id)
                entry["aging_artifact_status"] = _compute_aging_artifact_status(
                    base_id, available_aging, temp_code or "0293"
                )
            except Exception as e:
                # Fallback: mark as not_applicable if computation fails
                from common.logging import get_logger

                logger = get_logger("features.molecules.catalog")
                logger.warning(
                    "Failed to compute aging_artifact_status for %s: %s", entry["mol_id"], e
                )
                entry["aging_artifact_status"] = {
                    aging: {
                        "ready": None,
                        "source_id": None,
                        "consumer_ids": [],
                        "status": "not_applicable",
                    }
                    for aging in list(AGING_CATEGORY_MAP.values())
                }
        else:
            # additive / inorganic / water / ionic / unknown route
            entry["aging_artifact_status"] = {
                aging: {
                    "ready": None,
                    "source_id": None,
                    "consumer_ids": [],
                    "status": "not_applicable",
                }
                for aging in list(AGING_CATEGORY_MAP.values())
            }

    # Enrich only the current page with E_intra coverage (avoids N+1 on full list).
    # PR 3 (v01.04.18): use resolve_submission_e_intra_method() for SSOT consistency.
    # When e_intra_method is None, the resolver falls back to Settings default,
    # then env flags, then Method 1 baseline — matching the submission path.
    try:
        from config.dashboard_settings import resolve_submission_e_intra_method
        from contracts.policies.temperature import DEFAULT_BINDER_CELL_BATCH_TEMPERATURES_K
        from contracts.schema_enums import coerce_e_intra_method
        from database.repositories.e_intra_repo import EIntraRepository
        from features.common import run_in_session_async

        page_mol_ids = [r["mol_id"] for r in page]
        required_count = len(DEFAULT_BINDER_CELL_BATCH_TEMPERATURES_K)

        active_method = (
            coerce_e_intra_method(e_intra_method)
            if e_intra_method
            else resolve_submission_e_intra_method(None)
        )

        def _load_coverage(session):
            repo = EIntraRepository(session)
            return repo.get_coverage_bulk(page_mol_ids, method=active_method)

        coverage = await run_in_session_async(_load_coverage)
        # PR 2 (Codex Round 6): no-row fallback also carries the method tag
        # so the UI can render "no coverage for <method>" instead of looking
        # like "no coverage at all".
        method_tag = active_method.value
        for entry in page:
            cov = coverage.get(entry["mol_id"])
            if cov:
                entry["e_intra_coverage"] = cov
            else:
                entry["e_intra_coverage"] = {
                    "computed_count": 0,
                    "required_count": required_count,
                    "needs_calc": True,
                    "method": method_tag,
                }
    except Exception as e:
        # v01.02.17: Log exception for debugging, maintain UI contract shape
        from common.logging import get_logger

        logger = get_logger("features.molecules.catalog")
        logger.exception("Failed to load E_intra coverage: %s", e)

        # Provide fallback shape so UI doesn't break, with coverage_error flag
        try:
            from contracts.policies.temperature import DEFAULT_BINDER_CELL_BATCH_TEMPERATURES_K

            required_count = len(DEFAULT_BINDER_CELL_BATCH_TEMPERATURES_K)
        except Exception:
            required_count = 12  # Fallback to typical count

        # PR 3 (v01.04.18): use resolve_submission_e_intra_method() for error fallback.
        try:
            from config.dashboard_settings import (
                resolve_submission_e_intra_method as _resolve,
            )
            from contracts.schema_enums import coerce_e_intra_method as _coerce

            err_method = _coerce(e_intra_method).value if e_intra_method else _resolve(None).value
        except Exception:
            err_method = "single_molecule_vacuum"

        for entry in page:
            entry["e_intra_coverage"] = {
                "computed_count": 0,
                "required_count": required_count,
                "needs_calc": True,
                "coverage_error": True,  # Signal to UI that load failed
                "method": err_method,
            }

    # Enrich with artifact completeness (lightweight file-existence check)
    # Uses shared helpers to respect source_id / _variant_ resolution rules.
    try:
        from features.molecules.artifact_service import (
            _is_artifact_complete,
            get_artifact_path,
        )

        for entry in page:
            mol_id = entry["mol_id"]
            route = entry.get("route")
            if route == "water_model":
                # Water model uses hand-curated artifact — always complete
                entry["is_artifact_complete"] = True
            elif route in ("organic_curated_artifact", None):
                # Get ff_assignment for proper source_id resolution
                ff_assignment = db.get_ff_assignment(mol_id)
                art_path = get_artifact_path(mol_id, ff_assignment)
                entry["is_artifact_complete"] = (
                    _is_artifact_complete(art_path) if art_path.exists() else False
                )
            else:
                entry["is_artifact_complete"] = None
    except Exception:
        for entry in page:
            entry.setdefault("is_artifact_complete", None)

    return {
        "molecules": page,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


async def list_binder_types() -> dict:
    from api.deps import get_aging_config

    config = get_aging_config()
    if config is None or "binder_types" not in config:
        return {
            "binder_types": [
                {
                    "name": "AAA1",
                    "description": "AAA-1 asphalt binder (default)",
                    "sara_fractions": {},
                },
                {"name": "AAK1", "description": "AAK-1 asphalt binder", "sara_fractions": {}},
                {"name": "AAM1", "description": "AAM-1 asphalt binder", "sara_fractions": {}},
            ]
        }

    binder_types = []
    for name, data in config["binder_types"].items():
        binder_types.append(
            {
                "name": name,
                "description": data.get("description", ""),
                "sara_fractions": data.get("sara_fractions", {}),
            }
        )

    return {"binder_types": binder_types}


async def get_binder_composition(
    binder_type: str,
    size: str = "X1",
    aging: str = "non_aging",
    temp_code: str = "0293",
) -> BinderCompositionDetailResponse:
    from api.deps import get_aging_config

    _ = temp_code  # kept for API compatibility

    config = get_aging_config()
    if config is None or "binder_types" not in config:
        config = get_default_binder_config()

    if binder_type not in config["binder_types"]:
        raise ContractError(
            ErrorCode.RECORD_NOT_FOUND,
            f"Binder type '{binder_type}' not found. Available: {list(config['binder_types'].keys())}",
            {"binder_type": binder_type},
        )

    binder_data = config["binder_types"][binder_type]
    valid_sizes = list(binder_data.get("totals", {}).keys())
    if size not in valid_sizes:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            f"Invalid size. Must be one of: {valid_sizes}",
            {"size": size},
        )
    size_index = {s: i for i, s in enumerate(valid_sizes)}
    composition = binder_data.get("composition", {})

    sara_mapping = config.get(
        "sara_mapping",
        {
            "AR": "aromatic",
            "AS": "asphaltene",
            "RE": "resin",
            "SA": "saturate",
        },
    )

    mol_defs = {m["base_id"]: m for m in config.get("molecules", [])}

    molecules = []
    total_molecules = 0
    estimated_atoms = 0
    sara_counts = {"saturate": 0, "aromatic": 0, "resin": 0, "asphaltene": 0}

    for mol_id, counts in composition.items():
        count = counts[size_index[size]]
        total_molecules += count

        prefix = mol_id.split("-")[0] if "-" in mol_id else "SA"
        sara_type = sara_mapping.get(prefix, "unknown")

        mol_def = mol_defs.get(mol_id, {})
        atom_count = mol_def.get("atom_count", 50)

        molecules.append(
            {
                "mol_id": mol_id,
                "count": count,
                "sara_type": sara_type,
                "atom_count": atom_count,
            }
        )

        if sara_type in sara_counts:
            sara_counts[sara_type] += count

        estimated_atoms += count * atom_count

    return BinderCompositionDetailResponse(
        binder_type=binder_type,
        description=binder_data.get("description", ""),
        structure_size=size,
        aging_state=aging,
        molecules=molecules,
        total_molecules=total_molecules,
        sara_fractions=binder_data.get("sara_fractions", {}),
        sara_counts=sara_counts,
        estimated_atoms=estimated_atoms,
    )


async def list_additives() -> dict:
    """List active additives from database (synchronized projection).

    YAML is the authoring SSOT; DB is a synchronized projection for queries.
    sync_from_yaml() at startup keeps DB in sync. If YAML parse fails,
    DB retains previous state for API stability, but builds will fail-closed
    via MoleculeDB.get_additives_load_error() check in StructureBuilder.

    Wave 0: each additive is enriched with the ff_assignment SSOT
    route/status/is_submittable/blocked_reason so the frontend can render
    badges and disable blocked entries without per-row resolve_ff_hint
    round-trips.
    """
    from database.repositories.additive_repo import AdditiveRepository
    from features.common import run_in_session

    def _list(session):
        repo = AdditiveRepository(session)
        rows = repo.list_active()
        # Convert ORM objects to dicts INSIDE session to avoid DetachedInstanceError
        return [
            {
                "mol_id": row.mol_id,
                "name": row.name,
                "short_name": getattr(row, "short_name", None),
                "atom_count": row.atom_count,
                "molecular_weight": row.molecular_weight,
                "category": row.category,
                "default_counts": row.default_counts or {"X1": 2, "X2": 4, "X3": 6},
                "structure_file": row.structure_file,
            }
            for row in rows
        ]

    rows_as_dicts = run_in_session(_list)

    # Wave 0: enrich each row with ff_assignment SSOT fields via resolve_ff_hint.
    for row in rows_as_dicts:
        ff = resolve_ff_hint(row["mol_id"])
        row["route"] = ff.get("route")
        row["status"] = ff.get("status")
        row["is_submittable"] = bool(ff.get("is_submittable", True))
        row["blocked_reason"] = ff.get("blocked_reason")
        row["artifact_warning"] = ff.get("artifact_warning")

    additives = [AdditiveInfo(**d) for d in rows_as_dicts]

    # YAML fallback removed - DB is SSOT (sync_from_yaml guarantees consistency)
    return {"additives": additives}
