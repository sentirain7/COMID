"""Validation helpers for experiment submission."""

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from api.schemas import (
    EquilibrationSettingsRequest,
    ExperimentRequest,
    MoleculeCompositionPreviewRequest,
    MoleculeExperimentRequest,
    StageRequest,
)
from contracts.errors import CompositionError, ContractError, ErrorCode
from contracts.schemas import FFType, RunTier


def parse_tier_and_ff(run_tier: str, ff_type: str) -> tuple[RunTier, FFType]:
    """Parse and validate run tier / forcefield."""
    try:
        tier = RunTier(run_tier)
    except ValueError as exc:
        raise ContractError(
            ErrorCode.INVALID_TIER,
            f"Invalid run_tier '{run_tier}'. Must be one of: {[t.value for t in RunTier]}",
        ) from exc
    try:
        ff = FFType(ff_type)
    except ValueError as exc:
        raise ContractError(
            ErrorCode.INVALID_FF_TYPE,
            f"Invalid ff_type '{ff_type}'. Must be one of: {[f.value for f in FFType]}",
        ) from exc
    return tier, ff


def validate_composition_sum(request: ExperimentRequest) -> None:
    """Validate SARA composition sum with policy tolerance."""
    from contracts.policies.composition import DEFAULT_COMPOSITION_CONSTRAINTS

    comp_sum = (
        request.composition.asphaltene_wt
        + request.composition.resin_wt
        + request.composition.aromatic_wt
        + request.composition.saturate_wt
    )
    fractional_tolerance = (
        DEFAULT_COMPOSITION_CONSTRAINTS.sum_tolerance / DEFAULT_COMPOSITION_CONSTRAINTS.sum_wt_pct
    )
    if abs(comp_sum - 1.0) > fractional_tolerance:
        raise CompositionError(
            ErrorCode.COMPOSITION_SUM_ERROR,
            f"Composition must sum to 1.0, got {comp_sum:.3f}",
        )


def build_stage_duration_overrides_from_list(
    stage_durations,
    run_tier: RunTier,
    chain_key_override: str | None = None,
):
    """Validate optional stage duration overrides and return internal models.

    Args:
        stage_durations: List of stage duration override requests.
        run_tier: The RunTier enum value.
        chain_key_override: If provided, use this chain key instead of run_tier
            for override validation (e.g. 'tensile_layer' for layer workflows).
    """
    if not stage_durations:
        return None

    from protocols.duration_adjuster import ProtocolChainAdjuster, StageDurationOverride

    adjuster = ProtocolChainAdjuster()
    overrides = [
        StageDurationOverride(
            stage_name=sd.stage_name,
            duration_ps=sd.duration_ps,
            duration_steps=sd.duration_steps,
        )
        for sd in stage_durations
    ]
    validation_key = chain_key_override or run_tier.value
    errors = adjuster.validate_overrides(validation_key, overrides)
    if errors:
        raise ContractError(
            ErrorCode.VALIDATION_ERROR,
            f"Invalid stage durations: {'; '.join(errors)}",
        )
    return overrides


def build_stage_duration_overrides(request: MoleculeExperimentRequest, run_tier: RunTier):
    """Validate optional stage duration overrides and return internal models."""
    return build_stage_duration_overrides_from_list(request.stage_durations, run_tier)


@dataclass
class ResolvedStageConfiguration:
    """Canonical stage configuration used across submit flows."""

    stage_duration_overrides: list | None
    equilibration_settings: EquilibrationSettingsRequest | None
    has_equilibration: bool
    canonical_stage_requests: list[dict[str, Any]]


def _build_canonical_eq_request(
    stage_key: str,
    *,
    enabled: bool,
    duration_ps: float,
    params_override: dict[str, Any],
) -> dict[str, Any]:
    return {
        "stage_key": stage_key,
        "enabled": enabled,
        "duration_ps": duration_ps,
        "duration_steps": None,
        "params_override": params_override,
    }


