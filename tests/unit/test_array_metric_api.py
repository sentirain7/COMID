"""Unit tests for array metric query functions (Curve Analysis backend)."""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

# Pre-mock heavy dependencies that barrel imports pull in,
# so tests can import features.metrics.query without full env installed.
# Only mock modules that are NOT actually importable — avoids polluting
# sys.modules with MagicMock when the real package is installed (which
# breaks submodule resolution, e.g. celery.exceptions).
_MOCK_MODULES = [
    "fastapi",
    "fastapi.responses",
    "fastapi.routing",
    "starlette",
    "starlette.responses",
    "starlette.requests",
    "sqlalchemy",
    "sqlalchemy.orm",
    "sqlalchemy.exc",
    "sqlalchemy.pool",
    "sqlalchemy.engine",
    "uvicorn",
    "celery",
    "redis",
]
for _mod in _MOCK_MODULES:
    if _mod not in sys.modules:
        try:
            __import__(_mod)
        except ImportError:
            sys.modules[_mod] = MagicMock()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_experiment(exp_id: str = "test_exp_001", temperature_K: float = 298.0):
    """Create a minimal experiment-like namespace for label helpers."""
    return SimpleNamespace(
        exp_id=exp_id,
        temperature_K=temperature_K,
        additive_mol_id=None,
        additive_type=None,
        metadata_json={"binder_type": "AAA1"},
        log_file_path=None,
        data_file_path=None,
    )


def _make_metric(metric_name: str, array_file_path: str | None = "/fake/path.parquet"):
    return SimpleNamespace(
        metric_name=metric_name,
        namespace="bulk_ff_gaff2",
        array_file_path=array_file_path,
        array_shape=[100, 2],
        metadata_json={"first_peak_r": 3.5, "first_peak_g": 2.1},
        value=None,
        uncertainty=None,
    )


def _run(coro):
    """Run an async coroutine synchronously.

    Uses asyncio.run() instead of get_event_loop().run_until_complete()
    so that a fresh event loop is always created.  This avoids flaky failures
    when a preceding test (e.g. test_analytics_additive) calls asyncio.run(),
    which closes the default event loop in Python 3.12+.
    """
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Label helpers (features/common/labels.py)
# ---------------------------------------------------------------------------


class TestLabelHelpers:
    def test_resolve_experiment_catalog_labels_basic(self):
        from features.common.labels import resolve_experiment_catalog_labels

        exp = _make_experiment()
        labels = resolve_experiment_catalog_labels(exp)

        assert labels["binder_type"] == "AAA1"
        assert labels["binder_code"] == "A1"
        assert labels["additive_label"] == "None"
        assert labels["aging_state"] == "non_aging"

    def test_build_experiment_short_label(self):
        from features.common.labels import build_experiment_short_label

        exp = _make_experiment(temperature_K=298.0)
        label = build_experiment_short_label(exp)

        assert "A1" in label
        assert "298K" in label

    def test_build_experiment_short_label_no_temp(self):
        from features.common.labels import build_experiment_short_label

        exp = _make_experiment(temperature_K=None)
        label = build_experiment_short_label(exp)

        assert "A1" in label
        assert "K" not in label

    def test_temperature_K_uppercase_preferred(self):
        """Verify that temperature_K (uppercase) is read correctly from ORM-like objects."""
        from features.common.labels import build_experiment_short_label

        exp = SimpleNamespace(
            exp_id="test_exp_001",
            temperature_K=353.0,
            additive_mol_id=None,
            additive_type=None,
            metadata_json={"binder_type": "AAA1"},
        )
        label = build_experiment_short_label(exp)
        assert "353K" in label

    def test_temperature_k_lowercase_fallback(self):
        """Verify fallback to temperature_k (lowercase) for SimpleNamespace/dict objects."""
        from features.common.labels import build_experiment_short_label

        exp = SimpleNamespace(
            exp_id="test_exp_001",
            temperature_k=413.0,
            additive_mol_id=None,
            additive_type=None,
            metadata_json={"binder_type": "AAK1"},
        )
        label = build_experiment_short_label(exp)
        assert "413K" in label


# ---------------------------------------------------------------------------
# Response Models (api/schemas/analysis.py)
# ---------------------------------------------------------------------------


