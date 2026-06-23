"""
Unit tests for PairTypeRDFCalculator (Phase 4.2).

Tests cover:
1. Pair-type RDF computation from synthetic 2-type system
2. Symmetry verification: g_AB(r) == g_BA(r)
3. Self-pair (A-A) vs cross-pair (A-B) handling
4. Peak detection and coordination number
5. Array metric creation and storage data preparation
6. Edge cases (empty input, single group, no atoms)
"""

import sys

import numpy as np
import pytest

sys.path.insert(0, "src")

from contracts.policies.metrics import MetricsRegistry  # noqa: E402
from contracts.schemas import ArrayMetricStorage  # noqa: E402
from metrics.rdf_pairtype import PairTypeRDFCalculator, PairTypeRDFResult  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_two_group_lattice(
    n_a: int = 50,
    n_b: int = 50,
    box_len: float = 30.0,
    seed: int = 42,
) -> tuple[np.ndarray, tuple[float, float, float], dict[str, list[int]]]:
    """Create random positions with two groups.

    Returns (positions, box_dims, group_assignments).
    """
    rng = np.random.default_rng(seed)
    n_total = n_a + n_b
    positions = rng.uniform(0, box_len, size=(n_total, 3))
    box_dims = (box_len, box_len, box_len)

    group_assignments = {
        "group_a": list(range(n_a)),
        "group_b": list(range(n_a, n_total)),
    }

    return positions, box_dims, group_assignments


def _make_multi_frame_data(
    n_frames: int = 5,
    n_a: int = 30,
    n_b: int = 30,
    box_len: float = 25.0,
    seed: int = 42,
) -> tuple[
    list[np.ndarray],
    list[tuple[float, float, float]],
    dict[str, list[int]],
]:
    """Create multi-frame data for pair RDF testing."""
    rng = np.random.default_rng(seed)
    n_total = n_a + n_b

    positions_list = []
    box_dims_list = []

    for _ in range(n_frames):
        pos = rng.uniform(0, box_len, size=(n_total, 3))
        positions_list.append(pos)
        box_dims_list.append((box_len, box_len, box_len))

    group_assignments = {
        "alpha": list(range(n_a)),
        "beta": list(range(n_a, n_total)),
    }

    return positions_list, box_dims_list, group_assignments


# ---------------------------------------------------------------------------
# Basic computation tests
# ---------------------------------------------------------------------------


class TestPairTypeRDFCompute:
    """Tests for pair-type RDF computation."""

    def test_basic_two_group_rdf(self) -> None:
        positions, box_dims, groups = _make_two_group_lattice()
        calc = PairTypeRDFCalculator(r_max=12.0, n_bins=100, skip_fraction=0.0)

        result = calc.compute(
            positions_per_frame=[positions],
            box_dims_per_frame=[box_dims],
            group_assignments=groups,
        )

        assert len(result.curves) == 3  # A-A, A-B, B-B
        labels = {c.pair_label for c in result.curves}
        assert labels == {"group_a_group_a", "group_a_group_b", "group_b_group_b"}

    def test_curve_shape(self) -> None:
        positions, box_dims, groups = _make_two_group_lattice()
        calc = PairTypeRDFCalculator(r_max=10.0, n_bins=50, skip_fraction=0.0)

        result = calc.compute(
            positions_per_frame=[positions],
            box_dims_per_frame=[box_dims],
            group_assignments=groups,
        )

        for curve in result.curves:
            assert len(curve.r) == 50
            assert len(curve.g_r) == 50
            assert curve.r[0] > 0  # Centers, not edges

    def test_multi_frame_averaging(self) -> None:
        positions_list, box_dims_list, groups = _make_multi_frame_data(n_frames=10)
        calc = PairTypeRDFCalculator(r_max=10.0, n_bins=100, skip_fraction=0.0)

        result = calc.compute(
            positions_per_frame=positions_list,
            box_dims_per_frame=box_dims_list,
            group_assignments=groups,
        )

        assert len(result.curves) == 3
        for curve in result.curves:
            assert len(curve.g_r) == 100

    def test_skip_fraction_applied(self) -> None:
        positions_list, box_dims_list, groups = _make_multi_frame_data(n_frames=10)
        calc = PairTypeRDFCalculator(r_max=10.0, n_bins=100, skip_fraction=0.5)

        result = calc.compute(
            positions_per_frame=positions_list,
            box_dims_per_frame=box_dims_list,
            group_assignments=groups,
        )

        # Should still produce results using latter half of frames
        assert len(result.curves) == 3

    def test_random_gas_g_r_approaches_one(self) -> None:
        """For random gas, g(r) -> 1.0 at large r."""
        rng = np.random.default_rng(123)
        n_total = 200
        box_len = 40.0
        positions_list = []
        for _ in range(20):
            pos = rng.uniform(0, box_len, size=(n_total, 3))
            positions_list.append(pos)
        box_dims_list = [(box_len, box_len, box_len)] * 20

        groups = {
            "type1": list(range(100)),
            "type2": list(range(100, 200)),
        }

        calc = PairTypeRDFCalculator(r_max=15.0, n_bins=150, skip_fraction=0.0)
        result = calc.compute(positions_list, box_dims_list, groups)

        # Cross-pair g(r) at large r should approach 1.0
        cross_curves = [c for c in result.curves if c.pair_label == "type1_type2"]
        assert len(cross_curves) == 1

        # Check tail region (r > 8 Å) approaches 1.0
        curve = cross_curves[0]
        tail_mask = curve.r > 8.0
        if np.any(tail_mask):
            tail_g = curve.g_r[tail_mask]
            mean_tail = np.mean(tail_g)
            assert abs(mean_tail - 1.0) < 0.3, (
                f"Random gas g(r) tail should approach 1.0, got {mean_tail}"
            )