def resolve_stage_requests(
    *,
    stage_requests: list[StageRequest] | None,
    stage_durations,
    equilibration_settings: EquilibrationSettingsRequest | None,
    run_tier: RunTier,
    chain_key_override: str | None = None,
) -> ResolvedStageConfiguration:
    """Normalize new/legacy stage payloads into a canonical submit configuration."""
    from contracts.policies.equilibration import DEFAULT_EQUILIBRATION_POLICY as EQ
    from protocols.duration_adjuster import ProtocolChainAdjuster, StageDurationOverride

    adjuster = ProtocolChainAdjuster()

    if stage_requests is not None:
        request_map = {request.stage_key: request for request in stage_requests}
        ht_req = request_map.get("high_temp_nvt")
        hp_req = request_map.get("high_pressure_npt")

        eq_enabled_flags = [req.enabled for req in (ht_req, hp_req) if req is not None]
        has_equilibration = any(eq_enabled_flags)
        if eq_enabled_flags and len(set(eq_enabled_flags)) > 1:
            raise ContractError(
                ErrorCode.VALIDATION_ERROR,
                "Equilibration stages must be enabled/disabled together.",
            )

        resolved_eq = None
        canonical_requests: list[dict[str, Any]] = []
        if has_equilibration:
            ht_params = dict(ht_req.params_override or {}) if ht_req else {}
            hp_params = dict(hp_req.params_override or {}) if hp_req else {}
            try:
                resolved_eq = EquilibrationSettingsRequest(
                    enabled=True,
                    high_temp_nvt_temperature_K=float(
                        ht_params.get("temperature_K", EQ.high_temp_nvt_temperature_K)
                    ),
                    high_temp_nvt_duration_ps=float(
                        ht_req.duration_ps
                        if ht_req and ht_req.duration_ps is not None
                        else EQ.high_temp_nvt_duration_ps
                    ),
                    high_pressure_npt_temperature_K=float(
                        hp_params.get("temperature_K", EQ.high_pressure_npt_temperature_K)
                    ),
                    high_pressure_npt_pressure_atm=float(
                        hp_params.get("pressure_atm", EQ.high_pressure_npt_pressure_atm)
                    ),
                    high_pressure_npt_duration_ps=float(
                        hp_req.duration_ps
                        if hp_req and hp_req.duration_ps is not None
                        else EQ.high_pressure_npt_duration_ps
                    ),
                )
            except ValidationError as exc:
                raise ContractError(
                    ErrorCode.VALIDATION_ERROR,
                    "Invalid equilibration stage parameters.",
                ) from exc
            canonical_requests.extend(
                [
                    _build_canonical_eq_request(
                        "high_temp_nvt",
                        enabled=True,
                        duration_ps=resolved_eq.high_temp_nvt_duration_ps,
                        params_override={
                            "temperature_K": resolved_eq.high_temp_nvt_temperature_K,
                        },
                    ),
                    _build_canonical_eq_request(
                        "high_pressure_npt",
                        enabled=True,
                        duration_ps=resolved_eq.high_pressure_npt_duration_ps,
                        params_override={
                            "temperature_K": resolved_eq.high_pressure_npt_temperature_K,
                            "pressure_atm": resolved_eq.high_pressure_npt_pressure_atm,
                        },
                    ),
                ]
            )

        overrides: list[StageDurationOverride] = []
        for request in stage_requests:
            if request.stage_key in {"high_temp_nvt", "high_pressure_npt"}:
                continue
            if not request.enabled:
                canonical_requests.append(
                    {
                        "stage_key": request.stage_key,
                        "enabled": False,
                        "duration_ps": request.duration_ps,
                        "duration_steps": request.duration_steps,
                        "params_override": request.params_override,
                    }
                )
                continue

            if request.duration_ps is None and request.duration_steps is None:
                canonical_requests.append(
                    {
                        "stage_key": request.stage_key,
                        "enabled": True,
                        "duration_ps": None,
                        "duration_steps": None,
                        "params_override": request.params_override,
                    }
                )
                continue

            overrides.append(
                StageDurationOverride(
                    stage_name=request.stage_key,
                    duration_ps=request.duration_ps,
                    duration_steps=request.duration_steps,
                )
            )
            canonical_requests.append(
                {
                    "stage_key": request.stage_key,
                    "enabled": True,
                    "duration_ps": request.duration_ps,
                    "duration_steps": request.duration_steps,
                    "params_override": request.params_override,
                }
            )

        validation_key = chain_key_override or run_tier.value
        errors = adjuster.validate_overrides(validation_key, overrides)
        if errors:
            raise ContractError(
                ErrorCode.VALIDATION_ERROR,
                f"Invalid stage durations: {'; '.join(errors)}",
            )

        return ResolvedStageConfiguration(
            stage_duration_overrides=overrides or None,
            equilibration_settings=resolved_eq,
            has_equilibration=has_equilibration,
            canonical_stage_requests=canonical_requests,
        )

    filtered_stage_durations = []
    for sd in stage_durations or []:
        if getattr(sd, "stage_name", None) in {"high_temp_nvt", "high_pressure_npt"}:
            continue
        filtered_stage_durations.append(sd)

    overrides = build_stage_duration_overrides_from_list(
        filtered_stage_durations,
        run_tier,
        chain_key_override=chain_key_override,
    )
    resolved_eq = (
        equilibration_settings
        if equilibration_settings and equilibration_settings.enabled
        else None
    )
    canonical_requests = []
    if resolved_eq is not None:
        canonical_requests.extend(
            [
                _build_canonical_eq_request(
                    "high_temp_nvt",
                    enabled=True,
                    duration_ps=resolved_eq.high_temp_nvt_duration_ps,
                    params_override={
                        "temperature_K": resolved_eq.high_temp_nvt_temperature_K,
                    },
                ),
                _build_canonical_eq_request(
                    "high_pressure_npt",
                    enabled=True,
                    duration_ps=resolved_eq.high_pressure_npt_duration_ps,
                    params_override={
                        "temperature_K": resolved_eq.high_pressure_npt_temperature_K,
                        "pressure_atm": resolved_eq.high_pressure_npt_pressure_atm,
                    },
                ),
            ]
        )
    for override in overrides or []:
        canonical_requests.append(
            {
                "stage_key": override.stage_name,
                "enabled": True,
                "duration_ps": override.duration_ps,
                "duration_steps": override.duration_steps,
                "params_override": None,
            }
        )

    return ResolvedStageConfiguration(
        stage_duration_overrides=overrides,
        equilibration_settings=resolved_eq,
        has_equilibration=bool(resolved_eq and resolved_eq.enabled),
        canonical_stage_requests=canonical_requests,
    )


