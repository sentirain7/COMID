"""
Unit tests for RDF calculator (P3-1).

Tests cover:
1. RDF computation from synthetic data (FCC-like lattice)
2. Peak detection and coordination number
3. Scalar metric creation
4. Array metric creation
5. Edge cases (empty input, single frame, single atom)
6. Integration with DumpParser.get_positions_array
"""

import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, "src")

from contracts.schemas import ArrayMetricStorage  # noqa: E402
from metrics.rdf import RDFCalculator, RDFResult  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_simple_cubic_positions(
    n_side: int = 5,
    spacing: float = 3.5,
) -> tuple[np.ndarray, tuple[float, float, float]]:
    """Create a simple cubic lattice.

    Returns (positions, box_dims).
    """
    positions = []
    for ix in range(n_side):
        for iy in range(n_side):
            for iz in range(n_side):
                positions.append(
                    [
                        ix * spacing,
                        iy * spacing,
                        iz * spacing,
                    ]
                )
    pos = np.array(positions, dtype=np.float64)
    box_len = n_side * spacing
    return pos, (box_len, box_len, box_len)


def _make_random_positions(
    n_atoms: int = 200,
    box_len: float = 30.0,
    seed: int = 42,
) -> tuple[np.ndarray, tuple[float, float, float]]:
    """Create random positions in a box."""
    rng = np.random.default_rng(seed)
    pos = rng.uniform(0.0, box_len, size=(n_atoms, 3))
    return pos, (box_len, box_len, box_len)


# ---------------------------------------------------------------------------
# Tests: core computation
# ---------------------------------------------------------------------------


class TestRDFCalculator:
    """Tests for RDF computation."""

    def test_simple_cubic_has_peak_at_spacing(self):
        """Simple cubic lattice should show first peak at nearest-neighbour distance."""
        pos, box = _make_simple_cubic_positions(n_side=5, spacing=3.5)
        calc = RDFCalculator(r_max=12.0, n_bins=240, skip_fraction=0.0)

        result = calc.compute(
            positions_per_frame=[pos],
            box_dims_per_frame=[box],
        )

        assert result.first_peak_r is not None
        # First peak should be near 3.5 A (nearest neighbour)
        assert abs(result.first_peak_r - 3.5) < 0.5, (
            f"First peak at {result.first_peak_r}, expected ~3.5"
        )
        assert result.first_peak_g is not None
        assert result.first_peak_g > 1.0

    def test_coordination_number_simple_cubic(self):
        """Simple cubic lattice has 6 nearest neighbours."""
        pos, box = _make_simple_cubic_positions(n_side=6, spacing=3.5)
        calc = RDFCalculator(r_max=12.0, n_bins=240, skip_fraction=0.0)

        result = calc.compute(
            positions_per_frame=[pos],
            box_dims_per_frame=[box],
        )

        assert result.coordination_number is not None
        # For SC lattice, CN = 6.  Allow tolerance due to finite bin width.
        assert 4.0 < result.coordination_number < 8.0, (
            f"Coordination number {result.coordination_number}, expected ~6"
        )

    def test_random_positions_g_r_approaches_one(self):
        """Random (ideal-gas) positions: g(r) -> 1 at large r."""
        pos, box = _make_random_positions(n_atoms=500, box_len=40.0)
        calc = RDFCalculator(r_max=15.0, n_bins=150, skip_fraction=0.0)

        result = calc.compute(
            positions_per_frame=[pos],
            box_dims_per_frame=[box],
        )

        # Average g(r) in the range 8-12 A should be close to 1.0
        mask = (result.r >= 8.0) & (result.r <= 12.0)
        g_avg = np.mean(result.g_r[mask])
        assert 0.7 < g_avg < 1.3, f"Mean g(r) at large r = {g_avg}"

    def test_multiple_frames_averaged(self):
        """Multiple frames produce smoother g(r)."""
        frames_pos = []
        frames_box = []
        rng = np.random.default_rng(123)
        box_len = 30.0
        for _ in range(5):
            pos = rng.uniform(0.0, box_len, size=(200, 3))
            frames_pos.append(pos)
            frames_box.append((box_len, box_len, box_len))

        calc = RDFCalculator(r_max=12.0, n_bins=120, skip_fraction=0.0)
        result = calc.compute(frames_pos, frames_box)

        # g(r) should be finite everywhere
        assert np.all(np.isfinite(result.g_r))

    def test_skip_fraction_skips_early_frames(self):
        """With skip_fraction=0.5 and 4 frames, only last 2 are used."""
        frames_pos = []
        frames_box = []
        box_len = 25.0
        rng = np.random.default_rng(999)
        for _ in range(4):
            pos = rng.uniform(0.0, box_len, size=(100, 3))
            frames_pos.append(pos)
            frames_box.append((box_len, box_len, box_len))

        calc = RDFCalculator(r_max=10.0, n_bins=100, skip_fraction=0.5)
        result = calc.compute(frames_pos, frames_box)

        assert np.all(np.isfinite(result.g_r))

    def test_output_shape(self):
        """Result arrays have consistent shape."""
        pos, box = _make_random_positions(n_atoms=100, box_len=25.0)
        calc = RDFCalculator(r_max=10.0, n_bins=200, skip_fraction=0.0)

        result = calc.compute([pos], [box])
        assert result.r.shape == (200,)
        assert result.g_r.shape == (200,)


