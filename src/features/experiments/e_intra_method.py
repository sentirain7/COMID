"""Helpers for experiment-level E_intra/CED method provenance."""

from __future__ import annotations

from contracts.schema_enums import normalize_e_intra_method


def resolve_experiment_e_intra_method(exp) -> tuple[str | None, str | None, str | None]:
    """Resolve the canonical method tag + origin/resolution provenance.

    Precedence is chosen to match the value actually used for CED/E_intra-
    derived metrics:
    1. ``cohesive_energy_density`` metric metadata
    2. ``metadata_json["ced_provenance"]``
    3. ``metadata_json["e_intra_method"]``
    4. single-molecule input-file fallback for legacy imported rows
    """
    exp_meta = getattr(exp, "metadata_json", None) or {}
    origin = None
    if isinstance(exp_meta, dict):
        origin = exp_meta.get("e_intra_method_origin") or exp_meta.get("e_intra_method_source")

    exp_dict = getattr(exp, "__dict__", {}) or {}
    metrics = exp_dict.get("metrics") or []
    for metric in metrics:
        if getattr(metric, "metric_name", None) != "cohesive_energy_density":
            continue
        meta = getattr(metric, "metadata_json", None) or {}
        if isinstance(meta, dict):
            method = normalize_e_intra_method(meta.get("e_intra_method"))
            if method:
                return method, origin, "metric:cohesive_energy_density"

    if isinstance(exp_meta, dict):
        ced_meta = exp_meta.get("ced_provenance") or {}
        if isinstance(ced_meta, dict):
            method = normalize_e_intra_method(ced_meta.get("e_intra_method"))
            if method:
                return method, origin, "metadata:ced_provenance"

        method = normalize_e_intra_method(exp_meta.get("e_intra_method"))
        if method:
            return method, origin, "metadata:experiment"

    if getattr(exp, "study_type", None) == "single_molecule_vacuum":
        try:
            from protocols.e_intra_method_detect import detect_e_intra_method_from_input

            method = normalize_e_intra_method(
                detect_e_intra_method_from_input(getattr(exp, "input_file_path", None))
            )
            if method:
                return method, origin, "input_file"
        except Exception:
            pass

    return None, origin, None