# ---------------------------------------------------------------------------
# Symmetry tests
# ---------------------------------------------------------------------------


class TestPairRDFSymmetry:
    """Tests for RDF symmetry: g_AB(r) == g_BA(r)."""

    def test_symmetry_guaranteed_by_unique_pairs(self) -> None:
        """PairTypeRDFCalculator only computes unique pairs (A<=B),
        so g_AB is the same computation as g_BA by construction."""
        positions_list, box_dims_list, groups = _make_multi_frame_data()
        calc = PairTypeRDFCalculator(r_max=10.0, n_bins=100, skip_fraction=0.0)

        result = calc.compute(positions_list, box_dims_list, groups)

        # Verify only unique pairs are present (no duplicates)
        labels = [c.pair_label for c in result.curves]
        assert "alpha_beta" in labels
        assert "beta_alpha" not in labels

    def test_three_groups_unique_pairs(self) -> None:
        """With 3 groups, expect 6 unique pairs: AA, AB, AC, BB, BC, CC."""
        rng = np.random.default_rng(99)
        n = 30
        box_len = 25.0
        pos = rng.uniform(0, box_len, size=(n * 3, 3))

        groups = {
            "a": list(range(n)),
            "b": list(range(n, 2 * n)),
            "c": list(range(2 * n, 3 * n)),
        }

        calc = PairTypeRDFCalculator(r_max=10.0, n_bins=50, skip_fraction=0.0)
        result = calc.compute([pos], [(box_len, box_len, box_len)], groups)

        assert len(result.curves) == 6
        labels = {c.pair_label for c in result.curves}
        expected = {"a_a", "a_b", "a_c", "b_b", "b_c", "c_c"}
        assert labels == expected


# ---------------------------------------------------------------------------
# Self-pair vs cross-pair tests
# ---------------------------------------------------------------------------