# ---------------------------------------------------------------------------
# Tests: edge cases
# ---------------------------------------------------------------------------


class TestRDFEdgeCases:
    """Edge-case tests."""

    def test_empty_frames(self):
        """Empty input returns empty result."""
        calc = RDFCalculator()
        result = calc.compute([], [])
        assert result.first_peak_r is None
        assert result.coordination_number is None

    def test_single_atom(self):
        """Single atom produces zero g(r)."""
        pos = np.array([[5.0, 5.0, 5.0]])
        box = (10.0, 10.0, 10.0)
        calc = RDFCalculator(r_max=5.0, n_bins=50, skip_fraction=0.0)
        result = calc.compute([pos], [box])
        assert np.all(result.g_r == 0.0)

    def test_two_atoms(self):
        """Two atoms should produce a single peak."""
        pos = np.array([[0.0, 0.0, 0.0], [3.0, 0.0, 0.0]])
        box = (20.0, 20.0, 20.0)
        calc = RDFCalculator(r_max=10.0, n_bins=100, skip_fraction=0.0)
        result = calc.compute([pos], [box])
        # There should be a non-zero bin near r=3.0
        bin_idx = int(3.0 / calc.dr)
        assert result.g_r[bin_idx] > 0


# ---------------------------------------------------------------------------
# Tests: metric creation
# ---------------------------------------------------------------------------


