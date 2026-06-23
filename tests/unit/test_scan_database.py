"""Tests for scan_database feature — scanner, service, and router."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from features.scan_database.scanner import (
    ScannedExperiment,
    _parse_in_lammps_header,
    _parse_in_lammps_step_names,
    _parse_log_status,
    scan_experiment_directories,
)
from features.scan_database.service import (
    import_experiments,
)

# ---------------------------------------------------------------------------
# Fixtures — create minimal experiment directories on disk
# ---------------------------------------------------------------------------

IN_LAMMPS_HEADER = textwrap.dedent("""\
    # LAMMPS input script
    # Tier: screening
    # Force Field: bulk_ff_gaff2
    # Study Type: bulk
    # Temperature: 293.0 K
    # Pressure: 1.0 atm
    # Protocol hash: {hash}

    units real
""")

DATA_LAMMPS_HEADER = textwrap.dedent("""\
    LAMMPS data file

    5563 atoms
    0 bonds

    0.0 47.623047 xlo xhi
    0.0 47.623047 ylo yhi
    0.0 47.623047 zlo zhi

    Atoms
""")

LOG_COMPLETE = textwrap.dedent("""\
    LAMMPS (22 Jul 2025)
    Step Temp PotEng
    0 0.0 1000.0
    50000 293.0 -5000.0
    Total wall time: 0:12:34
""")

LOG_INCOMPLETE = textwrap.dedent("""\
    LAMMPS (22 Jul 2025)
    Step Temp PotEng
    0 0.0 1000.0
    30000 293.0 -3000.0
