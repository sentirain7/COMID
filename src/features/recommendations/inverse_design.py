"""Inverse-design recommendation service."""

from collections.abc import Mapping

from api.schemas import (
    InverseDesignRequest,
    InverseDesignResponse,
    InverseDesignResultItem,
)
from common.logging import get_logger
from contracts.errors import ContractError, ErrorCode, OrchestrationError
from contracts.policies.binders import SARA_COMPONENTS as _SARA_COMPONENTS
from contracts.policies.ml_policy import DEFAULT_ML_POLICY, FeatureSetVersion
from contracts.policies.recommendation_policy import DEFAULT_RECOMMENDATION_POLICY
from ml.extrapolation import HARD_EXTRAPOLATION, assess_prediction_context

logger = get_logger(__name__)


def _resolve_prediction_contract(
    request: InverseDesignRequest,
    target_set,
    capability_manifest: Mapping[str, object] | None,
) -> str:
    """Resolve requested/actual feature contract for inverse design routing."""
    if request.prediction_contract:
        return str(request.prediction_contract).lower()
    manifest_feature_sets = {
        str(capability_manifest.get("per_target_feature_set", {}).get(t.metric_name, "")).lower()
        for t in target_set.targets
        if capability_manifest
    }
    manifest_feature_sets.discard("")
    if request.aggregate_specs:
        return "v6" if "v6" in manifest_feature_sets else "v4"

    for version in ("v6", "v5", "v4", "v3", "v2", "v1"):
        if version in manifest_feature_sets:
            return version

    target_versions = {
        DEFAULT_ML_POLICY.target_feature_sets.get_version(t.metric_name) for t in target_set.targets
    }
    if FeatureSetVersion.V5 in target_versions:
        return "v5"
    if FeatureSetVersion.V3 in target_versions:
        return "v3"
    if FeatureSetVersion.V2 in target_versions:
        return "v2"
    return "v1"


def _validate_capability_manifest(
    *,
    request: InverseDesignRequest,
    target_set,
    capability_manifest: Mapping[str, object] | None,
    prediction_contract: str,
) -> None:
    """Fail fast on unsupported runtime capability before optimization work."""
    if capability_manifest is None:
        return

    supported_targets = {
        str(name) for name in capability_manifest.get("supported_targets", []) if name
    }
    missing_targets = [
        t.metric_name for t in target_set.targets if t.metric_name not in supported_targets
    ]
    if missing_targets:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            f"Targets {missing_targets} are not supported by the active champion model.",
            {
                "failure_mode": "unsupported_capability",
                "unsupported_targets": missing_targets,
            },
        )

    assessment = assess_prediction_context(
        capability_manifest=dict(capability_manifest),
        temperature_k=(
            request.temperature_k_fixed
            or (
                request.temperature_range_k.min_k
                if request.optimize_temperature and request.temperature_range_k is not None
                else None
            )
        ),
        layer_count=(2 if request.aggregate_specs else None),
        additive_type=request.additive_type,
    )
    if assessment.status == HARD_EXTRAPOLATION and not request.allow_extrapolation:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            "Requested inverse-design context is outside the champion capability domain.",
            {
                "failure_mode": "hard_extrapolation",
                "reasons": assessment.reasons,
            },
        )

    manifest_contracts = {
        str(value).lower()
        for value in capability_manifest.get("per_target_feature_set", {}).values()
    }
    if prediction_contract not in manifest_contracts and prediction_contract not in {"v1", "v2"}:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            f"Prediction contract '{prediction_contract}' is not supported by the active champion model.",
            {
                "failure_mode": "unsupported_capability",
                "prediction_contract": prediction_contract,
            },
        )


def _build_bounds_overrides(constraints) -> dict[str, tuple[float, float]]:
    """Convert request constraint fields into optimizer bounds overrides."""
    if constraints is None:
        return {}

    overrides: dict[str, tuple[float, float]] = {}
    data = constraints.model_dump(exclude_none=True) if hasattr(constraints, "model_dump") else {}
    for component in _SARA_COMPONENTS:
        min_key = f"min_{component}"
        max_key = f"max_{component}"
        low = data.get(min_key)
        high = data.get(max_key)
        if low is None and high is None:
            continue
        from contracts.policies.composition import DEFAULT_COMPOSITION_CONSTRAINTS

        default_low, default_high = DEFAULT_COMPOSITION_CONSTRAINTS.bounds.get(
            component, (0.0, 100.0)
        )
        overrides[component] = (
            float(low) if low is not None else float(default_low),
            float(high) if high is not None else float(default_high),
        )
    return overrides


