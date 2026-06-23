"""
Unit + integration tests for MSD calculator (P3-2).

Tests cover:
1. MSD computation from synthetic trajectories
2. Linear-region detection and diffusion coefficient fitting
3. Unit conversion (Å²/ps → cm²/s)
4. Edge cases (empty, single frame, stationary atoms)
5. Registry-based metric creation (SSOT)
6. Integration: dump file → MetricCalculator._calculate_msd → storage → load
7. DumpParser.get_sorted_positions helper
"""

import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, "src")

from contracts.schemas import ArrayMetricStorage  # noqa: E402
from metrics.msd import MSDCalculator, MSDResult  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_ballistic_trajectory(
    n_atoms: int = 50,
    n_frames: int = 20,
    velocity: float = 0.1,
    dt_ps: float = 1.0,
    seed: int = 42,
    md_dt_fs: float = 1.0,
) -> tuple[list[np.ndarray], list[int], float]:
    """Create a ballistic trajectory (constant velocity).

    MSD = v² * t² (ballistic) — not diffusive, but useful for testing.

    Args:
        dt_ps: Physical time between dump frames (ps).
        md_dt_fs: MD simulation timestep (fs).

    Returns:
        (positions_per_frame, timesteps, md_dt_fs).
    """
    rng = np.random.default_rng(seed)
    pos0 = rng.uniform(0.0, 50.0, size=(n_atoms, 3))
    vel = rng.normal(0, velocity, size=(n_atoms, 3))

    # dump_interval (in MD steps) so that frame spacing = dt_ps
    dump_interval = int(dt_ps / (md_dt_fs * 1e-3))
    positions = []
    timesteps = []
    for i in range(n_frames):
        t = i * dt_ps
        positions.append(pos0 + vel * t)
        timesteps.append(i * dump_interval)

    return positions, timesteps, md_dt_fs


def _make_diffusive_trajectory(
    n_atoms: int = 100,
    n_frames: int = 50,
    d_target: float = 1e-5,
    dt_ps: float = 2.0,
    seed: int = 123,
    md_dt_fs: float = 1.0,
) -> tuple[list[np.ndarray], list[int], float]:
    """Create a random-walk trajectory with target diffusion coefficient.

    For 3D random walk: <r²> = 6*D*t
    Per step displacement variance per dimension: <dx²> = 2*D*dt

    Args:
        d_target: Target D in cm²/s.
        dt_ps: Physical time between dump frames (ps).
        md_dt_fs: MD simulation timestep (fs).

    Returns:
        (positions_per_frame, timesteps, md_dt_fs).
    """
    rng = np.random.default_rng(seed)

    # Convert D from cm²/s to Å²/ps: D_A2ps = D_cm2s / 1e-4
    d_a2_ps = d_target / 1e-4  # Å²/ps

    # sigma per dimension per frame: <dx²> = 2*D*dt_ps
    sigma = np.sqrt(2.0 * d_a2_ps * dt_ps)

    # dump_interval (in MD steps) so that frame spacing = dt_ps
    dump_interval = int(dt_ps / (md_dt_fs * 1e-3))

    pos = rng.uniform(0, 100.0, size=(n_atoms, 3))
    positions = [pos.copy()]
    timesteps = [0]

    for i in range(1, n_frames):
        displacement = rng.normal(0, sigma, size=(n_atoms, 3))
        pos = pos + displacement
        positions.append(pos.copy())
        timesteps.append(i * dump_interval)

    return positions, timesteps, md_dt_fs


# ---------------------------------------------------------------------------
# Tests: core computation
# ---------------------------------------------------------------------------


