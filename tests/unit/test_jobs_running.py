"""Unit tests for running-jobs progress collection."""

from datetime import datetime
from types import SimpleNamespace

from features.jobs.running import _collect_running_from_db_exp, _resolve_current_step


class _FakeQuery:
    def __init__(self, result):
        self._result = result

    def filter_by(self, **_kwargs):
        return self

    def first(self):
        return self._result


class _FakeSession:
    def __init__(self, process_info):
        self._process_info = process_info

    def query(self, _model):
        return _FakeQuery(self._process_info)


def test_resolve_current_step_prefers_process_when_parser_missing() -> None:
    assert _resolve_current_step(840000, 0) == 840000


def test_collect_running_from_db_exp_uses_process_step_when_tail_parse_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        "features.jobs.running.parse_thermo_tail",
        lambda _path: ([], 0, None, None, None, None),
    )

    exp = SimpleNamespace(
        exp_id="A1_X1_NA_none_393K_1dbe73",
        run_tier="screening",
        stage_duration_overrides=None,
        log_file_path="/tmp/missing-log.lammps",
        created_at=datetime.utcnow(),
        last_heartbeat_at=datetime.utcnow(),
        gpu_id_allocated=1,
    )
    process_info = SimpleNamespace(
        total_steps=2310000,
        current_step=840000,
        temperature=None,
        pressure=None,
        density=None,
        energy=None,
        started_at=None,
    )
    session = _FakeSession(process_info)

    payload = _collect_running_from_db_exp(exp, session)

    assert payload["source"] == "db"
    assert payload["current_step"] == 840000
    assert payload["total_steps"] == 2310000
    assert payload["current_stage"] == "npt_production"
    assert payload["stage_progress"] == "3/3"


def test_collect_running_from_db_exp_prefers_db_telemetry(monkeypatch) -> None:
    monkeypatch.setattr(
        "features.jobs.running.parse_thermo_tail",
        lambda _path: ([], 1200, 111.0, 2.0, 0.8, -1.0),
    )

    exp = SimpleNamespace(
        exp_id="exp_db_telemetry",
        run_tier="screening",
        stage_duration_overrides=None,
        log_file_path="/tmp/log.lammps",
        created_at=datetime.utcnow(),
        last_heartbeat_at=datetime.utcnow(),
        gpu_id_allocated=0,
    )
    process_info = SimpleNamespace(
        total_steps=2310000,
        current_step=1300,
        temperature=333.3,
        pressure=1.23,
        density=0.95,
        energy=-1234.5,
        started_at=None,
    )
    session = _FakeSession(process_info)

    payload = _collect_running_from_db_exp(exp, session)

    assert payload["current_step"] == 1300
    assert payload["temperature"] == 333.3
    assert payload["pressure"] == 1.23
    assert payload["density"] == 0.95
    assert payload["energy"] == -1234.5


def test_marker_adjusts_payload_stage(monkeypatch) -> None:
    """When @@STAGE marker indicates tensile_pull, payload stage should be adjusted."""
    monkeypatch.setattr(
        "features.jobs.running.parse_thermo_tail",
        lambda _path: ([], 5000, 300.0, 1.0, 0.9, -100.0),
    )
    monkeypatch.setattr(
        "features.jobs.running.parse_stage_marker",
        lambda _path: (6, "tensile_pull"),
    )

    exp = SimpleNamespace(
        exp_id="tensile_test_exp",
        run_tier="screening",
        stage_duration_overrides=None,
        log_file_path="/tmp/log.lammps",
        created_at=datetime.utcnow(),
        last_heartbeat_at=datetime.utcnow(),
        gpu_id_allocated=0,
        metadata_json={"chain_key": "tensile_layer"},
    )
    process_info = SimpleNamespace(
        total_steps=None,
        current_step=5000,
        temperature=300.0,
        pressure=1.0,
        density=0.9,
        energy=-100.0,
        started_at=None,
    )
    session = _FakeSession(process_info)

    payload = _collect_running_from_db_exp(exp, session)

    assert payload["current_stage"] == "tensile_pull"
    # adjusted step should be > 3.7M (pre_cumulative for tensile_pull)
    assert payload["current_step"] > 3_700_000


def test_no_marker_preserves_payload(monkeypatch) -> None:
    """Without marker, payload preserves raw step behavior."""
    monkeypatch.setattr(
        "features.jobs.running.parse_thermo_tail",
        lambda _path: ([], 5000, 300.0, 1.0, 0.9, -100.0),
    )
    monkeypatch.setattr(
        "features.jobs.running.parse_stage_marker",
        lambda _path: None,
    )

    exp = SimpleNamespace(
        exp_id="no_marker_exp",
        run_tier="screening",
        stage_duration_overrides=None,
        log_file_path="/tmp/log.lammps",
        created_at=datetime.utcnow(),
        last_heartbeat_at=datetime.utcnow(),
        gpu_id_allocated=0,
        metadata_json={"chain_key": "tensile_layer"},
    )
    process_info = SimpleNamespace(
        total_steps=None,
        current_step=5000,
        temperature=300.0,
        pressure=1.0,
        density=0.9,
        energy=-100.0,
        started_at=None,
    )
    session = _FakeSession(process_info)

    payload = _collect_running_from_db_exp(exp, session)

    # Without marker, raw step 5000 -> high_temp_nvt (the regression)
    assert payload["current_stage"] == "high_temp_nvt"
    assert payload["current_step"] == 5000


def test_adjusted_progress_under_100(monkeypatch) -> None:
    """Adjusted progress must not exceed 100%."""
    monkeypatch.setattr(
        "features.jobs.running.parse_thermo_tail",
        lambda _path: ([], 1_999_000, 300.0, 1.0, 0.9, -100.0),
    )
    monkeypatch.setattr(
        "features.jobs.running.parse_stage_marker",
        lambda _path: (6, "tensile_pull"),
    )

    exp = SimpleNamespace(
        exp_id="progress_cap_exp",
        run_tier="screening",
        stage_duration_overrides=None,
        log_file_path="/tmp/log.lammps",
        created_at=datetime.utcnow(),
        last_heartbeat_at=datetime.utcnow(),
        gpu_id_allocated=0,
        metadata_json={"chain_key": "tensile_layer"},
    )
    process_info = SimpleNamespace(
        total_steps=None,
        current_step=1_999_000,
        temperature=300.0,
        pressure=1.0,
        density=0.9,
        energy=-100.0,
        started_at=None,
    )
    session = _FakeSession(process_info)

    payload = _collect_running_from_db_exp(exp, session)

    assert payload["progress"] <= 100.0
