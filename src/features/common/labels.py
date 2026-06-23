"""Shared experiment label helpers for UI and analytics."""

from __future__ import annotations

from common.pathing import AGING_ABBREV, BINDER_ABBREV, BINDER_ABBREV_REVERSE, parse_exp_id


def _normalize_additive_label(raw: object) -> str:
    value = str(raw or "").strip()
    if not value or value.lower() in {"none", "__none__", "null"}:
        return "None"
    return value


def resolve_experiment_catalog_labels(exp) -> dict[str, str]:
    """Resolve binder/size/aging/additive labels for UI and analytics from SSOT fields.

    Args:
        exp: Experiment model or any object with metadata_json, exp_id,
             additive_mol_id, additive_type attributes.

    Returns:
        Dict with keys: binder_type, binder_code, structure_size,
        aging_state, aging_code, additive_label.
    """
    metadata = dict(getattr(exp, "metadata_json", None) or {})
    parsed = parse_exp_id(str(getattr(exp, "exp_id", "") or ""))

    binder_full = str(metadata.get("binder_type") or "").strip()
    binder_code = ""
    parsed_binder = str(parsed.get("binder_type") or "").strip()
    if binder_full:
        binder_code = BINDER_ABBREV.get(binder_full, binder_full)
    elif parsed_binder:
        binder_code = parsed_binder
        binder_full = BINDER_ABBREV_REVERSE.get(parsed_binder, parsed_binder)
    else:
        binder_full = "custom"
        binder_code = BINDER_ABBREV.get(binder_full, binder_full)

    structure_size = str(
        metadata.get("structure_size") or parsed.get("structure_size") or ""
    ).strip()
    if not structure_size:
        structure_size = "X1"

    aging_state = str(metadata.get("aging_state") or parsed.get("aging_state") or "").strip()
    if not aging_state:
        aging_state = "non_aging"
    aging_code = AGING_ABBREV.get(aging_state, aging_state)

    additive_label = _normalize_additive_label(
        getattr(exp, "additive_mol_id", None)
        or getattr(exp, "additive_type", None)
        or metadata.get("additive_mol_id")
        or metadata.get("additive_type")
        or parsed.get("additive")
    )

    return {
        "binder_type": binder_full,
        "binder_code": binder_code,
        "structure_size": structure_size,
        "aging_state": aging_state,
        "aging_code": aging_code,
        "additive_label": additive_label,
    }


def build_experiment_short_label(exp) -> str:
    """Build short display label like 'A1 298K None' from experiment model.

    Args:
        exp: Experiment model or any object with the fields used by
             resolve_experiment_catalog_labels.

    Returns:
        Short string label for chart legends.
    """
    labels = resolve_experiment_catalog_labels(exp)
    temp = getattr(exp, "temperature_K", None) or getattr(exp, "temperature_k", None)
    temp_str = f"{int(temp)}K" if temp else ""
    return f"{labels['binder_code']} {temp_str} {labels['additive_label']}".strip()
