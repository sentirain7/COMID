"""Experiment submission operations."""

import hashlib

from api.schemas import (
    DependentMoleculeExperimentRequest,
    DependentMoleculeExperimentResponse,
    ExperimentRequest,
    ExperimentResponse,
    MoleculeCompositionPreviewRequest,
    MoleculeCompositionPreviewResponse,
    MoleculeExperimentRequest,
    MoleculeExperimentResponse,
    TypingChargePrecomputeItem,
    TypingChargePrecomputeRequest,
    TypingChargePrecomputeResponse,
)
from common.logging import get_logger
from common.pathing import get_project_root
from common.seed import generate_seed
from contracts.errors import ContractError, ErrorCode, OrchestrationError
from contracts.policies.forcefield import get_ff_display_label, get_ff_version
from contracts.schemas import FFType, SubmissionSource
from features.common import run_in_session, run_in_session_commit

from .composition_builder import build_molecule_composition
from .validation import (
    parse_tier_and_ff,
    resolve_stage_requests,
    validate_composition_sum,
    validate_molecule_request_config,
)

logger = get_logger("features.experiments.submission")


def _experiment_exists(exp_id: str) -> bool:
    """Check whether exp_id already exists in DB."""

    def _op(session) -> bool:
        from database.repositories.experiment_repo import ExperimentRepository

        return ExperimentRepository(session).get_by_id(exp_id) is not None

    return bool(run_in_session(_op))


def _resolve_unique_exp_id(
    *,
    base_seed: int,
    exp_id_builder,
    max_attempts: int = 128,
) -> tuple[str, int]:
    """
    Resolve a collision-free exp_id by shifting seed when needed.

    The ID format remains unchanged; only seed is incremented on collision.
    """
    for offset in range(max_attempts):
        candidate_seed = int(base_seed) + offset
        candidate_exp_id = str(exp_id_builder(candidate_seed))
        if not _experiment_exists(candidate_exp_id):
            return candidate_exp_id, candidate_seed
    raise ContractError(
        ErrorCode.DUPLICATE_RECORD,
        "Failed to allocate unique experiment id",
        {"base_seed": int(base_seed), "max_attempts": int(max_attempts)},
    )


def _compute_additive_metadata(request: MoleculeExperimentRequest, config, db):
    """Compute additive metadata (type, wt%, mol_id) for ML/analytics."""
    if not request.additives:
        return None, 0.0, None

    binder_weight = 0.0
    for mc in request.molecule_counts:
        mw = db.get_molecule_molecular_weight(config, mc.mol_id, default=400.0)
        binder_weight += mc.count * mw

    from database.repositories.additive_repo import AdditiveRepository
    from features.common import run_in_session

    requested_ids = [add.mol_id for add in request.additives if getattr(add, "mol_id", None)]

    def _load_additives(session):
        repo = AdditiveRepository(session)
        return {row.mol_id: row for row in repo.list_active() if row.mol_id in requested_ids}

    additive_catalog = run_in_session(_load_additives)
    rows: list[tuple[str, float]] = []
    total_additive_weight = 0.0

    for add in request.additives:
        add_id = add.mol_id
        mw = 0.0
        if add_id in additive_catalog:
            mw = float(additive_catalog[add_id].molecular_weight or 0.0)
        elif config and add_id in config.get("additives", {}):
            mw = float(config["additives"][add_id].get("molecular_weight", 0.0) or 0.0)
        if mw <= 0.0:
            mw = db.get_molecule_molecular_weight(config, add_id, default=0.0)
        weight = add.count * mw
        total_additive_weight += weight
        rows.append((add_id, weight))

    total_weight = binder_weight + total_additive_weight
    additive_wt = (total_additive_weight / total_weight * 100.0) if total_weight > 0 else 0.0

    if not rows:
        return None, additive_wt, None

    primary_additive = max(rows, key=lambda item: item[1])
    additive_type = primary_additive[0] if primary_additive[1] > 0 else rows[0][0]
    additive_mol_id = additive_type
    return additive_type, additive_wt, additive_mol_id


def _iter_unique_molecule_ids(
    molecule_counts: list,
    additives: list | None = None,
) -> list[str]:
    """Return unique mol_ids from molecule/additive counts while preserving order.

    Handles both Pydantic models (with attributes) and dicts (from model_dump()).
    """
    ordered: list[str] = []
    seen: set[str] = set()
    for item in [*(molecule_counts or []), *(additives or [])]:
        # Handle both dict and Pydantic model
        if isinstance(item, dict):
            mol_id = str(item.get("mol_id", "")).strip()
            count = int(item.get("count", 0) or 0)
        else:
            mol_id = str(getattr(item, "mol_id", "")).strip()
            count = int(getattr(item, "count", 0) or 0)
        if not mol_id or count <= 0 or mol_id in seen:
            continue
        seen.add(mol_id)
        ordered.append(mol_id)
    return ordered


def _get_mol_file_prefix(db, config: dict, base_id: str, aging: str) -> str:
    """Get aging prefix for a molecule following SSOT from composition_builder.

    This mirrors the logic in _get_full_mol_id but returns only the prefix
    for MOL file lookup (files are named without temp_code).

    Args:
        db: MoleculeDB instance
        config: Aging library config dict
        base_id: Base molecule ID (e.g., "SA-Squalane")
        aging: Aging state (e.g., "non_aging", "short_aging")

    Returns:
        Prefix string (e.g., "U", "S", "L")
    """
    aging_categories = config.get("aging_categories", {})
    aging_info = aging_categories.get(aging, {})
    prefix = aging_info.get("prefix", "U")
    fallback_to = aging_info.get("fallback_to")

    mol_def = db._find_molecule_def(config, base_id)
    if mol_def:
        available = mol_def.get("available_aging", ["non_aging"])
        if aging in available:
            return prefix
        if fallback_to and fallback_to in available:
            return config["aging_categories"][fallback_to]["prefix"]

    return "U"  # Default to non_aging prefix