def _resolve_binder_config(config: dict[str, Any] | None) -> dict[str, Any]:
    if config and config.get("binder_types"):
        return config

    from contracts.policies.binders import get_default_binder_config

    return get_default_binder_config()


def validate_binder_types(
    binder_types: list[str] | None,
    *,
    config: dict[str, Any] | None,
    allow_custom: bool = False,
) -> list[str]:
    """Validate binder types against the configured binder catalog."""
    normalized = [binder for binder in dict.fromkeys(binder_types or []) if binder]
    if not normalized:
        return []

    valid_binder_types = list(_resolve_binder_config(config).get("binder_types", {}).keys())
    if allow_custom:
        valid_binder_types.append("custom")

    invalid = [binder for binder in normalized if binder not in valid_binder_types]
    if invalid:
        raise ContractError(
            ErrorCode.VALIDATION_ERROR,
            f"Invalid binder_type(s): {invalid}. Must be one of: {valid_binder_types}",
        )

    return normalized


def load_active_additive_catalog(*, session=None) -> dict[str, dict[str, object]]:
    """Return active additive catalog payload keyed by mol_id."""
    from database.repositories.additive_repo import AdditiveRepository

    def _load(db_session):
        repo = AdditiveRepository(db_session)
        return {
            row.mol_id: {
                "name": row.name,
                "default_counts": row.default_counts or {"X1": 2, "X2": 4, "X3": 6},
                "molecular_weight": row.molecular_weight,
                "category": row.category,
            }
            for row in repo.list_active()
        }

    if session is not None:
        return _load(session)

    from features.common import run_in_session

    return run_in_session(_load)


def validate_additive_mol_ids(
    additive_types: list[str] | None,
    *,
    session=None,
) -> tuple[list[str], dict[str, dict[str, object]]]:
    """Validate additive mol_ids and return normalized ids plus catalog metadata."""
    normalized = [mol_id for mol_id in dict.fromkeys(additive_types or []) if mol_id]
    if not normalized:
        return [], {}

    catalog_map = load_active_additive_catalog(session=session)
    invalid = [mol_id for mol_id in normalized if mol_id not in catalog_map]
    if invalid:
        available = ", ".join(sorted(catalog_map.keys())[:30])
        raise ContractError(
            ErrorCode.VALIDATION_ERROR,
            f"Invalid additive mol_id(s): {invalid}. Available: [{available}]",
        )

    return normalized, {mol_id: catalog_map[mol_id] for mol_id in normalized}


def validate_molecule_request_config(
    request: MoleculeExperimentRequest | MoleculeCompositionPreviewRequest,
    config,
    molecule_db,
) -> list[str]:
    """Validate binder type and structure size for molecule-based request."""
    validate_binder_types([request.binder_type], config=config, allow_custom=True)

    if request.binder_type != "custom":
        valid_sizes = molecule_db.get_valid_structure_sizes(config, request.binder_type) or [
            "X1",
            "X2",
            "X3",
        ]
    else:
        valid_sizes = ["X1", "X2", "X3"]

    if request.structure_size not in valid_sizes:
        raise ContractError(
            ErrorCode.VALIDATION_ERROR,
            f"Invalid structure_size. Must be one of: {valid_sizes}",
        )

    if request.additives:
        requested = [a.mol_id for a in request.additives if getattr(a, "mol_id", None)]
        validate_additive_mol_ids(requested)

    return valid_sizes
