"""
Unit tests for metrics.__init__ lazy import mechanism.

Validates that all exported names resolve correctly
and that invalid names raise AttributeError.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


class TestMetricsLazyImports:
    """Test that every name in metrics.__all__ resolves."""

    @pytest.mark.parametrize(
        "name,expected_module",
        [
            ("MetricCalculator", "metrics.calculator"),
            ("DensityCalculator", "metrics.density"),
            ("CEDCalculator", "metrics.ced"),
            ("RDFCalculator", "metrics.rdf"),
            ("MSDCalculator", "metrics.msd"),
            ("ViscosityCalculator", "metrics.viscosity"),
            ("TgCalculator", "metrics.tg"),
            ("EIntraStore", "metrics.e_intra_store"),
            ("ArrayStorage", "metrics.array_storage"),
        ],
    )
    def test_lazy_import_resolves(self, name, expected_module):
        import metrics

        cls = getattr(metrics, name)
        assert cls is not None
        assert cls.__module__ == expected_module

    def test_invalid_attribute_raises(self):
        import metrics

        with pytest.raises(AttributeError, match="no attribute"):
            _ = metrics.NonExistentClass