def _resolve_mol_file_for_precompute(
    db, mol_id: str, *, config: dict | None = None, aging_state: str = "non_aging"
):
    """Resolve source MOL file used by typing/charge assignment.

    Args:
        db: MoleculeDB instance
        mol_id: Base molecule ID (e.g., "SA-Squalane") or additive mol_id
        config: Aging library config dict (for binder molecules)
        aging_state: Aging state for binder molecules (default: "non_aging")

    Returns:
        Path to MOL file or None if not found
    """
    # 1. Try exact mol_id match (works for additives and full mol_ids)
    mol_file = db.get_structure_file(mol_id, "mol")
    if mol_file and mol_file.exists():
        return mol_file

    # 2. Try aging library lookup with proper prefix (SSOT from composition_builder)
    config_path = getattr(db, "_aging_config_path", None)
    if config_path and config:
        prefix = _get_mol_file_prefix(db, config, mol_id, aging_state)
        prefixed_mol_id = f"{prefix}-{mol_id}"

        aging_file = db.get_structure_file_aging(prefixed_mol_id, config_path)
        if aging_file and aging_file.exists():
            if aging_file.suffix.lower() == ".mol":
                return aging_file
            sibling_mol = aging_file.with_suffix(".mol")
            if sibling_mol.exists():
                return sibling_mol

    # 3. Fallback: glob search
    molecules_root = get_project_root() / "data" / "molecules"

    # Try exact match first
    direct_matches = list(molecules_root.glob(f"**/{mol_id}.mol"))
    if direct_matches:
        return direct_matches[0]

    # Try with aging prefixes (U-, S-, L-) as last resort
    for prefix in ("U", "S", "L"):
        prefixed_matches = list(molecules_root.glob(f"**/{prefix}-{mol_id}.mol"))
        if prefixed_matches:
            return prefixed_matches[0]

    return None


async def submit_experiment(request: ExperimentRequest) -> ExperimentResponse:
    """Submit a new simulation experiment."""
    from api.deps import get_job_manager
    from common.pathing import generate_exp_id
    from config.dashboard_settings import load_dashboard_settings
    from orchestrator.request_factory import create_build_request, create_protocol_request
    from orchestrator.submission_facade import SubmissionFacade
    from protocols.e_intra_method_resolver import resolve_submission_e_intra_method
    from protocols.stage_plan_compiler import build_stage_plan_metadata

    validate_composition_sum(request)
    run_tier, ff_type = parse_tier_and_ff(request.run_tier, request.ff_type)

    composition = {
        "asphaltene": request.composition.asphaltene_wt,
        "resin": request.composition.resin_wt,
        "aromatic": request.composition.aromatic_wt,
        "saturate": request.composition.saturate_wt,
    }
    seed = generate_seed(request.seed)
    resolved_e_intra_method = resolve_submission_e_intra_method(
        getattr(request, "e_intra_method", None)
    ).value
    build_request = create_build_request(
        composition=composition,
        target_atoms=request.target_atoms,
        seed=seed,
        tier=run_tier,
    )
    protocol_request = create_protocol_request(
        tier=run_tier,
        ff_type=ff_type,
        temperature_K=request.temperature_K,
        pressure_atm=request.pressure_atm,
        e_intra_method=resolved_e_intra_method,
    )
    metadata = build_stage_plan_metadata(
        protocol_request=protocol_request,
        canonical_stage_requests=[],
        base_metadata={
            "source": SubmissionSource.EXPERIMENT_SUBMIT.value,
            "e_intra_method": resolved_e_intra_method,
            "e_intra_method_source": (
                "request" if getattr(request, "e_intra_method", None) else "settings_default"
            ),
        },
    )

    job_manager = get_job_manager()
    dashboard_settings = load_dashboard_settings()
    selected_gpus = dashboard_settings.get("selected_gpus", []) or None
    exp_id, seed = _resolve_unique_exp_id(
        base_seed=seed,
        exp_id_builder=lambda candidate_seed: generate_exp_id(
            binder_type="user",
            structure_size="custom",
            temperature_k=request.temperature_K,
            ff_type=ff_type.value,
            aging_state="non_aging",
            atom_count=request.target_atoms,
            seed=candidate_seed,
        ),
    )

    try:
        job_id, _ = SubmissionFacade.submit_experiment(
            job_manager=job_manager,
            exp_id=exp_id,
            run_tier=run_tier.value,
            ff_type=ff_type.value,
            target_atoms=request.target_atoms,
            temperature_k=request.temperature_K,
            pressure_atm=request.pressure_atm,
            seed=seed,
            comp_asphaltene_wt=request.composition.asphaltene_wt,
            comp_resin_wt=request.composition.resin_wt,
            comp_aromatic_wt=request.composition.aromatic_wt,
            comp_saturate_wt=request.composition.saturate_wt,
            build_request=build_request,
            protocol_request=protocol_request,
            material_id="user_experiment",
            selected_gpus=selected_gpus,
            metadata_json=metadata,
        )
    except Exception as exc:
        raise OrchestrationError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "Experiment submission failed",
            {"reason": str(exc), "exp_id": exp_id},
        ) from exc

    logger.info(f"Experiment submitted: {exp_id}, job_id: {job_id}")
    return ExperimentResponse(exp_id=exp_id, job_id=job_id, status="queued")