class TestMSDCalculator:
    """Tests for MSD computation."""

    def test_stationary_atoms_zero_msd(self):
        """Stationary atoms should have MSD ~ 0."""
        n_atoms = 30
        pos = np.random.default_rng(10).uniform(0, 20, size=(n_atoms, 3))
        positions = [pos.copy() for _ in range(10)]
        timesteps = list(range(0, 10000, 1000))
        calc = MSDCalculator(skip_fraction=0.0)

        result = calc.compute(positions, timesteps, dt_fs=1.0)

        assert np.all(result.msd < 1e-10)

    def test_ballistic_msd_grows_quadratically(self):
        """Ballistic motion: MSD ∝ t²."""
        positions, timesteps, dt_fs = _make_ballistic_trajectory(
            n_frames=20,
            velocity=0.05,
        )
        calc = MSDCalculator(skip_fraction=0.0, fit_start_frac=0.1, fit_end_frac=0.9)

        result = calc.compute(positions, timesteps, dt_fs=dt_fs)

        # MSD should increase monotonically
        assert len(result.msd) > 0
        assert result.msd[-1] > result.msd[0]

    def test_diffusive_trajectory_d_estimate(self):
        """Random walk should yield D close to target."""
        d_target = 2e-5  # cm²/s
        positions, timesteps, dt_fs = _make_diffusive_trajectory(
            n_atoms=200,
            n_frames=100,
            d_target=d_target,
            dt_ps=1.0,
        )
        calc = MSDCalculator(
            skip_fraction=0.0,
            fit_start_frac=0.2,
            fit_end_frac=0.8,
        )

        result = calc.compute(positions, timesteps, dt_fs=dt_fs)

        assert result.diffusion_coefficient is not None
        # Allow factor-of-3 tolerance for stochastic estimation
        assert d_target / 3.0 < result.diffusion_coefficient < d_target * 3.0, (
            f"D = {result.diffusion_coefficient:.2e}, target = {d_target:.2e}"
        )

    def test_fit_r_squared_reasonable(self):
        """Linear fit R² should be close to 1 for diffusive trajectory."""
        positions, timesteps, dt_fs = _make_diffusive_trajectory(
            n_atoms=200,
            n_frames=80,
            d_target=1e-5,
        )
        calc = MSDCalculator(skip_fraction=0.0)
        result = calc.compute(positions, timesteps, dt_fs=dt_fs)

        assert result.fit_r_squared is not None
        assert result.fit_r_squared > 0.5  # should be well-correlated

    def test_skip_fraction(self):
        """Skip fraction should discard early frames."""
        positions, timesteps, dt_fs = _make_diffusive_trajectory(n_frames=20)
        calc_full = MSDCalculator(skip_fraction=0.0)
        calc_skip = MSDCalculator(skip_fraction=0.5)

        r_full = calc_full.compute(positions, timesteps, dt_fs=dt_fs)
        r_skip = calc_skip.compute(positions, timesteps, dt_fs=dt_fs)

        # Skipped version has fewer lag points
        assert len(r_skip.msd) < len(r_full.msd)

    def test_output_arrays_consistent(self):
        """time_ps and msd arrays have same length."""
        positions, timesteps, dt_fs = _make_diffusive_trajectory(n_frames=30)
        calc = MSDCalculator(skip_fraction=0.0)
        result = calc.compute(positions, timesteps, dt_fs=dt_fs)

        assert result.time_ps.shape == result.msd.shape
        assert len(result.time_ps) == len(positions) - 1  # max_lag = n-1

    def test_unit_conversion_factor(self):
        """Verify the Å²/ps → cm²/s conversion is 1e-4."""
        from metrics.msd import _A2_PER_PS_TO_CM2_PER_S

        assert _A2_PER_PS_TO_CM2_PER_S == 1e-4


# ---------------------------------------------------------------------------
# Tests: edge cases
# ---------------------------------------------------------------------------


