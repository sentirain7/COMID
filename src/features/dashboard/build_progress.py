"""Pure helpers that translate builder events into a monotonic percent.

Monotonic enforcement and attempt reset live in the caller (pipeline.py
metadata writer). This module stays side-effect free so unit tests can
drive it without any DB or clock.
"""

from __future__ import annotations

import re

from contracts.policies.build_progress import (
    DEFAULT_BUILD_PROGRESS_POLICY,
    BuildProgressPolicy,
)

_MOL_PREFIX_RE = re.compile(r"\[(\d+)/(\d+)\s")


def _parse_mol_prefix(label: str | None, default_total: int) -> tuple[int, int]:
    """Extract ``(i, N)`` from a ``[i/N mol_id]``-prefixed label."""
    if not label:
        return 1, max(default_total, 1)
    match = _MOL_PREFIX_RE.match(label)
    if not match:
        return 1, max(default_total, 1)
    try:
        i = int(match.group(1))
        total = int(match.group(2))
    except (TypeError, ValueError):
        return 1, max(default_total, 1)
    if total <= 0 or i <= 0:
        return 1, max(default_total, 1)
    return i, total


def compute_build_percent(
    *,
    status: str,
    label: str | None,
    policy: BuildProgressPolicy = DEFAULT_BUILD_PROGRESS_POLICY,
) -> float | None:
    """Return target percent for a builder event, or ``None`` if unknown.

    Args:
        status: Raw builder status string (e.g., ``"packing_molecules"``,
            ``"artifact_parmchk2"``) or a mapped ``phase`` name.
        label: User-facing label. Artifact sub-steps expose an ``[i/N ...]``
            prefix when dispatched from the topology_assembly mol loop.
        policy: Injectable policy; defaults to ``DEFAULT_BUILD_PROGRESS_POLICY``.

    Returns:
        Non-negative percent target in ``[0, 100]``. ``None`` when ``status``
        is not recognized — the caller keeps the existing percent unchanged.
    """
    if status in policy.artifact_order:
        start, end = policy.artifact_range
        i, total = _parse_mol_prefix(label, policy.default_mol_count)
        idx_in_order = policy.artifact_order.index(status)
        completed_substeps = (i - 1) * len(policy.artifact_order) + (idx_in_order + 1)
        total_substeps = total * len(policy.artifact_order)
        if total_substeps <= 0:
            return start
        fraction = min(max(completed_substeps / total_substeps, 0.0), 1.0)
        return start + fraction * (end - start)

    weight = policy.phase_weights.get(status)
    if weight is not None:
        return float(weight)
    return None