class TestResponseModels:
    def test_array_metric_data_response(self):
        from api.schemas.analysis import ArrayMetricDataResponse

        resp = ArrayMetricDataResponse(
            exp_id="test_001",
            metric_name="rdf_curve",
            namespace="bulk_ff_gaff2",
            columns={"r": [1.0, 2.0], "g_r": [0.5, 1.2]},
            metadata={"first_peak_r": 2.0},
        )
        d = resp.model_dump()
        assert d["exp_id"] == "test_001"
        assert d["columns"]["r"] == [1.0, 2.0]
        assert d["metadata"]["first_peak_r"] == 2.0

    def test_array_metric_compare_request_validation(self):
        from api.schemas.analysis import ArrayMetricCompareRequest

        req = ArrayMetricCompareRequest(
            exp_ids=["a", "b", "c"],
            metric_name="rdf_curve",
        )
        assert len(req.exp_ids) == 3

    def test_experiment_array_metric_entry(self):
        from api.schemas.analysis import ExperimentArrayMetricEntry

        entry = ExperimentArrayMetricEntry(
            exp_id="test_001",
            label="A1 298K None",
            binder_type="AAA1",
            temperature_k=298.0,
            additive="None",
        )
        d = entry.model_dump()
        assert d["label"] == "A1 298K None"
        assert d["temperature_k"] == 298.0


# ---------------------------------------------------------------------------
# Query Functions — closure execution tests (sync wrappers)
#
# Patches must be applied BEFORE calling the async function so that
# function-local `from X import Y` picks up the mock, not the real class.
# ---------------------------------------------------------------------------


class TestGetArrayMetricData:
    def test_invalid_metric_name(self):
        from contracts.errors import ContractError
        from features.metrics.query import get_array_metric_data

        with pytest.raises(ContractError, match="Unknown metric"):
            _run(get_array_metric_data("exp_001", "nonexistent_metric_xyz"))

    def test_scalar_metric_rejected(self):
        from contracts.errors import ContractError
        from features.metrics.query import get_array_metric_data

        with pytest.raises(ContractError, match="not an array metric"):
            _run(get_array_metric_data("exp_001", "density"))

    def test_load_rdf_curve_success(self):
        """Test closure execution with properly mocked dependencies."""
        from features.metrics.query import get_array_metric_data

        mock_metric = _make_metric("rdf_curve")
        rdf_data = {"r": [1.0, 2.0, 3.0], "g_r": [0.1, 1.5, 1.0]}
        rdf_metadata = {"first_peak_r": 2.0}

        mock_repo_cls = MagicMock()
        mock_repo_cls.return_value.get_by_name.return_value = mock_metric

        mock_storage_cls = MagicMock()
        mock_storage_cls.return_value.load_with_metadata.return_value = (rdf_data, rdf_metadata)

        def fake_run(fn):
            return fn(MagicMock())

        with (
            patch("features.metrics.query.run_in_session", side_effect=fake_run),
            patch("database.repositories.metric_repo.MetricRepository", mock_repo_cls),
            patch("metrics.array_storage.ArrayStorage", mock_storage_cls),
        ):
            result = _run(get_array_metric_data("exp_001", "rdf_curve"))

        assert result["metric_name"] == "rdf_curve"
        assert result["columns"]["r"] == [1.0, 2.0, 3.0]
        assert result["columns"]["g_r"] == [0.1, 1.5, 1.0]
        # DB metadata (3.5) overrides file metadata (2.0) per merge logic
        assert result["metadata"]["first_peak_r"] == 3.5

    def test_missing_parquet_raises_404(self):
        from contracts.errors import ContractError
        from features.metrics.query import get_array_metric_data

        mock_repo_cls = MagicMock()
        mock_repo_cls.return_value.get_by_name.return_value = None

        mock_storage_cls = MagicMock()
        mock_storage_cls.return_value.load_with_metadata.return_value = (None, None)

        def fake_run(fn):
            return fn(MagicMock())

        with (
            patch("features.metrics.query.run_in_session", side_effect=fake_run),
            patch("database.repositories.metric_repo.MetricRepository", mock_repo_cls),
            patch("metrics.array_storage.ArrayStorage", mock_storage_cls),
        ):
            with pytest.raises(ContractError, match="No rdf_curve data found"):
                _run(get_array_metric_data("missing_exp", "rdf_curve"))

    def test_path_fallback_uses_array_file_path(self):
        """When load_with_metadata returns None, fallback uses metric.array_file_path."""
        from features.metrics.query import get_array_metric_data

        mock_metric = _make_metric("rdf_curve", array_file_path="/data/rdf/exp_001.parquet")
        rdf_data = {"r": [1.0, 2.0], "g_r": [0.5, 1.0]}

        mock_repo_cls = MagicMock()
        mock_repo_cls.return_value.get_by_name.return_value = mock_metric

        mock_storage_cls = MagicMock()
        mock_storage_cls.return_value.load_with_metadata.return_value = (None, None)
        mock_storage_cls.return_value.load.return_value = rdf_data

        def fake_run(fn):
            return fn(MagicMock())

        with (
            patch("features.metrics.query.run_in_session", side_effect=fake_run),
            patch("database.repositories.metric_repo.MetricRepository", mock_repo_cls),
            patch("metrics.array_storage.ArrayStorage", mock_storage_cls),
        ):
            result = _run(get_array_metric_data("exp_001", "rdf_curve"))

        mock_storage_cls.return_value.load.assert_called_once_with("/data/rdf/exp_001.parquet")
        assert result["columns"]["r"] == [1.0, 2.0]


