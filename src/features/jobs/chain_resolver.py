"""Chain key resolver for progress tracking.

Determines the correct stabilization chain key (e.g. "screening", "layer",
"tensile_layer") so that the progress tracker uses the same stage sequence
that was actually executed by the simulation.

Priority:
  1. metadata_json["chain_key"]  (persisted at submission time)
  2. Derived from ProtocolRequest  (Celery in-memory job)
  3. Fallback to run_tier          (legacy experiments without metadata)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from contracts.schemas import ProtocolRequest


def resolve_chain_key(
    *,
    protocol_request: ProtocolRequest | None = None,
    run_tier: str = "screening",
    metadata_json: dict[str, Any] | None = None,
) -> str:
    """Resolve the stabilization chain key for progress tracking.

    Args:
        protocol_request: In-memory protocol request (Celery job path).
        run_tier: Run tier string (always available as fallback).
        metadata_json: Persisted experiment metadata dict (DB path).

    Returns:
        Chain key string usable with DEFAULT_STABILIZATION_CHAIN.get_chain().
    """
    # Priority 1: explicit chain_key stored at submission time
    if metadata_json and isinstance(metadata_json, dict):
        compiled_plan = metadata_json.get("compiled_execution_plan")
        if isinstance(compiled_plan, dict):
            plan_key = compiled_plan.get("chain_key")
            if isinstance(plan_key, str) and plan_key:
                return plan_key
        stored = metadata_json.get("chain_key")
        if stored and isinstance(stored, str):
            return stored

    # Priority 2: derive from ProtocolRequest (mirrors protocol_chain.py:87-93)
    if protocol_request is not None:
        return derive_chain_key_from_request(protocol_request)

    # Priority 3: fallback to run_tier
    return run_tier


def derive_chain_key_from_request(request: ProtocolRequest) -> str:
    """Derive chain key from a ProtocolRequest.

    Mirrors the logic in ProtocolChainBuilder.build() (protocol_chain.py:87-93)
    to determine which stabilization chain is used for the simulation.

    Args:
        request: Protocol request object.

    Returns:
        Chain key string.
    """
    from contracts.schemas import StudyType

    tier_key = request.run_tier.value

    if request.study_type == StudyType.LAYER_BULKFF:
        tensile_spec = getattr(request, "tensile_spec", None)
        if tensile_spec is not None and tensile_spec.enabled:
            from contracts.schemas import TensileMode

            if getattr(tensile_spec, "mode", None) == TensileMode.QUASI_STATIC:
                tier_key = "tensile_layer_qs"
            else:
                tier_key = "tensile_layer"
        else:
            tier_key = "layer"

    return tier_key


def has_injected_equilibration(
    *,
    protocol_request: ProtocolRequest | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> bool:
    """Check whether equilibration stages were injected.

    Args:
        protocol_request: In-memory protocol request (Celery job path).
        metadata_json: Persisted experiment metadata dict (DB path).

    Returns:
        True if high-temperature/high-pressure equilibration was injected.
    """
    # Priority 1: explicit flag in metadata
    if metadata_json and isinstance(metadata_json, dict):
        compiled_plan = metadata_json.get("compiled_execution_plan")
        if isinstance(compiled_plan, dict):
            plan_stages = compiled_plan.get("stages") or []
            if any(
                isinstance(stage, dict)
                and stage.get("stage_key") in {"high_temp_nvt", "high_pressure_npt"}
                for stage in plan_stages
            ):
                return True
        flag = metadata_json.get("has_equilibration")
        if isinstance(flag, bool):
            return flag

    # Priority 2: derive from ProtocolRequest
    if protocol_request is not None:
        eq = getattr(protocol_request, "equilibration_settings", None)
        if eq is not None and getattr(eq, "enabled", False):
            return True

    return False
