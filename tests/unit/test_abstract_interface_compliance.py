"""
Tests for abstract interface compliance.

Verifies that implementation classes properly inherit from their
Abstract Base Classes and implement all required interface methods.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


# ── MetricRepository ──────────────────────────────────────────────


class TestMetricRepositoryInheritance:
    def test_inherits_abstract(self):
        from contracts.interfaces import AbstractMetricRepository
        from database.repositories.metric_repo import MetricRepository

        session = MagicMock()
        repo = MetricRepository(session)
        assert isinstance(repo, AbstractMetricRepository)

    def test_implements_save(self):
        from database.repositories.metric_repo import MetricRepository

        repo = MetricRepository(MagicMock())
        assert hasattr(repo, "save")
        assert callable(repo.save)

    def test_implements_save_batch(self):
        from database.repositories.metric_repo import MetricRepository

        repo = MetricRepository(MagicMock())
        assert hasattr(repo, "save_batch")
        assert callable(repo.save_batch)

    def test_implements_get_by_exp(self):
        from database.repositories.metric_repo import MetricRepository

        repo = MetricRepository(MagicMock())
        assert hasattr(repo, "get_by_exp")
        assert callable(repo.get_by_exp)


# ── LogParser ─────────────────────────────────────────────────────


class TestLogParserInheritance:
    def test_inherits_abstract(self):
        from contracts.interfaces import AbstractLogParser
        from parsers.log_parser import LogParser

        parser = LogParser()
        assert isinstance(parser, AbstractLogParser)

    def test_extract_final_values_from_file(self, tmp_path):
        from parsers.log_parser import LogParser

        log_content = (
            "LAMMPS version 2025Jun\n"
            "Step Temp Press Density\n"
            "0 300.0 1.0 0.95\n"
            "100 298.5 0.98 0.96\n"
            "200 299.0 1.01 0.965\n"
            "Loop time of 10.5\n"
            "Total wall time: 0:00:10\n"
        )
        log_file = tmp_path / "log.lammps"
        log_file.write_text(log_content)

        parser = LogParser()
        result = parser.extract_final_values(str(log_file))

        assert isinstance(result, dict)
        assert "Step" in result
        assert result["Step"] == 200.0
        assert "Density" in result
        assert result["Density"] == pytest.approx(0.965)

    def test_extract_final_values_missing_file(self, tmp_path):
        from parsers.log_parser import LogParser

        parser = LogParser()
        result = parser.extract_final_values(str(tmp_path / "nonexistent.log"))
        assert isinstance(result, dict)


# ── EIntraStore ───────────────────────────────────────────────────


class TestEIntraStoreInheritance:
    @pytest.fixture
    def store(self, tmp_path):
        from metrics.e_intra_store import EIntraStore

        return EIntraStore(cache_dir=tmp_path)

    def test_inherits_abstract(self, store):
        from contracts.interfaces import AbstractEIntraStore

        assert isinstance(store, AbstractEIntraStore)

    def test_put_delegates_to_set(self, store):
        from contracts.schemas import EIntraKey, EIntraValue

        key = EIntraKey(mol_id="SAT_001", ff_name="GAFF2", ff_version="1.0")
        value = EIntraValue(e_intra=-50.0)

        store.put(key, value)
        retrieved = store.get(key)
        assert retrieved is not None
        assert retrieved.e_intra == -50.0

    def test_has_delegates_to_exists(self, store):
        from contracts.schemas import EIntraKey, EIntraValue

        key = EIntraKey(mol_id="ARO_001", ff_name="GAFF2", ff_version="1.0")
        assert not store.has(key)

        store.put(key, EIntraValue(e_intra=-30.0))
        assert store.has(key)

    def test_list_keys_empty(self, store):
        keys = store.list_keys()
        assert keys == []

    def test_list_keys_after_set(self, store):
        from contracts.schemas import EIntraKey, EIntraValue

        key1 = EIntraKey(mol_id="SAT_001", ff_name="GAFF2", ff_version="1.0")
        key2 = EIntraKey(
            mol_id="ARO_001",
            ff_name="GAFF2",
            ff_version="1.0",
            method="single_molecule_vacuum",
        )

        store.set(key1, EIntraValue(e_intra=-50.0))
        store.set(key2, EIntraValue(e_intra=-30.0))

        keys = store.list_keys()
        assert len(keys) == 2
        mol_ids = {k.mol_id for k in keys}
        assert mol_ids == {"SAT_001", "ARO_001"}

    def test_list_keys_after_delete(self, store):
        from contracts.schemas import EIntraKey, EIntraValue

        key = EIntraKey(mol_id="SAT_001", ff_name="GAFF2", ff_version="1.0")
        store.set(key, EIntraValue(e_intra=-50.0))
        assert len(store.list_keys()) == 1

        store.delete(key)
        assert len(store.list_keys()) == 0

    def test_key_registry_persisted(self, tmp_path):
        """Verify _key_registry survives save/reload cycle."""
        from contracts.schemas import EIntraKey, EIntraValue
        from metrics.e_intra_store import EIntraStore

        store1 = EIntraStore(cache_dir=tmp_path)
        key = EIntraKey(mol_id="RES_001", ff_name="GAFF2", ff_version="1.0")
        store1.set(key, EIntraValue(e_intra=-40.0))

        # Create new store instance (reloads from disk)
        store2 = EIntraStore(cache_dir=tmp_path)
        keys = store2.list_keys()
        assert len(keys) == 1
        assert keys[0].mol_id == "RES_001"

    def test_legacy_cache_without_keys(self, tmp_path):
        """Old cache files without 'keys' field should still work."""
        cache_file = tmp_path / "e_intra_cache.json"
        cache_file.write_text(
            json.dumps(
                {
                    "updated_at": "2026-01-01",
                    "values": {"SAT_001_GAFF2_1.0_single_molecule_vacuum": -50.0},
                }
            )
        )

        from metrics.e_intra_store import EIntraStore

        store = EIntraStore(cache_dir=tmp_path)

        # Value should be loaded
        from contracts.schemas import EIntraKey

        key = EIntraKey(mol_id="SAT_001", ff_name="GAFF2", ff_version="1.0")
        val = store.get(key)
        assert val is not None
        assert val.e_intra == -50.0

        # But list_keys() should be empty (no registry for legacy entries)
        assert store.list_keys() == []


# ── LAMMPSRunner ──────────────────────────────────────────────────


class TestLAMMPSRunnerInheritance:
    def test_inherits_abstract(self):
        from contracts.interfaces import AbstractLAMMPSRunner
        from orchestrator.lammps_runner import LAMMPSRunner

        runner = LAMMPSRunner()
        assert isinstance(runner, AbstractLAMMPSRunner)

    def test_mock_inherits_abstract(self):
        from contracts.interfaces import AbstractLAMMPSRunner
        from orchestrator.lammps_runner import MockLAMMPSRunner

        runner = MockLAMMPSRunner()
        assert isinstance(runner, AbstractLAMMPSRunner)

    def test_mock_check_available(self):
        from orchestrator.lammps_runner import MockLAMMPSRunner

        runner = MockLAMMPSRunner()
        assert runner.check_lammps_available() is True

    def test_mock_get_version(self):
        from orchestrator.lammps_runner import MockLAMMPSRunner

        runner = MockLAMMPSRunner()
        assert "Mock" in runner.get_lammps_version()

    def test_run_signature_accepts_timeout(self):
        """Verify run() accepts timeout parameter."""
        from orchestrator.lammps_runner import MockLAMMPSRunner

        runner = MockLAMMPSRunner()
        pr = MagicMock()
        pr.input_script_path = "/mock/input.lmp"
        result = runner.run(pr, timeout=300)
        assert result.success is True


# ── ExperimentRepository ──────────────────────────────────────────


class TestExperimentRepositoryInheritance:
    @pytest.fixture
    def mock_session(self):
        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = None
        session.query.return_value.filter.return_value.all.return_value = []
        return session

    def test_inherits_abstract(self, mock_session):
        from contracts.interfaces import AbstractExperimentRepository
        from database.repositories.experiment_repo import ExperimentRepository

        repo = ExperimentRepository(mock_session)
        assert isinstance(repo, AbstractExperimentRepository)

    def test_get_returns_none_for_missing(self, mock_session):
        from database.repositories.experiment_repo import ExperimentRepository

        repo = ExperimentRepository(mock_session)
        result = repo.get("nonexistent")
        assert result is None

    def test_find_by_status_returns_list(self, mock_session):
        from database.repositories.experiment_repo import ExperimentRepository

        repo = ExperimentRepository(mock_session)
        result = repo.find_by_status("completed")
        assert isinstance(result, list)
        assert len(result) == 0

    def test_find_by_tier_returns_list(self, mock_session):
        from database.repositories.experiment_repo import ExperimentRepository

        repo = ExperimentRepository(mock_session)
        result = repo.find_by_tier("screening")
        assert isinstance(result, list)
        assert len(result) == 0

    def test_model_to_record_conversion(self, mock_session):
        from contracts.schemas import ExperimentRecord
        from database.repositories.experiment_repo import ExperimentRepository

        repo = ExperimentRepository(mock_session)

        model = MagicMock()
        model.exp_id = "binderA_bulk_ff_screening_T298K"
        model.ff_type = "bulk_ff_gaff2"
        model.run_tier = "screening"
        model.study_type = "bulk"
        model.status = "completed"
        model.temperature_K = 298.0
        model.pressure_atm = 1.0
        model.target_atoms = 100000
        model.additive_type = None
        model.additive_wt = 0.0
        model.additive_mol_id = None
        model.failure_category = None
        # v00.99.03 experiment contract fields
        model.force_field_name = "GAFF2"
        model.force_field_version = "1.0"
        model.aging_state = "non_aging"
        model.selection_reason_json = {}
        model.metadata_json = {}

        record = repo._model_to_record(model)
        assert isinstance(record, ExperimentRecord)
        assert record.exp_id == "binderA_bulk_ff_screening_T298K"

    def test_save_returns_string(self, mock_session):
        from database.repositories.experiment_repo import ExperimentRepository

        repo = ExperimentRepository(mock_session)
        result = repo.save({"exp_id": "test_001", "status": "pending"})
        assert isinstance(result, str)


# ── MoleculeRepository ────────────────────────────────────────────


class TestMoleculeRepositoryInheritance:
    @pytest.fixture
    def mock_session(self):
        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = None
        session.query.return_value.filter.return_value.all.return_value = []
        session.query.return_value.all.return_value = []
        return session

    def test_inherits_abstract(self, mock_session):
        from contracts.interfaces import AbstractMoleculeRepository
        from database.repositories.molecule_repo import MoleculeRepository

        repo = MoleculeRepository(mock_session)
        assert isinstance(repo, AbstractMoleculeRepository)

    def test_get_returns_none_for_missing(self, mock_session):
        from database.repositories.molecule_repo import MoleculeRepository

        repo = MoleculeRepository(mock_session)
        result = repo.get("nonexistent_mol")
        assert result is None

    def test_get_by_category_returns_list(self, mock_session):
        from database.repositories.molecule_repo import MoleculeRepository

        repo = MoleculeRepository(mock_session)
        result = repo.get_by_category("saturate")
        assert isinstance(result, list)

    def test_list_all_returns_specs(self, mock_session):
        from database.repositories.molecule_repo import MoleculeRepository

        repo = MoleculeRepository(mock_session)
        result = repo.list_all()
        assert isinstance(result, list)

    def test_model_to_spec_conversion(self, mock_session):
        from contracts.schemas import MoleculeSpec
        from database.repositories.molecule_repo import MoleculeRepository

        repo = MoleculeRepository(mock_session)

        model = MagicMock(spec=[])
        model.mol_id = "SAT_001"
        model.smiles = "CCCCCCCCCCCCCCCC"
        model.molecular_weight = 226.44
        model.num_atoms = 50
        model.sara_type = "saturate"
        del model.structure_file
        del model.topology_hash

        spec = repo._model_to_spec(model)
        assert isinstance(spec, MoleculeSpec)
        assert spec.mol_id == "SAT_001"
        assert spec.molecular_weight == 226.44

    def test_model_to_spec_null_fallback(self, mock_session):
        """Null DB fields should use fallback values, not fail."""
        from contracts.schemas import MoleculeSpec
        from database.repositories.molecule_repo import MoleculeRepository

        repo = MoleculeRepository(mock_session)

        model = MagicMock(spec=[])
        model.mol_id = "UNKNOWN"
        model.smiles = ""
        model.molecular_weight = None
        model.num_atoms = None
        model.sara_type = None
        del model.structure_file
        del model.topology_hash

        spec = repo._model_to_spec(model)
        assert isinstance(spec, MoleculeSpec)
        assert spec.molecular_weight == 1.0  # fallback
        assert spec.atom_count == 1  # fallback


# ── ArrayStorage ──────────────────────────────────────────────────


class TestArrayStorageInheritance:
    @pytest.fixture
    def storage(self, tmp_path, monkeypatch):
        import metrics.array_storage as mod

        monkeypatch.setattr(mod, "HAS_PARQUET", False)

        # Allow tmp_path (outside project root) to pass workspace path validation
        monkeypatch.setattr(
            "features.common.workspace.resolve_workspace_path",
            lambda p: Path(p).resolve(),
        )

        from metrics.array_storage import ArrayStorage

        return ArrayStorage(storage_dir=tmp_path)

    @pytest.fixture
    def sample_data(self):
        return {
            "r": [1.0, 2.0, 3.0, 4.0, 5.0],
            "g_r": [0.0, 0.5, 1.2, 0.8, 0.3],
        }

    def test_inherits_abstract(self, storage):
        from contracts.interfaces import AbstractArrayStorage

        assert isinstance(storage, AbstractArrayStorage)

    def test_save_returns_descriptor(self, storage, sample_data):
        from contracts.schemas import ArrayMetricStorage

        result = storage.save("exp_100", "rdf_curve", sample_data)
        assert isinstance(result, ArrayMetricStorage)
        assert result.shape == (5, 2)

    def test_load_by_path(self, storage, sample_data):
        """Test path-based load (AbstractArrayStorage interface)."""
        result = storage.save("exp_101", "rdf_curve", sample_data)
        loaded = storage.load(result.file_path)
        assert loaded is not None
        assert loaded["r"] == sample_data["r"]

    def test_load_legacy_key_based(self, storage, sample_data):
        """Test key-based load (legacy signature)."""
        storage.store("rdf_curve", "exp_102", sample_data)
        loaded = storage.load("rdf_curve", "exp_102")
        assert loaded is not None
        assert loaded["g_r"] == sample_data["g_r"]

    def test_delete_by_path(self, storage, sample_data, tmp_path):
        """Test path-based delete (AbstractArrayStorage interface)."""
        result = storage.save("exp_103", "rdf_curve", sample_data)
        assert Path(result.file_path).exists()

        storage.delete(result.file_path)
        assert not Path(result.file_path).exists()

    def test_delete_legacy_key_based(self, storage, sample_data):
        """Test key-based delete (legacy signature)."""
        storage.store("rdf_curve", "exp_104", sample_data)
        assert storage.exists("rdf_curve", "exp_104")

        storage.delete("rdf_curve", "exp_104")
        assert not storage.exists("rdf_curve", "exp_104")

    def test_load_nonexistent_path(self, storage):
        """Path-based load with missing file returns None."""
        result = storage.load("/nonexistent/file.json")
        assert result is None