async def submit_molecule_experiment(
    request: MoleculeExperimentRequest,
    *,
    exp_id_override: str | None = None,
) -> MoleculeExperimentResponse:
    """Submit a molecule-based experiment.

    Args:
        request: Molecule experiment request
        exp_id_override: Pre-generated exp_id (e.g., amorphous cell format).
            When provided, skips default binder-style exp_id generation.
    """
    from api.deps import get_aging_config, get_job_manager, get_molecule_db
    from config.dashboard_settings import load_dashboard_settings
    from orchestrator.exp_id_helper import generate_exp_id_from_material
    from orchestrator.request_factory import create_build_request, create_protocol_request
    from orchestrator.submission_facade import SubmissionFacade
    from protocols.e_intra_method_resolver import resolve_submission_e_intra_method
    from protocols.stage_plan_compiler import build_stage_plan_metadata

    run_tier, ff_type = parse_tier_and_ff(request.run_tier, request.ff_type)
    stage_config = resolve_stage_requests(
        stage_requests=request.stage_requests,
        stage_durations=request.stage_durations,
        equilibration_settings=request.equilibration_settings,
        run_tier=run_tier,
    )

    db = get_molecule_db()
    config = get_aging_config()
    validate_molecule_request_config(request, config, db)

    # FF eligibility gate — blocked molecules/additives prevent submission
    from forcefield.eligibility import collect_binder_ff_issues

    _mol_ids = [mc.mol_id for mc in (request.molecule_counts or [])]
    _add_ids = [a.mol_id for a in (request.additives or [])] if request.additives else []
    _ff_issues = collect_binder_ff_issues(_mol_ids, _add_ids)
    if _ff_issues["has_blocked"]:
        blocked_ids = [i["item_id"] for i in _ff_issues["blocked_items"]]
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            f"FF-blocked species in composition: {blocked_ids}. "
            "Remove blocked molecules/additives before submitting.",
            {"ff_blocked_items": _ff_issues["blocked_items"]},
        )

    # Stack governance gate — check validation_level for the target stack.
    # Uses build_ff_provenance to resolve stack_id, then checks policy.
    try:
        from contracts.policies.forcefield import build_ff_provenance
        from contracts.policies.stack_governance import assert_submit_allowed
        from forcefield.eligibility import collect_organic_source_provenance

        # Normalize StudyType enum to string for _stack_map lookup
        _st = request.study_type
        _st_str = _st.value if hasattr(_st, "value") else str(_st or "bulk")
        _org_sources = collect_organic_source_provenance(_mol_ids, _add_ids)
        _prov = build_ff_provenance(
            study_type=_st_str,
            ff_type=request.ff_type,
            organic_sources=_org_sources or None,
        )
        _stack_id = _prov["metadata"].get("stack_id", "")
        assert_submit_allowed(_stack_id)
    except ContractError:
        raise
    except Exception as _gov_err:
        logger.warning(
            "Stack governance gate degraded (non-ContractError): %s — "
            "submit proceeds in degraded mode. Fix governance import/config.",
            _gov_err,
        )

    temp_code = db.get_temperature_code(config, request.temperature_K)
    aging_state = request.aging_state or "non_aging"

    build_result = build_molecule_composition(request, config, db, temp_code, aging_state)
    seed = generate_seed(request.seed)
    additive_type, additive_wt, additive_mol_id = _compute_additive_metadata(request, config, db)
    resolved_e_intra_method = resolve_submission_e_intra_method(
        getattr(request, "e_intra_method", None)
    ).value

    build_request = create_build_request(
        composition=build_result.mol_composition,
        composition_mode="mol_count",
        target_atoms=build_result.estimated_atoms,
        seed=seed,
        tier=run_tier,
        box_dimensions=request.box_dimensions,
    )
    protocol_request = create_protocol_request(
        tier=run_tier,
        ff_type=ff_type,
        study_type=request.study_type or "bulk",
        temperature_K=request.temperature_K,
        e_intra_method=resolved_e_intra_method,
        equilibration_settings=stage_config.equilibration_settings.model_dump()
        if stage_config.equilibration_settings
        else None,
    )
    metadata = build_stage_plan_metadata(
        protocol_request=protocol_request,
        overrides=stage_config.stage_duration_overrides,
        canonical_stage_requests=stage_config.canonical_stage_requests,
        base_metadata={
            "source": SubmissionSource.MOLECULE_SUBMIT.value,
            "e_intra_method": resolved_e_intra_method,
            "e_intra_method_source": (
                "request" if getattr(request, "e_intra_method", None) else "settings_default"
            ),
        },
    )

    job_manager = get_job_manager()
    material_id = f"{request.binder_type}_{request.structure_size}_{aging_state}"

    dashboard_settings = load_dashboard_settings()
    selected_gpus = dashboard_settings.get("selected_gpus", []) or None

    if exp_id_override:
        # Use pre-generated exp_id (e.g., amorphous cell format)
        exp_id = exp_id_override
        if _experiment_exists(exp_id):
            # Collision: regenerate hash suffix with shifted seed
            _hash_len = 6
            _prefix = (
                exp_id_override[:-_hash_len]
                if len(exp_id_override) > _hash_len
                else exp_id_override + "_"
            )
            exp_id, seed = _resolve_unique_exp_id(
                base_seed=seed,
                exp_id_builder=lambda s: (
                    f"{_prefix}{hashlib.md5(f'{exp_id_override}_{s}'.encode()).hexdigest()[:_hash_len]}"
                ),
            )
    else:
        exp_id, seed = _resolve_unique_exp_id(
            base_seed=seed,
            exp_id_builder=lambda candidate_seed: generate_exp_id_from_material(
                material_id=material_id,
                temperature_k=request.temperature_K,
                ff_type=ff_type.value,
                atom_count=build_result.estimated_atoms,
                seed=candidate_seed,
            ),
        )

    try:
        job_id, _ = SubmissionFacade.submit_experiment(
            job_manager=job_manager,
            exp_id=exp_id,
            run_tier=run_tier.value,
            ff_type=ff_type.value,
            target_atoms=build_result.estimated_atoms,
            temperature_k=request.temperature_K,
            pressure_atm=1.0,
            seed=seed,
            comp_asphaltene_wt=build_result.sara_composition.get("asphaltene", 0.0),
            comp_resin_wt=build_result.sara_composition.get("resin", 0.0),
            comp_aromatic_wt=build_result.sara_composition.get("aromatic", 0.0),
            comp_saturate_wt=build_result.sara_composition.get("saturate", 0.0),
            build_request=build_request,
            protocol_request=protocol_request,
            material_id=material_id,
            selected_gpus=selected_gpus,
            stage_duration_overrides=stage_config.stage_duration_overrides,
            property_calculations=request.property_calculations.model_dump()
            if request.property_calculations
            else None,
            additive_type=additive_type,
            additive_wt=additive_wt,
            additive_mol_id=additive_mol_id,
            metadata_json=metadata,
        )
    except Exception as exc:
        raise OrchestrationError(
            ErrorCode.ORCHESTRATION_ERROR,
            "Failed to submit job",
            {"reason": str(exc)},
        ) from exc

    logger.info(
        f"Molecule-based experiment submitted: {exp_id}, job_id: {job_id}, "
        f"binder={request.binder_type}, size={request.structure_size}, "
        f"molecules={build_result.total_molecules}, atoms~{build_result.estimated_atoms}"
    )

    return MoleculeExperimentResponse(
        exp_id=exp_id,
        job_id=job_id,
        status="queued",
        binder_type=request.binder_type,
        structure_size=request.structure_size,
        total_molecules=build_result.total_molecules,
        estimated_atoms=build_result.estimated_atoms,
    )


