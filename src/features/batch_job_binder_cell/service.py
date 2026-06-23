"""Batch Job Binder Cell application service for API layer."""

from __future__ import annotations

from api.schemas import (
    BatchJobBinderCellJobResponse,
    BatchJobBinderCellRequest,
    BatchJobBinderCellResponse,
)
from contracts.errors import ContractError, ErrorCode
from features.common import run_in_session
from features.experiments.validation import (
    load_active_additive_catalog,
    parse_tier_and_ff,
    resolve_stage_requests,
)


def _resolve_batch_e_intra_method(
    request: BatchJobBinderCellRequest,
) -> tuple[str | None, str | None]:
    """Resolve the bulk CED E_intra method for new batch jobs.

    Priority:
    1. Explicit request override.
    2. Submission defaults from settings/env resolver.
    """
    from protocols.e_intra_method_resolver import resolve_submission_e_intra_method

    requested = str(request.e_intra_method or "").strip() or None
    resolved = resolve_submission_e_intra_method(requested).value
    return resolved, ("request" if requested else "settings_default")


def _enumerate_batch_binder_mol_ids(
    binder_types: list[str],
    structure_sizes: list[str],
    aging_states: list[str],
    temperatures_k: list[float],
) -> list[str]:
    """Enumerate unique binder molecule mol_ids across all batch combinations.

    v00.99.96: previously the batch validate/create FF gate only inspected
    additives, leaving binder molecules (SARA components) unchecked. An
    operator could submit a batch where asphaltenes/resins had no
    curated GAFF2 artifact, fail-closed at build time after tying up
    worker slots. This helper reproduces the frontend's Cartesian-product
    logic (`frontend/src/components/batch-binder-cell/payloadBuilder.js`
    buildPrecomputeCombinations + resolvePrecomputeMolecules) on the
    server so FF readiness is evaluated for the full binder mol set
    before the runner enqueues any jobs.

    Returns the **deduplicated** union of mol_ids across every enumerated
    (binder_type × structure_size × aging_state × temperature) tuple.
    Resolution uses the same ``get_binder_composition_with_aging`` path
    the runner (``orchestrator/batch_job_binder_cell.py:445``) invokes,
    so the FF gate is guaranteed to see the exact mol_ids the build
    will later consume.
    """
    from api.deps import get_aging_config, get_molecule_db

    db = get_molecule_db()
    config = get_aging_config()
    if config is None:
        return []

    seen: dict[str, None] = {}  # ordered deduplication

    # Fallback defaults mirror the runner's behaviour when a request axis
    # is empty. We avoid fabricating values here — if any axis is empty
    # the runner would already reject the spec, so we simply return an
    # empty list.
    if not (binder_types and structure_sizes and aging_states and temperatures_k):
        return []

    for binder_type in binder_types:
        for size in structure_sizes:
            for aging in aging_states:
                for temp in temperatures_k:
                    try:
                        temp_code = db.get_temperature_code(config, temp)
                        mol_counts = db.get_binder_composition_with_aging(
                            config,
                            binder_type=binder_type,
                            size=size,
                            aging=aging,
                            temp_code=temp_code,
                        )
                    except Exception:
                        # Composition resolution failure surfaces through
                        # the runner's own validation; we just skip for
                        # FF gating and let the runner report it.
                        continue
                    for mol_id in mol_counts.keys():
                        if mol_id and mol_id not in seen:
                            seen[mol_id] = None

    return list(seen.keys())


def _validate_additive_types(additive_types: list[str]) -> tuple[list[str], dict[str, dict]]:
    """Validate additive mol_ids against additive SSOT catalog.

    Note: 'none' is preserved in the returned list to signal control group generation.
    Only real additive mol_ids are validated against the catalog.
    """
    # Deduplicate while preserving order, keep 'none' for control group
    all_types = [a for a in dict.fromkeys(additive_types or []) if a]
    # Real additives for catalog validation (exclude 'none')
    real_types = [a for a in all_types if a != "none"]

    if not all_types:
        return [], {}

    # Only validate real additives against catalog
    if real_types:
        known_map = load_active_additive_catalog()
        invalid = [mol_id for mol_id in real_types if mol_id not in known_map]
        if invalid:
            available = ", ".join(sorted(known_map.keys())[:30])
            raise ContractError(
                ErrorCode.INVALID_REQUEST,
                f"Unknown additive mol_id(s): {invalid}. Available: [{available}]",
            )

        catalog_map = {
            mol_id: {
                "name": known_map[mol_id]["name"],
                "default_counts": known_map[mol_id]["default_counts"],
                "molecular_weight": known_map[mol_id]["molecular_weight"],
                "category": known_map[mol_id]["category"],
            }
            for mol_id in real_types
        }
    else:
        catalog_map = {}

    # Return all_types (including 'none') so runner can generate control group
    return all_types, catalog_map