""")


@pytest.fixture()
def memory_db():
    """Initialize in-memory SQLite DB for each test."""
    from database.connection import init_memory_db

    init_memory_db()
    yield


def _make_experiment(
    tmp_path: Path,
    exp_id: str,
    *,
    attempts: list[dict] | None = None,
) -> Path:
    """Create a minimal experiment directory structure.

    Each attempt dict can have keys:
      seed, hash, log_content, include_data, include_in, in_lammps_content
    """
    exp_dir = tmp_path / exp_id
    exp_dir.mkdir(parents=True, exist_ok=True)

    if attempts is None:
        return exp_dir

    for i, att in enumerate(attempts):
        attempt_id = att.get("attempt_id", f"attempt_{i:04d}")
        seed = att.get("seed", 20260316)
        work = exp_dir / attempt_id / f"seed_{seed}"
        work.mkdir(parents=True, exist_ok=True)

        if att.get("include_in", True):
            in_lammps_content = att.get("in_lammps_content")
            if in_lammps_content is None:
                h = att.get("hash", "deadbeef")
                in_lammps_content = IN_LAMMPS_HEADER.format(hash=h)
            (work / "in.lammps").write_text(in_lammps_content)

        if att.get("include_data", True):
            (work / "data.lammps").write_text(DATA_LAMMPS_HEADER)

        log_content = att.get("log_content")
        if log_content is not None:
            (work / "log.lammps").write_text(log_content)

    return exp_dir


# ---------------------------------------------------------------------------
# 1. In-lammps header parsing
# ---------------------------------------------------------------------------


class TestParseLammpsHeader:
    def test_parses_all_fields(self, tmp_path: Path) -> None:
        f = tmp_path / "in.lammps"
        f.write_text(IN_LAMMPS_HEADER.format(hash="abc12345"))
        result = _parse_in_lammps_header(f)
        assert result["tier"] == "screening"
        assert result["ff_type"] == "bulk_ff_gaff2"
        assert result["study_type"] == "bulk"
        assert result["temperature_k"] == 293.0
        assert result["pressure_atm"] == 1.0
        assert result["protocol_hash"] == "abc12345"

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        result = _parse_in_lammps_header(tmp_path / "nonexistent")
        assert result == {}


class TestParseLammpsSteps:
    def test_parses_step_names_from_body_comments(self, tmp_path: Path) -> None:
        f = tmp_path / "in.lammps"
        f.write_text(
            IN_LAMMPS_HEADER.format(hash="abc12345")
            + textwrap.dedent("""\

            # Step 1: minimize
            minimize 1e-4 1e-6 1000 10000

            # Step 2: high_temp_nvt
            run 100000

            # Step 3: high_pressure_npt
            run 200000

            # Step 4: nvt_equilibration
            run 300000

            # Step 5: npt_production
            run 2000000
            """)
        )

        assert _parse_in_lammps_step_names(f) == [
            "minimize",
            "high_temp_nvt",
            "high_pressure_npt",
            "nvt_equilibration",
            "npt_production",
        ]

    def test_rejects_non_sequential_step_markers(self, tmp_path: Path) -> None:
        f = tmp_path / "in.lammps"
        f.write_text(
            IN_LAMMPS_HEADER.format(hash="abc12345")
            + textwrap.dedent("""\

            # Step 1: minimize
            minimize 1e-4 1e-6 1000 10000

            # Step 3: npt_production
            run 2000000
            """)
        )

        assert _parse_in_lammps_step_names(f) == []


# ---------------------------------------------------------------------------
# 2. Log parsing — final_step extraction
# ---------------------------------------------------------------------------


class TestParseLogStatus:
    def test_completed_log(self, tmp_path: Path) -> None:
        log = tmp_path / "log.lammps"
        log.write_text(LOG_COMPLETE)
        completed, final_step = _parse_log_status(log)
        assert completed is True
        assert final_step == 50000

    def test_incomplete_log(self, tmp_path: Path) -> None:
        log = tmp_path / "log.lammps"
        log.write_text(LOG_INCOMPLETE)
        completed, final_step = _parse_log_status(log)
        assert completed is False
        assert final_step == 30000

    def test_missing_log(self, tmp_path: Path) -> None:
        completed, final_step = _parse_log_status(tmp_path / "missing.log")
        assert completed is False
        assert final_step == 0


# ---------------------------------------------------------------------------
# 3. Multi-attempt selection — importability priority + final_step tiebreak
# ---------------------------------------------------------------------------


class TestMultiAttemptSelection:
    def test_compatible_chosen_over_mismatch(self, tmp_path: Path) -> None:
        """Even if mismatch attempt is newer, compatible wins."""
        from features.scan_database.scanner import _compute_current_protocol_hash

        current_hash = _compute_current_protocol_hash(
            tier="screening",
            ff_type="bulk_ff_gaff2",
            study_type="bulk",
            temperature_k=293.0,
            pressure_atm=1.0,
            data_file_path=str(tmp_path / "dummy"),
        )
        assert current_hash is not None

        _make_experiment(
            tmp_path,
            "A1_test",
            attempts=[
                {
                    "attempt_id": "attempt_old",
                    "seed": 111,
                    "hash": "wronghash",
                    "log_content": LOG_COMPLETE,
                },
                {
                    "attempt_id": "attempt_new",
                    "seed": 222,
                    "hash": current_hash,
                    "log_content": LOG_INCOMPLETE,
                },
            ],
        )

        results = scan_experiment_directories(tmp_path)
        assert len(results) == 1
        exp = results[0]
        # compatible_incomplete beats protocol_mismatch
        assert exp.compatibility == "compatible_incomplete"
        assert exp.seed == 222

    def test_final_step_tiebreak(self, tmp_path: Path) -> None:
        """Among same compatibility, higher final_step wins."""
        from features.scan_database.scanner import _compute_current_protocol_hash

        current_hash = _compute_current_protocol_hash(
            tier="screening",
            ff_type="bulk_ff_gaff2",
            study_type="bulk",
            temperature_k=293.0,
            pressure_atm=1.0,
            data_file_path=str(tmp_path / "dummy"),
        )

        _make_experiment(
            tmp_path,
            "A1_step_test",
            attempts=[
                {
                    "attempt_id": "attempt_less",
                    "seed": 111,
                    "hash": current_hash,
                    "log_content": LOG_INCOMPLETE,  # final_step=30000
                },
                {
                    "attempt_id": "attempt_more",
                    "seed": 222,
                    "hash": current_hash,
                    "log_content": LOG_COMPLETE,  # final_step=50000, completed
                },
            ],
        )

        results = scan_experiment_directories(tmp_path)
        exp = results[0]
        # completed attempt (compatible, final_step=50000) beats incomplete
        assert exp.compatibility == "compatible"
        assert exp.seed == 222

    def test_scan_uses_embedded_step_comments_for_hash(self, tmp_path: Path) -> None:
        """A stored 5-step script should remain compatible even if current chain is 3-step."""
        from contracts.policies.forcefield import get_ff_version
        from protocols.protocol_hash import ProtocolHasher

        step_names = [
            "minimize",
            "high_temp_nvt",
            "high_pressure_npt",
            "nvt_equilibration",
            "npt_production",
        ]
        # ff_version must come from the SSOT registry (scanner uses
        # get_ff_version, e.g. GAFF2 "2.11") — hardcoding "1.0" diverges
        # from the production hash.
        expected_hash = ProtocolHasher().hash(
            tier="screening",
            force_field="bulk_ff_gaff2",
            ff_version=get_ff_version("bulk_ff_gaff2"),
            topology_hash="",
            temperature_K=293.0,
            pressure_atm=1.0,
            step_names=step_names,
        )

        five_step_script = IN_LAMMPS_HEADER.format(hash=expected_hash) + textwrap.dedent("""\

            # Step 1: minimize
            minimize 1e-4 1e-6 1000 10000

            # Step 2: high_temp_nvt
            run 100000

            # Step 3: high_pressure_npt
            run 200000

            # Step 4: nvt_equilibration
            run 300000

            # Step 5: npt_production
            run 2000000
            """)

        _make_experiment(
            tmp_path,
            "A1_five_step_scan",
            attempts=[
                {
                    "in_lammps_content": five_step_script,
                    "log_content": LOG_COMPLETE,
                }
            ],
        )

        results = scan_experiment_directories(tmp_path)
        exp = results[0]
        assert exp.protocol_hash_found == expected_hash
        assert exp.protocol_hash_current == expected_hash
        assert exp.compatibility == "compatible"


# ---------------------------------------------------------------------------
# 4. Batch import — partial failure isolation
# ---------------------------------------------------------------------------


class TestBatchImportPartialFailure:
    def test_one_failure_does_not_rollback_others(self, tmp_path: Path, memory_db) -> None:
        """If one import fails, previously imported experiments survive."""
        from features.scan_database.scanner import _compute_current_protocol_hash

        current_hash = _compute_current_protocol_hash(
            tier="screening",
            ff_type="bulk_ff_gaff2",
            study_type="bulk",
            temperature_k=293.0,
            pressure_atm=1.0,
            data_file_path=str(tmp_path / "dummy"),
        )

        # Create two experiments
        for name in ["A1_good", "A1_bad"]:
            _make_experiment(
                tmp_path,
                name,
                attempts=[
                    {
                        "hash": current_hash,
                        "log_content": LOG_COMPLETE,
                    }
                ],
            )

        # Patch _create_experiment_model to fail on the second one
        from features.scan_database import service as svc

        real_create = svc._create_experiment_model

        def failing_create(exp: ScannedExperiment):
            if exp.exp_id == "A1_bad":
                raise RuntimeError("Simulated DB error")
            return real_create(exp)

        from database.connection import session_scope
        from database.models import ExperimentModel

        with patch.object(svc, "_create_experiment_model", side_effect=failing_create):
            result = svc.import_experiments(
                exp_ids=["A1_good", "A1_bad"],
                force_import=False,
                database_dir=tmp_path,
            )

        assert result["imported"] == 1
        assert result["failed"] == 1

        # Verify A1_good is actually in DB
        with session_scope() as session:
            good = (
                session.query(ExperimentModel).filter(ExperimentModel.exp_id == "A1_good").first()
            )
            assert good is not None
            assert good.status == "completed"

            bad = session.query(ExperimentModel).filter(ExperimentModel.exp_id == "A1_bad").first()
            assert bad is None


# ---------------------------------------------------------------------------
# 5. Force import restrictions
# ---------------------------------------------------------------------------


class TestForceImportRestrictions:
    def test_never_importable_rejected_even_with_force(self, tmp_path: Path, memory_db) -> None:
        """hash_unverifiable, no_metadata, empty cannot be imported even with force=True."""
        # Empty dir
        _make_experiment(tmp_path, "empty_exp", attempts=[])
        # No in.lammps
        _make_experiment(
            tmp_path,
            "no_meta_exp",
            attempts=[{"include_in": False, "log_content": None}],
        )

        result = import_experiments(
            exp_ids=["empty_exp", "no_meta_exp"],
            force_import=True,
            database_dir=tmp_path,
        )
        assert result["imported"] == 0
        # All should be rejected or failed
        for r in result["results"]:
            assert r["status"] in ("rejected", "error")

    def test_mismatch_rejected_without_force(self, tmp_path: Path, memory_db) -> None:
        """protocol_mismatch is rejected when force_import=False."""
        _make_experiment(
            tmp_path,
            "A1_mismatch",
            attempts=[
                {
                    "hash": "wronghash",
                    "log_content": LOG_COMPLETE,
                }
            ],
        )

        result = import_experiments(
            exp_ids=["A1_mismatch"],
            force_import=False,
            database_dir=tmp_path,
        )
        assert result["imported"] == 0
        assert result["results"][0]["status"] == "rejected"

    def test_mismatch_allowed_with_force(self, tmp_path: Path, memory_db) -> None:
        """protocol_mismatch is importable when force_import=True."""
        _make_experiment(
            tmp_path,
            "A1_force_ok",
            attempts=[
                {
                    "hash": "wronghash",
                    "log_content": LOG_COMPLETE,
                }
            ],
        )

        result = import_experiments(
            exp_ids=["A1_force_ok"],
            force_import=True,
            database_dir=tmp_path,
        )
        assert result["imported"] == 1


# ---------------------------------------------------------------------------
# 6. Topology hash restoration
# ---------------------------------------------------------------------------


class TestTopologyHash:
    def test_computed_when_data_exists(self, tmp_path: Path) -> None:
        from features.scan_database.scanner import _compute_current_protocol_hash

        current_hash = _compute_current_protocol_hash(
            tier="screening",
            ff_type="bulk_ff_gaff2",
            study_type="bulk",
            temperature_k=293.0,
            pressure_atm=1.0,
            data_file_path=str(tmp_path / "dummy"),
        )

        _make_experiment(
            tmp_path,
            "A1_topo",
            attempts=[
                {
                    "hash": current_hash,
                    "include_data": True,
                    "log_content": LOG_COMPLETE,
                }
            ],
        )

        results = scan_experiment_directories(tmp_path)
        assert results[0].topology_hash is not None
        assert len(results[0].topology_hash) == 16

    def test_none_when_data_missing(self, tmp_path: Path) -> None:
        _make_experiment(
            tmp_path,
            "A1_no_data",
            attempts=[
                {
                    "hash": "somehash",
                    "include_data": False,
                    "log_content": None,
                }
            ],
        )

        results = scan_experiment_directories(tmp_path)
        assert results[0].topology_hash is None


# ---------------------------------------------------------------------------
# 7. Directory deletion
# ---------------------------------------------------------------------------


class TestDeleteExperimentDirs:
    def test_deletes_directory(self, tmp_path: Path) -> None:
        """Successfully deletes an experiment directory."""
        from features.scan_database.service import delete_experiment_dirs

        _make_experiment(tmp_path, "to_delete", attempts=[{"hash": "x", "log_content": None}])
        assert (tmp_path / "to_delete").exists()

        result = delete_experiment_dirs(["to_delete"], database_dir=tmp_path)
        assert result["deleted"] == 1
        assert result["failed"] == 0
        assert not (tmp_path / "to_delete").exists()

    def test_nonexistent_directory_fails(self, tmp_path: Path) -> None:
        """Trying to delete a missing directory returns error."""
        from features.scan_database.service import delete_experiment_dirs

        result = delete_experiment_dirs(["ghost_exp"], database_dir=tmp_path)
        assert result["deleted"] == 0
        assert result["failed"] == 1
        assert result["results"][0]["status"] == "error"

    def test_partial_delete(self, tmp_path: Path) -> None:
        """Mixed success/failure in batch delete."""
        from features.scan_database.service import delete_experiment_dirs

        _make_experiment(tmp_path, "exists", attempts=[{"hash": "x", "log_content": None}])

        result = delete_experiment_dirs(["exists", "missing"], database_dir=tmp_path)
        assert result["deleted"] == 1
        assert result["failed"] == 1

    def test_rejects_dot_root(self, tmp_path: Path) -> None:
        """'.' must not delete the database/ root."""
        from features.scan_database.service import delete_experiment_dirs

        result = delete_experiment_dirs(["."], database_dir=tmp_path)
        assert result["deleted"] == 0
        assert result["results"][0]["status"] == "rejected"
        assert tmp_path.exists()

    def test_rejects_dotdot(self, tmp_path: Path) -> None:
        """'..' must be rejected."""
        from features.scan_database.service import delete_experiment_dirs

        result = delete_experiment_dirs([".."], database_dir=tmp_path)
        assert result["deleted"] == 0
        assert result["results"][0]["status"] == "rejected"

    def test_rejects_empty_string(self, tmp_path: Path) -> None:
        """Empty string must be rejected."""
        from features.scan_database.service import delete_experiment_dirs

        result = delete_experiment_dirs([""], database_dir=tmp_path)
        assert result["deleted"] == 0
        assert result["results"][0]["status"] == "rejected"

    def test_rejects_path_separator(self, tmp_path: Path) -> None:
        """exp_id containing '/' must be rejected."""
        from features.scan_database.service import delete_experiment_dirs

        result = delete_experiment_dirs(["../escape"], database_dir=tmp_path)
        assert result["deleted"] == 0
        assert result["results"][0]["status"] == "rejected"

    def test_rejects_amorphous_cells(self, tmp_path: Path) -> None:
        """Protected directory 'amorphous_cells' must be rejected."""
        from features.scan_database.service import delete_experiment_dirs

        (tmp_path / "amorphous_cells").mkdir()
        result = delete_experiment_dirs(["amorphous_cells"], database_dir=tmp_path)
        assert result["deleted"] == 0
        assert result["results"][0]["status"] == "rejected"
        assert (tmp_path / "amorphous_cells").exists()

    def test_rejects_db_imported_experiment(self, tmp_path: Path, memory_db) -> None:
        """Experiment already in DB must not be deletable."""
        from features.scan_database.scanner import _compute_current_protocol_hash
        from features.scan_database.service import delete_experiment_dirs, import_experiments

        current_hash = _compute_current_protocol_hash(
            tier="screening",
            ff_type="bulk_ff_gaff2",
            study_type="bulk",
            temperature_k=293.0,
            pressure_atm=1.0,
            data_file_path=str(tmp_path / "dummy"),
        )
        _make_experiment(
            tmp_path,
            "A1_in_db",
            attempts=[{"hash": current_hash, "log_content": LOG_COMPLETE}],
        )

        # Import it first
        import_result = import_experiments(
            exp_ids=["A1_in_db"], force_import=False, database_dir=tmp_path
        )
        assert import_result["imported"] == 1

        # Now try to delete — must be rejected
        result = delete_experiment_dirs(["A1_in_db"], database_dir=tmp_path)
        assert result["deleted"] == 0
        assert result["results"][0]["status"] == "rejected"
        assert "DB" in result["results"][0]["reason"]
        assert (tmp_path / "A1_in_db").exists()


# ---------------------------------------------------------------------------
# 8. Metric auto-computation on import (v00.95.53)
# ---------------------------------------------------------------------------


LOG_COMPLETE_WITH_THERMO = textwrap.dedent("""\
    LAMMPS (22 Jul 2025)
    Step Temp Press PotEng KinEng TotEng Volume Density
    0 293.0 1.0 -5000.0 1500.0 -3500.0 100000.0 0.95
    10000 293.0 1.0 -5100.0 1480.0 -3620.0 99500.0 0.96
    20000 293.0 1.0 -5050.0 1490.0 -3560.0 99700.0 0.955
    50000 293.0 1.0 -5080.0 1485.0 -3595.0 99600.0 0.958
    Total wall time: 0:12:34
