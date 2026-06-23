"""Tests for TensileMode enum and TensileSpec quasi-static fields."""

import sys

import pytest

sys.path.insert(0, "src")

from contracts.schemas import TensileMode, TensileSpec


class TestTensileMode:
    """TensileMode enum values."""

    def test_continuous(self):
        assert TensileMode.CONTINUOUS.value == "continuous"

    def test_quasi_static(self):
        assert TensileMode.QUASI_STATIC.value == "quasi_static"


class TestTensileSpecDefaults:
    """Default values preserve backward compat."""

    def test_default_mode_continuous(self):
        ts = TensileSpec(enabled=True)
        assert ts.mode == TensileMode.CONTINUOUS

    def test_default_qs_params(self):
        ts = TensileSpec(enabled=True)
        assert ts.displacement_increment_angstrom == 0.5
        assert ts.relax_steps == 10000
        assert ts.force_average_steps == 1000

    def test_backward_compat_no_mode(self):
        """Existing code without mode field still works."""
        ts = TensileSpec(
            enabled=True,
            pull_velocity_A_per_fs=0.0001,
            grip_thickness_angstrom=15.0,
            max_strain=0.3,
        )
        assert ts.mode == TensileMode.CONTINUOUS


class TestTensileSpecQSValidation:
    """Validator: force_average_steps <= relax_steps in QS mode."""

    def test_valid_qs(self):
        ts = TensileSpec(
            enabled=True,
            mode=TensileMode.QUASI_STATIC,
            relax_steps=10000,
            force_average_steps=5000,
        )
        assert ts.force_average_steps == 5000

    def test_invalid_qs_force_avg_exceeds_relax(self):
        with pytest.raises(ValueError, match="force_average_steps"):
            TensileSpec(
                enabled=True,
                mode=TensileMode.QUASI_STATIC,
                relax_steps=1000,
                force_average_steps=2000,
            )

    def test_continuous_mode_allows_any_ratio(self):
        """In continuous mode, force_average_steps > relax_steps is OK."""
        ts = TensileSpec(
            enabled=True,
            mode=TensileMode.CONTINUOUS,
            relax_steps=1000,
            force_average_steps=2000,
        )
        assert ts.force_average_steps == 2000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