async def submit_dependent_molecule_experiment(
    request: DependentMoleculeExperimentRequest,
) -> DependentMoleculeExperimentResponse:
    """Create a deferred child experiment and dependency edge without immediate submit."""
    from api.deps import get_aging_config, get_molecule_db
    from config.dashboard_settings import load_dashboard_settings
    from orchestrator.exp_id_helper import generate_exp_id_from_material
    from orchestrator.request_factory import create_build_request, create_protocol_request
    from protocols.e_intra_method_resolver import resolve_submission_e_intra_method
    from protocols.stage_plan_compiler import build_stage_plan_metadata

    run_tier, ff_type = parse_tier_and_ff(request.run_tier, request.ff_type)
    stage_config = resolve_stage_requests(
        stage_requests=request.stage_requests,
        stage_durations=request.stage_durations,
        equilibration_settings=request.equilibration_settings,
        run_tier=run_tier,
    )

    db = get_molecule_db()
    config = get_aging_config()
    validate_molecule_request_config(request, config, db)

    # FF eligibility gate — same as submit_molecule_experiment()
    from forcefield.eligibility import collect_binder_ff_issues as _collect_dep

    _mol_ids_dep = [mc.mol_id for mc in (request.molecule_counts or [])]
    _add_ids_dep = [a.mol_id for a in (request.additives or [])] if request.additives else []
    _ff_issues_dep = _collect_dep(_mol_ids_dep, _add_ids_dep)
    if _ff_issues_dep["has_blocked"]:
        blocked_ids = [i["item_id"] for i in _ff_issues_dep["blocked_items"]]
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            f"FF-blocked species in deferred composition: {blocked_ids}. "
            "Remove blocked molecules/additives before creating dependent experiment.",
            {"ff_blocked_items": _ff_issues_dep["blocked_items"]},
        )

    # Stack governance gate — consistent with submit_molecule_experiment()
    try:
        from contracts.policies.forcefield import build_ff_provenance
        from contracts.policies.stack_governance import assert_submit_allowed
        from forcefield.eligibility import collect_organic_source_provenance

        _st = request.study_type
        _st_str = _st.value if hasattr(_st, "value") else str(_st or "bulk")
        _org_sources_dep = collect_organic_source_provenance(_mol_ids_dep, _add_ids_dep)
        _prov = build_ff_provenance(
            study_type=_st_str,
            ff_type=request.ff_type,
            organic_sources=_org_sources_dep or None,
        )
        assert_submit_allowed(_prov["metadata"].get("stack_id", ""))
    except ContractError:
        raise
    except Exception as _gov_err:
        logger.warning(
            "Stack governance gate degraded (dependent submit): %s",
            _gov_err,
        )

    temp_code = db.get_temperature_code(config, request.temperature_K)
    aging_state = request.aging_state or "non_aging"
    build_result = build_molecule_composition(request, config, db, temp_code, aging_state)
    seed = generate_seed(request.seed)
    additive_type, additive_wt, additive_mol_id = _compute_additive_metadata(request, config, db)
    resolved_e_intra_method = resolve_submission_e_intra_method(
        getattr(request, "e_intra_method", None)
    ).value

    build_request = create_build_request(
        composition=build_result.mol_composition,
        composition_mode="mol_count",
        target_atoms=build_result.estimated_atoms,
        seed=seed,
        tier=run_tier,
        box_dimensions=request.box_dimensions,
    )
    protocol_request = create_protocol_request(
        tier=run_tier,
        ff_type=ff_type,
        study_type=request.study_type or "bulk",
        temperature_K=request.temperature_K,
        e_intra_method=resolved_e_intra_method,
        equilibration_settings=stage_config.equilibration_settings.model_dump()
        if stage_config.equilibration_settings
        else None,
    )
    metadata = build_stage_plan_metadata(
        protocol_request=protocol_request,
        overrides=stage_config.stage_duration_overrides,
        canonical_stage_requests=stage_config.canonical_stage_requests,
        base_metadata={
            "source": SubmissionSource.DEPENDENT_MOLECULE_SUBMIT.value,
            "parent_exp_id": request.parent_exp_id,
            "e_intra_method": resolved_e_intra_method,
            "e_intra_method_source": (
                "request" if getattr(request, "e_intra_method", None) else "settings_default"
            ),
        },
    )

    material_id = f"{request.binder_type}_{request.structure_size}_{aging_state}"
    dashboard_settings = load_dashboard_settings()
    selected_gpus = dashboard_settings.get("selected_gpus", []) or None
    exp_id, seed = _resolve_unique_exp_id(
        base_seed=seed,
        exp_id_builder=lambda candidate_seed: generate_exp_id_from_material(
            material_id=material_id,
            temperature_k=request.temperature_K,
            ff_type=ff_type.value,
            atom_count=build_result.estimated_atoms,
            seed=candidate_seed,
        ),
    )

    def _create_deferred(session) -> None:
        from contracts.errors import ContractError, ErrorCode
        from database.repositories.experiment_repo import ExperimentRepository
        from database.repositories.job_dependency_repo import JobDependencyRepository

        exp_repo = ExperimentRepository(session)
        dep_repo = JobDependencyRepository(session)
        parent = exp_repo.get_by_id(request.parent_exp_id)
        if parent is None:
            raise ContractError(
                ErrorCode.RECORD_NOT_FOUND,
                f"Parent experiment not found: {request.parent_exp_id}",
                {"parent_exp_id": request.parent_exp_id},
            )
        if exp_repo.get_by_id(exp_id) is not None:
            raise ContractError(
                ErrorCode.DUPLICATE_RECORD,
                f"Experiment already exists: {exp_id}",
                {"exp_id": exp_id},
            )

        # Build FF provenance
        from contracts.policies.forcefield import build_ff_provenance

        _deferred_meta = {
            **metadata,
            "deferred_submission": {
                "build_request": build_request.model_dump(),
                "protocol_request": protocol_request.model_dump(),
                "material_id": material_id,
                "selected_gpus": selected_gpus,
                "stage_duration_overrides": [
                    o.model_dump() for o in stage_config.stage_duration_overrides
                ]
                if stage_config.stage_duration_overrides
                else None,
                "property_calculations": request.property_calculations.model_dump()
                if request.property_calculations
                else None,
                "additive_type": additive_type,
                "additive_wt": additive_wt,
                "additive_mol_id": additive_mol_id,
            },
        }
        _study = (
            protocol_request.study_type.value
            if hasattr(protocol_request.study_type, "value")
            else str(protocol_request.study_type)
        )
        prov = build_ff_provenance(
            study_type=_study,
            ff_type=ff_type.value,
            source_tag="deferred_molecule_submit",
            metadata_json=_deferred_meta,
            build_request=build_request,
            organic_sources=_org_sources_dep or None,
        )
        _deferred_meta["ff_provenance"] = prov["metadata"]

        exp_repo.create(
            exp_id=exp_id,
            run_tier=run_tier.value,
            ff_type=ff_type.value,
            material_id=material_id,
            binder_type=request.binder_type,
            structure_size=request.structure_size,
            aging_state=aging_state,
            force_field_name=get_ff_display_label(ff_type.value),
            force_field_version=get_ff_version(ff_type.value),
            comp_asphaltene_wt=build_result.sara_composition.get("asphaltene", 0.0),
            comp_resin_wt=build_result.sara_composition.get("resin", 0.0),
            comp_aromatic_wt=build_result.sara_composition.get("aromatic", 0.0),
            comp_saturate_wt=build_result.sara_composition.get("saturate", 0.0),
            target_atoms=build_result.estimated_atoms,
            temperature_K=request.temperature_K,
            pressure_atm=1.0,
            seed=seed,
            status="pending",
            additive_type=additive_type,
            additive_wt=additive_wt,
            additive_mol_id=additive_mol_id,
            stage_duration_overrides=[o.model_dump() for o in stage_config.stage_duration_overrides]
            if stage_config.stage_duration_overrides
            else None,
            metadata_json=_deferred_meta,
            conditions=prov["conditions"],
        )
        exp_repo.upsert_experiment_molecules(exp_id, build_result.mol_composition)
        dep_repo.create_dependency(request.parent_exp_id, exp_id)

    run_in_session_commit(_create_deferred)

    return DependentMoleculeExperimentResponse(
        exp_id=exp_id,
        job_id="deferred",
        status="pending",
        parent_exp_id=request.parent_exp_id,
        dependency_status="blocked",
        binder_type=request.binder_type,
        structure_size=request.structure_size,
        total_molecules=build_result.total_molecules,
        estimated_atoms=build_result.estimated_atoms,
    )