def resolve_property_target_set(request: InverseDesignRequest):
    """Resolve request to PropertyTargetSet from user-specified property targets."""
    from recommendation.property_targets import PropertyTarget, PropertyTargetSet

    if request.custom_targets is None or not request.custom_targets:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            "custom_targets is required: specify the property targets "
            "(e.g. viscosity, density, work_of_separation) to design for.",
        )

    return PropertyTargetSet(
        name="custom",
        description="User-defined custom targets",
        targets=[
            PropertyTarget(
                metric_name=t.metric_name,
                target_min=t.target_min,
                target_max=t.target_max,
                direction=t.direction,
                weight=t.weight,
            )
            for t in request.custom_targets
        ],
    )


async def run_inverse_design(request: InverseDesignRequest) -> InverseDesignResponse:
    """Run inverse design optimization for target PG grade.

    If request.aggregate_specs is provided, delegates to aggregate-aware design.
    """
    if (
        request.include_additive
        and request.additive_type is None
        and not request.explore_all_additives
    ):
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            "include_additive=True requires additive_type or explore_all_additives for inverse design",
        )
    if request.aggregate_specs:
        return await _run_aggregate_aware_design(request)
    return await _run_standard_design(request)


async def _run_standard_design(request: InverseDesignRequest) -> InverseDesignResponse:
    """Standard inverse design (bulk properties only).

    mol_counts 없으면 V2 only (binder_source_exp_id로 V3 활성화 가능).
    V4 targets는 aggregate_specs 없이 절대 허용하지 않음.
    """
    from api.deps import (
        get_ml_predictor_fn,
        get_ml_predictor_with_uncertainty_fn,
        get_runtime_capability_manifest,
        get_runtime_ood_detector,
    )
    from recommendation.inverse_designer import InverseDesigner

    target_set = resolve_property_target_set(request)

    ok, errors = target_set.validate_against_registry()
    if not ok:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            f"Invalid targets: {errors}",
        )

    # Guard: V4 targets require aggregate_specs (crystal/amorphous features).
    # Never silently drop targets — fail fast if any V4 target is present.
    v4_targets = [
        t
        for t in target_set.targets
        if DEFAULT_ML_POLICY.target_feature_sets.get_version(t.metric_name) == FeatureSetVersion.V4
    ]
    if v4_targets:
        v4_names = [t.metric_name for t in v4_targets]
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            f"Targets {v4_names} require crystal/amorphous features (V4). "
            "Provide aggregate_specs for layered optimization, "
            "or specify bulk-only property targets.",
        )

    # Resolve mol_counts from binder source experiment (V3 activation)
    mol_counts = None
    molecule_db = None
    if request.binder_source_exp_id:
        mol_counts, molecule_db = _load_mol_counts_from_experiment(request.binder_source_exp_id)

    capability_manifest = get_runtime_capability_manifest()
    prediction_contract = _resolve_prediction_contract(request, target_set, capability_manifest)
    _validate_capability_manifest(
        request=request,
        target_set=target_set,
        capability_manifest=capability_manifest,
        prediction_contract=prediction_contract,
    )

    predictor_fn = get_ml_predictor_with_uncertainty_fn(
        mol_counts=mol_counts, molecule_db=molecule_db
    )
    if predictor_fn is None:
        predictor_fn = get_ml_predictor_fn(mol_counts=mol_counts, molecule_db=molecule_db)
    if predictor_fn is None:
        raise OrchestrationError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "ML model not loaded. Train models first.",
            {"failure_mode": "model_unavailable"},
        )

    # Feasibility pre-screening: estimate target achievability before the
    # expensive optimization loop, failing fast on infeasible requests.
    feasibility = _scout_feasibility(request, target_set, predictor_fn)

    ood_detector = get_runtime_ood_detector(prediction_contract)

    designer = InverseDesigner(
        predictor_fn=predictor_fn,
        target_set=target_set,
        additive_type=request.additive_type,
        bounds_overrides=_build_bounds_overrides(request.constraints),
        ood_detector=ood_detector,
        optimize_temperature=request.optimize_temperature,
        temperature_range_k=(
            (request.temperature_range_k.min_k, request.temperature_range_k.max_k)
            if request.temperature_range_k is not None
            else None
        ),
        temperature_k_fixed=request.temperature_k_fixed,
        pressure_atm_fixed=request.pressure_atm_fixed,
        allow_extrapolation=request.allow_extrapolation,
        capability_manifest=capability_manifest,
    )

    result = designer.run(
        max_iterations=request.max_iterations,
        n_top=request.n_results,
    )

    return _build_response(
        result, target_set, prediction_contract=prediction_contract, feasibility=feasibility
    )