def _map_job_to_response(j) -> BatchJobBinderCellJobResponse:
    """Map a BatchJobBinderCellJob to BatchJobBinderCellJobResponse."""
    return BatchJobBinderCellJobResponse(
        exp_id=j.exp_id,
        binder_type=j.binder_type,
        structure_size=j.structure_size,
        temperature_k=j.temperature_k,
        aging_state=j.aging_state,
        tier=j.tier,
        status=j.status,
        error=j.error,
        additive_type=getattr(j, "additive_type", None),
        additive_concentration=getattr(j, "additive_concentration", 0.0),
        # v00.95.02: priority and similarity tracking
        priority=getattr(j, "priority", "medium"),
        similar_existing=getattr(j, "similar_existing", False),
        similar_experiment_ids=getattr(j, "similar_experiment_ids", []),
    )


def validate_batch_job_binder_cell(
    request: BatchJobBinderCellRequest,
) -> BatchJobBinderCellResponse:
    """Dry-run: generate batch Binder Cell jobs and check for duplicates."""
    from database.repositories.experiment_repo import ExperimentRepository
    from orchestrator.batch_job_binder_cell import (
        BatchJobBinderCellSpec,
        select_batch_runner_cls,
    )

    try:
        run_tier, ff_type = parse_tier_and_ff(
            request.tier.value if hasattr(request.tier, "value") else request.tier,
            request.ff_type,
        )
        stage_config = resolve_stage_requests(
            stage_requests=request.stage_requests,
            stage_durations=request.stage_durations,
            equilibration_settings=request.equilibration_settings,
            run_tier=run_tier,
        )
        additive_types, additive_catalog_map = _validate_additive_types(request.additive_types)

        # Extract similar_existing_action
        similar_action = getattr(request, "similar_existing_action", None)
        similar_action_str = (
            similar_action.value
            if hasattr(similar_action, "value")
            else str(similar_action or "unspecified")
        )
        e_intra_method, e_intra_method_source = _resolve_batch_e_intra_method(request)

        spec = BatchJobBinderCellSpec(
            binder_types=request.binder_types,
            structure_sizes=request.structure_sizes,
            temperatures_k=request.temperatures_k,
            aging_states=request.aging_states,
            tier=run_tier.value,
            ff_type=ff_type.value,
            seed=request.seed,
            temperature_priority=request.temperature_priority,
            additive_types=additive_types,
            additive_concentrations=request.additive_concentrations,
            additive_catalog_map=additive_catalog_map,
            initial_density=request.initial_density,
            stage_duration_overrides=stage_config.stage_duration_overrides,
            property_calculations=request.property_calculations.model_dump()
            if request.property_calculations
            else None,
            equilibration_settings=stage_config.equilibration_settings.model_dump()
            if stage_config.equilibration_settings
            else None,
            similar_existing_action=similar_action_str,
            stage_requests=stage_config.canonical_stage_requests,
            excluded_exp_ids=getattr(request, "excluded_exp_ids", []),
            interaction_analysis=request.interaction_analysis.model_dump()
            if request.interaction_analysis
            else None,
            e_intra_method=e_intra_method,
            e_intra_method_source=e_intra_method_source,
        )

        def _validate(session):
            experiment_repo = ExperimentRepository(session)
            runner = select_batch_runner_cls(spec)(experiment_repo=experiment_repo)
            return runner.validate(spec)

        result = run_in_session(_validate)
    except ValueError as exc:
        raise ContractError(ErrorCode.INVALID_REQUEST, str(exc)) from exc

    # FF eligibility check for batch — v00.99.96 includes binder molecules
    # in addition to additives. Previously only `additive_ids` were gated,
    # leaving binder mols (SARA components) unchecked; they would
    # fail-closed only at build time, wasting runner capacity.
    from api.schemas.experiments import EInterRecommendationResponse, FFEligibilityItem
    from forcefield.eligibility import collect_binder_ff_issues

    binder_mol_ids = _enumerate_batch_binder_mol_ids(
        binder_types=request.binder_types,
        structure_sizes=request.structure_sizes,
        aging_states=request.aging_states,
        temperatures_k=request.temperatures_k,
    )
    # Filter out "none" sentinel — it's a control group marker, not a real additive
    real_additive_ids = [a for a in (additive_types or []) if a and a.lower() != "none"]
    ff_issues = collect_binder_ff_issues(
        mol_ids=binder_mol_ids,
        additive_ids=real_additive_ids,
    )
    ff_blocked = [FFEligibilityItem(**i) for i in ff_issues["blocked_items"]]

    # E_inter precision analysis recommendation (Finding #8)
    from features.e_inter_compute.service import DEFAULT_E_INTER_COMPUTE_SERVICE

    e_inter_rec = DEFAULT_E_INTER_COMPUTE_SERVICE.get_recommendation(
        workflow="batch_binder_cell",
        tier=run_tier.value,
        has_additive=bool(real_additive_ids),
    )
    e_inter_response = EInterRecommendationResponse(
        level=e_inter_rec["level"],
        score=e_inter_rec["score"],
        reason_codes=e_inter_rec["reason_codes"],
        affected_metrics=e_inter_rec["affected_metrics"],
        estimated_cpu_cost_minutes=e_inter_rec["estimated_cpu_cost_minutes"],
        default_enabled=e_inter_rec["default_enabled"],
    )

    return BatchJobBinderCellResponse(
        batch_job_id=result.batch_job_id,
        total=result.total,
        new=result.new,
        duplicates=result.duplicates,
        submitted=result.submitted,
        errors=result.errors,
        jobs=[_map_job_to_response(j) for j in result.jobs],
        blocked=getattr(result, "blocked", 0),
        requires_similarity_decision=getattr(result, "requires_similarity_decision", False),
        similar_job_count=getattr(result, "similar_job_count", 0),
        excluded=getattr(result, "excluded", 0),
        ff_blocked_items=ff_blocked,
        e_inter_recommendation=e_inter_response,
    )