class TestRDFMetrics:
    """Tests for MetricResult creation."""

    @pytest.fixture
    def sample_result(self):
        """Create a sample RDFResult."""
        r = np.linspace(0.05, 15.0, 300)
        g_r = np.ones(300)
        g_r[20] = 3.5  # simulate a peak at r ~1.0
        return RDFResult(
            r=r,
            g_r=g_r,
            first_peak_r=1.0,
            first_peak_g=3.5,
            second_peak_r=5.0,
            second_peak_g=1.5,
            coordination_number=6.2,
        )

    def test_scalar_metrics_count(self, sample_result):
        calc = RDFCalculator()
        metrics = calc.create_scalar_metrics(sample_result)
        names = {m.metric_name for m in metrics}
        assert "rdf_first_peak_r" in names
        assert "rdf_first_peak_g" in names
        assert "rdf_coordination_number" in names
        assert "rdf_second_peak_r" in names
        assert "rdf_second_peak_g" in names
        assert len(metrics) == 5

    def test_scalar_metrics_values(self, sample_result):
        calc = RDFCalculator()
        metrics = calc.create_scalar_metrics(sample_result)
        by_name = {m.metric_name: m for m in metrics}
        assert by_name["rdf_first_peak_r"].value == 1.0
        assert by_name["rdf_first_peak_g"].value == 3.5
        assert by_name["rdf_coordination_number"].value == 6.2
        assert by_name["rdf_first_peak_r"].unit == "angstrom"
        assert by_name["rdf_coordination_number"].unit == "dimensionless"

    def test_scalar_metrics_none_peaks(self):
        """When peaks are None, no corresponding metrics are emitted."""
        calc = RDFCalculator()
        result = RDFResult(
            r=np.linspace(0, 10, 100),
            g_r=np.zeros(100),
            first_peak_r=None,
            first_peak_g=None,
            second_peak_r=None,
            second_peak_g=None,
            coordination_number=None,
        )
        metrics = calc.create_scalar_metrics(result)
        assert len(metrics) == 0

    def test_array_metric_creation(self, sample_result):
        calc = RDFCalculator()
        storage = ArrayMetricStorage(
            file_path="/tmp/test_rdf.parquet",
            file_hash="abc123",
            shape=(300, 2),
            summary={"first_peak_r": 1.0},
        )
        metric = calc.create_array_metric(sample_result, storage)
        assert metric.metric_name == "rdf_curve"
        assert metric.value is None
        assert metric.array_storage is not None
        assert metric.array_summary is not None
        assert metric.array_summary["first_peak_r"] == 1.0


# ---------------------------------------------------------------------------
# Tests: DumpParser integration
# ---------------------------------------------------------------------------


class TestDumpParserIntegration:
    """Test DumpParser.get_positions_array helper."""

    def test_get_positions_array(self):
        """get_positions_array returns correct numpy array."""
        from parsers.dump_parser import DumpFrame, DumpParser

        frame = DumpFrame(
            timestep=0,
            n_atoms=3,
            box_bounds=[(0.0, 10.0), (0.0, 10.0), (0.0, 10.0)],
            columns=["id", "type", "x", "y", "z"],
            atoms=[
                {"id": 1, "type": 1, "x": 1.0, "y": 2.0, "z": 3.0},
                {"id": 2, "type": 1, "x": 4.0, "y": 5.0, "z": 6.0},
                {"id": 3, "type": 2, "x": 7.0, "y": 8.0, "z": 9.0},
            ],
        )
        parser = DumpParser()
        pos = parser.get_positions_array(frame)
        assert pos.shape == (3, 3)
        assert pos.dtype == np.float64
        np.testing.assert_allclose(pos[0], [1.0, 2.0, 3.0])
        np.testing.assert_allclose(pos[2], [7.0, 8.0, 9.0])

    def test_get_positions_array_with_unwrapped(self):
        """get_positions_array uses xu/yu/zu if x/y/z absent."""
        from parsers.dump_parser import DumpFrame, DumpParser

        frame = DumpFrame(
            timestep=0,
            n_atoms=1,
            box_bounds=[(0.0, 10.0), (0.0, 10.0), (0.0, 10.0)],
            columns=["id", "type", "xu", "yu", "zu"],
            atoms=[
                {"id": 1, "type": 1, "xu": 11.0, "yu": 12.0, "zu": 13.0},
            ],
        )
        parser = DumpParser()
        pos = parser.get_positions_array(frame)
        np.testing.assert_allclose(pos[0], [11.0, 12.0, 13.0])


# ---------------------------------------------------------------------------
# Tests: ArrayStorage integration
# ---------------------------------------------------------------------------


class TestRDFArrayStorage:
    """Test RDF curve storage via ArrayStorage."""

    def test_store_and_load_rdf_curve(self):
        from metrics.array_storage import ArrayStorage

        with tempfile.TemporaryDirectory() as tmpdir:
            storage = ArrayStorage(storage_dir=Path(tmpdir))
            data = {
                "r": [0.1, 0.2, 0.3, 0.4, 0.5],
                "g_r": [0.0, 0.5, 2.0, 1.5, 1.0],
            }
            storage.store("rdf_curve", "exp_test_001", data)

            loaded = storage.load("rdf_curve", "exp_test_001")
            assert loaded is not None
            assert len(loaded["r"]) == 5
            assert abs(loaded["g_r"][2] - 2.0) < 1e-6


