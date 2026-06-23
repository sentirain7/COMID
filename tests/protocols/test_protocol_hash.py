"""Tests for protocol hash generation."""

import sys

import pytest

sys.path.insert(0, "src")

from protocols.protocol_hash import ProtocolHasher


class TestProtocolHasher:
    """Test protocol hasher."""

    @pytest.fixture
    def hasher(self):
        return ProtocolHasher()

    def test_hash_deterministic(self, hasher):
        """Test that hash is deterministic."""
        params = {
            "tier": "screening",
            "force_field": "GAFF2",
            "ff_version": "1.0",
            "topology_hash": "abc12345",
            "temperature_K": 298.0,
            "pressure_atm": 1.0,
            "step_names": ["minimize", "nvt_equil", "npt_equil"],
        }

        hash1 = hasher.hash(**params)
        hash2 = hasher.hash(**params)

        assert hash1 == hash2

    def test_hash_length(self, hasher):
        """Test hash length."""
        hash_val = hasher.hash(
            tier="screening",
            force_field="GAFF2",
            ff_version="1.0",
            topology_hash="test",
            temperature_K=298.0,
            pressure_atm=1.0,
            step_names=["minimize"],
        )

        assert len(hash_val) == 8  # Default length

    def test_hash_changes_with_tier(self, hasher):
        """Test that hash changes with tier."""
        base = {
            "force_field": "GAFF2",
            "ff_version": "1.0",
            "topology_hash": "test",
            "temperature_K": 298.0,
            "pressure_atm": 1.0,
            "step_names": ["minimize"],
        }

        hash1 = hasher.hash(tier="screening", **base)
        hash2 = hasher.hash(tier="confirm", **base)

        assert hash1 != hash2

    def test_hash_changes_with_temperature(self, hasher):
        """Test that hash changes with temperature."""
        base = {
            "tier": "screening",
            "force_field": "GAFF2",
            "ff_version": "1.0",
            "topology_hash": "test",
            "pressure_atm": 1.0,
            "step_names": ["minimize"],
        }

        hash1 = hasher.hash(temperature_K=298.0, **base)
        hash2 = hasher.hash(temperature_K=500.0, **base)

        assert hash1 != hash2

    def test_hash_changes_with_topology(self, hasher):
        """Test that hash changes with topology."""
        base = {
            "tier": "screening",
            "force_field": "GAFF2",
            "ff_version": "1.0",
            "temperature_K": 298.0,
            "pressure_atm": 1.0,
            "step_names": ["minimize"],
        }

        hash1 = hasher.hash(topology_hash="topo1", **base)
        hash2 = hasher.hash(topology_hash="topo2", **base)

        assert hash1 != hash2


class TestProtocolHasherExtraParams:
    """Test extra params handling."""

    @pytest.fixture
    def hasher(self):
        return ProtocolHasher()

    def test_extra_params_affects_hash(self, hasher):
        """Test that extra params change hash."""
        base = {
            "tier": "screening",
            "force_field": "GAFF2",
            "ff_version": "1.0",
            "topology_hash": "test",
            "temperature_K": 298.0,
            "pressure_atm": 1.0,
            "step_names": ["minimize"],
        }

        hash1 = hasher.hash(**base)
        hash2 = hasher.hash(**base, extra_params={"custom_param": 42})

        assert hash1 != hash2

    def test_extra_params_order_independent(self, hasher):
        """Test that extra params order doesn't affect hash."""
        base = {
            "tier": "screening",
            "force_field": "GAFF2",
            "ff_version": "1.0",
            "topology_hash": "test",
            "temperature_K": 298.0,
            "pressure_atm": 1.0,
            "step_names": ["minimize"],
        }

        hash1 = hasher.hash(**base, extra_params={"a": 1, "b": 2})
        hash2 = hasher.hash(**base, extra_params={"b": 2, "a": 1})

        assert hash1 == hash2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
