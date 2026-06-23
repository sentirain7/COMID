"""PR 2 (Method 1a SSOT) — method-aware E_intra integration tests.

Validates the v4 invariants:
- ``EIntraModel`` 5-column unique constraint stores Method 1 and Method 1a
  rows side-by-side without aliasing.
- ``EIntraRepository`` lookups are method-aware (exact / tolerance / coverage).
- ``CEDCalculator.calculate_from_thermo`` accepts an explicit
  ``e_intra_method`` and only resolves the requested method.
- Migration script ``migrate_e_intra_method`` is idempotent on a fresh /
  legacy / migrated DB.

These tests do not touch the real project DB — they use temporary SQLite
databases via ``sqlalchemy.create_engine``.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from contracts.schema_enums import EIntraMethod
from contracts.schemas import EIntraKey, EIntraValue
from database.models import Base, EIntraModel
from database.repositories.e_intra_repo import EIntraRepository

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def session() -> Session:
    """Fresh in-memory SQLite session with full ORM schema applied.

    Creates all tables (not just ``e_intra``) because ``EIntraRepository.set``
    does a join-side lookup against ``molecules``.
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _key(method: EIntraMethod | str = EIntraMethod.SINGLE_MOLECULE_VACUUM) -> EIntraKey:
    return EIntraKey(
        mol_id="U-AS-Test",
        ff_name="GAFF2",
        ff_version="2.11",
        temperature_K=298.0,
        method=method,
    )


# ---------------------------------------------------------------------------
# 5-column unique constraint: Method 1 and 1a co-exist
# ---------------------------------------------------------------------------


class TestMethodAwareDistinctRows:
    def test_distinct_rows_for_method_1_and_1a(self, session: Session) -> None:
        repo = EIntraRepository(session)
        repo.set(_key(EIntraMethod.SINGLE_MOLECULE_VACUUM), EIntraValue(e_intra=-45.2))
        repo.set(
            _key(EIntraMethod.SINGLE_MOLECULE_VACUUM_EXTENDED_CUTOFF),
            EIntraValue(e_intra=-47.0),
        )

        # Two distinct rows must coexist (no UC violation, no aliasing).
        rows = session.query(EIntraModel).all()
        assert len(rows) == 2
        methods = {r.method for r in rows}
        assert methods == {
            "single_molecule_vacuum",
            "single_molecule_vacuum_adaptive_cutoff",
        }

        # Lookups return the requested method only.
        assert repo.get(_key(EIntraMethod.SINGLE_MOLECULE_VACUUM)) == pytest.approx(-45.2)
        assert repo.get(_key(EIntraMethod.SINGLE_MOLECULE_VACUUM_EXTENDED_CUTOFF)) == pytest.approx(
            -47.0
        )

    def test_method_1a_set_does_not_overwrite_method_1(self, session: Session) -> None:
        repo = EIntraRepository(session)
        repo.set(_key(EIntraMethod.SINGLE_MOLECULE_VACUUM), EIntraValue(e_intra=-45.2))
        repo.set(
            _key(EIntraMethod.SINGLE_MOLECULE_VACUUM_EXTENDED_CUTOFF),
            EIntraValue(e_intra=-47.0),
        )
        # Re-read Method 1 — must still be -45.2 (no silent overwrite).
        assert repo.get(_key(EIntraMethod.SINGLE_MOLECULE_VACUUM)) == pytest.approx(-45.2)


# ---------------------------------------------------------------------------
# Repository: method-aware lookups
# ---------------------------------------------------------------------------


class TestMethodAwareLookups:
    def test_get_returns_none_for_wrong_method(self, session: Session) -> None:
        repo = EIntraRepository(session)
        repo.set(_key(EIntraMethod.SINGLE_MOLECULE_VACUUM), EIntraValue(e_intra=-45.2))
        # Method 1a not stored → lookup returns None.
        assert repo.get(_key(EIntraMethod.SINGLE_MOLECULE_VACUUM_EXTENDED_CUTOFF)) is None

    def test_exists_is_method_aware(self, session: Session) -> None:
        repo = EIntraRepository(session)
        repo.set(_key(EIntraMethod.SINGLE_MOLECULE_VACUUM), EIntraValue(e_intra=-45.2))
        assert repo.exists(_key(EIntraMethod.SINGLE_MOLECULE_VACUUM)) is True
        assert repo.exists(_key(EIntraMethod.SINGLE_MOLECULE_VACUUM_EXTENDED_CUTOFF)) is False

    def test_delete_is_method_aware(self, session: Session) -> None:
        repo = EIntraRepository(session)
        repo.set(_key(EIntraMethod.SINGLE_MOLECULE_VACUUM), EIntraValue(e_intra=-45.2))
        repo.set(
            _key(EIntraMethod.SINGLE_MOLECULE_VACUUM_EXTENDED_CUTOFF),
            EIntraValue(e_intra=-47.0),
        )
        # Delete Method 1 only — Method 1a survives.
        deleted = repo.delete(_key(EIntraMethod.SINGLE_MOLECULE_VACUUM))
        assert deleted is True
        assert repo.get(_key(EIntraMethod.SINGLE_MOLECULE_VACUUM)) is None
        assert repo.get(_key(EIntraMethod.SINGLE_MOLECULE_VACUUM_EXTENDED_CUTOFF)) == pytest.approx(
            -47.0
        )

    def test_get_for_molecules_filters_by_method(self, session: Session) -> None:
        repo = EIntraRepository(session)
        repo.set(_key(EIntraMethod.SINGLE_MOLECULE_VACUUM), EIntraValue(e_intra=-45.2))
        repo.set(
            _key(EIntraMethod.SINGLE_MOLECULE_VACUUM_EXTENDED_CUTOFF),
            EIntraValue(e_intra=-47.0),
        )

        v1 = repo.get_for_molecules(
            ["U-AS-Test"],
            ff_name="GAFF2",
            ff_version="2.11",
            temperature_K=298.0,
            method=EIntraMethod.SINGLE_MOLECULE_VACUUM,
        )
        assert v1 == {"U-AS-Test": pytest.approx(-45.2)}

        v1a = repo.get_for_molecules(
            ["U-AS-Test"],
            ff_name="GAFF2",
            ff_version="2.11",
            temperature_K=298.0,
            method=EIntraMethod.SINGLE_MOLECULE_VACUUM_EXTENDED_CUTOFF,
        )
        assert v1a == {"U-AS-Test": pytest.approx(-47.0)}