async def preview_molecule_composition(
    request: MoleculeCompositionPreviewRequest,
) -> MoleculeCompositionPreviewResponse:
    """Preview molecule-based composition results (SARA, atoms, totals)."""
    from api.deps import get_aging_config, get_molecule_db

    db = get_molecule_db()
    config = get_aging_config()
    validate_molecule_request_config(request, config, db)

    temp_code = db.get_temperature_code(config, request.temperature_K)
    aging_state = request.aging_state or "non_aging"

    build_result = build_molecule_composition(request, config, db, temp_code, aging_state)

    # FF eligibility check for preview
    from api.schemas.experiments import FFEligibilityItem
    from forcefield.eligibility import collect_binder_ff_issues

    mol_ids = [mc.mol_id for mc in (request.molecule_counts or [])]
    additive_ids = [a.mol_id for a in (request.additives or [])] if request.additives else []
    ff_issues = collect_binder_ff_issues(mol_ids, additive_ids)

    return MoleculeCompositionPreviewResponse(
        sara_fractions=build_result.sara_composition,
        estimated_atoms=build_result.estimated_atoms,
        total_molecules=build_result.total_molecules,
        ff_blocked_items=[FFEligibilityItem(**i) for i in ff_issues["blocked_items"]],
        ff_warning_items=[FFEligibilityItem(**i) for i in ff_issues["warning_items"]],
    )