def _scout_feasibility(
    request: InverseDesignRequest,
    target_set,
    predictor_fn,
) -> dict | None:
    """Run feasibility pre-screening, fail-fast on infeasible targets.

    Returns the feasibility report dict (attached to the response), or ``None``
    when scouting is disabled by policy.  Raises ``ContractError`` when targets
    are infeasible and ``allow_infeasible_exploration`` is not set.
    """
    policy = DEFAULT_RECOMMENDATION_POLICY.inverse_design
    if not policy.feasibility_scout_enabled:
        return None

    from recommendation.feasibility_scout import INFEASIBLE, FeasibilityScout

    # P1-9: scout the user-constrained composition space (not the full default
    # space), and sample deterministically so threshold-adjacent verdicts are
    # reproducible/auditable.
    validator = None
    overrides = _build_bounds_overrides(request.constraints)
    if overrides:
        from contracts.policies.composition import DEFAULT_COMPOSITION_CONSTRAINTS
        from recommendation.composition_validator import CompositionValidator

        merged_bounds = {**DEFAULT_COMPOSITION_CONSTRAINTS.bounds, **overrides}
        constraints = DEFAULT_COMPOSITION_CONSTRAINTS.model_copy(update={"bounds": merged_bounds})
        validator = CompositionValidator(constraints=constraints, auto_fix=True)

    scout = FeasibilityScout(
        predictor_fn=predictor_fn,
        target_set=target_set,
        validator=validator,
        additive_type=request.additive_type,
        temperature_k=request.temperature_k_fixed,
        seed=getattr(policy, "feasibility_seed", None),
    )
    report = scout.scout()

    if report.status == INFEASIBLE and not request.allow_infeasible_exploration:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            report.message,
            {"failure_mode": "infeasible_targets", "feasibility": report.to_dict()},
        )

    return report.to_dict()


async def _run_aggregate_aware_design(
    request: InverseDesignRequest,
) -> InverseDesignResponse:
    """Aggregate-aware inverse design for layered structures.

    For each (aggregate × additive) combination:
    1. Resolve crystal properties from DB→YAML→schema defaults chain.
    2. Build layered predictor with fixed crystal features.
    3. Run InverseDesigner with layered predictor.
    4. Rank across all combinations.
    """
    from api.deps import get_layered_predictor_fn, get_runtime_capability_manifest
    from ml.crystal_features import CrystalFeatureExtractor
    from recommendation.inverse_designer import InverseDesigner

    target_set = resolve_property_target_set(request)
    ok, errors = target_set.validate_against_registry()
    if not ok:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            f"Invalid targets: {errors}",
        )

    capability_manifest = get_runtime_capability_manifest()
    prediction_contract = _resolve_prediction_contract(request, target_set, capability_manifest)
    _validate_capability_manifest(
        request=request,
        target_set=target_set,
        capability_manifest=capability_manifest,
        prediction_contract=prediction_contract,
    )

    crystal_extractor = CrystalFeatureExtractor()

    # Resolve mol_counts from binder source experiment (V3 activation)
    mol_counts = None
    molecule_db = None
    if request.binder_source_exp_id:
        mol_counts, molecule_db = _load_mol_counts_from_experiment(request.binder_source_exp_id)

    # Determine additive list
    additive_types: list[str | None] = [request.additive_type]
    if request.explore_all_additives:
        try:
            from database.connection import session_scope
            from database.repositories.additive_repo import AdditiveRepository

            with session_scope() as session:
                repo = AdditiveRepository(session)
                active = repo.list_active()
                additive_types = [a.mol_id for a in active] if active else [None]
        except Exception:
            additive_types = [None]

    all_results = []
    missing_predictor_count = 0
    for agg_spec in request.aggregate_specs:
        crystal_props = _resolve_crystal_properties(agg_spec.material, agg_spec.surface)
        crystal_features = crystal_extractor.extract(crystal_props)

        for additive_type in additive_types:
            predictor_fn = get_layered_predictor_fn(
                crystal_features,
                mol_counts=mol_counts,
                molecule_db=molecule_db,
            )
            if predictor_fn is None:
                missing_predictor_count += 1
                continue

            designer = InverseDesigner(
                predictor_fn=predictor_fn,
                target_set=target_set,
                additive_type=additive_type,
                bounds_overrides=_build_bounds_overrides(request.constraints),
                optimize_temperature=request.optimize_temperature,
                temperature_range_k=(
                    (request.temperature_range_k.min_k, request.temperature_range_k.max_k)
                    if request.temperature_range_k is not None
                    else None
                ),
                temperature_k_fixed=request.temperature_k_fixed,
                pressure_atm_fixed=request.pressure_atm_fixed,
                allow_extrapolation=request.allow_extrapolation,
                capability_manifest=capability_manifest,
            )

            result = designer.run(
                max_iterations=request.max_iterations,
                n_top=request.n_results,
            )

            for c in result.best_compositions:
                c.composition["_aggregate_material"] = agg_spec.material
                c.composition["_aggregate_surface"] = agg_spec.surface
                if additive_type:
                    c.composition["_additive_type"] = additive_type
                all_results.append((c, target_set))

    if missing_predictor_count > 0:
        raise OrchestrationError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "Layered-capable ML model not loaded. Train or register a champion model first.",
        )

    if not all_results:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            "Aggregate-aware inverse design produced no candidates for the requested context.",
        )

    # Sort by number of satisfied targets desc, then by sum of distances asc
    all_results.sort(
        key=lambda x: (
            -sum(
                1
                for t in x[1].targets
                if t.is_satisfied(x[0].predicted_objectives.get(t.metric_name, 0))
            ),
            sum(x[1].compute_distances(x[0].predicted_objectives).values()),
        )
    )

    result_items = []
    for c, ts in all_results[: request.n_results]:
        distances = ts.compute_distances(c.predicted_objectives)
        satisfied = ts.are_all_satisfied(c.predicted_objectives)
        result_items.append(
            InverseDesignResultItem(
                composition=c.composition,
                predicted_properties=c.predicted_objectives,
                uncertainty=c.uncertainty,
                targets_satisfied=satisfied,
                target_distances=distances,
                is_ood=c.is_ood,
                rationale=c.rationale,
                extrapolation_status=c.extrapolation_status,
                high_uncertainty=c.high_uncertainty,
                capability_notes=list(c.capability_notes),
            )
        )

    return InverseDesignResponse(
        target_set_name=target_set.name,
        n_iterations=request.max_iterations,
        converged=len(result_items) > 0,
        feasibility_rate=(
            sum(1 for r in result_items if r.targets_satisfied) / max(len(result_items), 1)
        ),
        ood_flagged_count=sum(1 for r in result_items if r.is_ood),
        results=result_items,
        hypervolume_history=[],
        prediction_contract=prediction_contract,
    )


