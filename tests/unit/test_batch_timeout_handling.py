"""v00.99.73 — run_parallel_batch as_completed TimeoutError handling.

Before this fix, `as_completed(future_to_mol, timeout=timeout_per_mol)` had
no try/except wrapper. A worker stuck longer than the per-mol timeout would
raise TimeoutError mid-iteration, abort the while-loop, and leave the batch
in an incoherent state: partial results in ``results["details"]`` plus an
uncaught exception to the caller. Meanwhile the stuck worker kept running
with its subprocess pipeline unwound only by the lower-level
_run_subprocess_with_group_kill timeout.

The fix wraps as_completed in try/except TimeoutError, marks all in-flight
molecules as "timeout", cancels pending futures, and breaks the loop with a
coherent result payload.
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


class _NeverCompletesExecutor:
    """Stand-in for ProcessPoolExecutor whose submitted futures never
    resolve — lets us exercise the as_completed timeout branch without
    spinning up real worker processes."""

    def __init__(self, *args, **kwargs):
        self.submitted: list[Future] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        for fut in self.submitted:
            fut.cancel()

    def submit(self, fn, *args, **kwargs):
        fut: Future = Future()
        fut.set_running_or_notify_cancel()  # mark running so cancel() == False
        self.submitted.append(fut)
        return fut


def _run_with_timeout_harness(timeout_per_mol: float, mol_count: int = 2):
    from features.molecules import artifact_service

    mols = [
        {
            "mol_id": f"stuck-mol-{i}",
            "source_id": f"stuck-mol-{i}",
            "mol_path": Path("/tmp/nonexistent.mol"),
            "ff_assignment": {
                "route": "organic_curated_artifact",
                "source_id": f"stuck-mol-{i}",
            },
        }
        for i in range(mol_count)
    ]

    mock_store = MagicMock()
    mock_store.record_failure = MagicMock()

    with (
        patch(
            "concurrent.futures.ProcessPoolExecutor",
            _NeverCompletesExecutor,
        ),
        patch.object(
            artifact_service,
            "acquire_batch_slot",
            return_value=True,
        ),
        patch.object(artifact_service, "release_batch_slot"),
        patch.object(artifact_service, "_is_batch_cancelled", return_value=False),
        patch.object(artifact_service, "_update_batch_progress"),
        patch.object(
            artifact_service,
            "dedupe_by_source_id",
            side_effect=lambda xs: (xs, []),
        ),
        patch.object(artifact_service, "_low_priority_initializer", lambda: None),
        patch.object(
            artifact_service,
            "_admin_status_store",
            return_value=mock_store,
        ),
    ):
        from features.molecules.artifact_service import run_parallel_batch

        start = time.monotonic()
        results = run_parallel_batch(
            mols,
            max_workers=mol_count,  # one slot per mol so all get submitted
            timeout_per_mol=timeout_per_mol,
        )
        elapsed = time.monotonic() - start

    return results, elapsed


def test_batch_timeout_marks_stuck_mols_and_exits_cleanly():
    """as_completed TimeoutError is caught, stuck mols recorded as timeout
    errors, function returns a coherent dict with no exception propagated."""

    results, elapsed = _run_with_timeout_harness(timeout_per_mol=1, mol_count=2)

    assert isinstance(results, dict)
    assert "details" in results
    # Both stuck mols recorded as timeout errors.
    assert results["failed"] == 2
    assert results["cancelled"] is True
    for detail in results["details"]:
        assert detail["status"] == "error"
        assert "Batch timeout" in detail["error"]
    # Must exit promptly — not block on stuck workers beyond the timeout.
    assert elapsed < 5, f"batch should exit promptly on timeout, took {elapsed:.1f}s"


def test_batch_timeout_records_every_in_flight_mol():
    """Every in-flight mol must appear in details so the admin progress
    dashboard never shows a phantom in-progress slot after the batch
    function returned."""

    results, _ = _run_with_timeout_harness(timeout_per_mol=1, mol_count=3)

    recorded_ids = {d["mol_id"] for d in results["details"]}
    assert "stuck-mol-0" in recorded_ids
    assert "stuck-mol-1" in recorded_ids
    assert "stuck-mol-2" in recorded_ids
    assert results["failed"] == 3
