"""Regression tests for the GPU-allocation duplicate-protection index (P0-A).

The partial unique index ``uq_experiments_active_gpu_alloc`` enforces one active
job per GPU. That is correct for single-job mode (``slots == 1``) but is
incompatible with multi-job co-location (``slots > 1``, N=6), where it raised
``IntegrityError`` on every 2nd co-located job. ``connection.
_ensure_deferred_gpu_columns_and_indexes`` now creates the index only when
``slots == 1`` and drops it when ``slots > 1``.

The default in-memory test fixture never invokes the ensure-function, so these
tests wire it explicitly against a temp file DB and monkeypatch the slot policy.
"""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

import database.connection as conn_mod
from contracts.policies import budget as budget_mod
from database.models.base import Base

INDEX = "uq_experiments_active_gpu_alloc"


@pytest.fixture
def file_engine(tmp_path, monkeypatch):
    """Temp file-backed SQLite engine wired in as connection._engine."""
    engine = create_engine(f"sqlite:///{tmp_path / 'idx_test.db'}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(conn_mod, "_engine", engine)
    yield engine
    engine.dispose()


def _index_exists(engine) -> bool:
    with engine.connect() as c:
        row = c.execute(
            text("SELECT name FROM sqlite_master WHERE type='index' AND name=:n"),
            {"n": INDEX},
        ).fetchone()
    return row is not None


def _set_slots(monkeypatch, n: int) -> None:
    monkeypatch.setattr(
        budget_mod.DEFAULT_JOB_BUDGETING_POLICY, "max_concurrent_jobs_per_gpu", n
    )


def _insert(engine, exp_id: str, gpu_id: int, status: str = "running") -> None:
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO experiments "
                "(exp_id, run_tier, ff_type, study_type, status, "
                " comp_asphaltene_wt, comp_resin_wt, comp_aromatic_wt, comp_saturate_wt, "
                " attempt_no, gpu_id_allocated, created_at, updated_at) "
                "VALUES (:e, 'screening', 'bulk_ff', 'BULK', :s, "
                " 15, 35, 35, 15, 1, :g, datetime('now'), datetime('now'))"
            ),
            {"e": exp_id, "s": status, "g": gpu_id},
        )


def test_single_job_creates_index_and_rejects_second_on_same_gpu(file_engine, monkeypatch):
    """slots == 1 → index present; a 2nd active job on the same GPU is rejected."""
    _set_slots(monkeypatch, 1)
    conn_mod._ensure_deferred_gpu_columns_and_indexes()

    assert _index_exists(file_engine), "single-job mode must keep the 1-job/GPU index"

    _insert(file_engine, "exp-a", 0)
    with pytest.raises(IntegrityError):
        _insert(file_engine, "exp-b", 0)  # same GPU, active status → unique violation


def test_multi_job_drops_index_and_allows_colocation(file_engine, monkeypatch):
    """slots > 1 → index dropped (even from a legacy DB) and co-location commits."""
    # Simulate a legacy DB that already has the 1-job index.
    _set_slots(monkeypatch, 1)
    conn_mod._ensure_deferred_gpu_columns_and_indexes()
    assert _index_exists(file_engine)

    # Re-run under multi-job: the index must be dropped.
    _set_slots(monkeypatch, 6)
    conn_mod._ensure_deferred_gpu_columns_and_indexes()
    assert not _index_exists(file_engine), "multi-job mode must drop the 1-job/GPU index"

    # Two co-located jobs on GPU 0 both commit (no IntegrityError).
    _insert(file_engine, "exp-a", 0)
    _insert(file_engine, "exp-b", 0)
    with file_engine.connect() as c:
        n = c.execute(
            text("SELECT COUNT(*) FROM experiments WHERE gpu_id_allocated = 0")
        ).scalar()
    assert n == 2


def test_detect_overallocation_backstop():
    """Reconciliation backstop flags GPUs allocated beyond the slot limit."""
    from orchestrator.gpu_service import GPUService

    # 3 jobs on GPU 0, 1 on GPU 1, slots=2 → only GPU 0 is over-allocated.
    over = GPUService._detect_overallocation([0, 0, 0, 1, None], slots=2)
    assert over == {0: 3}

    # Within limits → empty.
    assert GPUService._detect_overallocation([0, 0, 1, 1], slots=2) == {}
