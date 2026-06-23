"""Fix D (v01.06.22): process-registration backstop against duplicate lmp.

register_process must REFUSE to register a second, conflicting lmp for one
experiment (a live duplicate PID on this host, or a GPU that disagrees with the
DB allocation SSOT) by raising ProcessRegistrationConflict. lammps_runner treats
that as fatal (kills the just-launched process), so a duplicate lmp never
survives — closing the gap where the old RuntimeError was swallowed after Popen.
"""

import socket
from datetime import datetime

import pytest

from database.models import ExperimentModel, ProcessInfoModel
from orchestrator.process_tracker import ProcessRegistrationConflict, ProcessTracker


def _seed_experiment_and_process(db_session, *, exp_id: str, pid: int, hostname: str) -> None:
    db_session.add(
        ExperimentModel(
            exp_id=exp_id,
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            status="running",
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
            gpu_id_allocated=0,
        )
    )
    db_session.flush()
    db_session.add(
        ProcessInfoModel(
            exp_id=exp_id,
            pid=pid,
            hostname=hostname,
            working_dir="/tmp/run",
            gpu_id=0,
            started_at=datetime.utcnow(),
            last_heartbeat=datetime.utcnow(),
        )
    )
    db_session.commit()


def _make_tracker(monkeypatch) -> ProcessTracker:
    tracker = ProcessTracker()
    # Avoid touching the real .pids directory during the unit test.
    monkeypatch.setattr(tracker, "_write_pid_file", lambda *a, **k: None)
    return tracker


def test_register_process_rejects_live_duplicate(db_session, monkeypatch):
    host = socket.gethostname()
    _seed_experiment_and_process(db_session, exp_id="exp_dup_live", pid=111111, hostname=host)

    tracker = _make_tracker(monkeypatch)
    # Treat the already-registered PID as a live lmp process.
    monkeypatch.setattr("orchestrator.process_tracker._is_live_lmp", lambda pid: True)

    with pytest.raises(ProcessRegistrationConflict):
        tracker.register_process(
            exp_id="exp_dup_live",
            pid=222222,
            hostname=host,
            working_dir="/tmp/run",
            gpu_id=0,
            total_steps=1000,
        )


def test_register_process_allows_when_prior_pid_dead(db_session, monkeypatch):
    host = socket.gethostname()
    _seed_experiment_and_process(db_session, exp_id="exp_dup_dead", pid=111111, hostname=host)

    tracker = _make_tracker(monkeypatch)
    # Prior PID is dead -> not a duplicate; registration must proceed.
    monkeypatch.setattr("orchestrator.process_tracker._is_live_lmp", lambda pid: False)

    tracker.register_process(
        exp_id="exp_dup_dead",
        pid=222222,
        hostname=host,
        working_dir="/tmp/run",
        gpu_id=0,
        total_steps=1000,
    )

    db_session.expire_all()
    row = db_session.query(ProcessInfoModel).filter_by(exp_id="exp_dup_dead").first()
    assert row.pid == 222222


def test_register_process_rejects_gpu_mismatch(db_session, monkeypatch):
    """A GPU that disagrees with the DB allocation SSOT is also fatal."""
    host = socket.gethostname()
    _seed_experiment_and_process(db_session, exp_id="exp_gpu_mismatch", pid=333333, hostname=host)

    tracker = _make_tracker(monkeypatch)
    monkeypatch.setattr("orchestrator.process_tracker._is_live_lmp", lambda pid: False)

    # DB allocation is GPU 0 (seed), but registration passes GPU 4.
    with pytest.raises(ProcessRegistrationConflict):
        tracker.register_process(
            exp_id="exp_gpu_mismatch",
            pid=444444,
            hostname=host,
            working_dir="/tmp/run",
            gpu_id=4,
            total_steps=1000,
        )