def _load_mol_counts_from_experiment(
    exp_id: str,
) -> tuple[dict[str, int] | None, object | None]:
    """Load mol_counts from an experiment's experiment_molecules table.

    Args:
        exp_id: Source experiment ID.

    Returns:
        (mol_counts, molecule_db) tuple.  Both None on failure.
    """
    try:
        from database.connection import session_scope
        from database.models import ExperimentModel, ExperimentMoleculeModel, MoleculeModel

        with session_scope() as session:
            exp = session.query(ExperimentModel).filter_by(exp_id=exp_id).first()
            if exp is None:
                return None, None
            rows = (
                session.query(MoleculeModel.mol_id, ExperimentMoleculeModel.count)
                .join(
                    ExperimentMoleculeModel,
                    MoleculeModel.id == ExperimentMoleculeModel.molecule_id,
                )
                .filter(ExperimentMoleculeModel.experiment_id == exp.id)
                .all()
            )
            if not rows:
                return None, None
            mol_counts = dict(rows)

        # Load molecule_db for MW lookup during feature extraction
        try:
            from api.deps import get_molecule_db

            molecule_db = get_molecule_db()
        except Exception:
            molecule_db = None

        return mol_counts, molecule_db
    except Exception:
        return None, None


def _resolve_crystal_properties(material: str, surface: str) -> dict:
    """Resolve crystal properties via DB → YAML → schema defaults chain.

    Args:
        material: Crystal material formula (e.g. "SiO2").
        surface: Miller index string (e.g. "001").

    Returns:
        Dict with keys: material, surface, hydroxyl_density,
        thickness_angstrom, xy_size_angstrom, atom_count.
    """
    from contracts.schemas import CrystalLayerSpec

    defaults = CrystalLayerSpec()

    # Priority 1: DB lookup
    try:
        from database.connection import session_scope
        from database.models import CrystalStructureModel

        with session_scope() as session:
            crystal = (
                session.query(CrystalStructureModel)
                .filter_by(material=material, surface=surface, status="ready")
                .first()
            )
            if crystal:
                return {
                    "material": material,
                    "surface": surface,
                    "hydroxyl_density": (
                        crystal.hydroxyl_density
                        if crystal.hydroxyl_density is not None
                        else defaults.hydroxyl_density
                    ),
                    "thickness_angstrom": (
                        crystal.thickness_angstrom
                        if crystal.thickness_angstrom is not None
                        else defaults.thickness_angstrom
                    ),
                    "xy_size_angstrom": (
                        crystal.xy_size_angstrom
                        if crystal.xy_size_angstrom is not None
                        else defaults.xy_size_angstrom
                    ),
                    "atom_count": (
                        crystal.atom_count
                        if crystal.atom_count is not None
                        else defaults.atom_count
                    ),
                }
    except Exception:
        pass

    # Priority 2: schema defaults (CrystalLayerSpec SSOT)
    return {
        "material": material,
        "surface": surface,
        "hydroxyl_density": defaults.hydroxyl_density,
        "thickness_angstrom": defaults.thickness_angstrom,
        "xy_size_angstrom": defaults.xy_size_angstrom,
        "atom_count": 5000,  # reasonable default; CrystalLayerSpec defines geometry, not count
    }


