"""
Unit tests for EInterCalculator (Phase 4.2).

Tests cover:
1. c_gg_* column detection from thermo data
2. Pairwise energy extraction with time windowing
3. Total E_inter summation
4. Per-atom normalization
5. MetricResult creation (e_inter_total, e_inter_additive_binder)
6. EInterResult schema conversion
7. Edge cases (no columns, empty data, single pair)
"""

import sys

sys.path.insert(0, "src")

from contracts.policies.metrics import MetricsRegistry  # noqa: E402
from contracts.schemas import EInterResult  # noqa: E402
from metrics.e_inter import (  # noqa: E402
    EInterCalculator,
    EInterFullResult,
    EInterPairResult,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_thermo_with_gg(
    n_samples: int = 100,
    pairs: dict[str, float] | None = None,
) -> dict[str, list[float]]:
    """Create synthetic thermo data with c_gg_* columns.

    Args:
        n_samples: Number of thermo samples.
        pairs: {pair_label: mean_energy} for each pair.

    Returns:
        Thermo data dict with standard + c_gg_* columns.
    """
    if pairs is None:
        pairs = {
            "saturate_aromatic": -150.0,
            "saturate_resin": -120.0,
            "aromatic_resin": -200.0,
        }

    data: dict[str, list[float]] = {
        "Step": [float(i * 1000) for i in range(n_samples)],
        "Temp": [298.0 + (i % 5) * 0.1 for i in range(n_samples)],
        "Press": [1.0 + (i % 3) * 0.01 for i in range(n_samples)],
        "PotEng": [-50000.0 + i * 0.1 for i in range(n_samples)],
        "KinEng": [12000.0 + i * 0.01 for i in range(n_samples)],
        "TotEng": [-38000.0 + i * 0.11 for i in range(n_samples)],
        "Volume": [125000.0 + i * 0.5 for i in range(n_samples)],
        "Density": [1.02 + i * 0.0001 for i in range(n_samples)],
    }

    for pair_label, mean_energy in pairs.items():
        col_name = f"c_gg_{pair_label}"
        # Add small fluctuations around mean
        data[col_name] = [mean_energy + (i % 7 - 3) * 0.5 for i in range(n_samples)]

    return data


# ---------------------------------------------------------------------------
# Column detection tests
# ---------------------------------------------------------------------------


class TestFindGGColumns:
    """Tests for c_gg_* column detection."""

    def test_finds_gg_columns(self) -> None:
        data = _make_thermo_with_gg()
        gg_cols = EInterCalculator.find_gg_columns(data)

        assert len(gg_cols) == 3
        assert "saturate_aromatic" in gg_cols
        assert "saturate_resin" in gg_cols
        assert "aromatic_resin" in gg_cols

    def test_column_name_mapping(self) -> None:
        data = _make_thermo_with_gg()
        gg_cols = EInterCalculator.find_gg_columns(data)

        assert gg_cols["saturate_aromatic"] == "c_gg_saturate_aromatic"
        assert gg_cols["saturate_resin"] == "c_gg_saturate_resin"

    def test_no_gg_columns(self) -> None:
        data = {
            "Step": [1.0, 2.0],
            "Temp": [300.0, 300.0],
        }
        gg_cols = EInterCalculator.find_gg_columns(data)
        assert len(gg_cols) == 0

    def test_ignores_non_gg_custom_columns(self) -> None:
        data = {
            "Step": [1.0],
            "c_pe_atom": [100.0],
            "c_gg_sat_aro": [-150.0],
        }
        gg_cols = EInterCalculator.find_gg_columns(data)
        assert len(gg_cols) == 1
        assert "sat_aro" in gg_cols

    def test_single_gg_column(self) -> None:
        data = {
            "Step": [1.0],
            "c_gg_additive_binder": [-85.0],
        }
        gg_cols = EInterCalculator.find_gg_columns(data)
        assert gg_cols == {"additive_binder": "c_gg_additive_binder"}


# ---------------------------------------------------------------------------
# Compute tests
# ---------------------------------------------------------------------------


class TestEInterCompute:
    """Tests for E_inter computation."""

    def test_basic_computation(self) -> None:
        data = _make_thermo_with_gg(n_samples=50)
        calc = EInterCalculator(window_ps=100.0, dt_fs=1.0, thermo_interval=1000)

        result = calc.compute(data)

        assert result is not None
        assert len(result.pair_results) == 3

    def test_pair_energies_near_expected(self) -> None:
        pairs = {"a_b": -100.0, "a_c": -200.0}
        data = _make_thermo_with_gg(n_samples=200, pairs=pairs)
        calc = EInterCalculator(window_ps=50.0, dt_fs=1.0, thermo_interval=1000)

        result = calc.compute(data)
        assert result is not None

        # Check pair energies are close to expected means
        pair_map = {pr.pair_label: pr for pr in result.pair_results}
        assert abs(pair_map["a_b"].energy_kcal_mol - (-100.0)) < 2.0
        assert abs(pair_map["a_c"].energy_kcal_mol - (-200.0)) < 2.0

    def test_total_e_inter_is_sum(self) -> None:
        pairs = {"x_y": -50.0, "x_z": -30.0, "y_z": -80.0}
        data = _make_thermo_with_gg(n_samples=100, pairs=pairs)
        calc = EInterCalculator(window_ps=50.0, dt_fs=1.0, thermo_interval=1000)

        result = calc.compute(data)
        assert result is not None

        pair_sum = sum(pr.energy_kcal_mol for pr in result.pair_results)
        assert abs(result.total_e_inter - pair_sum) < 1e-10

    def test_total_std_is_root_sum_squares(self) -> None:
        data = _make_thermo_with_gg(n_samples=100)
        calc = EInterCalculator(window_ps=50.0, dt_fs=1.0, thermo_interval=1000)

        result = calc.compute(data)
        assert result is not None

        expected_std = sum(pr.energy_std**2 for pr in result.pair_results) ** 0.5
        assert abs(result.total_e_inter_std - expected_std) < 1e-10

    def test_no_gg_columns_returns_none(self) -> None:
        data = {"Step": [1.0, 2.0], "Temp": [300.0, 300.0]}
        calc = EInterCalculator()

        result = calc.compute(data)
        assert result is None

    def test_empty_thermo_returns_none(self) -> None:
        data: dict[str, list[float]] = {}
        calc = EInterCalculator()

        result = calc.compute(data)
        assert result is None

    def test_per_atom_normalization(self) -> None:
        pairs = {"sat_aro": -100.0}
        data = _make_thermo_with_gg(n_samples=100, pairs=pairs)
        atom_counts = {"sat": 500, "aro": 300}
        calc = EInterCalculator(window_ps=50.0, dt_fs=1.0, thermo_interval=1000)

        result = calc.compute(data, atom_counts=atom_counts)
        assert result is not None

        assert "sat_aro" in result.normalized_per_atom
        expected = result.pair_results[0].energy_kcal_mol / (500 + 300)
        assert abs(result.normalized_per_atom["sat_aro"] - expected) < 1e-10

    def test_per_atom_normalization_unknown_group(self) -> None:
        pairs = {"sat_aro": -100.0}
        data = _make_thermo_with_gg(n_samples=100, pairs=pairs)
        # Only "sat" is known, not "aro"
        atom_counts = {"sat": 500}
        calc = EInterCalculator(window_ps=50.0, dt_fs=1.0, thermo_interval=1000)

        result = calc.compute(data, atom_counts=atom_counts)
        assert result is not None

        # Normalization uses only known atoms
        assert "sat_aro" in result.normalized_per_atom

    def test_n_samples_tracked(self) -> None:
        data = _make_thermo_with_gg(n_samples=100)
        calc = EInterCalculator(window_ps=50.0, dt_fs=1.0, thermo_interval=1000)

        result = calc.compute(data)
        assert result is not None

        for pr in result.pair_results:
            assert pr.n_samples > 0


# ---------------------------------------------------------------------------
# MetricResult creation tests
# ---------------------------------------------------------------------------


class TestEInterMetrics:
    """Tests for MetricResult creation."""

    def test_creates_total_metric(self) -> None:
        data = _make_thermo_with_gg(n_samples=100)
        calc = EInterCalculator(window_ps=50.0, dt_fs=1.0, thermo_interval=1000)

        result = calc.compute(data)
        assert result is not None

        metrics = calc.create_metrics(result)

        total_metrics = [m for m in metrics if m.metric_name == "e_inter_total"]
        assert len(total_metrics) == 1
        assert total_metrics[0].unit == "kcal/mol"
        assert total_metrics[0].namespace == "bulk_ff_gaff2"
        assert total_metrics[0].uncertainty is not None

    def test_creates_additive_binder_metric(self) -> None:
        pairs = {"additive_binder": -85.0, "sat_aro": -120.0}
        data = _make_thermo_with_gg(n_samples=100, pairs=pairs)
        calc = EInterCalculator(window_ps=50.0, dt_fs=1.0, thermo_interval=1000)

        result = calc.compute(data)
        assert result is not None

        metrics = calc.create_metrics(result, additive_pair_label="additive_binder")

        add_metrics = [m for m in metrics if m.metric_name == "e_inter_additive_binder"]
        assert len(add_metrics) == 1
        assert add_metrics[0].unit == "kcal/mol"
        assert abs(add_metrics[0].value - (-85.0)) < 2.0

    def test_no_additive_metric_without_label(self) -> None:
        data = _make_thermo_with_gg(n_samples=100)
        calc = EInterCalculator(window_ps=50.0, dt_fs=1.0, thermo_interval=1000)

        result = calc.compute(data)
        assert result is not None

        metrics = calc.create_metrics(result)

        add_metrics = [m for m in metrics if m.metric_name == "e_inter_additive_binder"]
        assert len(add_metrics) == 0

    def test_metric_validates_against_registry(self) -> None:
        registry = MetricsRegistry()

        data = _make_thermo_with_gg(n_samples=100)
        calc = EInterCalculator(registry=registry, window_ps=50.0, dt_fs=1.0, thermo_interval=1000)

        result = calc.compute(data)
        assert result is not None

        metrics = calc.create_metrics(result)
        for m in metrics:
            assert registry.is_valid_metric(m.metric_name)
            valid, error = registry.validate_metric(m.metric_name, m.unit, m.namespace)
            assert valid, f"Metric {m.metric_name} validation failed: {error}"

    def test_metric_provenance_is_attached_when_interface_index_provided(self) -> None:
        data = _make_thermo_with_gg(n_samples=100)
        calc = EInterCalculator(window_ps=50.0, dt_fs=1.0, thermo_interval=1000)

        result = calc.compute(data)
        assert result is not None

        metrics = calc.create_metrics(result, layer_index=2, interface_index=1)
        assert metrics
        for metric in metrics:
            assert metric.layer_index == 2
            assert metric.interface_index == 1


# ---------------------------------------------------------------------------
# Schema conversion tests
# ---------------------------------------------------------------------------


class TestEInterSchema:
    """Tests for EInterResult schema conversion."""

    def test_to_schema_conversion(self) -> None:
        data = _make_thermo_with_gg(n_samples=100)
        calc = EInterCalculator(window_ps=50.0, dt_fs=1.0, thermo_interval=1000)

        result = calc.compute(data)
        assert result is not None

        schema = calc.to_schema(result)

        assert isinstance(schema, EInterResult)
        assert schema.total_e_inter == result.total_e_inter
        assert len(schema.pair_energies) == len(result.pair_results)

    def test_schema_pair_energies(self) -> None:
        pairs = {"a_b": -100.0, "c_d": -200.0}
        data = _make_thermo_with_gg(n_samples=100, pairs=pairs)
        calc = EInterCalculator(window_ps=50.0, dt_fs=1.0, thermo_interval=1000)

        result = calc.compute(data)
        assert result is not None

        schema = calc.to_schema(result)

        assert "a_b" in schema.pair_energies
        assert "c_d" in schema.pair_energies

    def test_schema_serialization(self) -> None:
        full_result = EInterFullResult(
            total_e_inter=-300.0,
            total_e_inter_std=5.0,
            pair_results=[
                EInterPairResult(
                    pair_label="a_b",
                    energy_kcal_mol=-100.0,
                    energy_std=2.0,
                    n_samples=50,
                ),
                EInterPairResult(
                    pair_label="c_d",
                    energy_kcal_mol=-200.0,
                    energy_std=3.0,
                    n_samples=50,
                ),
            ],
        )
        calc = EInterCalculator()
        schema = calc.to_schema(full_result)

        json_data = schema.model_dump()
        assert json_data["total_e_inter"] == -300.0
        assert json_data["pair_energies"]["a_b"] == -100.0


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


class TestEInterEdgeCases:
    """Tests for edge cases."""

    def test_single_pair(self) -> None:
        pairs = {"only_pair": -50.0}
        data = _make_thermo_with_gg(n_samples=50, pairs=pairs)
        calc = EInterCalculator(window_ps=50.0, dt_fs=1.0, thermo_interval=1000)

        result = calc.compute(data)
        assert result is not None
        assert len(result.pair_results) == 1
        assert result.pair_results[0].pair_label == "only_pair"

    def test_very_few_samples(self) -> None:
        pairs = {"a_b": -100.0}
        data = _make_thermo_with_gg(n_samples=3, pairs=pairs)
        calc = EInterCalculator(window_ps=1.0, dt_fs=1.0, thermo_interval=1000)

        result = calc.compute(data)
        # Should still work with minimal data
        assert result is not None

    def test_zero_energy_pair(self) -> None:
        pairs = {"zero_pair": 0.0}
        data = _make_thermo_with_gg(n_samples=50, pairs=pairs)
        calc = EInterCalculator(window_ps=50.0, dt_fs=1.0, thermo_interval=1000)

        result = calc.compute(data)
        assert result is not None
        assert abs(result.pair_results[0].energy_kcal_mol) < 2.0


# ---------------------------------------------------------------------------
# Cross-category E_inter tests (CED_B v1 regression)
# ---------------------------------------------------------------------------


class TestEInterCrossCategory:
    """Tests capturing the current cross-category-only E_inter behavior."""

    def test_e_inter_total_is_cross_category_sum(self) -> None:
        """현재 e_inter_total은 주어진 c_gg_* cross-category 합이다.

        GroupAssignmentBuilder는 combinations(2)를 사용하여
        self-pair (saturate_saturate 등)를 생성하지 않음.
        따라서 현재 bulk 경로의 e_inter_total은 총 intermolecular energy가 아니라
        builder가 만든 cross-category pair 합에 해당한다.
        """
        # Cross-category pairs only (no self-pairs)
        pairs = {
            "aromatic_saturate": -100.0,
            "resin_saturate": -50.0,
        }
        data = _make_thermo_with_gg(n_samples=100, pairs=pairs)
        calc = EInterCalculator(window_ps=50.0, dt_fs=1.0, thermo_interval=1000)

        result = calc.compute(data)

        assert result is not None
        # total은 현재 제공된 cross-category pair 합
        assert result.total_e_inter < 0  # attractive
        assert len(result.pair_results) == 2
        assert abs(result.total_e_inter - (-150.0)) < 5.0

        # 각 pair label 확인
        pair_labels = {pr.pair_label for pr in result.pair_results}
        assert pair_labels == {"aromatic_saturate", "resin_saturate"}

    def test_no_self_pair_columns_in_thermo(self) -> None:
        """Calculator는 self-pair 컬럼이 있으면 그대로 감지한다.

        GroupAssignmentBuilder가 self-pair를 생성하지 않으므로
        실제 LAMMPS 출력에는 c_gg_saturate_saturate 같은 컬럼이 없음.
        즉, self-pair 부재는 calculator가 아니라 builder/inputs의 현재 제한이다.
        """
        # Hypothetical self-pair (GroupAssignmentBuilder는 생성하지 않음)
        data = {
            "Step": [1.0, 2.0, 3.0],
            "Temp": [300.0, 300.0, 300.0],
            "c_gg_aromatic_saturate": [-100.0, -100.0, -100.0],
            "c_gg_saturate_saturate": [-50.0, -50.0, -50.0],  # hypothetical self-pair
        }
        gg_cols = EInterCalculator.find_gg_columns(data)

        # Both detected (builder does not currently emit the self-pair input)
        assert "aromatic_saturate" in gg_cols
        assert "saturate_saturate" in gg_cols

    def test_attractive_cross_category_energy(self) -> None:
        """cross-category 상호작용 에너지는 일반적으로 음수(attractive)."""
        pairs = {
            "asphaltene_resin": -250.0,
            "aromatic_resin": -180.0,
            "saturate_aromatic": -120.0,
        }
        data = _make_thermo_with_gg(n_samples=100, pairs=pairs)
        calc = EInterCalculator(window_ps=50.0, dt_fs=1.0, thermo_interval=1000)

        result = calc.compute(data)

        assert result is not None
        # Total should be negative (attractive)
        assert result.total_e_inter < 0
        # Expected: ~(-250) + (-180) + (-120) = -550
        assert abs(result.total_e_inter - (-550.0)) < 10.0