# ---------------------------------------------------------------------------
# Migration script idempotency
# ---------------------------------------------------------------------------


class TestMigrationIdempotency:
    def test_legacy_to_method_aware_then_idempotent(self) -> None:
        from scripts.migrate_e_intra_method import apply, diagnose

        tmp = Path(tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
        try:
            # Build legacy 4-column schema with one row.
            conn = sqlite3.connect(tmp)
            conn.execute(
                """
                CREATE TABLE e_intra (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    molecule_id INTEGER,
                    mol_id VARCHAR(100) NOT NULL,
                    ff_name VARCHAR(50) NOT NULL,
                    ff_version VARCHAR(20) NOT NULL,
                    temperature_K FLOAT NOT NULL DEFAULT 298.0,
                    e_intra FLOAT NOT NULL,
                    e_components TEXT,
                    minimization_steps INTEGER,
                    source_exp_id VARCHAR(100),
                    averaging_window_ps FLOAT,
                    n_samples INTEGER,
                    created_at DATETIME,
                    updated_at DATETIME,
                    CONSTRAINT uq_e_intra_temp UNIQUE
                        (mol_id, ff_name, ff_version, temperature_K)
                )
                """
            )
            conn.execute(
                "INSERT INTO e_intra "
                "(mol_id, ff_name, ff_version, temperature_K, e_intra) "
                "VALUES (?,?,?,?,?)",
                ("U-AS-Test", "GAFF2", "2.11", 298.0, -45.2),
            )
            conn.commit()
            conn.close()

            d_before = diagnose(tmp)
            assert d_before.has_method_column is False
            assert d_before.has_correct_unique is False

            r1 = apply(tmp, do_backup=False)
            assert r1["applied"] is True

            d_after = diagnose(tmp)
            assert d_after.has_method_column is True
            assert d_after.has_correct_unique is True

            conn = sqlite3.connect(tmp)
            row = conn.execute("SELECT method, e_intra FROM e_intra").fetchone()
            conn.close()
            assert row == ("single_molecule_vacuum", -45.2)

            # Second apply is a no-op (idempotent).
            r2 = apply(tmp, do_backup=False)
            assert r2["applied"] is False
            assert r2["skipped_reason"] == "Already migrated (idempotent no-op)"
        finally:
            tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# CEDCalculator method-aware lookup
# ---------------------------------------------------------------------------


class TestCEDCalculatorMethodAware:
    def test_calculate_from_thermo_uses_specified_method(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CEDCalculator must look up E_intra under the supplied method only."""
        from metrics.ced import CEDCalculator
        from metrics.e_intra_store import AbstractEIntraStore

        repo = EIntraRepository(session)
        repo.set(_key(EIntraMethod.SINGLE_MOLECULE_VACUUM), EIntraValue(e_intra=-45.2))
        repo.set(
            _key(EIntraMethod.SINGLE_MOLECULE_VACUUM_EXTENDED_CUTOFF),
            EIntraValue(e_intra=-47.0),
        )

        # Adapter that delegates to EIntraRepository so we exercise the real
        # 5-column filter.
        class _RepoStore(AbstractEIntraStore):
            def __init__(self, r: EIntraRepository) -> None:
                self._r = r

            def get(self, key: EIntraKey) -> EIntraValue | None:
                return self._r.get_value(key, temperature_tolerance_k=0.0)

            def put(self, key: EIntraKey, value: EIntraValue) -> None:
                self._r.set(key, value)

            def has(self, key: EIntraKey) -> bool:
                return self._r.exists(key)

            def list_keys(self) -> list[EIntraKey]:
                return []

            def delete(self, key: EIntraKey) -> None:
                self._r.delete(key)

        store = _RepoStore(repo)
        calc = CEDCalculator(e_intra_store=store, coverage_mode="exact_required")

        thermo = {
            "PotEng": [-1000.0, -1000.0, -1000.0, -1000.0, -1000.0],
            "Volume": [1000.0, 1000.0, 1000.0, 1000.0, 1000.0],
        }
        mol_counts = {"U-AS-Test": 1}

        # Method 1 lookup
        m1 = calc.calculate_from_thermo(
            thermo_data=thermo,
            mol_counts=mol_counts,
            ff_name="GAFF2",
            ff_version="2.11",
            temperature_K=298.0,
            e_intra_method="single_molecule_vacuum",
        )
        assert m1 is not None
        assert m1.array_summary["e_intra_method"] == "single_molecule_vacuum"

        # Method 1a lookup — different E_intra → different CED.
        m1a = calc.calculate_from_thermo(
            thermo_data=thermo,
            mol_counts=mol_counts,
            ff_name="GAFF2",
            ff_version="2.11",
            temperature_K=298.0,
            e_intra_method="single_molecule_vacuum_adaptive_cutoff",
        )
        assert m1a is not None
        assert m1a.array_summary["e_intra_method"] == "single_molecule_vacuum_adaptive_cutoff"
        assert m1.value != m1a.value, "Method 1 and 1a CED must differ given different E_intra"

    def test_unknown_method_lookup_returns_none(self, session: Session) -> None:
        """Looking up a method that has no row → fail-closed (None)."""
        from metrics.ced import CEDCalculator
        from metrics.e_intra_store import AbstractEIntraStore

        repo = EIntraRepository(session)
        repo.set(_key(EIntraMethod.SINGLE_MOLECULE_VACUUM), EIntraValue(e_intra=-45.2))

        class _RepoStore(AbstractEIntraStore):
            def __init__(self, r: EIntraRepository) -> None:
                self._r = r

            def get(self, key: EIntraKey) -> EIntraValue | None:
                return self._r.get_value(key, temperature_tolerance_k=0.0)

            def put(self, key: EIntraKey, value: EIntraValue) -> None:
                self._r.set(key, value)

            def has(self, key: EIntraKey) -> bool:
                return self._r.exists(key)

            def list_keys(self) -> list[EIntraKey]:
                return []

            def delete(self, key: EIntraKey) -> None:
                self._r.delete(key)

        store = _RepoStore(repo)
        calc = CEDCalculator(e_intra_store=store, coverage_mode="exact_required")

        thermo = {"PotEng": [-1000.0] * 5, "Volume": [1000.0] * 5}
        result = calc.calculate_from_thermo(
            thermo_data=thermo,
            mol_counts={"U-AS-Test": 1},
            ff_name="GAFF2",
            ff_version="2.11",
            temperature_K=298.0,
            e_intra_method="single_molecule_vacuum_adaptive_cutoff",  # not stored
        )
        # exact_required + no Method 1a row → fail-closed None
        assert result is None


# ---------------------------------------------------------------------------
# EIntraKey backward compatibility (str → EIntraMethod coercion)
# ---------------------------------------------------------------------------


class TestEIntraKeyMethodCoercion:
    def test_string_method_coerces_to_enum(self) -> None:
        k = EIntraKey(
            mol_id="M",
            ff_name="GAFF2",
            ff_version="1.0",
            temperature_K=298.0,
            method="single_molecule_vacuum_adaptive_cutoff",
        )
        assert k.method is EIntraMethod.SINGLE_MOLECULE_VACUUM_EXTENDED_CUTOFF

    def test_invalid_method_raises(self) -> None:
        with pytest.raises(ValidationError):
            EIntraKey(
                mol_id="M",
                ff_name="GAFF2",
                ff_version="1.0",
                temperature_K=298.0,
                method="not_a_real_method",
            )


# ---------------------------------------------------------------------------
# Codex peer-review fixes (Round 2)
# ---------------------------------------------------------------------------


class TestExpIdMethodAware:
    """exp_id must encode method so Method 1 and 1a jobs do not collide."""

    def test_distinct_exp_ids_for_distinct_methods(self) -> None:
        from features.experiments.single_molecule import _make_single_molecule_exp_id

        e1 = _make_single_molecule_exp_id(
            "U-AS", 298.0, "bulk_ff_gaff2", 50, 42, method="single_molecule_vacuum"
        )
        e1a = _make_single_molecule_exp_id(
            "U-AS",
            298.0,
            "bulk_ff_gaff2",
            50,
            42,
            method="single_molecule_vacuum_adaptive_cutoff",
        )
        assert e1 != e1a

    def test_legacy_default_preserves_hash(self) -> None:
        """Method 1 default must match the pre-PR2 hash to keep existing IDs valid."""
        from features.experiments.single_molecule import _make_single_molecule_exp_id

        e_explicit = _make_single_molecule_exp_id(
            "U-AS", 298.0, "bulk_ff_gaff2", 50, 42, method="single_molecule_vacuum"
        )
        e_default = _make_single_molecule_exp_id("U-AS", 298.0, "bulk_ff_gaff2", 50, 42)
        assert e_explicit == e_default


class TestScanDetectorRecognisesNoChargeVacuum:
    """``_detect_e_intra_method_from_input`` must catch ``lj/cut`` form too."""

    def test_no_charge_extended_cutoff_recognised(self, tmp_path: Path) -> None:
        from features.scan_database.service import _detect_e_intra_method_from_input

        p = tmp_path / "in.lammps"
        p.write_text("# header\npair_style lj/cut 80.0\n")
        assert _detect_e_intra_method_from_input(str(p)) == "single_molecule_vacuum_adaptive_cutoff"

    def test_charged_legacy_returns_method_1(self, tmp_path: Path) -> None:
        from features.scan_database.service import _detect_e_intra_method_from_input

        p = tmp_path / "in.lammps"
        p.write_text("# header\npair_style lj/cut/coul/cut 12.0\n")
        assert _detect_e_intra_method_from_input(str(p)) == "single_molecule_vacuum"

    def test_periodic_pppm_recognised(self, tmp_path: Path) -> None:
        from features.scan_database.service import _detect_e_intra_method_from_input

        p = tmp_path / "in.lammps"
        p.write_text("# header\npair_style lj/cut/coul/long 12.0\nkspace_style pppm 1.0e-4\n")
        assert _detect_e_intra_method_from_input(str(p)) == "single_molecule_periodic"


class TestForceRecomputeIsolatesMethod:
    """force_recompute must delete only the targeted method's row."""

    def test_method_1_cleanup_preserves_method_1a(self, session: Session) -> None:
        repo = EIntraRepository(session)
        repo.set(_key(EIntraMethod.SINGLE_MOLECULE_VACUUM), EIntraValue(e_intra=-45.2))
        repo.set(
            _key(EIntraMethod.SINGLE_MOLECULE_VACUUM_EXTENDED_CUTOFF),
            EIntraValue(e_intra=-47.0),
        )
        # Simulate the cleanup helper's per-method delete
        deleted = repo.delete(_key(EIntraMethod.SINGLE_MOLECULE_VACUUM))
        assert deleted is True

        # Method 1a row must survive
        assert repo.get(_key(EIntraMethod.SINGLE_MOLECULE_VACUUM_EXTENDED_CUTOFF)) == pytest.approx(
            -47.0
        )
        assert repo.get(_key(EIntraMethod.SINGLE_MOLECULE_VACUUM)) is None

    def test_legacy_db_tag_is_read_via_canonical_method(self, session: Session) -> None:
        """Canonical Method 1a lookups must still find legacy stored tags."""
        from database.models import EIntraModel

        session.add(
            EIntraModel(
                mol_id="U-AS-Test",
                ff_name="GAFF2",
                ff_version="2.11",
                temperature_K=298.0,
                method="single_molecule_vacuum_extended_cutoff",
                e_intra=-47.0,
            )
        )
        session.commit()

        repo = EIntraRepository(session)
        assert repo.get(_key(EIntraMethod.SINGLE_MOLECULE_VACUUM_EXTENDED_CUTOFF)) == pytest.approx(
            -47.0
        )


class TestDataCoverageResponseExposesMethodResolution:
    """Codex Round 8: coverage response carries method + resolution status."""

    def test_response_model_has_method_resolution_fields(self) -> None:
        from api.schemas.ml_visualization import DataCoverageResponse

        # Default — cold start, no champion.
        r = DataCoverageResponse(
            total_experiments=0,
            per_target={},
            feature_set_eligibility={},
            composition_coverage={},
        )
        assert r.method_resolution_status == "cold_start_no_champion"
        assert r.e_intra_method is None

        # Champion lineage — explicit method.
        r2 = DataCoverageResponse(
            total_experiments=10,
            per_target={},
            feature_set_eligibility={},
            composition_coverage={},
            e_intra_method="single_molecule_vacuum_adaptive_cutoff",
            method_resolution_status="champion_lineage",
        )
        assert r2.method_resolution_status == "champion_lineage"
        assert r2.e_intra_method == "single_molecule_vacuum_adaptive_cutoff"


class TestProtocolResultPropagatesProvenance:
    """Codex Round 7: ProtocolResult must carry e_intra_method/vacuum_cutoff_a."""

    def test_protocol_result_accepts_method_and_cutoff(self) -> None:
        from contracts.schemas import ProtocolResult

        r = ProtocolResult(
            input_script_path="/tmp/in.lammps",
            expected_outputs=["log.lammps"],
            estimated_steps=100,
            protocol_hash="x",
            stabilization_chain=[],
            e_intra_method="single_molecule_vacuum_adaptive_cutoff",
            vacuum_cutoff_a=80.0,
        )
        assert r.e_intra_method == "single_molecule_vacuum_adaptive_cutoff"
        assert r.vacuum_cutoff_a == 80.0


class TestChampionResolverStrictMode:
    """Codex Round 7: critical paths must fail-closed on registry errors."""

    def test_strict_mode_re_raises_on_registry_failure(self) -> None:
        from unittest.mock import MagicMock

        from api.deps import _resolve_champion_e_intra_method

        # Simulate a registry failure: any session.query() raises.
        broken_session = MagicMock()
        broken_session.query.side_effect = RuntimeError("simulated DB outage")

        # Lax mode: silent baseline (legacy behaviour).
        assert _resolve_champion_e_intra_method(broken_session, strict=False) is None

        # Strict mode: re-raise instead of silent baseline.
        with pytest.raises(RuntimeError, match="champion e_intra_method"):
            _resolve_champion_e_intra_method(broken_session, strict=True)


class TestPipelineImportDecoupling:
    """Codex Round 6: pipeline / non-API workers must not pull in FastAPI."""

    def test_detect_helper_import_does_not_load_scan_database_router(self) -> None:
        # Importing the lightweight detector must not trigger the FastAPI
        # router subtree.  We assert by module bookkeeping rather than
        # uninstalling starlette in this process.
        import importlib
        import sys

        # Force re-import of the detector module so the assertion reflects
        # *its* transitive imports, not whatever earlier tests loaded.
        for mod in list(sys.modules):
            if mod.startswith("features.scan_database"):
                sys.modules.pop(mod, None)
            if mod == "protocols.e_intra_method_detect":
                sys.modules.pop(mod, None)

        importlib.import_module("protocols.e_intra_method_detect")

        bad = [m for m in sys.modules if m.startswith("features.scan_database.router")]
        assert not bad, (
            "Importing protocols.e_intra_method_detect must not pull in "
            f"features.scan_database.router (got {bad})"
        )


class TestContinuousLoopForwardsMethod:
    """Codex Round 6: drift dataset loaders must forward e_intra_method."""

    def test_load_target_dataset_forwards_method(self) -> None:
        from unittest.mock import MagicMock

        from ml.data_loader import TargetVariable
        from orchestrator.continuous_loop import ContinuousLearningLoop

        # Replace the DataLoader instance with a mock so we can inspect args.
        loop = ContinuousLearningLoop(
            MagicMock(), e_intra_method="single_molecule_vacuum_adaptive_cutoff"
        )
        loop._loader = MagicMock()
        loop._loader.load_from_database = MagicMock(return_value=None)

        loop._load_target_dataset(TargetVariable.CED)

        # Ensure the e_intra_method kwarg propagated to the DataLoader call.
        called_kwargs = loop._loader.load_from_database.call_args.kwargs
        assert called_kwargs.get("e_intra_method") == ("single_molecule_vacuum_adaptive_cutoff")


class TestRetrainRequestSupportsMethodOverride:
    """Codex Round 6: explicit method override on the API surface."""

    def test_retrain_request_has_e_intra_method_field(self) -> None:
        from api.schemas.resources import RetrainRequest

        req = RetrainRequest(
            force=True,
            triggered_by="test",
            e_intra_method="single_molecule_vacuum_adaptive_cutoff",
        )
        assert req.e_intra_method == "single_molecule_vacuum_adaptive_cutoff"

    def test_retrain_request_default_is_none(self) -> None:
        from api.schemas.resources import RetrainRequest

        req = RetrainRequest()
        assert req.e_intra_method is None  # → champion auto-inherit


class TestCoverageFallbackPreservesMethod:
    """Codex Round 6: empty-coverage fallback must include the method tag."""

    def test_no_row_fallback_carries_method(self, session: Session) -> None:
        repo = EIntraRepository(session)
        # Insert ONLY Method 1a; ask for Method 1 → no rows but payload must
        # still tag the method that was requested.
        repo.set(
            _key(EIntraMethod.SINGLE_MOLECULE_VACUUM_EXTENDED_CUTOFF),
            EIntraValue(e_intra=-47.0),
        )
        cov = repo.get_coverage_bulk(
            ["U-AS-Test"],
            ff_name="GAFF2",
            ff_version="2.11",
            method=EIntraMethod.SINGLE_MOLECULE_VACUUM,
        )
        assert cov["U-AS-Test"]["method"] == "single_molecule_vacuum"
        assert cov["U-AS-Test"]["computed_count"] == 0


class TestPipelineMethodMismatchWarning:
    """Codex Round 5: drift warning path must reference exp_id_for_lookup,
    not the undefined ``exp_id`` free variable."""

    def test_method_mismatch_warning_uses_exp_id_for_lookup(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging
        import types

        from contracts.schemas import BuildRequest, ProtocolRequest
        from orchestrator.pipeline import Pipeline as _OP  # noqa: F401

        # Synthetic LAMMPS input with extended cutoff (Method 1a),
        # while metadata claims Method 1 — forces the mismatch path.
        in_file = tmp_path / "in.lammps"
        in_file.write_text("# header\npair_style lj/cut/coul/cut 80.0\n")
        log_file = tmp_path / "log.lammps"
        log_file.write_text("# stub\n")

        # Stub LAMMPSRunResult-like object.
        run_result = types.SimpleNamespace(
            log_file=str(log_file),
            exp_id="EXP-DRIFT-001",
            mol_counts={},
            temperature_K=298.0,
            force_field=None,
            ff_version=None,
            study_type="bulk",
            e_intra_method=None,
            vacuum_cutoff_a=None,
        )

        # Stub ProtocolRequest with SINGLE_MOLECULE_VACUUM study_type.
        from contracts.schema_enums import FFType, RunTier, StudyType

        proto = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            pressure_atm=1.0,
            study_type=StudyType.SINGLE_MOLECULE_VACUUM,
            data_file_path=str(tmp_path / "data.lammps"),
        )
        build = BuildRequest(
            composition={"U-AS-Test": 1.0},
            composition_mode="mol_count",
            target_atoms=10,
            seed=1,
            tier=RunTier.SCREENING,
        )

        # Pre-populate metadata as Method 1 to force a mismatch with the
        # input file's Method 1a; we monkeypatch the DB lookup path so the
        # function reads our synthetic metadata directly.

        # Patch session_scope helper used inside _attach_ced_lookup_metadata
        # so the structured-provenance step returns Method 1.
        from contextlib import contextmanager

        class _StubExp:
            metadata_json = {"e_intra_method": "single_molecule_vacuum"}

        class _StubSession:
            def query(self, model):
                return self

            def filter(self, *_a, **_kw):
                return self

            def first(self):
                return _StubExp()

        @contextmanager
        def _stub_session_scope():
            yield _StubSession()

        # The pipeline imports session_scope inside the function body; patch
        # the module the import resolves to.
        from database import connection as _conn_mod

        monkey_session_scope = _conn_mod.session_scope
        _conn_mod.session_scope = _stub_session_scope

        try:
            caplog.set_level(logging.WARNING, logger="orchestrator.pipeline")
            _OP._attach_ced_lookup_metadata(run_result, build, proto)
            # No NameError — drift warning path executed cleanly.
            assert run_result.e_intra_method == "single_molecule_vacuum"
            mismatch_msgs = [r.message for r in caplog.records if "method drift" in r.message]
            assert any("EXP-DRIFT-001" in m for m in mismatch_msgs), (
                "Mismatch warning must include exp_id_for_lookup, "
                "not raise NameError on undefined ``exp_id``."
            )
        finally:
            _conn_mod.session_scope = monkey_session_scope

    def test_missing_provenance_ignores_env_and_uses_method1_baseline(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging
        import types
        from contextlib import contextmanager

        from config import dashboard_settings as _ds_mod
        from contracts.schema_enums import FFType, RunTier, StudyType
        from contracts.schemas import BuildRequest, ProtocolRequest
        from orchestrator.pipeline import Pipeline as _OP

        monkeypatch.setenv("ASPHALT_VACUUM_EXTENDED_CUTOFF", "1")
        monkeypatch.setattr(
            _ds_mod,
            "load_dashboard_settings",
            lambda: {"default_e_intra_method": "single_molecule_vacuum_adaptive_cutoff"},
        )

        log_file = tmp_path / "log.lammps"
        log_file.write_text("# no input companion\n", encoding="utf-8")

        run_result = types.SimpleNamespace(
            log_file=str(log_file),
            exp_id="EXP-NO-PROV-001",
            mol_counts={},
            temperature_K=298.0,
            force_field=None,
            ff_version=None,
            study_type="bulk",
            e_intra_method=None,
            vacuum_cutoff_a=None,
        )

        proto = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            pressure_atm=1.0,
            study_type=StudyType.SINGLE_MOLECULE_VACUUM,
            data_file_path=str(tmp_path / "missing.data"),
        )
        build = BuildRequest(
            composition={"U-AS-Test": 1.0},
            composition_mode="mol_count",
            target_atoms=10,
            seed=1,
            tier=RunTier.SCREENING,
        )

        class _EmptySession:
            def query(self, model):
                return self

            def filter(self, *_a, **_kw):
                return self

            def first(self):
                return None

        @contextmanager
        def _stub_session_scope():
            yield _EmptySession()

        from database import connection as _conn_mod

        monkey_session_scope = _conn_mod.session_scope
        _conn_mod.session_scope = _stub_session_scope

        try:
            caplog.set_level(logging.WARNING, logger="orchestrator.pipeline")
            _OP._attach_ced_lookup_metadata(run_result, build, proto)
            assert run_result.e_intra_method == "single_molecule_vacuum"
            assert run_result.vacuum_cutoff_a == 12.0
            assert any(
                "ambient env/settings fallback" in record.message for record in caplog.records
            )
        finally:
            _conn_mod.session_scope = monkey_session_scope


class TestChampionMethodAutoInherit:
    """Codex Round 5: get_model_retrainer must auto-inherit champion method."""

    def test_get_model_retrainer_uses_champion_method(self, tmp_path: Path) -> None:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from api.deps import _resolve_champion_e_intra_method
        from database.models import Base, MLModelVersionModel

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        S = sessionmaker(bind=engine)()

        # Insert a champion row tagged with Method 1a.
        champion = MLModelVersionModel(
            version_id="v_test_1",
            model_type="multi_target",
            target_names=["density"],
            feature_set_version="V1",
            status="champion",
            training_samples=10,
            training_seed=42,
            training_config_json={"e_intra_method": "single_molecule_vacuum_adaptive_cutoff"},
            model_artifact_path=str(tmp_path),
        )
        S.add(champion)
        S.commit()

        resolved = _resolve_champion_e_intra_method(S)
        assert resolved == "single_molecule_vacuum_adaptive_cutoff"


class TestCoveragePayloadIncludesMethod:
    """Codex Round 4: coverage payload must carry the method tag."""

    def test_get_coverage_payload_has_method(self, session: Session) -> None:
        repo = EIntraRepository(session)
        repo.set(_key(EIntraMethod.SINGLE_MOLECULE_VACUUM), EIntraValue(e_intra=-45.2))
        cov = repo.get_coverage(
            "U-AS-Test",
            ff_name="GAFF2",
            ff_version="2.11",
            method=EIntraMethod.SINGLE_MOLECULE_VACUUM,
        )
        assert cov["method"] == "single_molecule_vacuum"

    def test_get_coverage_bulk_payload_has_method(self, session: Session) -> None:
        repo = EIntraRepository(session)
        repo.set(
            _key(EIntraMethod.SINGLE_MOLECULE_VACUUM_EXTENDED_CUTOFF),
            EIntraValue(e_intra=-47.0),
        )
        cov = repo.get_coverage_bulk(
            ["U-AS-Test"],
            ff_name="GAFF2",
            ff_version="2.11",
            method=EIntraMethod.SINGLE_MOLECULE_VACUUM_EXTENDED_CUTOFF,
        )
        assert cov["U-AS-Test"]["method"] == "single_molecule_vacuum_adaptive_cutoff"

    def test_get_coverage_accepts_legacy_method_1a_alias_rows(self, session: Session) -> None:
        repo = EIntraRepository(session)
        repo.set(
            _key(EIntraMethod.SINGLE_MOLECULE_VACUUM_EXTENDED_CUTOFF),
            EIntraValue(e_intra=-47.0),
        )

        cov = repo.get_coverage(
            "U-AS-Test",
            ff_name="GAFF2",
            ff_version="2.11",
            required_temperatures=[298.0],
            method=EIntraMethod.SINGLE_MOLECULE_VACUUM_EXTENDED_CUTOFF,
        )

        assert cov["computed_count"] == 1
        assert cov["needs_calc"] is False
        assert cov["latest_values_by_temperature"][298.0] == pytest.approx(-47.0)

    def test_get_coverage_bulk_accepts_legacy_method_1a_alias_rows(self, session: Session) -> None:
        repo = EIntraRepository(session)
        repo.set(
            _key(EIntraMethod.SINGLE_MOLECULE_VACUUM_EXTENDED_CUTOFF),
            EIntraValue(e_intra=-47.0),
        )

        cov = repo.get_coverage_bulk(
            ["U-AS-Test"],
            ff_name="GAFF2",
            ff_version="2.11",
            required_temperatures=[298.0],
            method=EIntraMethod.SINGLE_MOLECULE_VACUUM_EXTENDED_CUTOFF,
        )

        assert cov["U-AS-Test"]["computed_count"] == 1
        assert cov["U-AS-Test"]["needs_calc"] is False
        assert cov["U-AS-Test"]["latest_values_by_temperature"][298.0] == pytest.approx(-47.0)


class TestModelLineageRecordsMethod:
    """Codex Round 4: model registry row must persist e_intra_method."""

    def test_register_model_writes_training_config(self, tmp_path: Path) -> None:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from database.models import Base
        from ml.model_registry import ModelRegistry

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        S = sessionmaker(bind=engine)()

        # Minimal stub predictor — only needs ``fitted_targets`` and ``save``.
        class _Stub:
            fitted_targets = ["density", "cohesive_energy_density"]
            _feature_schema_hash = "x"
            _capability_manifest = {}

            def save(self, model_dir):  # type: ignore[no-untyped-def]
                from pathlib import Path as _Path

                _Path(model_dir).mkdir(parents=True, exist_ok=True)

        registry = ModelRegistry(S)
        # Redirect artefact dir to tmp_path (avoid writing under repo root).
        registry._base_dir = tmp_path  # type: ignore[attr-defined]
        row = registry.register_model(
            _Stub(),
            feature_set_version="V1",
            training_samples=10,
            training_seed=42,
            e_intra_method="single_molecule_vacuum_adaptive_cutoff",
        )
        S.flush()

        cfg = row.training_config_json or {}
        assert cfg.get("e_intra_method") == "single_molecule_vacuum_adaptive_cutoff"


class TestSubmissionMethodSchemas:
    """Submission-edge request schemas must accept and preserve method override."""

    def test_experiment_request_accepts_e_intra_method(self) -> None:
        from api.schemas.experiments import CompositionRequest, ExperimentRequest

        req = ExperimentRequest(
            composition=CompositionRequest(
                asphaltene_wt=0.2,
                resin_wt=0.3,
                aromatic_wt=0.35,
                saturate_wt=0.15,
            ),
            e_intra_method="single_molecule_vacuum_adaptive_cutoff",
        )
        assert req.e_intra_method == "single_molecule_vacuum_adaptive_cutoff"

    def test_molecule_experiment_request_accepts_e_intra_method(self) -> None:
        from api.schemas.experiments import MoleculeExperimentRequest

        req = MoleculeExperimentRequest(
            binder_type="AAA1",
            structure_size="X1",
            aging_state="non_aging",
            molecule_counts=[{"mol_id": "U-AS-Test", "count": 1}],
            e_intra_method="single_molecule_vacuum_adaptive_cutoff",
        )
        assert req.e_intra_method == "single_molecule_vacuum_adaptive_cutoff"


class TestSubmissionMethodResolver:
    """settings.json default is the submission default for new jobs."""

    def test_resolver_prefers_request_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from config import dashboard_settings as ds

        monkeypatch.setattr(
            ds,
            "load_dashboard_settings",
            lambda: {"default_e_intra_method": "single_molecule_vacuum"},
        )

        assert (
            ds.resolve_submission_e_intra_method("single_molecule_vacuum_adaptive_cutoff")
            == EIntraMethod.SINGLE_MOLECULE_VACUUM_EXTENDED_CUTOFF
        )

    def test_resolver_uses_settings_default_before_env_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from config import dashboard_settings as ds
        from protocols import lammps_force_field as lff

        monkeypatch.setattr(
            ds,
            "load_dashboard_settings",
            lambda: {"default_e_intra_method": "single_molecule_vacuum_adaptive_cutoff"},
        )
        monkeypatch.setattr(lff, "vacuum_extended_cutoff_enabled", lambda: False)

        assert ds.resolve_submission_e_intra_method() == (
            EIntraMethod.SINGLE_MOLECULE_VACUUM_EXTENDED_CUTOFF
        )

    def test_resolver_ignores_reserved_periodic_in_settings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from config import dashboard_settings as ds
        from protocols import lammps_force_field as lff

        monkeypatch.setattr(
            ds,
            "load_dashboard_settings",
            lambda: {"default_e_intra_method": "single_molecule_periodic"},
        )
        monkeypatch.setattr(lff, "vacuum_extended_cutoff_enabled", lambda: False)

        assert ds.resolve_submission_e_intra_method() == EIntraMethod.SINGLE_MOLECULE_VACUUM


class TestPublicSubmissionMethodValidation:
    """Public submit/settings schemas must reject reserved Method 2."""

    @pytest.mark.parametrize(
        ("builder", "field_name"),
        [
            (
                lambda: __import__(
                    "api.schemas.resources", fromlist=["SettingsUpdateRequest"]
                ).SettingsUpdateRequest(default_e_intra_method="single_molecule_periodic"),
                "default_e_intra_method",
            ),
            (
                lambda: __import__(
                    "api.schemas.experiments", fromlist=["ExperimentRequest", "CompositionRequest"]
                ).ExperimentRequest(
                    composition=__import__(
                        "api.schemas.experiments",
                        fromlist=["CompositionRequest"],
                    ).CompositionRequest(),
                    e_intra_method="single_molecule_periodic",
                ),
                "e_intra_method",
            ),
            (
                lambda: __import__(
                    "api.schemas.experiments", fromlist=["MoleculeExperimentRequest"]
                ).MoleculeExperimentRequest(
                    binder_type="AAA1",
                    structure_size="X1",
                    aging_state="non_aging",
                    molecule_counts=[{"mol_id": "U-AS-Test", "count": 1}],
                    e_intra_method="single_molecule_periodic",
                ),
                "e_intra_method",
            ),
            (
                lambda: __import__(
                    "api.schemas.experiments", fromlist=["BatchJobBinderCellRequest"]
                ).BatchJobBinderCellRequest(
                    binder_type="AAA1",
                    structure_size="X1",
                    aging_state="non_aging",
                    additives=[],
                    job_name="job",
                    scenario_label="scenario",
                    temperatures_k=[298.0],
                    e_intra_method="single_molecule_periodic",
                ),
                "e_intra_method",
            ),
            (
                lambda: __import__(
                    "api.schemas.experiments", fromlist=["SingleMoleculeBatchRequest"]
                ).SingleMoleculeBatchRequest(
                    mol_ids=["U-AS-Test"],
                    temperatures_k=[298.0],
                    e_intra_method="single_molecule_periodic",
                ),
                "e_intra_method",
            ),
            (
                lambda: __import__(
                    "api.schemas.structures",
                    fromlist=["LayeredStructureSubmitRequest", "LayerStackItemRequest"],
                ).LayeredStructureSubmitRequest(
                    layers=[
                        __import__(
                            "api.schemas.structures",
                            fromlist=["LayerStackItemRequest"],
                        ).LayerStackItemRequest(source_type="binder_cell", source_id="binder_001"),
                        __import__(
                            "api.schemas.structures",
                            fromlist=["LayerStackItemRequest"],
                        ).LayerStackItemRequest(
                            source_type="interface_molecule_cell",
                            source_id="iface_001",
                        ),
                    ],
                    e_intra_method="single_molecule_periodic",
                ),
                "e_intra_method",
            ),
        ],
    )
    def test_public_request_models_reject_periodic(self, builder, field_name: str) -> None:
        with pytest.raises(ValueError, match="single_molecule_periodic"):
            builder()


class TestMLDataLoaderForwardsMethod:
    """Codex Round 3: dataset_router → DataLoader must forward e_intra_method."""

    def test_dataset_router_signature_accepts_method(self) -> None:
        import inspect as _inspect

        from ml.dataset_router import load_training_dataset

        sig = _inspect.signature(load_training_dataset)
        assert "e_intra_method" in sig.parameters

    def test_data_loader_signature_accepts_method(self) -> None:
        import inspect as _inspect

        from ml.data_loader import DataLoader

        sig = _inspect.signature(DataLoader.load_from_database)
        assert "e_intra_method" in sig.parameters

    def test_retrainer_constructor_accepts_method(self) -> None:
        import inspect as _inspect

        from ml.retrainer import ModelRetrainer

        sig = _inspect.signature(ModelRetrainer.__init__)
        assert "e_intra_method" in sig.parameters


class TestBulkCEDExplicitMethodResolution:
    """Codex Round 3: bulk CED must resolve method from explicit data, not env."""

    def test_calculator_accepts_bulk_method_override(self) -> None:
        from metrics.calculator import MetricCalculator

        calc = MetricCalculator(bulk_e_intra_method="single_molecule_vacuum_adaptive_cutoff")
        assert calc.bulk_e_intra_method == "single_molecule_vacuum_adaptive_cutoff"


class TestEngineSettingsPostMigration:
    """Codex Round 3 regression: post-migration engine must keep canonical
    SQLite settings (StaticPool + check_same_thread=False + FK pragma)."""

    def test_post_migration_engine_uses_static_pool_and_fk(self, tmp_path: Path) -> None:
        import sqlite3

        from sqlalchemy.pool import StaticPool

        db = tmp_path / "legacy.db"
        # Build legacy 4-column DB (forces auto-migration path).
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE molecules ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "mol_id VARCHAR(100) NOT NULL UNIQUE)"
        )
        conn.execute(
            """
            CREATE TABLE e_intra (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                molecule_id INTEGER,
                mol_id VARCHAR(100) NOT NULL,
                ff_name VARCHAR(50) NOT NULL,
                ff_version VARCHAR(20) NOT NULL,
                temperature_K FLOAT NOT NULL DEFAULT 298.0,
                e_intra FLOAT NOT NULL,
                e_components TEXT,
                created_at DATETIME,
                updated_at DATETIME,
                CONSTRAINT uq_e_intra_temp UNIQUE
                    (mol_id, ff_name, ff_version, temperature_K)
            )
            """
        )
        conn.commit()
        conn.close()

        from database.connection import close_db, get_engine, init_db

        try:
            init_db(f"sqlite:///{db}")
            eng = get_engine()
            assert isinstance(eng.pool, StaticPool), (
                f"Engine pool regressed to {type(eng.pool).__name__} "
                "after auto-migration; must remain StaticPool."
            )
            with eng.connect() as c:
                fk = c.exec_driver_sql("PRAGMA foreign_keys").scalar()
            assert fk == 1, "PRAGMA foreign_keys must be ON after auto-migration."
        finally:
            close_db()


class TestAutoMigrationOnInitDB:
    """init_db() must rebuild a 4-column legacy SQLite to 5-column UC."""

    def test_legacy_db_auto_migrates_via_init_db(self, tmp_path: Path) -> None:
        import sqlite3

        # Build legacy 4-column DB with one row.
        db_path = tmp_path / "legacy.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE molecules ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "mol_id VARCHAR(100) NOT NULL UNIQUE)"
        )
        conn.execute(
            """
            CREATE TABLE e_intra (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                molecule_id INTEGER,
                mol_id VARCHAR(100) NOT NULL,
                ff_name VARCHAR(50) NOT NULL,
                ff_version VARCHAR(20) NOT NULL,
                temperature_K FLOAT NOT NULL DEFAULT 298.0,
                e_intra FLOAT NOT NULL,
                e_components TEXT,
                minimization_steps INTEGER,
                source_exp_id VARCHAR(100),
                averaging_window_ps FLOAT,
                n_samples INTEGER,
                created_at DATETIME,
                updated_at DATETIME,
                CONSTRAINT uq_e_intra_temp UNIQUE
                    (mol_id, ff_name, ff_version, temperature_K)
            )
            """
        )
        conn.execute(
            "INSERT INTO e_intra "
            "(mol_id, ff_name, ff_version, temperature_K, e_intra) "
            "VALUES (?,?,?,?,?)",
            ("U-AS", "GAFF2", "2.11", 298.0, -45.2),
        )
        conn.commit()
        conn.close()

        from database.connection import close_db, init_db
        from scripts.migrate_e_intra_method import diagnose

        url = f"sqlite:///{db_path}"
        try:
            init_db(url)
            d = diagnose(db_path)
            assert d.has_method_column is True
            assert d.has_correct_unique is True
        finally:
            close_db()