def _build_response(
    result, target_set, *, prediction_contract: str | None = None, feasibility: dict | None = None
) -> InverseDesignResponse:
    """Build InverseDesignResponse from optimizer result."""
    result_items = []
    for c in result.best_compositions:
        distances = target_set.compute_distances(c.predicted_objectives)
        satisfied = target_set.are_all_satisfied(c.predicted_objectives)
        result_items.append(
            InverseDesignResultItem(
                composition=c.composition,
                predicted_properties=c.predicted_objectives,
                uncertainty=c.uncertainty,
                targets_satisfied=satisfied,
                target_distances=distances,
                is_ood=c.is_ood,
                rationale=c.rationale,
                extrapolation_status=c.extrapolation_status,
                high_uncertainty=c.high_uncertainty,
                capability_notes=list(c.capability_notes),
            )
        )

    hv_history = [h.get("hypervolume", 0.0) for h in result.history]
    pareto_front = _build_pareto_front(result)
    audit_log = _build_audit_log(result)

    return InverseDesignResponse(
        target_set_name=result.target_set.name,
        n_iterations=result.n_iterations,
        converged=result.converged,
        feasibility_rate=result.feasibility_rate,
        ood_flagged_count=result.ood_flagged_count,
        results=result_items,
        hypervolume_history=hv_history,
        prediction_contract=prediction_contract,
        feasibility=feasibility,
        pareto_front=pareto_front,
        audit_log=audit_log,
    )


def _jsonable(value):
    """Coerce numpy scalars/arrays nested in dicts/lists to native Python types."""
    import numpy as np

    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    return value


def _build_pareto_front(result) -> list[dict] | None:
    """Expose top Pareto-optimal candidates for manual trade-off exploration."""
    front = getattr(result, "pareto_front", None)
    if front is None:
        return None
    max_points = DEFAULT_RECOMMENDATION_POLICY.inverse_design.pareto_front_max_points
    points = front.get_top_k(k=max_points, sort_by="crowding_distance")
    return [
        {
            "composition": _jsonable(p.composition),
            "predicted_properties": _jsonable(p.predicted_properties),
            "crowding_distance": float(p.crowding_distance),
            "is_pareto": bool(p.is_pareto),
        }
        for p in points
    ]


def _build_audit_log(result) -> dict:
    """Build a decision-trace audit log from the optimization result."""
    policy = DEFAULT_RECOMMENDATION_POLICY.inverse_design
    return {
        "acquisition_function": getattr(result, "acquisition_function", ""),
        "acquisition_rationale": getattr(result, "acquisition_rationale", ""),
        "ranking": {
            "formula": (
                "sum(direction-weighted objectives) "
                "- ood_penalty*is_ood "
                "- uncertainty_penalty_lambda*max_uncertainty_ratio "
                "- extrapolation_penalty*(status == combinatorial_generalization)"
            ),
            "ood_penalty": policy.ood_penalty,
            "uncertainty_penalty_lambda": policy.uncertainty_penalty_lambda,
            "extrapolation_penalty": policy.extrapolation_penalty,
            "high_uncertainty_ratio_threshold": policy.high_uncertainty_ratio_threshold,
        },
        "convergence": {
            "converged": bool(result.converged),
            "threshold": policy.convergence_threshold,
            "window": policy.convergence_window,
        },
        "iterations": _jsonable(list(result.history)),
    }