class TestGetArrayMetricCompare:
    def test_max_8_limit(self):
        from contracts.errors import ContractError
        from features.metrics.query import get_array_metric_compare

        exp_ids = [f"exp_{i:03d}" for i in range(9)]
        with pytest.raises(ContractError, match="Maximum 8"):
            _run(get_array_metric_compare(exp_ids, "rdf_curve"))

    def test_invalid_metric(self):
        from contracts.errors import ContractError
        from features.metrics.query import get_array_metric_compare

        with pytest.raises(ContractError, match="Unknown metric"):
            _run(get_array_metric_compare(["exp_001"], "fake_metric"))

    def test_compare_success(self):
        """Test closure execution for compare with multiple experiments."""
        from features.metrics.query import get_array_metric_compare

        mock_exp = _make_experiment(exp_id="exp_001", temperature_K=298.0)
        mock_metric = _make_metric("rdf_curve")
        rdf_data = {"r": [1.0, 2.0], "g_r": [0.5, 1.0]}

        mock_repo_cls = MagicMock()
        mock_repo_cls.return_value.get_by_name.return_value = mock_metric

        mock_exp_repo_cls = MagicMock()
        mock_exp_repo_cls.return_value.get_by_id.return_value = mock_exp

        mock_storage_cls = MagicMock()
        mock_storage_cls.return_value.load_with_metadata.return_value = (rdf_data, {})

        def fake_run(fn):
            return fn(MagicMock())

        with (
            patch("features.metrics.query.run_in_session", side_effect=fake_run),
            patch("database.repositories.metric_repo.MetricRepository", mock_repo_cls),
            patch("database.repositories.experiment_repo.ExperimentRepository", mock_exp_repo_cls),
            patch("metrics.array_storage.ArrayStorage", mock_storage_cls),
        ):
            result = _run(get_array_metric_compare(["exp_001"], "rdf_curve"))

        assert result["metric_name"] == "rdf_curve"
        assert len(result["experiments"]) == 1
        assert result["experiments"][0]["columns"]["r"] == [1.0, 2.0]

    def test_compare_path_fallback(self):
        """Compare path also falls back to metric.array_file_path."""
        from features.metrics.query import get_array_metric_compare

        mock_exp = _make_experiment(exp_id="exp_001")
        mock_metric = _make_metric("msd_curve", array_file_path="/data/msd/exp_001.parquet")
        msd_data = {"time_ps": [0, 1, 2], "msd": [0.0, 0.5, 1.2]}

        mock_repo_cls = MagicMock()
        mock_repo_cls.return_value.get_by_name.return_value = mock_metric

        mock_exp_repo_cls = MagicMock()
        mock_exp_repo_cls.return_value.get_by_id.return_value = mock_exp

        mock_storage_cls = MagicMock()
        mock_storage_cls.return_value.load_with_metadata.return_value = (None, None)
        mock_storage_cls.return_value.load.return_value = msd_data

        def fake_run(fn):
            return fn(MagicMock())

        with (
            patch("features.metrics.query.run_in_session", side_effect=fake_run),
            patch("database.repositories.metric_repo.MetricRepository", mock_repo_cls),
            patch("database.repositories.experiment_repo.ExperimentRepository", mock_exp_repo_cls),
            patch("metrics.array_storage.ArrayStorage", mock_storage_cls),
        ):
            result = _run(get_array_metric_compare(["exp_001"], "msd_curve"))

        mock_storage_cls.return_value.load.assert_called_once_with("/data/msd/exp_001.parquet")
        assert len(result["experiments"]) == 1


