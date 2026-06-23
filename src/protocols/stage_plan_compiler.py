"""Compiler for canonical execution plans used by submit/progress flows."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from contracts.execution_plan import CompiledExecutionPlan, CompiledStage
from contracts.schemas import ProtocolRequest, StudyType
from protocols.duration_adjuster import ProtocolChainAdjuster, StageDurationOverride
from protocols.protocol_chain import ProtocolChainBuilder
from protocols.stage_catalog import get_stage_metadata


def resolve_chain_key_from_request(
    request: ProtocolRequest,
    chain_key_override: str | None = None,
) -> str:
    """Resolve the canonical chain key used to execute the request.

    Args:
        request: Protocol request describing tier/study type.
        chain_key_override: Explicit chain key to use instead of deriving from request.

    Returns:
        Canonical chain key used by protocol execution and progress tracking.
    """
    if chain_key_override:
        return chain_key_override

    tier_key = request.run_tier.value
    if request.study_type == StudyType.LAYER_BULKFF:
        tensile_spec = getattr(request, "tensile_spec", None)
        if tensile_spec is not None and tensile_spec.enabled:
            from contracts.schemas import TensileMode

            if getattr(tensile_spec, "mode", None) == TensileMode.QUASI_STATIC:
                return "tensile_layer_qs"
            return "tensile_layer"
        return "layer"
    return tier_key


def _parse_duration(duration: str | None) -> tuple[float | None, int | None]:
    """Parse a duration string into ps/steps components.

    Args:
        duration: Duration string such as ``"300 ps"`` or ``"1000 steps"``.

    Returns:
        Tuple of ``(duration_ps, duration_steps)`` with the non-applicable entry set to ``None``.
    """
    if not duration:
        return None, None

    dur_lower = duration.strip().lower()
    if "steps" in dur_lower:
        return None, int(dur_lower.replace("steps", "").strip())
    if "ps" in dur_lower:
        return float(dur_lower.replace("ps", "").strip()), None
    return None, None


class StagePlanCompiler:
    """Build a stable execution plan from the exact protocol inputs."""

    def __init__(self) -> None:
        self.chain_builder = ProtocolChainBuilder()
        self.adjuster = ProtocolChainAdjuster()

    def compile(
        self,
        request: ProtocolRequest,
        overrides: list[StageDurationOverride] | None = None,
        *,
        chain_key_override: str | None = None,
        dt_fs: float = 1.0,
    ) -> CompiledExecutionPlan:
        """Compile a canonical execution plan for preview/progress persistence.

        Args:
            request: Fully resolved protocol request used to build the real chain.
            overrides: Optional validated duration overrides for non-equilibration stages.
            chain_key_override: Optional explicit chain key for non-standard workflows.
            dt_fs: Timestep used to convert ps durations to expected steps.

        Returns:
            Immutable execution plan describing resolved stage order and boundaries.
        """
        chain = self.chain_builder.build(request)
        if overrides:
            chain = self.adjuster.apply_overrides(chain, overrides)

        cumulative_steps = 0
        total_duration_ps = 0.0
        compiled_stages: list[CompiledStage] = []

        for step in chain.steps:
            duration_ps, duration_steps = _parse_duration(step.duration)
            expected_steps = 0
            if step.step_type != "minimize" and duration_ps is not None:
                expected_steps = int(duration_ps * 1000 / dt_fs)
                total_duration_ps += duration_ps

            cumulative_steps += expected_steps
            metadata = get_stage_metadata(step.name)
            parameters = dict(step.extra_params or {})
            parameters.setdefault("temperature_K", step.temperature_K)
            if step.ensemble == "npt":
                parameters.setdefault("pressure_atm", step.pressure_atm)

            compiled_stages.append(
                CompiledStage(
                    stage_key=step.name,
                    type=step.step_type,
                    duration_ps=duration_ps,
                    duration_steps=duration_steps,
                    expected_steps=expected_steps,
                    cumulative_steps=cumulative_steps,
                    parameters=parameters,
                    display_name=metadata.get("display_name"),
                    short_name=metadata.get("short_name"),
                    color=metadata.get("color"),
                )
            )

        chain_key = resolve_chain_key_from_request(request, chain_key_override)
        payload = {
            "chain_key": chain_key,
            "base_tier": request.run_tier.value,
            "stages": [stage.model_dump() for stage in compiled_stages],
            "total_steps": cumulative_steps,
            "total_duration_ps": total_duration_ps,
            "dt_fs": dt_fs,
        }
        plan_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[
            :16
        ]

        return CompiledExecutionPlan(
            chain_key=chain_key,
            base_tier=request.run_tier.value,
            stages=compiled_stages,
            total_steps=cumulative_steps,
            total_duration_ps=total_duration_ps,
            dt_fs=dt_fs,
            compiled_at=datetime.now(UTC).isoformat(),
            plan_hash=plan_hash,
        )


def build_stage_plan_metadata(
    *,
    protocol_request: ProtocolRequest,
    overrides: list[StageDurationOverride] | None = None,
    chain_key_override: str | None = None,
    canonical_stage_requests: list[dict] | None = None,
    base_metadata: dict | None = None,
) -> dict:
    """Attach canonical plan metadata to experiment submission payloads.

    Args:
        protocol_request: Request used to build the actual protocol chain.
        overrides: Optional validated duration overrides.
        chain_key_override: Explicit chain key for workflows such as layered/tensile.
        canonical_stage_requests: Canonical request payload persisted for auditing/debugging.
        base_metadata: Existing metadata to merge into the returned payload.

    Returns:
        Metadata dictionary containing chain identifiers and compiled execution plan.
    """
    compiler = StagePlanCompiler()
    plan = compiler.compile(
        protocol_request,
        overrides,
        chain_key_override=chain_key_override,
    )
    metadata = dict(base_metadata or {})
    metadata["chain_key"] = plan.chain_key
    metadata["has_equilibration"] = any(
        stage.stage_key in {"high_temp_nvt", "high_pressure_npt"} for stage in plan.stages
    )
    metadata["compiled_execution_plan"] = plan.model_dump()
    if canonical_stage_requests is not None:
        metadata["stage_requests"] = canonical_stage_requests
    return metadata