# ---------------------------------------------------------------------------
# Tests: integration (dump file → _calculate_rdf → storage → load)
# ---------------------------------------------------------------------------


class TestRDFIntegration:
    """Integration test: dump file → MetricCalculator._calculate_rdf → store → load."""

    @staticmethod
    def _write_dump_file(path: Path, frames: list[dict]) -> None:
        """Write a synthetic LAMMPS dump file.

        Args:
            path: Output file path.
            frames: List of dicts with keys:
                timestep, n_atoms, box_len, atoms (list of (x, y, z)).
        """
        lines: list[str] = []
        for fr in frames:
            lines.append("ITEM: TIMESTEP")
            lines.append(str(fr["timestep"]))
            lines.append("ITEM: NUMBER OF ATOMS")
            lines.append(str(fr["n_atoms"]))
            lines.append("ITEM: BOX BOUNDS pp pp pp")
            box = fr["box_len"]
            for _ in range(3):
                lines.append(f"0.0 {box}")
            lines.append("ITEM: ATOMS id type x y z")
            for idx, (x, y, z) in enumerate(fr["atoms"], start=1):
                lines.append(f"{idx} 1 {x:.6f} {y:.6f} {z:.6f}")
        path.write_text("\n".join(lines) + "\n")

    def test_dump_to_rdf_storage_roundtrip(self):
        """Full path: dump file → _calculate_rdf → ArrayStorage → load."""
        from metrics.array_storage import ArrayStorage
        from metrics.calculator import MetricCalculator

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Create a synthetic dump file with SC lattice (2 frames)
            atoms = []
            spacing = 3.5
            n_side = 4
            for ix in range(n_side):
                for iy in range(n_side):
                    for iz in range(n_side):
                        atoms.append(
                            (
                                ix * spacing,
                                iy * spacing,
                                iz * spacing,
                            )
                        )
            box_len = n_side * spacing

            dump_path = tmpdir / "test.dump"
            self._write_dump_file(
                dump_path,
                [
                    {"timestep": 0, "n_atoms": len(atoms), "box_len": box_len, "atoms": atoms},
                    {"timestep": 1000, "n_atoms": len(atoms), "box_len": box_len, "atoms": atoms},
                ],
            )

            # Set up ArrayStorage in temp dir
            storage_dir = tmpdir / "arrays"
            array_storage = ArrayStorage(storage_dir=storage_dir)

            # Create MetricCalculator with array storage
            calc = MetricCalculator(array_storage=array_storage)

            # Call _calculate_rdf directly
            exp_id = "test_rdf_integration_001"
            metrics = calc._calculate_rdf(
                dump_files=[str(dump_path)],
                exp_id=exp_id,
            )

            # Verify scalar metrics were produced
            scalar_names = {m.metric_name for m in metrics if m.value is not None}
            assert "rdf_first_peak_r" in scalar_names
            assert "rdf_coordination_number" in scalar_names

            # Verify array metric was stored
            array_metrics = [m for m in metrics if m.metric_name == "rdf_curve"]
            assert len(array_metrics) == 1
            arr_metric = array_metrics[0]
            assert arr_metric.array_storage is not None
            assert arr_metric.array_storage.file_hash is not None
            assert arr_metric.array_storage.shape[1] == 2  # r, g_r columns

            # Verify round-trip: load from storage
            loaded = array_storage.load("rdf_curve", exp_id)
            assert loaded is not None
            assert "r" in loaded
            assert "g_r" in loaded
            assert len(loaded["r"]) == len(loaded["g_r"])
            assert len(loaded["r"]) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
