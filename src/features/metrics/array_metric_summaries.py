"""Pure extractors for array metric summary statistics.

These compute summary scalars from actual array metric data payloads
(NOT from metadata_json summaries, which may lack per-element values).

These are analysis/export artifacts only — NOT ML input features.
Using same-experiment outputs as prediction inputs causes target leakage.
"""

from __future__ import annotations


def summarize_cross_cut_profile(data: dict[str, list]) -> dict[str, float]:
    """Extract summary statistics from cross_cut_interaction_profile array data.

    Args:
        data: Array payload with columns "cut_index" and "cross_cut_mJ_m2".

    Returns:
        Summary dict with weakest/strongest/mean cut values and count.
    """
    values = data.get("cross_cut_mJ_m2", [])
    if not values:
        return {
            "weakest_cut_mJ_m2": 0.0,
            "strongest_cut_mJ_m2": 0.0,
            "mean_cut_mJ_m2": 0.0,
            "n_cuts": 0,
        }
    return {
        "weakest_cut_mJ_m2": float(min(values)),
        "strongest_cut_mJ_m2": float(max(values)),
        "mean_cut_mJ_m2": float(sum(values) / len(values)),
        "n_cuts": len(values),
    }


def summarize_layer_matrix(data: dict[str, list]) -> dict[str, float]:
    """Extract summary statistics from e_inter_layer_matrix array data.

    Args:
        data: Array payload with columns "pair_label" and "e_inter".

    Returns:
        Summary dict with total/min/max interaction and pair count.
    """
    values = data.get("e_inter", [])
    if not values:
        return {
            "layer_pair_count": 0,
            "layer_e_inter_total": 0.0,
            "layer_e_inter_min": 0.0,
            "layer_e_inter_max": 0.0,
        }
    return {
        "layer_pair_count": len(values),
        "layer_e_inter_total": float(sum(values)),
        "layer_e_inter_min": float(min(values)),
        "layer_e_inter_max": float(max(values)),
    }
