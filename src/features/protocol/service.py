"""Protocol configuration service."""

from api.schemas import DefaultStagesResponse, StageCondition, StageConfigResponse
from contracts.errors import ContractError, ErrorCode
from contracts.policies.equilibration import DEFAULT_EQUILIBRATION_POLICY as EQ_POLICY
from contracts.policies.stabilization import StabilizationStep
from protocols.stage_catalog import get_optional_stage_keys, get_stage_defaults, get_stage_metadata


def _build_stage_condition(step: StabilizationStep) -> StageCondition | None:
    """Build structured condition metadata from a stabilization step.

    Args:
        step: StabilizationStep from the stabilization chain policy.

    Returns:
        StageCondition with temperature/pressure mode info, or None.
    """
    params = step.parameters or {}
    step_type = step.type

    if step_type == "minimize":
        return StageCondition(temperature_mode="none")

    if step_type == "annealing":
        return StageCondition(
            temperature_mode="ramp",
            fixed_temperature_K=params.get("temp_high_K", 500.0),
            uses_target_temperature=True,  # temp_low = target
            n_cycles=params.get("n_cycles"),
        )

    if step_type == "tensile":
        return StageCondition(
            temperature_mode="target",
            uses_target_temperature=True,
        )

    if "temperature_K" in params:
        if "temp_start_K" in params:
            return StageCondition(
                temperature_mode="ramp_from",
                fixed_temperature_K=params["temperature_K"],
                temp_start_K=params["temp_start_K"],
            )
        # Policy-fixed temperature (e.g. high_temp_nvt 500K)
        return StageCondition(
            temperature_mode="fixed",
            fixed_temperature_K=params["temperature_K"],
        )

    # Remaining: target temperature stages (nvt, npt, nemd, etc.)
    return StageCondition(
        temperature_mode="target",
        uses_target_temperature=True,
        uses_target_pressure=(step_type in ("npt",)),
    )


def _build_optional_stage_step(stage_name: str) -> StabilizationStep:
    """Build a synthetic step for optional UI stages not present in the base chain."""
    defaults = get_stage_defaults(stage_name)
    duration_ps = defaults.get("duration_ps")
    duration_steps = defaults.get("duration_steps")
    duration = None
    if duration_steps is not None:
        duration = f"{duration_steps} steps"
    elif duration_ps is not None:
        duration = f"{duration_ps} ps"

    parameters: dict[str, float | int] = {}
    if stage_name == "high_temp_nvt":
        parameters["temperature_K"] = EQ_POLICY.high_temp_nvt_temperature_K
    elif stage_name == "high_pressure_npt":
        parameters["temperature_K"] = EQ_POLICY.high_pressure_npt_temperature_K
        parameters["pressure_atm"] = EQ_POLICY.high_pressure_npt_pressure_atm

    return StabilizationStep(
        name=stage_name,
        type=defaults.get("type") or "npt",
        duration=duration,
        parameters=parameters,
    )


async def get_default_stages(tier: str, include_optional: bool = False) -> DefaultStagesResponse:
    """Return default protocol stages for a given chain key.

    Args:
        tier: Chain key identifier (e.g. "screening", "layer", "tensile_layer").
            Despite the parameter name, this maps to stabilization chain keys,
            not just RunTier values.
        include_optional: Whether to append optional stage metadata useful for
            frontend stage selection UIs.

    Returns:
        DefaultStagesResponse with stage configurations.
    """
    from contracts.policies.stabilization import DEFAULT_STABILIZATION_CHAIN

    valid_chain_keys = [
        "screening",
        "confirm",
        "viscosity",
        "validation",
        "screening_mini",
        "layer",
        "tensile_layer",
        "tensile_layer_qs",
    ]
    if tier not in valid_chain_keys:
        raise ContractError(
            ErrorCode.INVALID_REQUEST,
            f"Invalid chain key: {tier}. Valid keys: {valid_chain_keys}",
            {"tier": tier},
        )

    try:
        chain = DEFAULT_STABILIZATION_CHAIN.get_chain(tier)
    except ValueError as exc:
        raise ContractError(ErrorCode.INVALID_REQUEST, str(exc), {"tier": tier}) from exc

    def _build_stage_response(
        step: StabilizationStep,
        *,
        synthetic_optional: bool = False,
    ) -> StageConfigResponse:
        duration_ps = None
        duration_steps = None

        if step.duration:
            dur_lower = step.duration.strip().lower()
            if "steps" in dur_lower:
                duration_steps = int(dur_lower.replace("steps", "").strip())
            elif "ps" in dur_lower:
                duration_ps = float(dur_lower.replace("ps", "").strip())

        return StageConfigResponse(
            name=step.name,
            type=step.type,
            duration_ps=duration_ps,
            duration_steps=duration_steps,
            editable=True,
            condition=_build_stage_condition(step),
            **get_stage_metadata(step.name, synthetic_optional=synthetic_optional),
        )

    stages = [_build_stage_response(step) for step in chain]
    if include_optional:
        existing_stage_names = {stage.name for stage in stages}
        for optional_stage_name in get_optional_stage_keys(tier):
            if optional_stage_name in existing_stage_names:
                continue
            stages.append(
                _build_stage_response(
                    _build_optional_stage_step(optional_stage_name),
                    synthetic_optional=True,
                )
            )
        stages.sort(key=lambda stage: stage.order_index)

    total_duration = DEFAULT_STABILIZATION_CHAIN.get_total_duration_ps(tier)
    return DefaultStagesResponse(tier=tier, stages=stages, total_duration_ps=total_duration)