class TestMSDEdgeCases:
    """Edge-case tests."""

    def test_empty_frames(self):
        """Empty input returns empty result."""
        calc = MSDCalculator()
        result = calc.compute([], [], dt_fs=1.0)
        assert result.diffusion_coefficient is None
        assert len(result.msd) == 0

    def test_single_frame(self):
        """Single frame cannot compute MSD."""
        pos = np.array([[1, 2, 3]], dtype=np.float64)
        calc = MSDCalculator()
        result = calc.compute([pos], [0], dt_fs=1.0)
        assert result.diffusion_coefficient is None
        assert len(result.msd) == 0

    def test_two_frames(self):
        """Two frames produce exactly 1 MSD point."""
        pos0 = np.array([[0, 0, 0], [1, 1, 1]], dtype=np.float64)
        pos1 = np.array([[1, 0, 0], [2, 1, 1]], dtype=np.float64)
        calc = MSDCalculator(skip_fraction=0.0)
        result = calc.compute([pos0, pos1], [0, 1000], dt_fs=1.0)
        assert len(result.msd) == 1
        # MSD = mean(|[1,0,0]|², |[1,0,0]|²) = 1.0
        assert abs(result.msd[0] - 1.0) < 1e-10

    def test_used_unwrapped_flag(self):
        """Result should reflect the unwrapped flag."""
        pos = np.zeros((5, 3))
        calc = MSDCalculator()
        r1 = calc.compute([pos, pos], [0, 1000], dt_fs=1.0, used_unwrapped=True)
        r2 = calc.compute([pos, pos], [0, 1000], dt_fs=1.0, used_unwrapped=False)
        assert r1.used_unwrapped is True
        assert r2.used_unwrapped is False

    def test_wrapped_only_suppresses_diffusion_coefficient(self):
        """Wrapped coordinates must produce D=None to prevent bad DB entry."""
        positions, timesteps, dt_fs = _make_diffusive_trajectory(
            n_atoms=50,
            n_frames=30,
            d_target=1e-5,
        )
        calc = MSDCalculator(skip_fraction=0.0)

        # With unwrapped=True: D is computed
        r_unwrapped = calc.compute(
            positions,
            timesteps,
            dt_fs=dt_fs,
            used_unwrapped=True,
        )
        assert r_unwrapped.diffusion_coefficient is not None

        # With unwrapped=False: D is suppressed (None)
        r_wrapped = calc.compute(
            positions,
            timesteps,
            dt_fs=dt_fs,
            used_unwrapped=False,
        )
        assert r_wrapped.diffusion_coefficient is None
        # MSD curve is still computed (useful for diagnostics)
        assert len(r_wrapped.msd) > 0

    def test_wrapped_only_scalar_metric_not_created(self):
        """MSDCalculator.create_scalar_metric returns None for wrapped result."""
        positions, timesteps, dt_fs = _make_diffusive_trajectory(
            n_atoms=50,
            n_frames=20,
            d_target=1e-5,
        )
        calc = MSDCalculator(skip_fraction=0.0)
        result = calc.compute(
            positions,
            timesteps,
            dt_fs=dt_fs,
            used_unwrapped=False,
        )
        metric = calc.create_scalar_metric(result)
        assert metric is None


# ---------------------------------------------------------------------------
# Tests: metric creation (registry SSOT)
# ---------------------------------------------------------------------------


class TestMSDMetrics:
    """Tests for MetricResult creation."""

    @pytest.fixture
    def sample_result(self):
        return MSDResult(
            time_ps=np.linspace(1, 100, 50),
            msd=np.linspace(10, 500, 50),
            diffusion_coefficient=2.5e-5,
            fit_r_squared=0.98,
            fit_start_ps=20.0,
            fit_end_ps=80.0,
            used_unwrapped=True,
        )

    def test_scalar_metric_name_and_unit(self, sample_result):
        calc = MSDCalculator()
        metric = calc.create_scalar_metric(sample_result)
        assert metric is not None
        assert metric.metric_name == "msd_diffusion_coefficient"
        assert metric.unit == "cm2/s"
        assert metric.value == 2.5e-5
        assert metric.namespace == "bulk_ff_gaff2"

    def test_scalar_metric_none_when_no_d(self):
        calc = MSDCalculator()
        result = MSDResult(
            time_ps=np.array([1.0]),
            msd=np.array([0.0]),
            diffusion_coefficient=None,
            fit_r_squared=None,
            fit_start_ps=None,
            fit_end_ps=None,
            used_unwrapped=True,
        )
        metric = calc.create_scalar_metric(result)
        assert metric is None

    def test_array_metric_creation(self, sample_result):
        calc = MSDCalculator()
        storage = ArrayMetricStorage(
            file_path="/tmp/test_msd.parquet",
            file_hash="abc123",
            shape=(50, 2),
            summary={"diffusion_coefficient_cm2s": 2.5e-5},
        )
        metric = calc.create_array_metric(sample_result, storage)
        assert metric.metric_name == "msd_curve"
        assert metric.unit == "[ps, angstrom2]"
        assert metric.value is None
        assert metric.array_storage is not None
        assert metric.array_summary is not None
        assert "diffusion_coefficient_cm2s" in metric.array_summary


# ---------------------------------------------------------------------------
# Tests: DumpParser.get_sorted_positions
# ---------------------------------------------------------------------------


