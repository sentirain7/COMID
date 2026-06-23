"""Unit tests for v00.99.57 batch progress bucketed counters.

Verifies `_update_batch_progress` call sequence and final snapshot of the
module-level `_batch_progress` dict for:

  - baseline-only success (retried_succeeded stays 0)
  - baseline fail → sqm_robust recover (retried_succeeded bumps)
  - baseline fail → sqm_robust still fails (retried bumps, retried_succeeded 0)
  - in_progress decrement across a chunked ProcessPoolExecutor
  - cancel reports in_progress=0 on the skipped update
  - release_batch_slot clears new fields
  - conflict pre-fill surfaces `failed` on the initial _update_batch_progress

Strategy: run `run_parallel_batch` directly, but swap `ProcessPoolExecutor`
and `as_completed` for in-process fakes so `_generate_one_worker` (stubbed via
monkeypatch) runs synchronously in the test process.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from features.molecules import artifact_service as svc  # noqa: E402

# --- Fake executor plumbing -------------------------------------------------


class _FakeFuture:
    def __init__(self, result_dict: dict):
        self._result = result_dict

    def result(self, timeout=None):
        return self._result


class _FakeExecutor:
    """Synchronous stand-in for ProcessPoolExecutor.

    Accepts ``**kwargs`` so new ProcessPoolExecutor options introduced
    over time (e.g. ``initializer=`` added in v00.99.70) don't break the
    test harness.
    """

    last_kwargs: dict = {}

    def __init__(self, max_workers=None, **kwargs):
        self.max_workers = max_workers
        type(self).last_kwargs = dict(kwargs)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def submit(self, fn, *args, **kwargs):
        # Accept any positional/keyword arguments so callers adding
        # parameters (e.g. the v00.99.90 phase_map Manager proxy) don't
        # need per-signature updates here.
        return _FakeFuture(fn(*args, **kwargs))


def _fake_as_completed(futures, timeout=None):
    # Accept timeout to match the real concurrent.futures.as_completed
    # signature (run_parallel_batch passes timeout=timeout_per_mol).
    del timeout
    return list(futures)  # preserves submission order


# --- Fixtures ---------------------------------------------------------------


@pytest.fixture
def spy_updates(monkeypatch):
    original = svc._update_batch_progress
    calls: list[dict] = []

    def wrapped(**kwargs):
        calls.append(dict(kwargs))
        return original(**kwargs)

    monkeypatch.setattr(svc, "_update_batch_progress", wrapped)
    return calls


@pytest.fixture
def fake_executor(monkeypatch):
    monkeypatch.setattr("concurrent.futures.ProcessPoolExecutor", _FakeExecutor)
    monkeypatch.setattr("concurrent.futures.as_completed", _fake_as_completed)


@pytest.fixture(autouse=True)
def _reset_batch_slot():
    svc.release_batch_slot()
    yield
    svc.release_batch_slot()


# --- Helpers ---------------------------------------------------------------


def _mol(mol_id: str, *, source_id: str | None = None, mol_path: str = "p") -> dict:
    return {
        "mol_id": mol_id,
        "source_id": source_id or mol_id,
        "mol_path": mol_path,
        "route": "organic_curated_artifact",
        "structure_file": f"{mol_id}.mol",
    }


def _stub_success(mol_info):
    return {"mol_id": mol_info["mol_id"], "status": "completed"}


def _stub_retry_recovered(mol_info):
    return {
        "mol_id": mol_info["mol_id"],
        "status": "completed",
        "retried": True,
        "retry_reason": "sqm_timeout→sqm_robust",
    }


def _stub_retry_final_failed(mol_info):
    return {
        "mol_id": mol_info["mol_id"],
        "status": "error",
        "retried": True,
        "retry_reason": "sqm_timeout; robust also failed",
        "error": "sqm_nonconverged",
    }


# --- Tests ------------------------------------------------------------------


class TestBatchProgressCounters:
    def test_process_pool_uses_spawn_context_by_default(self, monkeypatch, fake_executor):
        monkeypatch.delenv("ASPHALT_ARTIFACT_POOL_START_METHOD", raising=False)
        monkeypatch.setattr(svc, "_generate_one_worker", _stub_success)

        svc.run_parallel_batch([_mol("M1")], max_workers=1, batch_kind="admin")

        ctx = _FakeExecutor.last_kwargs.get("mp_context")
        assert ctx is not None
        assert ctx.get_start_method() == "spawn"

    def test_process_pool_start_method_env_override(self, monkeypatch, fake_executor):
        monkeypatch.setenv("ASPHALT_ARTIFACT_POOL_START_METHOD", "fork")
        monkeypatch.setattr(svc, "_generate_one_worker", _stub_success)

        svc.run_parallel_batch([_mol("M1")], max_workers=1, batch_kind="admin")

        ctx = _FakeExecutor.last_kwargs.get("mp_context")
        assert ctx is not None
        assert ctx.get_start_method() == "fork"

    def test_baseline_only_success(self, monkeypatch, spy_updates, fake_executor):
        monkeypatch.setattr(svc, "_generate_one_worker", _stub_success)
        pending = [_mol(f"M{i}") for i in range(3)]

        result = svc.run_parallel_batch(pending, max_workers=2, batch_kind="admin")
        snap = svc.get_batch_progress()

        assert result["success"] == 3
        assert result["retried"] == 0
        assert result["retried_succeeded"] == 0
        assert snap["completed"] == 3
        assert snap["retried"] == 0
        assert snap["retried_succeeded"] == 0
        assert snap["in_progress"] == 0

    def test_retry_recovered_increments_retried_succeeded(
        self, monkeypatch, spy_updates, fake_executor
    ):
        monkeypatch.setattr(svc, "_generate_one_worker", _stub_retry_recovered)
        pending = [_mol("M1")]

        result = svc.run_parallel_batch(pending, max_workers=1, batch_kind="admin")

        assert result["success"] == 1
        assert result["retried"] == 1
        assert result["retried_succeeded"] == 1
        # The final _update_batch_progress call (last spy entry) reflects the
        # in-flight snapshot before release_batch_slot resets counters.
        last_update = spy_updates[-1]
        assert last_update.get("retried_succeeded") == 1
        assert last_update.get("retried") == 1
        assert last_update.get("completed") == 1

    def test_retry_final_failed_keeps_retried_succeeded_zero(
        self, monkeypatch, spy_updates, fake_executor
    ):
        monkeypatch.setattr(svc, "_generate_one_worker", _stub_retry_final_failed)
        pending = [_mol("M1")]

        result = svc.run_parallel_batch(pending, max_workers=1, batch_kind="admin")
        snap = svc.get_batch_progress()

        assert result["retried"] == 1
        assert result["retried_succeeded"] == 0
        assert result["failed"] == 1
        assert snap["retried_succeeded"] == 0
        assert snap["failed"] == 1

    def test_in_progress_decrements_to_zero_at_chunk_end(
        self, monkeypatch, spy_updates, fake_executor
    ):
        monkeypatch.setattr(svc, "_generate_one_worker", _stub_success)
        pending = [_mol(f"M{i}") for i in range(3)]

        svc.run_parallel_batch(pending, max_workers=2, batch_kind="admin")

        # Collect in_progress values reported on every update.
        in_progress_values = [c.get("in_progress") for c in spy_updates if "in_progress" in c]
        assert in_progress_values, "expected at least one in_progress report"
        # At least one chunk-start report > 0 (workers took the lock).
        assert any(v > 0 for v in in_progress_values)
        # Must eventually settle at 0 (last chunk emptied).
        assert in_progress_values[-1] == 0
        assert svc.get_batch_progress()["in_progress"] == 0

    def test_cancel_reports_in_progress_zero(self, monkeypatch, spy_updates, fake_executor):
        monkeypatch.setattr(svc, "_generate_one_worker", _stub_success)

        # Pre-acquire slot, flip cancel flag so the first chunk_start check
        # skips everything; we can then assert the skipped update.
        svc.acquire_batch_slot("admin", "baseline")
        with svc._batch_lock:
            svc._batch_progress["cancelled"] = True

        pending = [_mol(f"M{i}") for i in range(3)]
        result = svc.run_parallel_batch(
            pending,
            max_workers=2,
            batch_kind="admin",
            slot_already_acquired=True,
        )

        assert result["cancelled"] is True
        assert result["skipped"] == 3
        # The skipped update must include explicit in_progress=0.
        skipped_update = next(
            (c for c in spy_updates if "skipped" in c and c.get("skipped", 0) > 0),
            None,
        )
        assert skipped_update is not None
        assert skipped_update.get("in_progress") == 0

    def test_release_clears_new_fields(self):
        svc.acquire_batch_slot("admin", "baseline")
        with svc._batch_lock:
            svc._batch_progress["in_progress"] = 7
            svc._batch_progress["retried_succeeded"] = 3

        svc.release_batch_slot()
        snap = svc.get_batch_progress()

        assert snap["in_progress"] == 0
        assert snap["retried_succeeded"] == 0

    def test_conflict_prefill_surfaces_failed_on_initial_update(
        self, monkeypatch, spy_updates, fake_executor
    ):
        # Two rows share source_id="shared" with different mol_path → conflict.
        rows = [
            _mol("M1", source_id="shared", mol_path="a"),
            _mol("M2", source_id="shared", mol_path="b"),
        ]
        monkeypatch.setattr(svc, "_generate_one_worker", _stub_success)
        monkeypatch.setattr(svc, "_admin_status_store", lambda: MagicMock())

        svc.run_parallel_batch(rows, max_workers=1, batch_kind="admin")

        # First _update_batch_progress call (initialization) carries
        # failed=len(conflicts), so operators see conflicts on the first poll.
        init_call = spy_updates[0]
        assert init_call.get("failed", 0) >= 1
        assert init_call.get("retried_succeeded") == 0
        assert init_call.get("in_progress") == 0