async def check_typing_charge_readiness(
    request: TypingChargePrecomputeRequest,
) -> TypingChargePrecomputeResponse:
    """Check typing/charge artifact readiness without generating or executing.

    **OBSERVE-ONLY**: This function does NOT call any executor functions
    (assign_inorganic_with_cache, assign_ionic, assign_water, assign_organic).
    It only checks metadata and artifact existence.

    Routes each molecule through the typing router and checks:
    - ORGANIC_CURATED_ARTIFACT: ``is_artifact_ready()`` (file existence)
    - INORGANIC_PROFILE: profile_id presence in decision
    - IONIC_PROFILE: profile activation status via metadata
    - WATER_MODEL: source_id presence in decision
    - BLOCKED: blocked_reason from router

    Use this in submit/validate paths where blocking is unacceptable.
    For molecules needing artifact generation, direct users to Molecules catalog.
    """
    from api.deps import get_aging_config, get_molecule_db
    from config.settings import get_settings
    from forcefield.typing_router import TypingStrategy, resolve_typing_strategy

    try:
        ff_type = FFType(request.ff_type)
    except ValueError as exc:
        raise ContractError(
            ErrorCode.INVALID_FF_TYPE,
            f"Invalid ff_type '{request.ff_type}'. Must be one of: {[f.value for f in FFType]}",
        ) from exc

    db = get_molecule_db()
    config = get_aging_config()
    validate_molecule_request_config(request, config, db)

    unique_mol_ids = _iter_unique_molecule_ids(request.molecule_counts, request.additives)
    aging_state = getattr(request, "aging_state", "non_aging") or "non_aging"

    typing_settings = get_settings().typing_charge
    if not typing_settings.enabled:
        raise ContractError(
            ErrorCode.VALIDATION_ERROR,
            "Typing/charge assignment is disabled by server settings",
        )

    details: list[TypingChargePrecomputeItem] = []
    cached = 0
    computed = 0  # Always 0 in observe-only mode
    failed = 0

    for mol_id in unique_mol_ids:
        additive_def = db.get_additive_definition(mol_id)
        has_additive_def = additive_def is not None
        mol_file = _resolve_mol_file_for_precompute(
            db,
            mol_id,
            config=None if has_additive_def else config,
            aging_state="non_aging" if has_additive_def else aging_state,
        )
        if mol_file is None:
            failed += 1
            details.append(
                TypingChargePrecomputeItem(
                    mol_id=mol_id,
                    status="failed",
                    message="MOL topology file not found",
                )
            )
            continue

        topology = db.parse_mol_topology(mol_file, mol_id)
        if topology is None or not topology.atoms:
            failed += 1
            details.append(
                TypingChargePrecomputeItem(
                    mol_id=mol_id,
                    status="failed",
                    message=f"Failed to parse MOL topology: {mol_file}",
                )
            )
            continue

        ff_assignment = db.get_ff_assignment(mol_id)
        decision = resolve_typing_strategy(mol_id, additive_def, ff_assignment)

        # BLOCKED
        if decision.strategy == TypingStrategy.BLOCKED:
            failed += 1
            details.append(
                TypingChargePrecomputeItem(
                    mol_id=mol_id,
                    status="failed",
                    atom_count=len(topology.atoms),
                    message=decision.blocked_reason or "Molecule is blocked by typing router",
                )
            )
            continue

        # INORGANIC_PROFILE — observe-only: check profile active via SSOT
        if decision.strategy == TypingStrategy.INORGANIC_PROFILE:
            from forcefield.inorganic_parameter_service import InorganicParameterService

            profile_id = decision.profile_id or decision.source_id
            # Use SSOT: InorganicParameterService.is_profile_active()
            inorg_service = InorganicParameterService()
            is_active = profile_id and inorg_service.is_profile_active(profile_id)

            if is_active:
                cached += 1
                details.append(
                    TypingChargePrecomputeItem(
                        mol_id=mol_id,
                        status="cached",
                        atom_count=len(topology.atoms),
                        charge_model="clayff_interface",
                        message=f"Inorganic profile active: {profile_id}",
                    )
                )
            else:
                failed += 1
                reason = "No profile_id" if not profile_id else f"Profile '{profile_id}' not active"
                details.append(
                    TypingChargePrecomputeItem(
                        mol_id=mol_id,
                        status="failed",
                        atom_count=len(topology.atoms),
                        message=f"Inorganic blocked: {reason}",
                    )
                )
            continue

        # ORGANIC_CURATED_ARTIFACT — observe-only: is_artifact_ready()
        if decision.strategy == TypingStrategy.ORGANIC_CURATED_ARTIFACT:
            from features.molecules.artifact_runtime import is_artifact_ready

            _ff_fam = "organic_gaff2"
            ready, _source_id = is_artifact_ready(mol_id, ff_assignment or {}, _ff_fam)
            if not ready:
                failed += 1
                details.append(
                    TypingChargePrecomputeItem(
                        mol_id=mol_id,
                        status="failed",
                        atom_count=len(topology.atoms),
                        message=f"Artifact not found for {_source_id}. Generate via Molecules catalog.",
                    )
                )
                continue

            cached += 1
            details.append(
                TypingChargePrecomputeItem(
                    mol_id=mol_id,
                    status="cached",
                    atom_count=len(topology.atoms),
                    charge_model="am1bcc",
                )
            )
            continue

        # IONIC_PROFILE — observe-only: check activation via SSOT
        if decision.strategy == TypingStrategy.IONIC_PROFILE:
            from forcefield.ionic_executor import is_activated as ionic_is_activated

            profile_id = decision.profile_id or decision.source_id
            # Use SSOT: is_activated() checks env var + YAML + profile status + policy
            activated, blocking_reasons = ionic_is_activated(profile_id or "")

            if activated:
                cached += 1
                details.append(
                    TypingChargePrecomputeItem(
                        mol_id=mol_id,
                        status="cached",
                        atom_count=len(topology.atoms),
                        message=f"Ionic profile active: {profile_id}",
                    )
                )
            else:
                failed += 1
                reason = (
                    "; ".join(blocking_reasons) if blocking_reasons else "Ionic route not activated"
                )
                details.append(
                    TypingChargePrecomputeItem(
                        mol_id=mol_id,
                        status="failed",
                        atom_count=len(topology.atoms),
                        message=f"Ionic blocked: {reason}",
                    )
                )
            continue

        # WATER_MODEL — observe-only: check source_id presence
        if decision.strategy == TypingStrategy.WATER_MODEL:
            source_id = decision.source_id or mol_id
            if source_id:
                cached += 1
                details.append(
                    TypingChargePrecomputeItem(
                        mol_id=mol_id,
                        status="cached",
                        atom_count=len(topology.atoms),
                        message="Water model (TIP3P) ready",
                    )
                )
            else:
                failed += 1
                details.append(
                    TypingChargePrecomputeItem(
                        mol_id=mol_id,
                        status="failed",
                        atom_count=len(topology.atoms),
                        message="Water model source_id not found",
                    )
                )
            continue

        # Default/fallback organic path — check if route is valid
        # If we reach here with a valid strategy, assume ready (legacy path)
        if decision.strategy and decision.source_id:
            cached += 1
            details.append(
                TypingChargePrecomputeItem(
                    mol_id=mol_id,
                    status="cached",
                    atom_count=len(topology.atoms),
                    message=f"Route available: {decision.strategy.value}",
                )
            )
        else:
            failed += 1
            details.append(
                TypingChargePrecomputeItem(
                    mol_id=mol_id,
                    status="failed",
                    atom_count=len(topology.atoms),
                    message="No valid typing route found",
                )
            )

    return TypingChargePrecomputeResponse(
        ff_type=ff_type.value,
        total_molecules=sum(max(0, int(item.count)) for item in request.molecule_counts)
        + sum(max(0, int(item.count)) for item in (request.additives or [])),
        unique_molecules=len(unique_mol_ids),
        cached=cached,
        computed=computed,
        failed=failed,
        details=details,
    )


