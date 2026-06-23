"""Progress and stage calculation helpers for running jobs.

Key design decisions:
- Minimize stages contribute 0 steps to cumulative totals because LAMMPS
  does not advance the global timestep during energy minimization, and
  ``reset_timestep 0`` is called immediately after minimize.
- Equilibration injection (high_temp_nvt + high_pressure_npt) is detected
  via ``has_equilibration`` flag and the extra stages are spliced into the
  stage list using the SSOT defaults from contracts.policies.equilibration.
"""

from __future__ import annotations


def _stages_from_compiled_plan(compiled_plan: dict | None) -> list[dict]:
    """Normalize persisted compiled plan stages to the progress stage format."""
    if not compiled_plan or not isinstance(compiled_plan, dict):
        return []

    result: list[dict] = []
    for stage in compiled_plan.get("stages", []) or []:
        if not isinstance(stage, dict):
            continue
        result.append(
            {
                "name": stage.get("stage_key", "unknown"),
                "type": stage.get("type", "unknown"),
                "steps": int(stage.get("expected_steps", 0) or 0),
                "cumulative": int(stage.get("cumulative_steps", 0) or 0),
            }
        )
    return result


def _stage_steps(stage: dict, dt_fs: float) -> int:
    """Compute effective step count for a single stage.

    Minimize stages return 0 because LAMMPS does not advance the
    global timestep during minimization.
    """
    if stage["type"] == "minimize":
        return 0
    duration_ps = stage.get("duration_ps") or 0
    return int(duration_ps * 1000 / dt_fs)


def _inject_equilibration_stages(stages: list[dict], dt_fs: float) -> list[dict]:
    """Splice high-temp NVT + high-pressure NPT stages after minimize.

    Uses SSOT defaults from contracts.policies.equilibration for durations.
    These stages are only injected for bulk chains when the experiment was
    submitted with equilibration_settings.enabled=True.
    """
    from contracts.policies.equilibration import DEFAULT_EQUILIBRATION_POLICY as EQ

    eq_stages = [
        {
            "stage_name": "high_temp_nvt",
            "type": "nvt",
            "duration_ps": EQ.high_temp_nvt_duration_ps,
            "is_override": False,
        },
        {
            "stage_name": "high_pressure_npt",
            "type": "npt",
            "duration_ps": EQ.high_pressure_npt_duration_ps,
            "is_override": False,
        },
    ]

    result: list[dict] = []
    for stage in stages:
        result.append(stage)
        if stage["type"] == "minimize":
            result.extend(eq_stages)
    return result


def _build_stage_list(
    tier: str,
    overrides: list | None,
    dt_fs: float,
    has_equilibration: bool,
    compiled_plan: dict | None = None,
) -> list[dict]:
    """Build the stage list with cumulative step boundaries.

    Args:
        tier: Chain key (e.g. "screening", "layer", "tensile_layer").
        overrides: User-specified StageDurationOverride objects (or None).
        dt_fs: Timestep in femtoseconds.
        has_equilibration: Whether equilibration stages were injected.

    Returns:
        List of stage dicts with name/type/steps/cumulative keys.
    """
    persisted_stages = _stages_from_compiled_plan(compiled_plan)
    if persisted_stages:
        return persisted_stages

    if overrides:
        from protocols.duration_adjuster import ProtocolChainAdjuster

        adjuster = ProtocolChainAdjuster()
        merged = adjuster.merge_with_defaults(tier, overrides)
    else:
        from contracts.policies.stabilization import DEFAULT_STABILIZATION_CHAIN

        chain = DEFAULT_STABILIZATION_CHAIN.get_chain(tier)
        merged = []
        for step in chain:
            duration_ps = None
            duration_steps = None
            if step.duration:
                dur_lower = step.duration.strip().lower()
                if "steps" in dur_lower:
                    duration_steps = int(dur_lower.replace("steps", "").strip())
                elif "ps" in dur_lower:
                    duration_ps = float(dur_lower.replace("ps", "").strip())
            merged.append(
                {
                    "stage_name": step.name,
                    "type": step.type,
                    "duration_ps": duration_ps,
                    "duration_steps": duration_steps,
                    "is_override": False,
                }
            )

    # Inject equilibration stages for bulk chains when enabled
    if has_equilibration:
        # Only inject for non-layer chains (layer chains already include these in SSOT)
        if tier not in ("layer", "tensile_layer", "tensile_layer_qs"):
            merged = _inject_equilibration_stages(merged, dt_fs)

    cumulative = 0
    stages: list[dict] = []
    for stage in merged:
        steps = _stage_steps(stage, dt_fs)
        cumulative += steps
        stages.append(
            {
                "name": stage["stage_name"],
                "type": stage["type"],
                "steps": steps,
                "cumulative": cumulative,
            }
        )
    return stages


