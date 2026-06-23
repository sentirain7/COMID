"""Shared helper for storing E_intra (PE_total) from metric results.

Used by both the pipeline (orchestrator.pipeline) and scan_database import
to avoid duplicating the PE → EIntraModel storage logic.
"""

from __future__ import annotations

from common.logging import get_logger
from contracts.policies.forcefield import get_ff_display_label, get_ff_version

logger = get_logger("features.common.e_intra_helper")


def store_e_intra_from_metrics(
    mol_id: str,
    metrics: list,
    ff_type: str,
    temperature_k: float,
    exp_id: str,
    session=None,
    n_samples: int | None = None,
    averaging_window_ps: float | None = None,
    method: str = "single_molecule_vacuum",
) -> bool:
    """Extract potential_energy from metrics and store as E_intra.

    Args:
        mol_id: Molecule identifier.
        metrics: List of MetricResult (or objects with .metric_name / .value).
        ff_type: Force field type key (e.g. ``"bulk_ff_gaff2"``).
        temperature_k: Temperature in Kelvin.
        exp_id: Source experiment ID.
        session: If provided, use this DB session (flush only, caller commits).
                 If None, open a new session_scope and commit.
        n_samples: Number of samples averaged (optional metadata).
        averaging_window_ps: Averaging window in ps (optional metadata).
        method: E_intra calculation method tag.  Recognised values include
            ``"single_molecule_vacuum"`` (Method 1, legacy 12 Å cutoff baseline),
            ``"single_molecule_vacuum_adaptive_cutoff"`` (Method 1a, cutoff =
            max(50 Å, 2 × molecular_extent)), and ``"single_molecule_periodic"``
            (Method 2, future).  Stored on ``EIntraKey.method``.

    Returns:
        True if E_intra was stored, False if potential_energy not found.
    """
    # Find potential_energy metric
    pe_value = None
    for metric in metrics:
        name = getattr(metric, "metric_name", None)
        if name == "potential_energy" and getattr(metric, "value", None) is not None:
            pe_value = metric.value
            # Extract averaging metadata if available
            summary = getattr(metric, "array_summary", None)
            if summary and isinstance(summary, dict):
                if n_samples is None:
                    n_samples = summary.get("n_samples")
                if averaging_window_ps is None:
                    averaging_window_ps = summary.get("window_ps")
            break

    if pe_value is None:
        logger.warning(
            "No potential_energy metric for E_intra storage (exp=%s, mol=%s)",
            exp_id,
            mol_id,
        )
        return False

    from contracts.schemas import EIntraKey, EIntraValue
    from database.repositories.e_intra_repo import EIntraRepository

    ff_name = get_ff_display_label(ff_type)
    ff_version = get_ff_version(ff_type)

    key = EIntraKey(
        mol_id=mol_id,
        ff_name=ff_name,
        ff_version=ff_version,
        temperature_K=temperature_k,
        method=method,
    )
    value = EIntraValue(
        e_intra=pe_value,
        temperature_K=temperature_k,
        source_exp_id=exp_id,
        averaging_window_ps=averaging_window_ps,
        n_samples=n_samples,
    )

    if session is not None:
        repo = EIntraRepository(session)
        repo.set(key, value)
    else:
        from database.connection import session_scope

        with session_scope() as s:
            repo = EIntraRepository(s)
            repo.set(key, value)
            s.commit()

    logger.info(
        "Stored E_intra for %s @ %.0fK: %.2f kcal/mol (exp=%s)",
        mol_id,
        temperature_k,
        pe_value,
        exp_id,
    )

    # Write-through to the git-tracked per-molecule sidecar so the value is
    # shareable without a manual export step (DB = cache, sidecar = source of
    # truth).  Best-effort: a sidecar failure must never break the DB store.
    try:
        from features.common.e_intra_sidecar import upsert_entry

        upsert_entry(
            mol_id=mol_id,
            ff_name=ff_name,
            ff_version=ff_version,
            method=method,
            temperature_K=temperature_k,
            e_intra=pe_value,
            n_samples=n_samples,
            averaging_window_ps=averaging_window_ps,
        )
    except Exception:  # noqa: BLE001 - sidecar write must not break DB store
        logger.exception("E_intra sidecar write-through failed (mol=%s, T=%.0fK)", mol_id, temperature_k)

    return True
