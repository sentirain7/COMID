"""v00.99.93 — real ProcessPoolExecutor batch lifecycle regression.

The v00.99.90 phase_map IPC hung the batch teardown, leaving
_batch_progress["running"] latched indefinitely. All prior tests used
a synchronous ``_FakeExecutor`` so that hang was never exercised.

This test drives `run_parallel_batch` with an **actual**
``ProcessPoolExecutor`` (spawned subprocess workers, real OS-level
semantics) using a tiny batch of mol rows whose `mol_path` does not
exist. Workers hit the preflight ``if not mol_path.exists()`` branch
in ``_generate_one_worker`` and return an error payload in under a
second — enough to verify the full lifecycle without spending minutes
on real AM1-BCC runs.

Contract locked here:

* ``run_parallel_batch`` returns.
* ``get_batch_progress()["running"]`` transitions back to False
  (v00.99.93 slot release on teardown).
* The progress payload does NOT carry the v00.99.90 phase-split
  fields (``in_progress_baseline`` / ``in_progress_robust``) — the
  front-end ``hasPhaseSplit`` guard falls back to the single
  ``Running N`` label.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


@pytest.fixture(autouse=True)
def _reset_batch_state():
    """Ensure each test starts with a clean slot so test ordering is
    irrelevant."""
    from features.molecules import artifact_service

    artifact_service.release_batch_slot()
    yield
    artifact_service.release_batch_slot()


def _preflight_fail_rows(count: int) -> list[dict]:
    """Produce rows whose ``mol_path`` does not exist so the real
    worker short-circuits on preflight."""
    return [
        {
            "mol_id": f"MissingMol-{i}",
            "source_id": f"MissingMol-{i}",
            "mol_path": f"/nonexistent/does-not-exist-{i}.mol",
            "smiles": "C",
            "formal_charge": 0,
            "consumer_ids": [f"MissingMol-{i}"],
            "generation_profile": "baseline",
            "ff_assignment": {
                "route": "organic_curated_artifact",
                "status": "active",
                "source_id": f"MissingMol-{i}",
                "formal_charge": 0,
                "canonical_smiles": "C",
            },
            "artifact_type": "organic",
        }
        for i in range(count)
    ]


def test_real_pool_batch_returns_and_releases_slot():
    """Full lifecycle smoke test — real ProcessPoolExecutor workers."""
    from features.molecules import artifact_service

    rows = _preflight_fail_rows(2)

    start = time.monotonic()
    # max_workers=2 keeps the test fast and deterministic.
    result = artifact_service.run_parallel_batch(
        rows,
        max_workers=2,
        batch_kind="admin",
        generation_profile="baseline",
    )
    elapsed = time.monotonic() - start

    # 1. Function returned with a coherent summary.
    assert isinstance(result, dict)
    assert result["total"] == 2
    assert result["failed"] == 2
    assert result["success"] == 0

    # 2. Slot is released — no latch.
    progress = artifact_service.get_batch_progress()
    assert progress["running"] is False, (
        "release_batch_slot must fire after batch teardown; otherwise the "
        "next acquire_batch_slot will return False and all further batch "
        "submissions will 409"
    )

    # 3. v00.99.90 phase-split fields must NOT reappear — the rollback
    #    contract is that the front-end `hasPhaseSplit` guard falls back.
    assert "in_progress_baseline" not in progress
    assert "in_progress_robust" not in progress

    # 4. Batch returned in a reasonable time (preflight short-circuit
    #    should take well under a minute even on a loaded CI runner).
    assert elapsed < 60, f"preflight-only batch should be fast, took {elapsed:.1f}s"


def test_real_pool_batch_running_false_with_single_mol():
    """Single-mol variant catches the specific payload shape that
    latched in the observed incident (total=1, failed=1)."""
    from features.molecules import artifact_service

    rows = _preflight_fail_rows(1)

    result = artifact_service.run_parallel_batch(
        rows,
        max_workers=2,
        batch_kind="admin",
        generation_profile="baseline",
    )

    assert result["total"] == 1
    assert result["failed"] == 1

    progress = artifact_service.get_batch_progress()
    assert progress["running"] is False
    assert progress["completed"] == 0
    assert progress["failed"] == 1
    assert "in_progress_baseline" not in progress
    assert "in_progress_robust" not in progress
