"""Tests for CED coverage_mode exact/approximate/missing classification."""

import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, "src")

from contracts.schemas import EIntraKey, EIntraValue
from metrics.ced import CEDCalculator


def _make_thermo(n: int = 50) -> dict[str, list[float]]:
    """Create minimal thermo data for CED calculation."""
    return {
        "PotEng": [-1000.0] * n,
        "Volume": [50000.0] * n,
    }


def _make_store(values: dict[str, tuple[float, float]]):
    """Create a mock store returning specified (e_intra, temperature_K) per mol_id.

    Args:
        values: {mol_id: (e_intra, temperature_K)} — None value means missing.
    """
    store = MagicMock()

    def _get(key: EIntraKey):
        entry = values.get(key.mol_id)
        if entry is None:
            return None
        return EIntraValue(e_intra=entry[0], temperature_K=entry[1])

    store.get = MagicMock(side_effect=_get)
    store.list_keys = MagicMock(return_value=[])
    return store


class TestExactRequired:
    """exact_required mode tests."""

    def test_exact_match_produces_ced(self):
        store = _make_store({"mol_A": (-50.0, 298.0)})
        calc = CEDCalculator(e_intra_store=store, coverage_mode="exact_required")
        result = calc.calculate_from_thermo(
            _make_thermo(), {"mol_A": 10}, "GAFF2", "1.0", temperature_K=298.0
        )
        assert result is not None
        assert result.metric_name == "cohesive_energy_density"
        assert result.array_summary["is_exact"] is True
        assert result.array_summary["exact_count"] == 1
        assert result.array_summary["approximate_count"] == 0

    def test_approximate_hit_returns_none(self):
        # DB returns 293K when 298K was requested → approximate
        store = _make_store({"mol_A": (-50.0, 293.0)})
        calc = CEDCalculator(e_intra_store=store, coverage_mode="exact_required")
        result = calc.calculate_from_thermo(
            _make_thermo(), {"mol_A": 10}, "GAFF2", "1.0", temperature_K=298.0
        )
        assert result is None

    def test_missing_molecule_returns_none(self):
        store = _make_store({})  # no entries
        calc = CEDCalculator(e_intra_store=store, coverage_mode="exact_required")
        result = calc.calculate_from_thermo(
            _make_thermo(), {"mol_A": 10}, "GAFF2", "1.0", temperature_K=298.0
        )
        assert result is None


class TestAllowTolerance:
    """allow_tolerance mode tests."""

    def test_approximate_hit_produces_ced(self):
        store = _make_store({"mol_A": (-50.0, 295.0)})
        calc = CEDCalculator(e_intra_store=store, coverage_mode="allow_tolerance")
        result = calc.calculate_from_thermo(
            _make_thermo(), {"mol_A": 10}, "GAFF2", "1.0", temperature_K=298.0
        )
        assert result is not None
        assert result.array_summary["is_exact"] is False
        assert result.array_summary["approximate_count"] == 1

    def test_missing_still_fails(self):
        store = _make_store({})
        calc = CEDCalculator(e_intra_store=store, coverage_mode="allow_tolerance")
        result = calc.calculate_from_thermo(
            _make_thermo(), {"mol_A": 10}, "GAFF2", "1.0", temperature_K=298.0
        )
        assert result is None


class TestAllowMissingPeOverV:
    """allow_missing_pe_over_v mode tests."""

    def test_missing_produces_ced_with_fallback(self):
        store = _make_store({})
        calc = CEDCalculator(e_intra_store=store, coverage_mode="allow_missing_pe_over_v")
        result = calc.calculate_from_thermo(
            _make_thermo(), {"mol_A": 10}, "GAFF2", "1.0", temperature_K=298.0
        )
        assert result is not None
        assert result.array_summary["missing_molecules"] == ["mol_A"]

    def test_provenance_complete(self):
        store = _make_store({"mol_A": (-50.0, 298.0), "mol_B": (-30.0, 295.0)})
        calc = CEDCalculator(e_intra_store=store, coverage_mode="allow_missing_pe_over_v")
        result = calc.calculate_from_thermo(
            _make_thermo(),
            {"mol_A": 5, "mol_B": 5, "mol_C": 3},
            "GAFF2",
            "1.0",
            temperature_K=298.0,
        )
        assert result is not None
        s = result.array_summary
        assert s["exact_count"] == 1  # mol_A
        assert s["approximate_count"] == 1  # mol_B (295K)
        assert s["missing_molecules"] == ["mol_C"]
        assert s["coverage_mode"] == "allow_missing_pe_over_v"
        assert "matched_temperatures_k" in s


class TestMakeMetricsCalculatorCoverageMode:
    """Verify make_metrics_calculator passes coverage_mode to adapter."""

    def test_exact_required_uses_zero_tolerance(self):
        """exact_required should create adapter with temperature_tolerance_k=0.0."""
        with patch("orchestrator.task_runners._get_e_intra_adapter") as mock_get:
            mock_get.return_value = MagicMock()
            from orchestrator.task_runners import make_metrics_calculator

            make_metrics_calculator(session=MagicMock(), ced_coverage_mode="exact_required")
            mock_get.assert_called_once()
            _, kwargs = mock_get.call_args
            assert kwargs["temperature_tolerance_k"] == 0.0

    def test_allow_tolerance_uses_none(self):
        """allow_tolerance should pass temperature_tolerance_k=None (DB default)."""
        with patch("orchestrator.task_runners._get_e_intra_adapter") as mock_get:
            mock_get.return_value = MagicMock()
            from orchestrator.task_runners import make_metrics_calculator

            make_metrics_calculator(session=MagicMock(), ced_coverage_mode="allow_tolerance")
            _, kwargs = mock_get.call_args
            assert kwargs["temperature_tolerance_k"] is None
