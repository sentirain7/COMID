"""Cumulative pipeline elapsed-time calculator for the dashboard.

Uses metadata timestamps written by ``orchestrator.pipeline`` plus the
existing ``ExperimentModel.lammps_start_time`` / ``wall_time_seconds``
columns. Pure function: no DB access, no side effects.

Design rule: queue / pending wait is **excluded**. Only execution time
(build + run) is accumulated. When ``dashboard_build_started_at`` is
absent (legacy rows or freshly re-queued retries) the function returns
``None`` so the caller can fall back to the pre-existing display.
"""

from __future__ import annotations

from datetime import UTC, datetime

_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "timeout"})
# Intentionally excludes "ready": ready is reached only AFTER build completes
# (see orchestrator.task_maintenance / task_runners) so the ticker should
# freeze at build_duration rather than drop to —.
_PRE_EXECUTION_STATUSES = frozenset({"pending", "queued"})


def _parse_iso(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def compute_pipeline_elapsed_seconds(
    *,
    status: str | None,
    metadata_json: dict | None,
    lammps_start_time: datetime | None,
    wall_time_seconds: float | None,
    completed_at: datetime | None = None,
    updated_at: datetime | None = None,
    now: datetime | None = None,
) -> float | None:
    """Return cumulative execution seconds across build + run stages.

    Stages considered:
      * ``building``: ``now - build_started_at``
      * ``ready`` / analyzing (build done, LAMMPS not yet started):
        freeze at ``build_completed_at - build_started_at``
      * ``running``: ``build_duration + (now - lammps_start_time)``
      * terminal (``completed|failed|cancelled|timeout``):
        ``build_duration + (wall_time_seconds or 0)`` when build reached
        ``build_complete``. If build was interrupted (no
        ``dashboard_build_completed_at``), freeze at ``completed_at`` or
        ``updated_at`` minus ``build_started`` so the ticker stops for
        cancel/failure mid-build.

    Pre-execution states (``pending|queued|ready``) return ``None`` —
    retries reuse the row and we do not surface the previous attempt's
    freeze value while the pipeline has not yet re-entered build. New
    ``dashboard_build_started_at`` is written inside pipeline's
    ``composition_validation`` entry (monotonic reset).
    """
    meta = metadata_json or {}
    build_started = _as_aware(_parse_iso(meta.get("dashboard_build_started_at")))
    if build_started is None:
        return None

    status_lc = (status or "").lower()

    # Pre-execution: do not report elapsed for queued/pending. Prevents
    # stale freeze value from surviving a retry transition.
    if status_lc in _PRE_EXECUTION_STATUSES:
        return None

    build_completed = _as_aware(_parse_iso(meta.get("dashboard_build_completed_at")))
    lammps_started = _as_aware(lammps_start_time)
    now_utc = now or datetime.now(UTC)

    if status_lc in _TERMINAL_STATUSES:
        if build_completed is not None:
            build_duration = max((build_completed - build_started).total_seconds(), 0.0)
            return max(build_duration + (wall_time_seconds or 0.0), 0.0)
        freeze_at = _as_aware(completed_at) or _as_aware(updated_at)
        if freeze_at is not None:
            return max((freeze_at - build_started).total_seconds(), 0.0)
        # No terminal timestamp recorded — cap growth at "now" until the
        # DB row is refetched with a completed timestamp.
        return max((now_utc - build_started).total_seconds(), 0.0)

    if status_lc == "building" or build_completed is None:
        return max((now_utc - build_started).total_seconds(), 0.0)

    build_duration = max((build_completed - build_started).total_seconds(), 0.0)

    if status_lc == "running" and lammps_started is not None:
        return max(build_duration + (now_utc - lammps_started).total_seconds(), 0.0)

    # Any other intermediate status with build_completed set: freeze.
    return build_duration