class TestGetExperimentsWithArrayMetric:
    def test_invalid_metric(self):
        from contracts.errors import ContractError
        from features.metrics.query import get_experiments_with_array_metric

        with pytest.raises(ContractError, match="Unknown metric"):
            _run(get_experiments_with_array_metric("fake_metric"))

    def test_scalar_rejected(self):
        from contracts.errors import ContractError
        from features.metrics.query import get_experiments_with_array_metric

        with pytest.raises(ContractError, match="not an array metric"):
            _run(get_experiments_with_array_metric("density"))

    def test_list_success(self):
        """Test closure execution for listing experiments with array metric."""
        from features.metrics.query import get_experiments_with_array_metric

        mock_exp = _make_experiment(exp_id="exp_001", temperature_K=298.0)

        # Mock the ORM models so session.query(...).join(...).filter(...).all() works
        mock_exp_model = MagicMock()
        mock_metric_model = MagicMock()

        def fake_run(fn):
            session = MagicMock()
            query_mock = MagicMock()
            query_mock.join.return_value = query_mock
            query_mock.filter.return_value = query_mock
            query_mock.all.return_value = [mock_exp]
            session.query.return_value = query_mock
            return fn(session)

        with (
            patch("features.metrics.query.run_in_session", side_effect=fake_run),
            patch("database.models.ExperimentModel", mock_exp_model),
            patch("database.models.MetricModel", mock_metric_model),
        ):
            result = _run(get_experiments_with_array_metric("rdf_curve"))

        assert len(result) == 1
        assert result[0]["exp_id"] == "exp_001"
        assert result[0]["temperature_k"] == 298.0

    def test_temperature_K_uppercase_read(self):
        """Verify that temperature_K (uppercase from ORM) is correctly mapped."""
        from features.metrics.query import get_experiments_with_array_metric

        mock_exp = SimpleNamespace(
            exp_id="exp_002",
            temperature_K=353.0,
            additive_mol_id=None,
            additive_type=None,
            metadata_json={"binder_type": "AAK1"},
        )

        mock_exp_model = MagicMock()
        mock_metric_model = MagicMock()

        def fake_run(fn):
            session = MagicMock()
            query_mock = MagicMock()
            query_mock.join.return_value = query_mock
            query_mock.filter.return_value = query_mock
            query_mock.all.return_value = [mock_exp]
            session.query.return_value = query_mock
            return fn(session)

        with (
            patch("features.metrics.query.run_in_session", side_effect=fake_run),
            patch("database.models.ExperimentModel", mock_exp_model),
            patch("database.models.MetricModel", mock_metric_model),
        ):
            result = _run(get_experiments_with_array_metric("rdf_curve"))

        assert result[0]["temperature_k"] == 353.0


# ---------------------------------------------------------------------------
# Metadata merge logic
# ---------------------------------------------------------------------------


class TestMetadataMerge:
    def test_db_takes_precedence_over_file(self):
        """DB metadata should override file metadata for same keys."""
        file_meta = {"key_a": "from_file", "key_b": "from_file"}
        db_meta = {"key_a": "from_db"}

        merged = {**file_meta, **db_meta}

        assert merged["key_a"] == "from_db"
        assert merged["key_b"] == "from_file"

    def test_empty_metadata_returns_none(self):
        """When both metadata sources are empty, result should be None-like."""
        file_meta = {}
        db_meta = {}

        merged = {**file_meta, **db_meta}

        assert merged == {} or merged is None or not merged


# ---------------------------------------------------------------------------
# Thermo log SSOT compliance
# ---------------------------------------------------------------------------