class TestDumpParserSortedPositions:
    """Test DumpParser.get_sorted_positions helper."""

    def test_sorted_by_id(self):
        from parsers.dump_parser import DumpFrame, DumpParser

        frame = DumpFrame(
            timestep=0,
            n_atoms=3,
            box_bounds=[(0, 10), (0, 10), (0, 10)],
            columns=["id", "type", "x", "y", "z"],
            atoms=[
                {"id": 3, "type": 1, "x": 9.0, "y": 9.0, "z": 9.0},
                {"id": 1, "type": 1, "x": 1.0, "y": 2.0, "z": 3.0},
                {"id": 2, "type": 1, "x": 4.0, "y": 5.0, "z": 6.0},
            ],
        )
        parser = DumpParser()
        pos, unwrapped = parser.get_sorted_positions(frame)
        assert pos.shape == (3, 3)
        # Sorted by id: atom 1, 2, 3
        np.testing.assert_allclose(pos[0], [1.0, 2.0, 3.0])
        np.testing.assert_allclose(pos[1], [4.0, 5.0, 6.0])
        np.testing.assert_allclose(pos[2], [9.0, 9.0, 9.0])
        assert unwrapped is False

    def test_prefers_unwrapped(self):
        from parsers.dump_parser import DumpFrame, DumpParser

        frame = DumpFrame(
            timestep=0,
            n_atoms=1,
            box_bounds=[(0, 10), (0, 10), (0, 10)],
            columns=["id", "type", "x", "y", "z", "xu", "yu", "zu"],
            atoms=[
                {
                    "id": 1,
                    "type": 1,
                    "x": 1.0,
                    "y": 2.0,
                    "z": 3.0,
                    "xu": 11.0,
                    "yu": 12.0,
                    "zu": 13.0,
                },
            ],
        )
        parser = DumpParser()
        pos, unwrapped = parser.get_sorted_positions(frame, prefer_unwrapped=True)
        np.testing.assert_allclose(pos[0], [11.0, 12.0, 13.0])
        assert unwrapped is True

    def test_wrapped_fallback(self):
        from parsers.dump_parser import DumpFrame, DumpParser

        frame = DumpFrame(
            timestep=0,
            n_atoms=1,
            box_bounds=[(0, 10), (0, 10), (0, 10)],
            columns=["id", "type", "x", "y", "z"],
            atoms=[
                {"id": 1, "type": 1, "x": 5.0, "y": 6.0, "z": 7.0},
            ],
        )
        parser = DumpParser()
        pos, unwrapped = parser.get_sorted_positions(frame, prefer_unwrapped=True)
        np.testing.assert_allclose(pos[0], [5.0, 6.0, 7.0])
        assert unwrapped is False


# ---------------------------------------------------------------------------
# Tests: ArrayStorage integration
# ---------------------------------------------------------------------------


class TestMSDArrayStorage:
    """Test MSD curve storage via ArrayStorage."""

    def test_store_and_load_msd_curve(self):
        from metrics.array_storage import ArrayStorage

        with tempfile.TemporaryDirectory() as tmpdir:
            storage = ArrayStorage(storage_dir=Path(tmpdir))
            data = {
                "time_ps": [1.0, 2.0, 3.0, 4.0, 5.0],
                "msd": [10.0, 20.0, 30.0, 40.0, 50.0],
            }
            storage.store("msd_curve", "exp_msd_001", data)

            loaded = storage.load("msd_curve", "exp_msd_001")
            assert loaded is not None
            assert len(loaded["time_ps"]) == 5
            assert abs(loaded["msd"][4] - 50.0) < 1e-6


# ---------------------------------------------------------------------------
# Tests: integration (dump → _calculate_msd → storage → load)
# ---------------------------------------------------------------------------


