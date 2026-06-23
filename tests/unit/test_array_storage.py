"""
Unit tests for metrics.array_storage module.

Tests JSON fallback storage, store/load round-trip, metadata handling,
listing, deletion, and store_metric descriptor generation.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


@pytest.fixture
def storage(tmp_path, monkeypatch):
    """Create ArrayStorage with explicit dir (flat layout, JSON fallback)."""
    import metrics.array_storage as mod

    monkeypatch.setattr(mod, "HAS_PARQUET", False)

    from metrics.array_storage import ArrayStorage

    return ArrayStorage(storage_dir=tmp_path)


@pytest.fixture
def sample_data():
    return {
        "r": [1.0, 2.0, 3.0, 4.0, 5.0],
        "g_r": [0.0, 0.5, 1.2, 0.8, 0.3],
    }


# ── store / load round-trip ──────────────────────────────────────


class TestStoreLoad:
    def test_round_trip(self, storage, sample_data):
        storage.store("rdf_curve", "exp_001", sample_data)
        loaded = storage.load("rdf_curve", "exp_001")

        assert loaded is not None
        assert loaded["r"] == sample_data["r"]
        assert loaded["g_r"] == sample_data["g_r"]

    def test_load_nonexistent_returns_none(self, storage):
        assert storage.load("rdf_curve", "no_such_exp") is None

    def test_store_with_metadata(self, storage, sample_data):
        metadata = {"units": "angstrom", "temperature_K": 298.0}
        storage.store("rdf_curve", "exp_002", sample_data, metadata=metadata)
        loaded = storage.load("rdf_curve", "exp_002")
        assert loaded is not None

    def test_load_with_metadata(self, storage, sample_data):
        metadata = {"source": "test"}
        storage.store("rdf_curve", "exp_003", sample_data, metadata=metadata)
        data, meta = storage.load_with_metadata("rdf_curve", "exp_003")
        assert data is not None
        assert meta is not None
        assert meta["source"] == "test"

    def test_load_with_metadata_nonexistent(self, storage):
        data, meta = storage.load_with_metadata("rdf_curve", "no_exp")
        assert data is None
        assert meta is None


# ── store_metric ──────────────────────────────────────────────────


class TestStoreMetric:
    def test_returns_array_metric_storage(self, storage, sample_data):
        from contracts.schemas import ArrayMetricStorage

        result = storage.store_metric(
            "rdf_curve",
            "exp_010",
            sample_data,
            summary={"peak_r": 3.0, "peak_g": 1.2},
        )
        assert isinstance(result, ArrayMetricStorage)
        assert result.shape == (5, 2)
        assert result.summary["peak_r"] == 3.0
        assert len(result.file_hash) == 16

    def test_store_metric_empty_summary(self, storage, sample_data):
        result = storage.store_metric("msd_curve", "exp_011", sample_data)
        assert result.summary == {}

    def test_store_metric_file_path_set(self, storage, sample_data):
        result = storage.store_metric("rdf_curve", "exp_012", sample_data)
        assert "exp_012" in result.file_path
        assert "rdf_curve" in result.file_path


# ── exists / delete ───────────────────────────────────────────────


class TestExistsDelete:
    def test_exists_after_store(self, storage, sample_data):
        assert not storage.exists("rdf_curve", "exp_020")
        storage.store("rdf_curve", "exp_020", sample_data)
        assert storage.exists("rdf_curve", "exp_020")

    def test_delete_removes_file(self, storage, sample_data):
        storage.store("rdf_curve", "exp_021", sample_data)
        assert storage.exists("rdf_curve", "exp_021")
        storage.delete("rdf_curve", "exp_021")
        assert not storage.exists("rdf_curve", "exp_021")

    def test_delete_nonexistent_no_error(self, storage):
        storage.delete("rdf_curve", "exp_999")  # should not raise


# ── listing ───────────────────────────────────────────────────────


class TestListing:
    def test_list_experiments(self, storage, sample_data):
        storage.store("rdf_curve", "exp_030", sample_data)
        storage.store("rdf_curve", "exp_031", sample_data)

        exps = storage.list_experiments("rdf_curve")
        assert "exp_030" in exps
        assert "exp_031" in exps

    def test_list_metrics(self, storage, sample_data):
        storage.store("rdf_curve", "exp_040", sample_data)
        storage.store("msd_curve", "exp_040", sample_data)

        metrics = storage.list_metrics("exp_040")
        assert "rdf_curve" in metrics
        assert "msd_curve" in metrics

    def test_list_empty(self, storage):
        assert storage.list_experiments("rdf_curve") == []
        assert storage.list_metrics("exp_none") == []


# ── storage stats ─────────────────────────────────────────────────


class TestStorageStats:
    def test_basic_stats(self, storage, sample_data):
        storage.store("rdf_curve", "exp_050", sample_data)
        stats = storage.get_storage_stats()

        assert stats["num_files"] >= 1
        assert stats["total_size_bytes"] > 0
        assert stats["format"] == "json"

    def test_stats_empty_dir(self, storage):
        stats = storage.get_storage_stats()
        assert stats["num_files"] == 0
        assert stats["total_size_bytes"] == 0
