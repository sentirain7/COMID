"""Canonical ordering helpers for analysis endpoints (SSOT).

All analysis sort rules are defined here. Backend endpoints and frontend
canonicalOrdering.js must agree with these orderings.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Canonical ordering maps
# ---------------------------------------------------------------------------

AGING_ORDER: dict[str, int] = {
    "non_aging": 0,
    "short_aging": 1,
    "long_aging": 2,
}

# Must match _LAYER_TYPE_MAP ordering in layered_structures/layered_analysis.py
LAYER_TYPE_ORDER: dict[str, int] = {
    "interface": 0,
    "water-interface": 1,
    "3-layer": 2,
    "aged-fresh": 3,
    "water-aged-fresh": 4,
    "binder-binder": 5,
}

BINDER_ORDER: dict[str, int] = {
    "A1": 0,
    "K1": 1,
    "M1": 2,
    "C": 3,
}

SIZE_ORDER: dict[str, int] = {
    "X1": 0,
    "X2": 1,
    "X3": 2,
    "custom": 3,
}

_NONE_SENTINELS = {"none", "None", "", None}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def canonical_value_key(dimension: str, value: Any) -> tuple[int, str]:
    """Return a sort key ``(priority, label)`` for *value* in *dimension*.

    Unknown dimensions fall back to ``(99, str(value))``.
    """
    label = str(value) if value is not None else ""
    dim = dimension.lower().replace("-", "_")

    if dim in ("aging", "aging_state"):
        return (AGING_ORDER.get(label, 99), label)

    if dim in ("layer_type",):
        return (LAYER_TYPE_ORDER.get(label, 99), label)

    if dim in ("binder", "binder_type"):
        return (BINDER_ORDER.get(label, 99), label)

    if dim in ("size", "structure_size"):
        return (SIZE_ORDER.get(label, 99), label)

    if dim in ("additive", "additive_type"):
        return (0 if value in _NONE_SENTINELS else 1, label.lower())

    if dim in ("temperature_k", "temperature"):
        try:
            return (0, f"{float(value):012.4f}")
        except (ValueError, TypeError):
            return (99, label)

    if dim in ("additive_wt",):
        try:
            return (0, f"{float(value):012.6f}")
        except (ValueError, TypeError):
            return (99, label)

    # Fallback: alphabetical
    return (99, label)


def stable_sort_records(
    records: list[dict[str, Any]],
    keys: list[str],
    *,
    exp_id_key: str = "exp_id",
) -> list[dict[str, Any]]:
    """Sort *records* by *keys* with deterministic tie-breaking on *exp_id_key*.

    Each key in *keys* is resolved via :func:`canonical_value_key`.
    The final tie-breaker is always ``exp_id`` ascending.
    """

    def _sort_tuple(record: dict[str, Any]) -> tuple:
        parts: list[tuple[int, str]] = []
        for k in keys:
            parts.append(canonical_value_key(k, record.get(k)))
        # Tie-breaker
        parts.append((0, str(record.get(exp_id_key, ""))))
        return tuple(parts)

    return sorted(records, key=_sort_tuple)


def group_sort_key(group_by: str, label: str) -> tuple[int, str]:
    """Drop-in replacement for ``analysis/service._group_sort_key``.

    Uses canonical ordering maps so all endpoints share the same rule.
    """
    return canonical_value_key(group_by, label)