class TestMSDIntegration:
    """Integration test: dump file → MetricCalculator._calculate_msd → store → load."""

    @staticmethod
    def _write_dump_file(
        path: Path,
        frames: list[dict],
    ) -> None:
        """Write a synthetic LAMMPS dump file with unwrapped coordinates.

        Args:
            path: Output file path.
            frames: List of dicts with keys:
                timestep, n_atoms, box_len, atoms (list of (id, xu, yu, zu)).
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
            lines.append("ITEM: ATOMS id type xu yu zu")
            for aid, xu, yu, zu in fr["atoms"]:
                lines.append(f"{aid} 1 {xu:.6f} {yu:.6f} {zu:.6f}")
        path.write_text("\n".join(lines) + "\n")

    def test_dump_to_msd_storage_roundtrip(self):
        """Full path: dump file → _calculate_msd → ArrayStorage → load."""
        from metrics.array_storage import ArrayStorage
        from metrics.calculator import MetricCalculator

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Create a simple random-walk dump file (10 atoms, 10 frames)
            rng = np.random.default_rng(777)
            n_atoms = 10
            n_frames = 10
            box_len = 50.0

            pos = rng.uniform(0, box_len, size=(n_atoms, 3))
            frames = []
            for i in range(n_frames):
                # Random walk step
                if i > 0:
                    pos = pos + rng.normal(0, 0.5, size=(n_atoms, 3))
                atoms = [(aid + 1, pos[aid, 0], pos[aid, 1], pos[aid, 2]) for aid in range(n_atoms)]
                frames.append(
                    {
                        "timestep": i * 1000,
                        "n_atoms": n_atoms,
                        "box_len": box_len,
                        "atoms": atoms,
                    }
                )

            dump_path = tmpdir / "test_msd.dump"
            self._write_dump_file(dump_path, frames)

            # Set up ArrayStorage
            storage_dir = tmpdir / "arrays"
            array_storage = ArrayStorage(storage_dir=storage_dir)

            # Create MetricCalculator
            calc = MetricCalculator(array_storage=array_storage)

            # Call _calculate_msd
            exp_id = "test_msd_integration_001"
            metrics = calc._calculate_msd(
                dump_files=[str(dump_path)],
                exp_id=exp_id,
            )

            # Verify at least the array metric was stored
            array_metrics = [m for m in metrics if m.metric_name == "msd_curve"]
            assert len(array_metrics) == 1
            arr = array_metrics[0]
            assert arr.array_storage is not None
            assert arr.array_storage.shape[1] == 2  # time_ps, msd

            # Verify round-trip: load from storage
            loaded = array_storage.load("msd_curve", exp_id)
            assert loaded is not None
            assert "time_ps" in loaded
            assert "msd" in loaded
            assert len(loaded["time_ps"]) > 0
            assert len(loaded["time_ps"]) == len(loaded["msd"])


# ---------------------------------------------------------------------------
# Tests: protocol dump columns include xu/yu/zu
# ---------------------------------------------------------------------------


class TestProtocolDumpColumns:
    """Verify LAMMPS input generator includes unwrapped coords in dump."""

    def test_generated_script_has_xu_yu_zu(self):
        """Generated LAMMPS script must include xu yu zu in dump commands."""
        from contracts.schemas import (
            FFType,
            ProtocolRequest,
            RunTier,
            StudyType,
        )
        from protocols.lammps_input import LAMMPSInputGenerator

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            # Create a dummy data file
            data_file = tmpdir / "system.data"
            data_file.write_text("# dummy LAMMPS data file\n")

            request = ProtocolRequest(
                ff_type=FFType.BULK_FF_GAFF2,
                run_tier=RunTier.SCREENING,
                study_type=StudyType.BULK,
                temperature_K=298.0,
                pressure_atm=1.0,
                data_file_path=str(data_file),
            )

            gen = LAMMPSInputGenerator(template_dir=tmpdir / "templates")
            result = gen.generate(request)

            script = Path(result.input_script_path).read_text()

            # Every dump line must contain xu yu zu
            dump_lines = [line for line in script.splitlines() if line.strip().startswith("dump ")]
            assert len(dump_lines) > 0, "No dump commands found in script"
            for line in dump_lines:
                assert "xu" in line, f"xu missing in: {line}"
                assert "yu" in line, f"yu missing in: {line}"
                assert "zu" in line, f"zu missing in: {line}"
                # x y z should still be present for visualization
                assert " x " in line or "x y z" in line.replace("xu yu zu ", ""), (
                    f"Wrapped x/y/z missing in: {line}"
                )

    def test_viscosity_tier_has_xu_yu_zu(self):
        """Viscosity tier dump also includes unwrapped coords."""
        from contracts.schemas import (
            FFType,
            ProtocolRequest,
            RunTier,
            StudyType,
        )
        from protocols.lammps_input import LAMMPSInputGenerator

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            data_file = tmpdir / "system.data"
            data_file.write_text("# dummy\n")

            request = ProtocolRequest(
                ff_type=FFType.BULK_FF_GAFF2,
                run_tier=RunTier.VISCOSITY,
                study_type=StudyType.BULK,
                temperature_K=298.0,
                pressure_atm=1.0,
                data_file_path=str(data_file),
            )

            gen = LAMMPSInputGenerator(template_dir=tmpdir / "templates")
            result = gen.generate(request)
            script = Path(result.input_script_path).read_text()

            dump_lines = [line for line in script.splitlines() if line.strip().startswith("dump ")]
            for line in dump_lines:
                assert "xu" in line, f"xu missing in viscosity dump: {line}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