""")


class TestMetricAutoComputation:
    def test_completed_import_creates_metrics(self, tmp_path: Path, memory_db) -> None:
        """Completed experiments should have metrics computed and stored."""
        from database.connection import session_scope
        from database.models import MetricModel
        from features.scan_database.scanner import _compute_current_protocol_hash

        current_hash = _compute_current_protocol_hash(
            tier="screening",
            ff_type="bulk_ff_gaff2",
            study_type="bulk",
            temperature_k=293.0,
            pressure_atm=1.0,
            data_file_path=str(tmp_path / "dummy"),
        )

        _make_experiment(
            tmp_path,
            "A1_metrics_ok",
            attempts=[{"hash": current_hash, "log_content": LOG_COMPLETE_WITH_THERMO}],
        )

        result = import_experiments(
            exp_ids=["A1_metrics_ok"], force_import=False, database_dir=tmp_path
        )
        assert result["imported"] == 1
        assert "metrics computed" in result["results"][0]["reason"]

        with session_scope() as session:
            metrics = session.query(MetricModel).filter(MetricModel.exp_id == "A1_metrics_ok").all()
            assert len(metrics) > 0
            metric_names = {m.metric_name for m in metrics}
            assert "density" in metric_names or "temperature" in metric_names

    def test_incomplete_import_skips_metrics(self, tmp_path: Path, memory_db) -> None:
        """Incomplete experiments should NOT have metrics computed."""
        from database.connection import session_scope
        from database.models import MetricModel
        from features.scan_database.scanner import _compute_current_protocol_hash

        current_hash = _compute_current_protocol_hash(
            tier="screening",
            ff_type="bulk_ff_gaff2",
            study_type="bulk",
            temperature_k=293.0,
            pressure_atm=1.0,
            data_file_path=str(tmp_path / "dummy"),
        )

        _make_experiment(
            tmp_path,
            "A1_incomplete",
            attempts=[{"hash": current_hash, "log_content": LOG_INCOMPLETE}],
        )

        result = import_experiments(
            exp_ids=["A1_incomplete"], force_import=False, database_dir=tmp_path
        )
        assert result["imported"] == 1
        assert "metrics computed" not in result["results"][0]["reason"]

        with session_scope() as session:
            metrics = session.query(MetricModel).filter(MetricModel.exp_id == "A1_incomplete").all()
            assert len(metrics) == 0


# ---------------------------------------------------------------------------
# 9. Composition & metadata enrichment (v00.95.53)
# ---------------------------------------------------------------------------


class TestCompositionAndMetadata:
    def test_aaa1_composition_restored(self, tmp_path: Path, memory_db) -> None:
        """A1_ exp_id should map to AAA1 composition (20/30/35/15)."""
        from database.connection import session_scope
        from database.models import ExperimentModel
        from features.scan_database.scanner import _compute_current_protocol_hash

        current_hash = _compute_current_protocol_hash(
            tier="screening",
            ff_type="bulk_ff_gaff2",
            study_type="bulk",
            temperature_k=293.0,
            pressure_atm=1.0,
            data_file_path=str(tmp_path / "dummy"),
        )

        _make_experiment(
            tmp_path,
            "A1_X1_NA_none_293K_abcdef",
            attempts=[{"hash": current_hash, "log_content": LOG_COMPLETE}],
        )

        result = import_experiments(
            exp_ids=["A1_X1_NA_none_293K_abcdef"],
            force_import=False,
            database_dir=tmp_path,
        )
        assert result["imported"] == 1

        with session_scope() as session:
            exp = (
                session.query(ExperimentModel)
                .filter(ExperimentModel.exp_id == "A1_X1_NA_none_293K_abcdef")
                .first()
            )
            assert exp is not None
            assert exp.comp_asphaltene_wt == 20.0
            assert exp.comp_resin_wt == 30.0
            assert exp.comp_aromatic_wt == 35.0
            assert exp.comp_saturate_wt == 15.0
            # Metadata enrichment
            meta = exp.metadata_json
            assert meta["binder_type"] == "AAA1"
            assert meta["aging_state"] == "non_aging"
            assert meta["structure_size"] == "X1"
            assert meta["scan_version"] == "v00.95.53"

    def test_aak1_composition_restored(self, tmp_path: Path, memory_db) -> None:
        """K1_ exp_id should map to AAK1 composition (17/38/33/12)."""
        from database.connection import session_scope
        from database.models import ExperimentModel
        from features.scan_database.scanner import _compute_current_protocol_hash

        current_hash = _compute_current_protocol_hash(
            tier="screening",
            ff_type="bulk_ff_gaff2",
            study_type="bulk",
            temperature_k=293.0,
            pressure_atm=1.0,
            data_file_path=str(tmp_path / "dummy"),
        )

        _make_experiment(
            tmp_path,
            "K1_X1_NA_none_293K_abcdef",
            attempts=[{"hash": current_hash, "log_content": LOG_COMPLETE}],
        )

        result = import_experiments(
            exp_ids=["K1_X1_NA_none_293K_abcdef"],
            force_import=False,
            database_dir=tmp_path,
        )
        assert result["imported"] == 1

        with session_scope() as session:
            exp = (
                session.query(ExperimentModel)
                .filter(ExperimentModel.exp_id == "K1_X1_NA_none_293K_abcdef")
                .first()
            )
            assert exp is not None
            assert exp.comp_asphaltene_wt == 17.0
            assert exp.comp_resin_wt == 38.0
            assert exp.comp_aromatic_wt == 33.0
            assert exp.comp_saturate_wt == 12.0
            assert exp.metadata_json["binder_type"] == "AAK1"

    def test_unknown_binder_gets_zero_composition(self, tmp_path: Path, memory_db) -> None:
        """Unknown binder prefix should get (0,0,0,0) composition."""
        from database.connection import session_scope
        from database.models import ExperimentModel
        from features.scan_database.scanner import _compute_current_protocol_hash

        current_hash = _compute_current_protocol_hash(
            tier="screening",
            ff_type="bulk_ff_gaff2",
            study_type="bulk",
            temperature_k=293.0,
            pressure_atm=1.0,
            data_file_path=str(tmp_path / "dummy"),
        )

        _make_experiment(
            tmp_path,
            "ZZ_X1_NA_none_293K_abcdef",
            attempts=[{"hash": current_hash, "log_content": LOG_COMPLETE}],
        )

        result = import_experiments(
            exp_ids=["ZZ_X1_NA_none_293K_abcdef"],
            force_import=False,
            database_dir=tmp_path,
        )
        assert result["imported"] == 1

        with session_scope() as session:
            exp = (
                session.query(ExperimentModel)
                .filter(ExperimentModel.exp_id == "ZZ_X1_NA_none_293K_abcdef")
                .first()
            )
            assert exp is not None
            assert exp.comp_asphaltene_wt == 0.0
            assert exp.comp_resin_wt == 0.0


# ---------------------------------------------------------------------------
# 10. DB empty warning (v00.95.53)
# ---------------------------------------------------------------------------


class TestEmptyExperimentsWarning:
    def test_warns_when_table_empty_and_dirs_exist(self, tmp_path: Path) -> None:
        """Warning should fire when experiments table is empty but filesystem has dirs."""
        import database.connection as conn_mod
        from database.connection import _warn_empty_experiments_with_filesystem_data, init_memory_db

        init_memory_db()

        # Create fake database/ dir with experiment subdirectories
        db_dir = tmp_path / "database"
        db_dir.mkdir()
        (db_dir / "A1_exp1").mkdir()
        (db_dir / "A1_exp2").mkdir()

        with patch.object(conn_mod, "_resolve_project_root", return_value=tmp_path):
            with patch.object(conn_mod.logger, "warning") as mock_warn:
                _warn_empty_experiments_with_filesystem_data()
                mock_warn.assert_called_once()
                call_args = str(mock_warn.call_args)
                assert "experiment dirs" in call_args

    def test_no_warn_when_no_filesystem_dirs(self) -> None:
        """No warning when database/ directory does not exist."""
        import database.connection as conn_mod
        from database.connection import _warn_empty_experiments_with_filesystem_data, init_memory_db

        init_memory_db()

        with patch.object(
            conn_mod, "_resolve_project_root", return_value=Path("/nonexistent_path_xyz")
        ):
            with patch.object(conn_mod.logger, "warning") as mock_warn:
                _warn_empty_experiments_with_filesystem_data()
                mock_warn.assert_not_called()


# ---------------------------------------------------------------------------
# 11. Dump file discovery (v00.95.54)
# ---------------------------------------------------------------------------


class TestDumpFileDiscovery:
    def test_dump_file_found(self, tmp_path: Path) -> None:
        """dump_file_path populated when dump file exists in attempt dir."""
        from features.scan_database.scanner import _compute_current_protocol_hash

        current_hash = _compute_current_protocol_hash(
            tier="screening",
            ff_type="bulk_ff_gaff2",
            study_type="bulk",
            temperature_k=293.0,
            pressure_atm=1.0,
            data_file_path=str(tmp_path / "dummy"),
        )

        exp_dir = _make_experiment(
            tmp_path,
            "A1_dump_test",
            attempts=[{"hash": current_hash, "log_content": LOG_COMPLETE}],
        )
        # Create dump file in the work dir
        work = exp_dir / "attempt_0000" / "seed_20260316"
        (work / "dump_npt.lammpstrj").write_text("ITEM: TIMESTEP\n0\n")

        results = scan_experiment_directories(tmp_path)
        exp = [r for r in results if r.exp_id == "A1_dump_test"][0]
        assert exp.dump_file_path is not None
        assert "dump_npt.lammpstrj" in exp.dump_file_path

    def test_multiple_dumps_selects_sorted_first(self, tmp_path: Path) -> None:
        """When multiple dump files exist, sorted()[0] is selected."""
        from features.scan_database.scanner import _compute_current_protocol_hash

        current_hash = _compute_current_protocol_hash(
            tier="screening",
            ff_type="bulk_ff_gaff2",
            study_type="bulk",
            temperature_k=293.0,
            pressure_atm=1.0,
            data_file_path=str(tmp_path / "dummy"),
        )

        exp_dir = _make_experiment(
            tmp_path,
            "A1_multi_dump",
            attempts=[{"hash": current_hash, "log_content": LOG_COMPLETE}],
        )
        work = exp_dir / "attempt_0000" / "seed_20260316"
        (work / "dump_nvt.lammpstrj").write_text("ITEM: TIMESTEP\n0\n")
        (work / "dump_minimize.lammpstrj").write_text("ITEM: TIMESTEP\n0\n")

        results = scan_experiment_directories(tmp_path)
        exp = [r for r in results if r.exp_id == "A1_multi_dump"][0]
        assert exp.dump_file_path is not None
        # sorted: dump_minimize < dump_nvt
        assert "dump_minimize.lammpstrj" in exp.dump_file_path

    def test_no_dump_file_stays_none(self, tmp_path: Path) -> None:
        """dump_file_path is None when no dump files exist."""
        from features.scan_database.scanner import _compute_current_protocol_hash

        current_hash = _compute_current_protocol_hash(
            tier="screening",
            ff_type="bulk_ff_gaff2",
            study_type="bulk",
            temperature_k=293.0,
            pressure_atm=1.0,
            data_file_path=str(tmp_path / "dummy"),
        )

        _make_experiment(
            tmp_path,
            "A1_no_dump",
            attempts=[{"hash": current_hash, "log_content": LOG_COMPLETE}],
        )

        results = scan_experiment_directories(tmp_path)
        exp = [r for r in results if r.exp_id == "A1_no_dump"][0]
        assert exp.dump_file_path is None

    def test_import_stores_dump_file_path(self, tmp_path: Path, memory_db) -> None:
        """After import, ExperimentModel.dump_file_path is set."""
        from database.connection import session_scope
        from database.models import ExperimentModel
        from features.scan_database.scanner import _compute_current_protocol_hash

        current_hash = _compute_current_protocol_hash(
            tier="screening",
            ff_type="bulk_ff_gaff2",
            study_type="bulk",
            temperature_k=293.0,
            pressure_atm=1.0,
            data_file_path=str(tmp_path / "dummy"),
        )

        exp_dir = _make_experiment(
            tmp_path,
            "A1_dump_import",
            attempts=[{"hash": current_hash, "log_content": LOG_COMPLETE}],
        )
        work = exp_dir / "attempt_0000" / "seed_20260316"
        (work / "dump_npt.lammpstrj").write_text("ITEM: TIMESTEP\n0\n")

        result = import_experiments(
            exp_ids=["A1_dump_import"], force_import=False, database_dir=tmp_path
        )
        assert result["imported"] == 1

        with session_scope() as session:
            exp = (
                session.query(ExperimentModel)
                .filter(ExperimentModel.exp_id == "A1_dump_import")
                .first()
            )
            assert exp is not None
            assert exp.dump_file_path is not None
            assert "dump_npt.lammpstrj" in exp.dump_file_path