def compute_total_steps_with_overrides(
    tier: str,
    overrides: list,
    dt_fs: float = 1.0,
    has_equilibration: bool = False,
    compiled_plan: dict | None = None,
) -> int:
    """Compute total expected steps for a chain.

    Args:
        tier: Chain key.
        overrides: User-specified StageDurationOverride objects.
        dt_fs: Timestep in femtoseconds.
        has_equilibration: Whether equilibration stages were injected.

    Returns:
        Total steps (minimize excluded from count).
    """
    stages = _build_stage_list(tier, overrides, dt_fs, has_equilibration, compiled_plan)
    return stages[-1]["cumulative"] if stages else 0


def _adjust_step_for_reset(
    raw_step: int,
    stage_marker: tuple[int, str],
    stages: list[dict],
) -> int:
    """Adjust raw LAMMPS step for reset_timestep within a stage.

    When a stage (e.g. tensile_pull) uses ``reset_timestep 0``, the raw step
    resets to 0.  This function converts it back to a cumulative step using
    the @@STAGE marker as an advisory signal.

    Conditions for adjustment (all must hold):
    1. marker_index is within valid range
    2. marker name matches stages[marker_index]["name"]
    3. raw_step < pre_cumulative (reset actually occurred)

    Args:
        raw_step: Current LAMMPS step (possibly reset).
        stage_marker: (0-based index, stage name) from @@STAGE marker.
        stages: Stage list from _build_stage_list().

    Returns:
        Adjusted cumulative step, or raw_step if conditions are not met.
    """
    marker_index, marker_name = stage_marker

    # Condition 1: valid range
    if marker_index < 0 or marker_index >= len(stages):
        return raw_step

    # Condition 2: name must match
    if stages[marker_index]["name"] != marker_name:
        return raw_step

    pre_cumulative = stages[marker_index - 1]["cumulative"] if marker_index > 0 else 0

    # Condition 3: reset actually occurred
    if raw_step >= pre_cumulative:
        return raw_step

    adjusted = max(0, pre_cumulative + raw_step)

    # Cap: don't exceed stage boundary
    if marker_index < len(stages) - 1:
        adjusted = min(adjusted, stages[marker_index]["cumulative"] - 1)
    else:
        adjusted = min(adjusted, stages[-1]["cumulative"])

    return adjusted


def get_stage_info_with_overrides(
    tier: str,
    current_step: int,
    overrides: list | None,
    dt_fs: float = 1.0,
    has_equilibration: bool = False,
    compiled_plan: dict | None = None,
    stage_marker: tuple[int, str] | None = None,
) -> dict:
    """Determine current stage from step counter.

    Args:
        tier: Chain key.
        current_step: Current LAMMPS timestep.
        overrides: User-specified StageDurationOverride objects (or None).
        dt_fs: Timestep in femtoseconds.
        has_equilibration: Whether equilibration stages were injected.

    Returns:
        Dict with current_stage, stage_type, stage_index, total_stages,
        stage_step, stage_total_steps, stage_percent.
    """
    stages = _build_stage_list(tier, overrides, dt_fs, has_equilibration, compiled_plan)

    if stage_marker is not None:
        current_step = _adjust_step_for_reset(current_step, stage_marker, stages)

    total_stages = len(stages)
    for i, stage in enumerate(stages):
        prev_cumulative = stages[i - 1]["cumulative"] if i > 0 else 0
        if current_step < stage["cumulative"]:
            stage_step = current_step - prev_cumulative
            stage_total = stage["steps"]
            return {
                "current_stage": stage["name"],
                "stage_type": stage["type"],
                "stage_index": i + 1,
                "total_stages": total_stages,
                "stage_step": stage_step,
                "stage_total_steps": stage_total,
                "stage_percent": (
                    round(stage_step / stage_total * 100, 1) if stage_total > 0 else 0
                ),
                "adjusted_step": current_step,
            }

    if stages:
        last = stages[-1]
        return {
            "current_stage": last["name"],
            "stage_type": last["type"],
            "stage_index": total_stages,
            "total_stages": total_stages,
            "stage_step": last["steps"],
            "stage_total_steps": last["steps"],
            "stage_percent": 100.0,
            "adjusted_step": current_step,
        }

    return {
        "current_stage": "unknown",
        "stage_type": "unknown",
        "stage_index": 1,
        "total_stages": 1,
        "stage_step": current_step,
        "stage_total_steps": 1000000,
        "stage_percent": 0.0,
        "adjusted_step": current_step,
    }


def format_elapsed_eta(
    current_step: int, total_steps: int, elapsed_seconds: float
) -> tuple[str, str]:
    """Format elapsed/ETA strings."""
    elapsed_str = f"{int(elapsed_seconds // 3600)}h {int((elapsed_seconds % 3600) // 60)}m"
    eta_str = "calculating..."

    if current_step > 0 and elapsed_seconds > 0:
        steps_per_second = current_step / elapsed_seconds
        remaining_steps = total_steps - current_step
        if steps_per_second > 0:
            eta_seconds = remaining_steps / steps_per_second
            eta_str = f"{int(eta_seconds // 3600)}h {int((eta_seconds % 3600) // 60)}m"

    return elapsed_str, eta_str