async def precompute_typing_charge(
    request: TypingChargePrecomputeRequest,
) -> TypingChargePrecomputeResponse:
    """Precompute and warm typing/charge cache for selected molecules.

    .. warning::
        This function may **generate** artifacts via ``ensure_organic_artifact()``,
        which can block uvicorn for 17+ minutes. For submit/validate paths that
        require observe-only behavior, use :func:`check_typing_charge_readiness`
        instead.

    Routes each molecule through the shared typing router so that organic
    additives use the curated GAFF2 artifact pipeline while active inorganic
    profile additives use ``InorganicParameterService`` with a persistent
    cache. Both routes share the same fail-closed semantics as the build
    path (see ``builder/structure_builder.py``).
    """
    from api.deps import get_aging_config, get_molecule_db
    from config.settings import get_settings
    from forcefield.inorganic_executor import (
        InorganicTypingCache,
        assign_inorganic_with_cache,
    )
    from forcefield.inorganic_parameter_service import (
        InorganicParameterizationError,
        InorganicParameterService,
    )
    from forcefield.organic_typing_executor import TypingChargeAssignmentError
    from forcefield.typing_router import TypingStrategy, resolve_typing_strategy

    try:
        ff_type = FFType(request.ff_type)
    except ValueError as exc:
        raise ContractError(
            ErrorCode.INVALID_FF_TYPE,
            f"Invalid ff_type '{request.ff_type}'. Must be one of: {[f.value for f in FFType]}",
        ) from exc

    db = get_molecule_db()
    config = get_aging_config()
    validate_molecule_request_config(request, config, db)

    unique_mol_ids = _iter_unique_molecule_ids(request.molecule_counts, request.additives)
    aging_state = getattr(request, "aging_state", "non_aging") or "non_aging"

    typing_settings = get_settings().typing_charge
    if not typing_settings.enabled:
        raise ContractError(
            ErrorCode.VALIDATION_ERROR,
            "Typing/charge assignment is disabled by server settings",
        )

    organic_assigner = None  # legacy assigner removed in Phase 6
    inorganic_service = InorganicParameterService()
    inorganic_cache = InorganicTypingCache()

    details: list[TypingChargePrecomputeItem] = []
    cached = 0
    computed = 0
    failed = 0

    for mol_id in unique_mol_ids:
        # Always look up additive_def from MoleculeDB regardless of
        # whether the mol_id was sent in request.additives or
        # request.molecule_counts. A molecule that IS an additive in
        # the SSOT (e.g., SiO2) must be treated as one even when the
        # user sends it via molecule_counts (single molecule screen).
        additive_def = db.get_additive_definition(mol_id)
        has_additive_def = additive_def is not None
        mol_file = _resolve_mol_file_for_precompute(
            db,
            mol_id,
            config=None if has_additive_def else config,
            aging_state="non_aging" if has_additive_def else aging_state,
        )
        if mol_file is None:
            failed += 1
            details.append(
                TypingChargePrecomputeItem(
                    mol_id=mol_id,
                    status="failed",
                    message="MOL topology file not found",
                )
            )
            continue

        topology = db.parse_mol_topology(mol_file, mol_id)
        if topology is None or not topology.atoms:
            failed += 1
            details.append(
                TypingChargePrecomputeItem(
                    mol_id=mol_id,
                    status="failed",
                    message=f"Failed to parse MOL topology: {mol_file}",
                )
            )
            continue

        # Route via shared SSOT.
        # Wave 0: ff_assignment is authoritative; additive_def (looked up
        # above from MoleculeDB, not from request context) is a legacy
        # fallback used by the router for profile_id resolution.
        ff_assignment = db.get_ff_assignment(mol_id)
        decision = resolve_typing_strategy(mol_id, additive_def, ff_assignment)

        if decision.strategy == TypingStrategy.BLOCKED:
            failed += 1
            details.append(
                TypingChargePrecomputeItem(
                    mol_id=mol_id,
                    status="failed",
                    atom_count=len(topology.atoms),
                    message=decision.blocked_reason or "Molecule is blocked by typing router",
                )
            )
            continue

        if decision.strategy == TypingStrategy.INORGANIC_PROFILE:
            try:
                bundle = assign_inorganic_with_cache(
                    topology=topology,
                    mol_file=mol_file,
                    additive_def=additive_def or {},
                    service=inorganic_service,
                    cache=inorganic_cache,
                )
            except InorganicParameterizationError as exc:
                failed += 1
                details.append(
                    TypingChargePrecomputeItem(
                        mol_id=mol_id,
                        status="failed",
                        atom_count=len(topology.atoms),
                        message=f"Inorganic parameterization failed: {exc}",
                    )
                )
                continue

            if bundle.cache_hit:
                cached += 1
                status = "cached"
            else:
                computed += 1
                status = "computed"
            details.append(
                TypingChargePrecomputeItem(
                    mol_id=mol_id,
                    status=status,
                    atom_count=len(topology.atoms),
                    charge_model="clayff_interface",
                )
            )
            continue

        # Curated artifact route — validate artifact completeness (fail-closed)
        if decision.strategy == TypingStrategy.ORGANIC_CURATED_ARTIFACT:
            from features.molecules.artifact_runtime import ensure_organic_artifact
            from forcefield.organic_curated_artifact import (
                ArtifactIncompleteError,
                ArtifactMissingError,
            )

            _ff_fam = "organic_gaff2"
            try:
                _source_id = ensure_organic_artifact(
                    mol_id=mol_id,
                    mol_path=mol_file,
                    ff_assignment=ff_assignment or {},
                    ff_family=_ff_fam,
                )
            except ArtifactMissingError as exc:
                failed += 1
                details.append(
                    TypingChargePrecomputeItem(
                        mol_id=mol_id,
                        status="failed",
                        atom_count=len(topology.atoms),
                        message=f"Artifact missing: {str(exc)[:200]}",
                    )
                )
                continue
            except ArtifactIncompleteError as exc:
                failed += 1
                details.append(
                    TypingChargePrecomputeItem(
                        mol_id=mol_id,
                        status="failed",
                        atom_count=len(topology.atoms),
                        message=f"Artifact incomplete: {str(exc)[:200]}",
                    )
                )
                continue

            if decision.source_id != _source_id:
                from forcefield.typing_router import TypingRouterDecision

                decision = TypingRouterDecision(
                    strategy=decision.strategy,
                    source_id=_source_id,
                    status=decision.status,
                )

        # Ionic profile — activation-ready dispatch (gate inside executor)
        if decision.strategy == TypingStrategy.IONIC_PROFILE:
            from forcefield.ionic_executor import IonicNotActivatedError, assign_ionic

            try:
                assign_ionic(
                    topology=topology,
                    profile_id=decision.profile_id or decision.source_id,
                    artifact_id=decision.source_id or mol_id,
                    usage_context="vacuum",
                )
            except IonicNotActivatedError as exc:
                failed += 1
                details.append(
                    TypingChargePrecomputeItem(
                        mol_id=mol_id,
                        status="failed",
                        message=f"Ionic blocked: {str(exc)[:200]}",
                    )
                )
                continue
            details.append(
                TypingChargePrecomputeItem(
                    mol_id=mol_id,
                    status="ok",
                    message="Ionic profile applied",
                )
            )
            continue

        # Water model — separate dispatch (no auto-gen, no organic executor)
        if decision.strategy == TypingStrategy.WATER_MODEL:
            from forcefield.water_executor import WaterAssignmentError, assign_water

            try:
                assign_water(
                    topology=topology,
                    source_id=decision.source_id or mol_id,
                )
            except WaterAssignmentError as exc:
                failed += 1
                details.append(
                    TypingChargePrecomputeItem(
                        mol_id=mol_id,
                        status="failed",
                        message=f"Water model failed: {exc.message[:200]}",
                    )
                )
                continue
            details.append(
                TypingChargePrecomputeItem(
                    mol_id=mol_id,
                    status="ok",
                    message="Water model (TIP3P) applied",
                )
            )
            continue

        # Default: organic typing path.
        from forcefield.organic_typing_executor import (
            OrganicAssignmentError,
            assign_organic,
        )

        try:
            result = assign_organic(
                topology=topology,
                mol_file=mol_file,
                strategy=decision.strategy,
                source_id=decision.source_id,
                ff_name=ff_type.value,
                charge_model_primary=typing_settings.charge_model_primary,
                charge_model_fallback=typing_settings.charge_model_fallback,
                total_charge_tolerance=typing_settings.total_charge_tolerance,
                legacy_assigner=organic_assigner,
            )
        except OrganicAssignmentError as exc:
            failed += 1
            details.append(
                TypingChargePrecomputeItem(
                    mol_id=mol_id,
                    status="failed",
                    atom_count=len(topology.atoms),
                    message=f"Organic typing/charge assignment failed: {exc.message}",
                )
            )
            continue
        except TypingChargeAssignmentError as exc:
            failed += 1
            details.append(
                TypingChargePrecomputeItem(
                    mol_id=mol_id,
                    status="failed",
                    atom_count=len(topology.atoms),
                    message=f"Typing/charge assignment failed: {exc.message}",
                )
            )
            continue

        if result.cache_hit:
            cached += 1
            status = "cached"
        else:
            computed += 1
            status = "computed"
        details.append(
            TypingChargePrecomputeItem(
                mol_id=mol_id,
                status=status,
                atom_count=len(topology.atoms),
                charge_model=result.charge_model,
            )
        )

    return TypingChargePrecomputeResponse(
        ff_type=ff_type.value,
        total_molecules=sum(max(0, int(item.count)) for item in request.molecule_counts)
        + sum(max(0, int(item.count)) for item in (request.additives or [])),
        unique_molecules=len(unique_mol_ids),
        cached=cached,
        computed=computed,
        failed=failed,
        details=details,
    )