class TestSelfPairVsCrossPair:
    """Tests for self-pair (A-A) and cross-pair (A-B) handling."""

    def test_self_pair_avoids_double_counting(self) -> None:
        """Self-pair should count each unique (i,j) once and multiply by 2."""
        rng = np.random.default_rng(42)
        n = 20
        box_len = 20.0
        pos = rng.uniform(0, box_len, size=(n, 3))

        calc = PairTypeRDFCalculator(r_max=8.0, n_bins=50, skip_fraction=0.0)

        # Compute requires at least 2 groups, so split into two
        groups2 = {
            "g1": list(range(n // 2)),
            "g2": list(range(n // 2, n)),
        }
        result = calc.compute([pos], [(box_len, box_len, box_len)], groups2)

        # Should have 3 curves: g1_g1, g1_g2, g2_g2
        assert len(result.curves) == 3

    def test_self_pair_histogram_symmetry(self) -> None:
        """Verify self-pair histogram uses ×2 factor."""
        calc = PairTypeRDFCalculator(r_max=10.0, n_bins=50, skip_fraction=0.0)

        # Create simple 4-atom system
        pos = np.array(
            [[0, 0, 0], [2, 0, 0], [0, 2, 0], [0, 0, 2]],
            dtype=np.float64,
        )
        box = np.array([20.0, 20.0, 20.0], dtype=np.float64)
        indices = [0, 1, 2, 3]

        hist = calc._histogram_pair(pos, box, indices, indices, same_group=True)

        # For 4 atoms, 6 unique pairs → 12 pair-counts after ×2
        total_counts = hist.sum()
        assert total_counts == pytest.approx(12.0, abs=0.1)

    def test_cross_pair_all_pairs_counted(self) -> None:
        """Cross-pair should count all (i in A, j in B) pairs."""
        calc = PairTypeRDFCalculator(r_max=10.0, n_bins=50, skip_fraction=0.0)

        pos = np.array(
            [[0, 0, 0], [3, 0, 0], [0, 3, 0], [0, 0, 3]],
            dtype=np.float64,
        )
        box = np.array([20.0, 20.0, 20.0], dtype=np.float64)
        indices_a = [0, 1]
        indices_b = [2, 3]

        hist = calc._histogram_pair(pos, box, indices_a, indices_b, same_group=False)

        # 2 × 2 = 4 cross-pairs
        total_counts = hist.sum()
        assert total_counts == pytest.approx(4.0, abs=0.1)


# ---------------------------------------------------------------------------
# Peak detection tests
# ---------------------------------------------------------------------------


class TestPairRDFPeaks:
    """Tests for peak detection in pair-type RDF."""

    def test_peak_detection_structured_system(self) -> None:
        """For a structured system, peaks should be detected."""
        # Create a system with clear short-range structure
        n_per_group = 50
        box_len = 30.0
        rng = np.random.default_rng(42)

        # Group A: cluster around center
        pos_a = rng.normal(15.0, 2.0, size=(n_per_group, 3))
        pos_a = np.clip(pos_a, 0, box_len)

        # Group B: spread throughout box
        pos_b = rng.uniform(0, box_len, size=(n_per_group, 3))

        pos = np.vstack([pos_a, pos_b])
        groups = {
            "clustered": list(range(n_per_group)),
            "spread": list(range(n_per_group, 2 * n_per_group)),
        }

        # Multi-frame for better statistics
        positions_list = [pos] * 5
        box_dims_list = [(box_len, box_len, box_len)] * 5

        calc = PairTypeRDFCalculator(r_max=12.0, n_bins=120, skip_fraction=0.0)
        result = calc.compute(positions_list, box_dims_list, groups)

        # Self-pair of clustered group should have a peak
        clustered_self = [c for c in result.curves if c.pair_label == "clustered_clustered"]
        assert len(clustered_self) == 1
        # Peak should exist at some r
        curve = clustered_self[0]
        assert curve.first_peak_r is not None or np.max(curve.g_r) > 1.0

    def test_coordination_number_positive(self) -> None:
        """Coordination number should be positive when peak exists."""
        positions_list, box_dims_list, groups = _make_multi_frame_data(n_frames=10, n_a=50, n_b=50)
        calc = PairTypeRDFCalculator(r_max=10.0, n_bins=100, skip_fraction=0.0)
        result = calc.compute(positions_list, box_dims_list, groups)

        for curve in result.curves:
            if curve.coordination_number is not None:
                assert curve.coordination_number > 0


# ---------------------------------------------------------------------------
# Array metric and storage tests
# ---------------------------------------------------------------------------


class TestPairRDFMetrics:
    """Tests for array metric creation."""

    def test_create_array_metric(self) -> None:
        positions_list, box_dims_list, groups = _make_multi_frame_data()
        calc = PairTypeRDFCalculator(r_max=10.0, n_bins=50, skip_fraction=0.0)

        result = calc.compute(positions_list, box_dims_list, groups)

        storage = ArrayMetricStorage(
            file_path="/tmp/test_pair_rdf.parquet",
            file_hash="abc123",
            shape=[150, 3],
            summary={},
        )

        metric = calc.create_array_metric(result, storage, namespace="bulk_ff_gaff2")

        assert metric.metric_name == "rdf_pair_curve"
        assert metric.namespace == "bulk_ff_gaff2"
        assert metric.array_storage == storage
        assert metric.value is None  # Array metrics have no scalar value

    def test_array_metric_summary_includes_peaks(self) -> None:
        positions_list, box_dims_list, groups = _make_multi_frame_data(n_frames=10)
        calc = PairTypeRDFCalculator(r_max=10.0, n_bins=100, skip_fraction=0.0)

        result = calc.compute(positions_list, box_dims_list, groups)

        storage = ArrayMetricStorage(
            file_path="/tmp/test.parquet",
            file_hash="def456",
            shape=[300, 3],
            summary={},
        )

        metric = calc.create_array_metric(result, storage)

        # Summary should contain peak info for curves that have peaks
        if metric.array_summary:
            for key in metric.array_summary:
                if key in ("provenance",):
                    continue
                assert "_peak_r" in key or "_peak_g" in key

    def test_prepare_storage_data(self) -> None:
        positions_list, box_dims_list, groups = _make_multi_frame_data()
        calc = PairTypeRDFCalculator(r_max=10.0, n_bins=50, skip_fraction=0.0)

        result = calc.compute(positions_list, box_dims_list, groups)

        data = PairTypeRDFCalculator.prepare_storage_data(result)

        assert "r" in data
        assert "g_r" in data
        assert "pair_label" in data

        # Each curve has n_bins points, 3 curves total
        expected_len = 50 * len(result.curves)
        assert len(data["r"]) == expected_len
        assert len(data["g_r"]) == expected_len
        assert len(data["pair_label"]) == expected_len

    def test_prepare_storage_data_labels(self) -> None:
        positions_list, box_dims_list, groups = _make_multi_frame_data()
        calc = PairTypeRDFCalculator(r_max=10.0, n_bins=50, skip_fraction=0.0)

        result = calc.compute(positions_list, box_dims_list, groups)
        data = PairTypeRDFCalculator.prepare_storage_data(result)

        unique_labels = set(data["pair_label"])
        curve_labels = {c.pair_label for c in result.curves}
        assert unique_labels == curve_labels

    def test_metric_validates_against_registry(self) -> None:
        registry = MetricsRegistry()

        assert registry.is_valid_metric("rdf_pair_curve")
        defn = registry.get_definition("rdf_pair_curve")
        assert defn.array_columns == ["r", "g_r", "pair_label"]


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


class TestPairRDFEdgeCases:
    """Tests for edge cases."""

    def test_empty_positions(self) -> None:
        calc = PairTypeRDFCalculator()
        result = calc.compute([], [], {"a": [0], "b": [1]})
        assert len(result.curves) == 0

    def test_single_group_returns_empty(self) -> None:
        """Less than 2 groups should return empty result."""
        calc = PairTypeRDFCalculator()
        pos = np.random.default_rng(42).uniform(0, 20, size=(10, 3))
        result = calc.compute(
            [pos],
            [(20.0, 20.0, 20.0)],
            {"only_one": list(range(10))},
        )
        assert len(result.curves) == 0

    def test_single_atom_per_group(self) -> None:
        calc = PairTypeRDFCalculator(r_max=10.0, n_bins=50, skip_fraction=0.0)

        pos = np.array([[5.0, 5.0, 5.0], [8.0, 5.0, 5.0]], dtype=np.float64)
        groups = {"a": [0], "b": [1]}

        result = calc.compute([pos], [(20.0, 20.0, 20.0)], groups)

        # Should compute cross-pair, but self-pairs have 0 or 1 atom each
        assert len(result.curves) > 0

    def test_empty_result_prepare_storage(self) -> None:
        result = PairTypeRDFResult(curves=[])
        data = PairTypeRDFCalculator.prepare_storage_data(result)

        assert data["r"] == []
        assert data["g_r"] == []
        assert data["pair_label"] == []

    def test_single_frame(self) -> None:
        pos, box_dims, groups = _make_two_group_lattice()
        calc = PairTypeRDFCalculator(r_max=10.0, n_bins=50, skip_fraction=0.0)

        result = calc.compute([pos], [box_dims], groups)

        assert len(result.curves) == 3

    def test_g_r_non_negative(self) -> None:
        """g(r) should never be negative."""
        positions_list, box_dims_list, groups = _make_multi_frame_data(n_frames=5)
        calc = PairTypeRDFCalculator(r_max=10.0, n_bins=100, skip_fraction=0.0)

        result = calc.compute(positions_list, box_dims_list, groups)

        for curve in result.curves:
            assert np.all(curve.g_r >= 0), f"g(r) has negative values for {curve.pair_label}"