def create_batch_job_binder_cell(request: BatchJobBinderCellRequest) -> BatchJobBinderCellResponse:
    """Create and submit a batch Binder Cell job."""
    from api.deps import get_job_manager
    from api.schemas.experiments import FFEligibilityItem
    from database.repositories.experiment_repo import ExperimentRepository
    from forcefield.eligibility import collect_binder_ff_issues
    from orchestrator.batch_job_binder_cell import (
        BatchJobBinderCellSpec,
        select_batch_runner_cls,
    )

    try:
        run_tier, ff_type = parse_tier_and_ff(
            request.tier.value if hasattr(request.tier, "value") else request.tier,
            request.ff_type,
        )
        stage_config = resolve_stage_requests(
            stage_requests=request.stage_requests,
            stage_durations=request.stage_durations,
            equilibration_settings=request.equilibration_settings,
            run_tier=run_tier,
        )
        additive_types, additive_catalog_map = _validate_additive_types(request.additive_types)

        # FF eligibility gate BEFORE runner.submit() — fail-closed policy.
        # "none" is a control group sentinel, not a real additive; exclude it.
        binder_mol_ids = _enumerate_batch_binder_mol_ids(
            binder_types=request.binder_types,
            structure_sizes=request.structure_sizes,
            aging_states=request.aging_states,
            temperatures_k=request.temperatures_k,
        )
        real_additive_ids = [a for a in (additive_types or []) if a and a.lower() != "none"]
        ff_issues = collect_binder_ff_issues(
            mol_ids=binder_mol_ids,
            additive_ids=real_additive_ids,
        )

        # Extract similar_existing_action
        similar_action = getattr(request, "similar_existing_action", None)
        similar_action_str = (
            similar_action.value
            if hasattr(similar_action, "value")
            else str(similar_action or "unspecified")
        )
        e_intra_method, e_intra_method_source = _resolve_batch_e_intra_method(request)

        spec = BatchJobBinderCellSpec(
            binder_types=request.binder_types,
            structure_sizes=request.structure_sizes,
            temperatures_k=request.temperatures_k,
            aging_states=request.aging_states,
            tier=run_tier.value,
            ff_type=ff_type.value,
            seed=request.seed,
            temperature_priority=request.temperature_priority,
            additive_types=additive_types,
            additive_concentrations=request.additive_concentrations,
            additive_catalog_map=additive_catalog_map,
            initial_density=request.initial_density,
            stage_duration_overrides=stage_config.stage_duration_overrides,
            property_calculations=request.property_calculations.model_dump()
            if request.property_calculations
            else None,
            equilibration_settings=stage_config.equilibration_settings.model_dump()
            if stage_config.equilibration_settings
            else None,
            similar_existing_action=similar_action_str,
            stage_requests=stage_config.canonical_stage_requests,
            excluded_exp_ids=getattr(request, "excluded_exp_ids", []),
            interaction_analysis=request.interaction_analysis.model_dump()
            if request.interaction_analysis
            else None,
            e_intra_method=e_intra_method,
            e_intra_method_source=e_intra_method_source,
        )

        # Validate (preview) then submit through a single session-bound runner.
        # SubmissionFacade opens its own committed sessions for the actual
        # writes, so sharing one session here is safe and removes the prior
        # double runner instantiation. The runner always carries job_manager
        # (validate ignores it); submit is skipped when FF-blocked.
        def _validate_and_submit(session):
            experiment_repo = ExperimentRepository(session)
            runner = select_batch_runner_cls(spec)(
                experiment_repo=experiment_repo,
                job_manager=get_job_manager(),
            )
            preview = runner.validate(spec)
            if ff_issues["has_blocked"]:
                return preview, None
            return preview, runner.submit(spec)

        preview_result, result = run_in_session(_validate_and_submit)

        # If any molecule is FF-blocked, runner.submit() was skipped — return
        # the preview info with submitted=0.
        if ff_issues["has_blocked"]:
            return BatchJobBinderCellResponse(
                batch_job_id=preview_result.batch_job_id or "ff_blocked",
                total=preview_result.total,
                new=preview_result.new,
                duplicates=preview_result.duplicates,
                submitted=0,  # Not submitted due to FF block
                errors=0,  # int, not list
                jobs=[_map_job_to_response(j) for j in preview_result.jobs],
                blocked=getattr(preview_result, "blocked", 0),
                requires_similarity_decision=getattr(
                    preview_result, "requires_similarity_decision", False
                ),
                similar_job_count=getattr(preview_result, "similar_job_count", 0),
                excluded=getattr(preview_result, "excluded", 0),
                ff_blocked_items=[FFEligibilityItem(**i) for i in ff_issues["blocked_items"]],
            )
    except ValueError as exc:
        raise ContractError(ErrorCode.INVALID_REQUEST, str(exc)) from exc

    # E_inter recommendation for response (submitted jobs may have interaction_analysis)
    from api.schemas.experiments import EInterRecommendationResponse
    from features.e_inter_compute.service import DEFAULT_E_INTER_COMPUTE_SERVICE

    real_additive_ids = [a for a in (additive_types or []) if a and a.lower() != "none"]
    e_inter_rec = DEFAULT_E_INTER_COMPUTE_SERVICE.get_recommendation(
        workflow="batch_binder_cell",
        tier=run_tier.value,
        has_additive=bool(real_additive_ids),
    )
    e_inter_response = EInterRecommendationResponse(
        level=e_inter_rec["level"],
        score=e_inter_rec["score"],
        reason_codes=e_inter_rec["reason_codes"],
        affected_metrics=e_inter_rec["affected_metrics"],
        estimated_cpu_cost_minutes=e_inter_rec["estimated_cpu_cost_minutes"],
        default_enabled=e_inter_rec["default_enabled"],
    )

    # FF passed above — return success response with empty blocked list
    return BatchJobBinderCellResponse(
        batch_job_id=result.batch_job_id,
        total=result.total,
        new=result.new,
        duplicates=result.duplicates,
        submitted=result.submitted,
        errors=result.errors,
        jobs=[_map_job_to_response(j) for j in result.jobs],
        blocked=getattr(result, "blocked", 0),
        requires_similarity_decision=getattr(result, "requires_similarity_decision", False),
        similar_job_count=getattr(result, "similar_job_count", 0),
        excluded=getattr(result, "excluded", 0),
        ff_blocked_items=[],
        e_inter_recommendation=e_inter_response,
    )