def prepare_typing_charge_background(
    molecule_counts: list[dict],
    additives: list[dict] | None,
    ff_type: str,
    aging_state: str,
) -> None:
    """Background task: 선택된 분자의 누락 organic artifact 병렬 생성.

    ⚠️ 동기 함수 — ``BackgroundTasks.add_task()``에서 별도 스레드로 실행됨.
    ``async def``로 만들면 event loop를 블로킹할 수 있음.

    Args:
        molecule_counts: List of molecule count dicts with ``mol_id`` and ``count``.
        additives: Optional list of additive count dicts.
        ff_type: Force field type (e.g., "bulk_ff_gaff2").
        aging_state: Aging state (e.g., "non_aging", "short_aging", "long_aging").

    Note:
        Slot acquisition is done by the router BEFORE calling this function.
        This function MUST release the slot in ALL exit paths (including early
        returns and exceptions). release_batch_slot() is idempotent.
    """
    from features.molecules.artifact_service import (
        get_pending_molecules,
        release_batch_slot,
        run_parallel_batch,
    )

    try:
        # 1. Extract request mol_ids
        unique_mol_ids = _iter_unique_molecule_ids(molecule_counts, additives)
        request_set = set(unique_mol_ids)

        if not request_set:
            logger.info("prepare_typing_charge_background: no molecules requested")
            return  # finally will release slot

        # 2. Build aging-aware consumer ID set for matching
        # If request has base mol_id (e.g., "AS-Thio") with aging_state,
        # also match U-/S-/L- prefixed consumer_ids
        aging_prefix_map = {
            "non_aging": "U",
            "short_aging": "S",
            "long_aging": "L",
        }
        expanded_request_set = set(request_set)
        prefix = aging_prefix_map.get(aging_state, "U")
        for mol_id in request_set:
            # Add prefixed variants for base mol_ids (no existing prefix)
            if not any(mol_id.startswith(f"{p}-") for p in ("U", "S", "L")):
                expanded_request_set.add(f"{prefix}-{mol_id}")

        # 3. Get pending molecules and filter
        all_pending = get_pending_molecules()

        def _matches_request(item: dict) -> bool:
            """Check if pending item matches any requested mol_id."""
            # source_id or mol_id direct match
            if item.get("mol_id", "") in expanded_request_set:
                return True
            if item.get("source_id", "") in expanded_request_set:
                return True
            # consumer_ids match (U-/S-/L- variants)
            for cid in item.get("consumer_ids", []):
                if cid in expanded_request_set:
                    return True
            return False

        # Filter: match request, organic only, incomplete only
        filtered = [
            p
            for p in all_pending
            if _matches_request(p)
            and p.get("artifact_type") == "organic"
            and not p.get("is_complete", False)
        ]

        if not filtered:
            logger.info(
                "prepare_typing_charge_background: no incomplete organic artifacts "
                "for %d requested molecules (all ready or non-organic)",
                len(request_set),
            )
            return  # finally will release slot

        # 4. Pass filtered rows to run_parallel_batch (it handles dedupe internally)
        # Do NOT call dedupe_by_source_id here - run_parallel_batch does it and
        # records conflicts in sidecar.
        logger.info(
            "prepare_typing_charge_background: starting batch for %d rows "
            "(from %d requested molecules)",
            len(filtered),
            len(request_set),
        )
        run_parallel_batch(
            filtered,
            max_workers=None,  # CPU core-based auto
            batch_kind="typing_prepare",
            generation_profile="baseline",
            slot_already_acquired=True,
        )
        # run_parallel_batch releases slot in its finally block

    except Exception as exc:
        logger.exception("prepare_typing_charge_background failed: %s", exc)
        raise

    finally:
        # ALWAYS release slot in finally — idempotent call is safe.
        # Covers all paths: early return, exception before/during run_parallel_batch,
        # or run_parallel_batch's own finally already released it.
        try:
            release_batch_slot()
        except Exception:
            pass