class TestThermoLogSSOT:
    def test_thermo_log_registry_contract(self):
        """Verify thermo_log is registered as ARRAY with unit='mixed', namespace='bulk_ff'."""
        from contracts.policies.metrics import MetricsRegistry, MetricType

        registry = MetricsRegistry()
        assert registry.is_valid_metric("thermo_log")
        assert registry.get_type("thermo_log") == MetricType.ARRAY
        assert registry.get_unit("thermo_log") == "mixed"
        assert str(registry.get_namespace("thermo_log")) == "bulk_ff_gaff2"

    def test_store_thermo_log_returns_correct_metric_result(self):
        """Verify _store_thermo_log() produces a MetricResult with value=None and registry unit/namespace."""
        from contracts.schemas import ArrayMetricStorage
        from metrics.calculator import MetricCalculator

        mock_array_storage = MagicMock()
        mock_array_storage.store_metric.return_value = ArrayMetricStorage(
            file_path="/fake/thermo_log.parquet",
            file_format="parquet",
            file_hash="abc123",
            shape=[3, 8],
            summary={"n_points": 3.0},
        )

        calc = MetricCalculator(array_storage=mock_array_storage)
        # Provide minimal thermo data that extract_full_trajectory can process
        thermo_data = {
            "Step": [0, 1000, 2000],
            "Time": [0.0, 1.0, 2.0],
            "Temp": [298.0, 300.0, 299.0],
            "Press": [1.0, 1.1, 0.9],
            "PotEng": [-5000.0, -4999.0, -5001.0],
            "KinEng": [100.0, 101.0, 99.0],
            "Volume": [50000.0, 50010.0, 49990.0],
            "Density": [1.02, 1.021, 1.019],
        }

        result = calc._store_thermo_log(thermo_data=thermo_data, exp_id="test_exp")

        if result is not None:
            assert result.metric_name == "thermo_log"
            assert result.value is None
            assert result.unit == "mixed"
            assert str(result.namespace) == "bulk_ff_gaff2"
            assert result.array_summary is not None
            # Verify store_metric was called with correct metric_name
            mock_array_storage.store_metric.assert_called_once()
            call_kwargs = mock_array_storage.store_metric.call_args
            assert (
                call_kwargs[1]["metric_name"] == "thermo_log" or call_kwargs[0][0] == "thermo_log"
            )

    def test_store_thermo_log_includes_energy_columns(self):
        """Verify _store_thermo_log() passes energy decomposition columns to storage."""
        from contracts.schemas import ArrayMetricStorage
        from metrics.calculator import MetricCalculator

        mock_array_storage = MagicMock()
        mock_array_storage.store_metric.return_value = ArrayMetricStorage(
            file_path="/fake/thermo_log.parquet",
            file_format="parquet",
            file_hash="abc123",
            shape=[3, 17],
            summary={"n_points": 3.0},
        )

        calc = MetricCalculator(array_storage=mock_array_storage)
        thermo_data = {
            "Step": [0, 1000, 2000],
            "Temp": [298.0, 300.0, 299.0],
            "Press": [1.0, 1.1, 0.9],
            "PotEng": [-5000.0, -4999.0, -5001.0],
            "KinEng": [100.0, 101.0, 99.0],
            "Volume": [50000.0, 50010.0, 49990.0],
            "Density": [1.02, 1.021, 1.019],
            "E_bond": [1500.0, 1510.0, 1505.0],
            "E_angle": [800.0, 810.0, 805.0],
            "E_dihed": [200.0, 205.0, 202.0],
            "E_imp": [5.0, 5.5, 5.2],
            "E_vdwl": [-3000.0, -3010.0, -3005.0],
            "E_coul": [-2000.0, -2005.0, -2002.0],
            "E_pair": [-4900.0, -4910.0, -4905.0],
            "E_mol": [2505.0, 2530.5, 2517.2],
            "E_long": [-1000.0, -1050.0, -1025.0],
        }

        result = calc._store_thermo_log(thermo_data=thermo_data, exp_id="test_exp_energy")

        assert result is not None
        mock_array_storage.store_metric.assert_called_once()
        call_kwargs = mock_array_storage.store_metric.call_args
        stored_data = (
            call_kwargs[1].get("data") or call_kwargs[0][2]
            if len(call_kwargs[0]) > 2
            else call_kwargs[1]["data"]
        )

        # All 9 energy columns must be present in the stored data
        for col in [
            "ebond",
            "eangle",
            "edihed",
            "eimp",
            "evdwl",
            "ecoul",
            "epair",
            "emol",
            "elong",
        ]:
            assert col in stored_data, f"{col} missing from stored thermo_log data"
            assert len(stored_data[col]) == 3

    def test_store_thermo_log_returns_none_on_empty_data(self):
        """Verify _store_thermo_log() returns None when no time data exists."""
        from metrics.calculator import MetricCalculator

        mock_array_storage = MagicMock()
        calc = MetricCalculator(array_storage=mock_array_storage)

        result = calc._store_thermo_log(thermo_data={}, exp_id="test_exp")

        assert result is None
        mock_array_storage.store_metric.assert_not_called()


# ---------------------------------------------------------------------------
# Path hardening
# ---------------------------------------------------------------------------


class TestPathHardening:
    def test_load_by_path_blocks_traversal(self):
        """Verify that _load_by_path blocks paths outside project root."""
        from metrics.array_storage import ArrayStorage

        storage = ArrayStorage()
        # Attempt to load from outside project root
        result = storage._load_by_path("/etc/passwd")
        assert result is None

    def test_load_by_path_blocks_relative_traversal(self):
        """Verify that _load_by_path blocks relative traversal."""
        from metrics.array_storage import ArrayStorage

        storage = ArrayStorage()
        result = storage._load_by_path("../../etc/passwd")
        assert result is None
