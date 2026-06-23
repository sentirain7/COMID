"""v00.99.91 — release_batch_slot invokes cleanup_stale_generation_locks.

Lock files are intentionally preserved on generation success (fcntl
inode-lock semantics). Without an explicit sweep they accumulate between
batches and the ``cleanup_stale_generation_locks`` helper only runs
inside ``source_generation_lock`` acquire, which skews towards "just
before starting more work". Calling it in ``release_batch_slot`` ensures
a sweep also runs at the natural "batch just finished" moment.

Contract lock:
* Every call to ``release_batch_slot`` triggers exactly one
  ``cleanup_stale_generation_locks`` call.
* The cleanup call happens **outside** ``_batch_lock`` so a slow sweep
  cannot block the slot reset from the caller's perspective.
* Cleanup failure (unexpected OS error) is swallowed — the slot is
  still released and the caller never sees the exception.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from features.molecules import artifact_service  # noqa: E402


def _prime_running_state() -> None:
    """Put _batch_progress in a 'batch in progress' shape so
    release_batch_slot has meaningful work to undo."""
    artifact_service._batch_progress.update(
        {
            "running": True,
            "batch_kind": "admin",
            "generation_profile": "baseline",
            "started_at": 1.0,
            "current_mol_id": "X",
            "in_progress": 2,
            "retried_succeeded": 0,
        }
    )


def test_release_batch_slot_triggers_stale_lock_sweep():
    _prime_running_state()
    with patch.object(artifact_service, "cleanup_stale_generation_locks") as sweep:
        artifact_service.release_batch_slot()
    sweep.assert_called_once()
    # Slot reset still happened (sweep runs after, doesn't block).
    assert artifact_service._batch_progress["running"] is False
    # v00.99.93: in_progress_baseline / in_progress_robust were removed when
    # the v00.99.90 phase_map IPC was rolled back. Release resets in_progress.
    assert artifact_service._batch_progress["in_progress"] == 0


def test_release_batch_slot_swallows_sweep_exception():
    _prime_running_state()

    def _blowup(*a, **kw):
        raise OSError("simulated filesystem glitch")

    with patch.object(artifact_service, "cleanup_stale_generation_locks", side_effect=_blowup):
        # Must NOT raise — cleanup failure cannot prevent slot release.
        artifact_service.release_batch_slot()

    assert artifact_service._batch_progress["running"] is False


def test_release_batch_slot_cleanup_runs_outside_batch_lock():
    """If cleanup raises while holding _batch_lock the slot reset is
    still visible in the final state. Tests that slot reset happens
    before sweep (sweep is the *last* step)."""

    _prime_running_state()

    observed_running: list[bool] = []

    def _observe(*a, **kw):
        # At the moment the sweep runs, the batch must already be released
        # (running=False). This is the invariant the production code must
        # maintain: reset state first, sweep after.
        observed_running.append(artifact_service._batch_progress["running"])

    with patch.object(artifact_service, "cleanup_stale_generation_locks", side_effect=_observe):
        artifact_service.release_batch_slot()

    assert observed_running == [False]
