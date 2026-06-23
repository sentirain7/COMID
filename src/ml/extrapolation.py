"""Runtime extrapolation policy helpers.

Classifies a prediction/design request into:
- in_domain
- combinatorial_generalization
- hard_extrapolation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

IN_DOMAIN = "in_domain"
COMBINATORIAL_GENERALIZATION = "combinatorial_generalization"
HARD_EXTRAPOLATION = "hard_extrapolation"


@dataclass(slots=True)
class ExtrapolationAssessment:
    """Structured extrapolation decision."""

    status: str = IN_DOMAIN
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _normalize_supported_set(raw: Any) -> set[str]:
    if not isinstance(raw, (list, tuple, set)):
        return set()
    return {str(item) for item in raw if item not in (None, "")}


def assess_prediction_context(
    *,
    capability_manifest: dict[str, Any] | None,
    temperature_k: float | None = None,
    layer_count: int | None = None,
    additive_type: str | None = None,
    binder_type: str | None = None,
    aging_state: str | None = None,
) -> ExtrapolationAssessment:
    """Classify runtime prediction context against champion capability metadata."""
    if not capability_manifest:
        return ExtrapolationAssessment(
            status=COMBINATORIAL_GENERALIZATION,
            warnings=["Capability manifest unavailable; treating request as exploratory."],
        )

    reasons: list[str] = []
    warnings: list[str] = []

    temp_range = capability_manifest.get("supported_temperature_range_k")
    if (
        isinstance(temp_range, (list, tuple))
        and len(temp_range) == 2
        and temperature_k is not None
        and (temperature_k < float(temp_range[0]) or temperature_k > float(temp_range[1]))
    ):
        reasons.append(
            f"temperature_k={temperature_k} outside supported range [{temp_range[0]}, {temp_range[1]}]"
        )

    if layer_count is not None:
        supported_layer_counts = {
            int(v)
            for v in _normalize_supported_set(capability_manifest.get("supported_layer_counts"))
            if str(v).isdigit()
        }
        if supported_layer_counts and layer_count not in supported_layer_counts:
            reasons.append(
                f"layer_count={layer_count} outside supported layer counts {sorted(supported_layer_counts)}"
            )

    for field_name, value, manifest_key in (
        ("additive_type", additive_type, "supported_additives"),
        ("binder_type", binder_type, "supported_binder_types"),
        ("aging_state", aging_state, "supported_aging_states"),
    ):
        if not value:
            continue
        supported = _normalize_supported_set(capability_manifest.get(manifest_key))
        if supported and str(value) not in supported:
            reasons.append(f"{field_name}={value} is not present in supported {manifest_key}")

    if reasons:
        return ExtrapolationAssessment(status=HARD_EXTRAPOLATION, reasons=reasons)

    if any(value is not None for value in (temperature_k, layer_count)) or any(
        value for value in (additive_type, binder_type, aging_state)
    ):
        warnings.append(
            "Request uses contextual variables; combination-level support is treated as exploratory unless explicitly covered."
        )
        return ExtrapolationAssessment(
            status=COMBINATORIAL_GENERALIZATION,
            warnings=warnings,
        )

    return ExtrapolationAssessment(status=IN_DOMAIN)
