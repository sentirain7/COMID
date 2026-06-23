"""Unit tests for TensileMetricCalculator (Phase 4.3)."""

import pytest

from contracts.policies.metrics import DEFAULT_METRICS_REGISTRY
from metrics.tensile_metrics import TensileMetricCalculator


class TestTensileMetricCalculator:
    """Tests for TensileMetricCalculator."""

    def _write_ss_file(self, tmp_path, content=None):
        """Helper: create stress-strain data file."""
        ss_file = tmp_path / "stress_strain_tensile_pull.dat"
        if content is None:
            content = (
                "# strain stress_MPa\n"
                "0.00 0.0\n"
                "0.01 50.0\n"
                "0.02 100.0\n"
                "0.03 150.0\n"
                "0.04 120.0\n"
                "0.05 80.0\n"
                "0.06 40.0\n"
            )
        ss_file.write_text(content)
        return ss_file

    def test_calculate_basic(self, tmp_path):
        """Test basic metric calculation."""
        ss_file = self._write_ss_file(tmp_path)
        calc = TensileMetricCalculator()
        metrics = calc.calculate_from_file(ss_file, exp_id="test_001")

        metric_names = {m.metric_name for m in metrics}

        # Must produce these metrics (work_of_separation requires gap)
        assert "interfacial_tensile_strength" in metric_names
        assert "tensile_strength" in metric_names
        assert "ductility" in metric_names
        assert "toughness" in metric_names

        # Peak stress should be 150.0 MPa
        its = next(m for m in metrics if m.metric_name == "interfacial_tensile_strength")
        assert its.value == pytest.approx(150.0)
        assert its.unit == "MPa"
        assert its.namespace == "mechanical"

    def test_tensile_strength_is_alias(self, tmp_path):
        """Test tensile_strength equals interfacial_tensile_strength."""
        ss_file = self._write_ss_file(tmp_path)
        calc = TensileMetricCalculator()
        metrics = calc.calculate_from_file(ss_file)

        its = next(m for m in metrics if m.metric_name == "interfacial_tensile_strength")
        ts = next(m for m in metrics if m.metric_name == "tensile_strength")
        assert its.value == ts.value

    def test_ductility_is_peak_strain(self, tmp_path):
        """Test ductility equals strain at peak stress."""
        ss_file = self._write_ss_file(tmp_path)
        calc = TensileMetricCalculator()
        metrics = calc.calculate_from_file(ss_file)

        ductility = next(m for m in metrics if m.metric_name == "ductility")
        assert ductility.value == pytest.approx(0.03)
        assert ductility.unit == "dimensionless"

    def test_work_of_separation_with_gap(self, tmp_path):
        """Test W_sep = toughness * gap * 0.1 (no area division)."""
        ss_file = self._write_ss_file(tmp_path)
        calc = TensileMetricCalculator()
        metrics = calc.calculate_from_file(ss_file, original_gap_angstrom=50.0, exp_id="test_wsep")

        metric_names = {m.metric_name for m in metrics}
        assert "work_of_separation" in metric_names

        wsep = next(m for m in metrics if m.metric_name == "work_of_separation")
        toughness = next(m for m in metrics if m.metric_name == "toughness")

        # W_sep = toughness * gap * 0.1
        expected = toughness.value * 50.0 * 0.1
        assert wsep.value == pytest.approx(expected)
        assert wsep.unit == "mJ/m2"

    def test_work_of_separation_without_gap(self, tmp_path):
        """Test W_sep is NOT produced when gap is None."""
        ss_file = self._write_ss_file(tmp_path)
        calc = TensileMetricCalculator()
        metrics = calc.calculate_from_file(ss_file, original_gap_angstrom=None)

        metric_names = {m.metric_name for m in metrics}
        assert "work_of_separation" not in metric_names

    def test_elastic_modulus_present(self, tmp_path):
        """Test elastic_modulus is calculated when enough data in linear region."""
        # Dense linear region: 0, 0.005, 0.01, 0.015, 0.02
        content = (
            "# strain stress_MPa\n"
            "0.000 0.0\n"
            "0.005 10.0\n"
            "0.010 20.0\n"
            "0.015 30.0\n"
            "0.020 40.0\n"
            "0.050 60.0\n"
            "0.100 50.0\n"
        )
        ss_file = self._write_ss_file(tmp_path, content)
        calc = TensileMetricCalculator()
        metrics = calc.calculate_from_file(ss_file)

        metric_names = {m.metric_name for m in metrics}
        assert "elastic_modulus" in metric_names

        em = next(m for m in metrics if m.metric_name == "elastic_modulus")
        assert em.unit == "GPa"
        # E ≈ 2000 MPa / 1000 = 2.0 GPa
        assert em.value == pytest.approx(2.0, rel=0.01)

    def test_metrics_registry_valid(self):
        """Test all tensile metrics are registered in MetricsRegistry."""
        registry = DEFAULT_METRICS_REGISTRY
        tensile_metrics = [
            "interfacial_tensile_strength",
            "tensile_strength",
            "elastic_modulus",
            "ductility",
            "toughness",
            "work_of_separation",
            "stress_strain_curve",
        ]
        for name in tensile_metrics:
            assert registry.is_valid_metric(name), f"{name} not in registry"

    def test_provenance_is_attached_when_interface_index_provided(self, tmp_path):
        """Optional layer/interface provenance should propagate into MetricResult."""
        ss_file = self._write_ss_file(tmp_path)
        calc = TensileMetricCalculator()
        metrics = calc.calculate_from_file(
            ss_file,
            original_gap_angstrom=25.0,
            exp_id="test_provenance",
            layer_index=2,
            interface_index=1,
        )

        assert metrics
        for metric in metrics:
            assert metric.layer_index == 2
            assert metric.interface_index == 1
