"""Tests for E_intra store."""

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, "src")

from contracts.schemas import EIntraKey, EIntraValue
from metrics.e_intra_store import EIntraStore


class TestEIntraStore:
    """Test E_intra store."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def store(self, temp_dir):
        return EIntraStore(cache_dir=temp_dir / "e_intra")

    @pytest.fixture
    def sample_key(self):
        return EIntraKey(
            mol_id="asphaltene_01",
            ff_name="GAFF2",
            ff_version="1.0",
        )

    @pytest.fixture
    def sample_value(self):
        return EIntraValue(
            e_intra=-150.5,
        )

    def test_set_and_get(self, store, sample_key, sample_value):
        """Test storing and retrieving values."""
        store.set(sample_key, sample_value)
        result = store.get(sample_key)

        assert result is not None
        assert result.e_intra == pytest.approx(-150.5)

    def test_exists(self, store, sample_key, sample_value):
        """Test exists method."""
        assert store.exists(sample_key) is False

        store.set(sample_key, sample_value)

        assert store.exists(sample_key) is True

    def test_delete(self, store, sample_key, sample_value):
        """Test delete method."""
        store.set(sample_key, sample_value)
        assert store.exists(sample_key) is True

        store.delete(sample_key)
        assert store.exists(sample_key) is False

    def test_clear(self, store, sample_key, sample_value):
        """Test clear method."""
        store.set(sample_key, sample_value)
        assert store.count() == 1

        store.clear()
        assert store.count() == 0

    def test_persistence(self, temp_dir, sample_key, sample_value):
        """Test that data persists across instances."""
        # Create first store and add value
        store1 = EIntraStore(cache_dir=temp_dir / "e_intra")
        store1.set(sample_key, sample_value)

        # Create second store and verify value exists
        store2 = EIntraStore(cache_dir=temp_dir / "e_intra")
        result = store2.get(sample_key)

        assert result is not None
        assert result.e_intra == pytest.approx(-150.5)

    def test_get_for_molecules(self, store):
        """Test getting values for multiple molecules."""
        # Set up some values
        for i, mol_id in enumerate(["mol1", "mol2", "mol3"]):
            key = EIntraKey(mol_id=mol_id, ff_name="GAFF2", ff_version="1.0")
            value = EIntraValue(e_intra=-100.0 * (i + 1))
            store.set(key, value)

        # Get values
        result = store.get_for_molecules(
            mol_ids=["mol1", "mol2", "mol4"],  # mol4 doesn't exist
            ff_name="GAFF2",
            ff_version="1.0",
        )

        assert len(result) == 2
        assert result["mol1"] == pytest.approx(-100.0)
        assert result["mol2"] == pytest.approx(-200.0)

    def test_missing_molecules(self, store):
        """Test finding missing molecules."""
        # Set up some values
        for mol_id in ["mol1", "mol2"]:
            key = EIntraKey(mol_id=mol_id, ff_name="GAFF2", ff_version="1.0")
            value = EIntraValue(e_intra=-100.0)
            store.set(key, value)

        # Check missing
        missing = store.missing_molecules(
            mol_ids=["mol1", "mol2", "mol3", "mol4"],
            ff_name="GAFF2",
            ff_version="1.0",
        )

        assert len(missing) == 2
        assert "mol3" in missing
        assert "mol4" in missing


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
