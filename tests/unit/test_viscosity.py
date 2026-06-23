"""
Tests for viscosity calculator (Muller-Plathe RNEMD).

Covers:
- ViscosityCalculator core computation (success / failure / edge cases)
- Velocity profile parsing
- Thermo column discovery
- Box dimension extraction
- MetricResult creation with registry SSOT
- MetricCalculator integration
- Protocol template f_viscosity fix
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from contracts.policies.metrics import MetricsRegistry  # noqa: E402
from metrics.viscosity import (  # noqa: E402
    _REAL_TO_MPAS,
    VelocityProfile,
    ViscosityCalculator,
    ViscosityResult,
)

# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def registry():
    return MetricsRegistry()


@pytest.fixture
def calc(registry):
    return ViscosityCalculator(skip_fraction=0.3, registry=registry)


def _make_linear_f_viscosity(
    n_points: int = 100,
    slope_per_fs: float = 1e-3,
    dt_fs: float = 1000.0,
) -> tuple[list[float], np.ndarray]:
    """Generate a linear f_viscosity time series.

    f_viscosity = slope_per_fs * t  (cumulative momentum in g·Å/(mol·fs))
    """
    time_fs = np.arange(n_points, dtype=np.float64) * dt_fs
    f_values = [slope_per_fs * t for t in time_fs]
    return f_values, time_fs


def _make_velocity_profile(
    n_bins: int = 20,
    lz: float = 50.0,
    gradient: float = 1e-6,
) -> VelocityProfile:
    """Generate a linear velocity profile for the first half.

    vx(z) = gradient * z  for z in [0, Lz/2]
    vx(z) = gradient * (Lz - z) for z in [Lz/2, Lz]  (triangular)
    """
    dz = lz / n_bins
    z = np.array([(i + 0.5) * dz for i in range(n_bins)])
    vx = np.where(z <= lz / 2, gradient * z, gradient * (lz - z))
    return VelocityProfile(z=z, vx=vx, n_blocks=10)


# ======================================================================
# TestViscosityCalculator — core computation
# ======================================================================


class TestViscosityCalculator:
    """Tests for the core compute_from_rnemd method."""

    def test_known_viscosity(self, calc):
        """With known slope and gradient, viscosity should match analytical value."""
        slope = 1e-3  # g·Å/(mol·fs²)  — d(f_viscosity)/dt
        gradient = 1e-6  # 1/fs  — dv_x/dz
        area = 2500.0  # Å²  — Lx × Ly

        # η_raw = |slope| / (2 * A * |gradient|)
        # η_mPas = η_raw * _REAL_TO_MPAS
        expected_raw = slope / (2.0 * area * gradient)
        expected_mPas = expected_raw * _REAL_TO_MPAS

        f_values, time_fs = _make_linear_f_viscosity(
            n_points=100,
            slope_per_fs=slope,
            dt_fs=1000.0,
        )
        # 10-bin linear profile in first half of a 50 Å box
        profile = _make_velocity_profile(n_bins=20, lz=50.0, gradient=gradient)

        result = calc.compute_from_rnemd(
            f_viscosity_values=f_values,
            time_fs=time_fs,
            box_area_A2=area,
            velocity_profile=profile,
        )

        assert result.viscosity_mPas is not None
        assert result.viscosity_mPas == pytest.approx(expected_mPas, rel=0.15)
        assert result.error is None
        assert result.method == "rnemd_muller_plathe"

    def test_no_profile_returns_none(self, calc):
        """Without velocity profile, viscosity should be None."""
        f_values, time_fs = _make_linear_f_viscosity(n_points=50)
        result = calc.compute_from_rnemd(
            f_viscosity_values=f_values,
            time_fs=time_fs,
            box_area_A2=2500.0,
            velocity_profile=None,
        )
        assert result.viscosity_mPas is None
        assert result.momentum_flux_rate is not None
        assert "No velocity profile" in (result.error or "")

    def test_flux_rate_computed(self, calc):
        """Momentum flux rate should match input slope."""
        slope = 2e-3
        f_values, time_fs = _make_linear_f_viscosity(
            n_points=100,
            slope_per_fs=slope,
        )
        result = calc.compute_from_rnemd(
            f_viscosity_values=f_values,
            time_fs=time_fs,
            box_area_A2=2500.0,
            velocity_profile=None,
        )
        assert result.momentum_flux_rate is not None
        assert result.momentum_flux_rate == pytest.approx(slope, rel=0.05)

    def test_flux_r_squared_near_1(self, calc):
        """Linear f_viscosity should give R² ≈ 1.0."""
        f_values, time_fs = _make_linear_f_viscosity(n_points=100)
        result = calc.compute_from_rnemd(
            f_viscosity_values=f_values,
            time_fs=time_fs,
            box_area_A2=2500.0,
        )
        assert result.flux_fit_r_squared is not None
        assert result.flux_fit_r_squared > 0.99


# ======================================================================
# TestEdgeCases
# ======================================================================


class TestEdgeCases:
    """Edge cases and error handling."""

    def test_too_few_samples(self, calc):
        """< 3 samples should return error result."""
        result = calc.compute_from_rnemd(
            f_viscosity_values=[1.0, 2.0],
            time_fs=np.array([0.0, 1000.0]),
            box_area_A2=2500.0,
        )
        assert result.viscosity_mPas is None
        assert "Insufficient" in (result.error or "")

    def test_nan_values(self, calc):
        """NaN values should be filtered out."""
        f_values = [0.0, 1.0, float("nan"), 3.0, float("nan"), 5.0, 6.0, 7.0, 8.0, 9.0]
        time_fs = np.arange(10, dtype=np.float64) * 1000.0
        result = calc.compute_from_rnemd(
            f_viscosity_values=f_values,
            time_fs=time_fs,
            box_area_A2=2500.0,
        )
        # Should still compute flux rate from valid points
        assert result.momentum_flux_rate is not None

    def test_all_nan(self, calc):
        """All NaN should return error."""
        f_values = [float("nan")] * 10
        time_fs = np.arange(10, dtype=np.float64) * 1000.0
        result = calc.compute_from_rnemd(
            f_viscosity_values=f_values,
            time_fs=time_fs,
            box_area_A2=2500.0,
        )
        assert result.viscosity_mPas is None
        assert "non-NaN" in (result.error or "")

    def test_zero_gradient(self, calc):
        """Zero velocity gradient should return None viscosity."""
        f_values, time_fs = _make_linear_f_viscosity(n_points=50)
        # Profile with all vx = 0 → gradient = 0
        profile = VelocityProfile(
            z=np.linspace(0, 50, 10),
            vx=np.zeros(10),
            n_blocks=5,
        )
        result = calc.compute_from_rnemd(
            f_viscosity_values=f_values,
            time_fs=time_fs,
            box_area_A2=2500.0,
            velocity_profile=profile,
        )
        assert result.viscosity_mPas is None
        assert "gradient" in (result.error or "").lower()

    def test_empty_f_viscosity(self, calc):
        """Empty f_viscosity list should return error."""
        result = calc.compute_from_rnemd(
            f_viscosity_values=[],
            time_fs=np.array([]),
            box_area_A2=2500.0,
        )
        assert result.viscosity_mPas is None
        assert result.n_thermo_samples == 0


# ======================================================================
# TestVelocityProfileParsing
# ======================================================================


class TestVelocityProfileParsing:
    """Tests for parse_velocity_profile."""

    def test_parse_single_block(self, calc, tmp_path):
        """Parse a single-block velocity profile file."""
        content = textwrap.dedent("""\
            # Time-averaged data for fix vprof
            # Timestep Number-of-chunks Total-count
            # Chunk Coord1 Ncount vx
            1000 5 500
            1 2.5 100 0.001
            2 7.5 100 0.003
            3 12.5 100 0.005
            4 17.5 100 0.003
            5 22.5 100 0.001
        """)
        fpath = tmp_path / "vprofile.dat"
        fpath.write_text(content)

        profile = calc.parse_velocity_profile(fpath)
        assert profile is not None
        assert len(profile.z) == 5
        assert profile.n_blocks == 1
        assert profile.vx[2] == pytest.approx(0.005)

    def test_parse_multi_block(self, calc, tmp_path):
        """Parse multiple blocks and average steady-state."""
        lines = ["# comment"]
        for ts in range(1000, 5001, 1000):
            lines.append(f"{ts} 3 300")
            for i in range(1, 4):
                lines.append(f"{i} {i * 5.0} 100 {ts * 0.001 * i * 0.001}")
        fpath = tmp_path / "vprofile.dat"
        fpath.write_text("\n".join(lines))

        profile = calc.parse_velocity_profile(fpath)
        assert profile is not None
        assert profile.n_blocks == 5
        # With skip_fraction=0.3: skip first 1 block, average last 4
        assert len(profile.vx) == 3

    def test_parse_missing_file(self, calc, tmp_path):
        """Missing file should return None."""
        result = calc.parse_velocity_profile(tmp_path / "nonexistent.dat")
        assert result is None

    def test_parse_empty_file(self, calc, tmp_path):
        """Empty file should return None."""
        fpath = tmp_path / "empty.dat"
        fpath.write_text("")
        assert calc.parse_velocity_profile(fpath) is None


# ======================================================================
# TestColumnDiscovery
# ======================================================================


class TestColumnDiscovery:
    """Tests for find_f_viscosity_column."""

    def test_standard_name(self):
        data = {"Step": [1], "f_viscosity_3": [0.5]}
        assert ViscosityCalculator.find_f_viscosity_column(data) == "f_viscosity_3"

    def test_legacy_name(self):
        data = {"Step": [1], "f_viscosity": [0.5]}
        assert ViscosityCalculator.find_f_viscosity_column(data) == "f_viscosity"

    def test_no_column(self):
        data = {"Step": [1], "Temp": [300.0]}
        assert ViscosityCalculator.find_f_viscosity_column(data) is None


# ======================================================================
# TestBoxDimensions
# ======================================================================


class TestBoxDimensions:
    """Tests for box area extraction helpers."""

    def test_extract_from_log(self):
        log_text = textwrap.dedent("""\
            LAMMPS (2 Jun 2025)
            Created orthogonal box = (0 0 0) to (50.0 50.0 50.0)
            100000 atoms
            orthogonal box = (0 0 0) to (48.5 48.5 48.5)
        """)
        area = ViscosityCalculator.extract_box_area_from_log(log_text)
        # Should return the LAST box: 48.5 * 48.5 = 2352.25
        assert area == pytest.approx(48.5 * 48.5)

    def test_no_box_in_log(self):
        assert ViscosityCalculator.extract_box_area_from_log("no box here") is None

    def test_estimate_from_volume(self):
        vol = 125000.0  # 50^3
        area = ViscosityCalculator.estimate_box_area_from_volume(vol)
        assert area == pytest.approx(50.0**2, rel=0.01)

    def test_estimate_zero_volume(self):
        assert ViscosityCalculator.estimate_box_area_from_volume(0.0) == 0.0


# ======================================================================
# TestMetricCreation
# ======================================================================


class TestMetricCreation:
    """Tests for scalar metric creation with registry SSOT."""

    def test_metric_name_and_unit(self, calc, registry):
        """Metric should use SSOT name and unit."""
        result = ViscosityResult(
            viscosity_mPas=500.0,
            momentum_flux_rate=1e-3,
            velocity_gradient=1e-6,
            flux_fit_r_squared=0.99,
            gradient_fit_r_squared=0.95,
        )
        metric = calc.create_scalar_metric(result)
        assert metric is not None
        assert metric.metric_name == "viscosity"
        assert metric.unit == registry.get_unit("viscosity")
        assert metric.unit == "mPa.s"
        assert metric.value == 500.0
        assert metric.namespace == "bulk_ff_gaff2"

    def test_none_when_no_viscosity(self, calc):
        """Should return None when viscosity is None."""
        result = ViscosityResult(
            viscosity_mPas=None,
            momentum_flux_rate=1e-3,
            velocity_gradient=None,
            flux_fit_r_squared=None,
            gradient_fit_r_squared=None,
            error="No profile",
        )
        assert calc.create_scalar_metric(result) is None


# ======================================================================
# TestMetadata
# ======================================================================


class TestMetadata:
    """Tests for non-blocking metadata recording."""

    def test_success_metadata(self):
        result = ViscosityResult(
            viscosity_mPas=500.0,
            momentum_flux_rate=1e-3,
            velocity_gradient=1e-6,
            flux_fit_r_squared=0.99,
            gradient_fit_r_squared=0.95,
            n_thermo_samples=70,
        )
        meta = ViscosityCalculator.get_metadata(result)
        assert meta["viscosity_parse_status"] == "success"
        assert meta["viscosity_method"] == "rnemd_muller_plathe"
        assert "viscosity_error" not in meta
        assert meta["viscosity_n_samples"] == 70

    def test_failure_metadata(self):
        result = ViscosityResult(
            viscosity_mPas=None,
            momentum_flux_rate=1e-3,
            velocity_gradient=None,
            flux_fit_r_squared=0.99,
            gradient_fit_r_squared=None,
            error="No velocity profile available — cannot compute viscosity",
        )
        meta = ViscosityCalculator.get_metadata(result)
        assert meta["viscosity_parse_status"] == "failed"
        assert "viscosity_error" in meta
        assert "No velocity profile" in meta["viscosity_error"]


# ======================================================================
# TestUnitConversion
# ======================================================================


class TestUnitConversion:
    """Tests for the LAMMPS real → mPa·s conversion factor."""

    def test_conversion_factor_value(self):
        """Verify _REAL_TO_MPAS ≈ 16.61."""
        assert _REAL_TO_MPAS == pytest.approx(16.61, rel=0.01)

    def test_round_trip(self, calc):
        """Known viscosity should survive compute → convert round-trip."""
        # Target: η = 1000 mPa·s (water at 20°C ≈ 1 mPa·s; asphalt >> 1)
        # η_raw = η_mPas / _REAL_TO_MPAS
        eta_mPas_target = 1000.0
        eta_raw = eta_mPas_target / _REAL_TO_MPAS

        # Choose slope, area, gradient so that η_raw = slope / (2 * A * grad)
        area = 2500.0
        gradient = 1e-6
        slope = eta_raw * 2.0 * area * gradient

        f_values, time_fs = _make_linear_f_viscosity(
            n_points=200,
            slope_per_fs=slope,
            dt_fs=500.0,
        )
        profile = _make_velocity_profile(n_bins=20, lz=50.0, gradient=gradient)

        result = calc.compute_from_rnemd(
            f_viscosity_values=f_values,
            time_fs=time_fs,
            box_area_A2=area,
            velocity_profile=profile,
        )
        assert result.viscosity_mPas is not None
        assert result.viscosity_mPas == pytest.approx(eta_mPas_target, rel=0.15)


# ======================================================================
# TestProtocolTemplate — thermo column fix
# ======================================================================


class TestProtocolTemplate:
    """Verify the protocol generates correct f_<fix_id> reference."""

    def _generate_viscosity_script(self) -> str:
        import tempfile

        from contracts.schemas import FFType, ProtocolRequest, RunTier, StudyType
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
            return Path(result.input_script_path).read_text()

    def test_thermo_references_correct_fix_id(self):
        """thermo_style must reference f_viscosity_N, not bare f_viscosity."""
        script = self._generate_viscosity_script()
        # Find thermo_style lines with f_viscosity
        thermo_lines = [
            line.strip()
            for line in script.split("\n")
            if "thermo_style" in line and "f_viscosity" in line
        ]
        assert len(thermo_lines) >= 1
        for line in thermo_lines:
            # Should have f_viscosity_N (with step index suffix)
            assert "f_viscosity_" in line, f"Missing fix ID suffix in: {line}"

    def test_velocity_profile_dump(self):
        """Script should include velocity profile dump commands."""
        script = self._generate_viscosity_script()
        assert "compute chunks_" in script
        assert "fix vprof_" in script
        assert "vprofile_" in script
        assert "unfix vprof_" in script
        assert "uncompute chunks_" in script

    def test_thermo_reset_before_write_restart(self):
        """Regression (v01.06.24): after the viscosity run completes, fix
        viscosity_N is unfixed; the subsequent write_restart triggers a System
        init that re-evaluates thermo_style. thermo_style MUST be reset to drop
        the f_viscosity_N reference before write_restart, else LAMMPS aborts the
        already-completed run with
        'ERROR: Could not find thermo fix ID viscosity_N' (thermo.cpp).
        """
        script = self._generate_viscosity_script()
        lines = [line.strip() for line in script.split("\n")]

        unfix_idx = next(
            (i for i, line in enumerate(lines) if line.startswith("unfix viscosity_")),
            None,
        )
        assert unfix_idx is not None, "no 'unfix viscosity_N' found in viscosity script"

        wr_idx = next(
            (i for i in range(unfix_idx, len(lines)) if lines[i].startswith("write_restart")),
            None,
        )
        assert wr_idx is not None, "no write_restart after 'unfix viscosity_N'"

        between = lines[unfix_idx:wr_idx]
        resets = [line for line in between if line.startswith("thermo_style")]
        assert resets, (
            "thermo_style must be reset between 'unfix viscosity_N' and write_restart "
            "to avoid 'Could not find thermo fix ID viscosity_N'"
        )
        for line in resets:
            assert "f_viscosity" not in line, (
                f"thermo_style reset still references the removed fix: {line}"
            )

    def test_thermostat_uses_profile_unbiased_temperature(self):
        """Accuracy fix A (v01.06.25): the NVT thermostat in the viscosity stage
        must thermostat on the PROFILE-UNBIASED temperature (temp_profile), i.e.
        a 'fix_modify nvt_N temp temp_profile' must be present. Otherwise the
        thermostat removes the imposed Muller-Plathe streaming velocity, erasing
        the dv_x/dz gradient and yielding a meaningless (noise) viscosity.
        """
        script = self._generate_viscosity_script()
        lines = [line.strip() for line in script.split("\n")]

        # The profile-unbiased temperature compute must be defined ...
        assert any(
            line.startswith("compute") and "temp/profile" in line for line in lines
        ), "compute temp/profile (profile-unbiased temperature) missing"

        # ... AND linked to the viscosity-stage NVT thermostat.
        fix_modify = [
            line
            for line in lines
            if line.startswith("fix_modify nvt_") and "temp temp_profile" in line
        ]
        assert fix_modify, (
            "viscosity NVT thermostat must use the profile-unbiased temperature "
            "via 'fix_modify nvt_N temp temp_profile'"
        )

        # The fix_modify must come AFTER the temp_profile compute is defined.
        compute_idx = next(
            i for i, line in enumerate(lines) if line.startswith("compute") and "temp/profile" in line
        )
        modify_idx = next(
            i
            for i, line in enumerate(lines)
            if line.startswith("fix_modify nvt_") and "temp temp_profile" in line
        )
        assert modify_idx > compute_idx, "fix_modify must follow the temp_profile compute"


# ======================================================================
# TestCalculatorIntegration — MetricCalculator._calculate_viscosity
# ======================================================================


class TestCalculatorIntegration:
    """Integration test with MetricCalculator."""

    def test_calculate_viscosity_with_thermo(self, tmp_path):
        """_calculate_viscosity should produce metric from synthetic thermo data."""
        from contracts.schemas import LAMMPSRunResult
        from metrics.calculator import MetricCalculator

        # Write a minimal log file with box info
        log_content = textwrap.dedent("""\
            LAMMPS (2 Jun 2025)
            orthogonal box = (0 0 0) to (50.0 50.0 50.0)
            100000 atoms
            Total wall time: 0:05:00
        """)
        log_path = tmp_path / "log.lammps"
        log_path.write_text(log_content)

        # Write velocity profile file
        vprofile_content = _make_vprofile_file_content(
            n_bins=20,
            lz=50.0,
            gradient=1e-6,
            n_blocks=10,
        )
        (tmp_path / "vprofile_viscosity_nemd.dat").write_text(vprofile_content)

        # Synthetic thermo data with f_viscosity_3 column
        slope = 1e-3
        n_pts = 100
        thermo_data = {
            "Step": [float(i * 1000) for i in range(200 + n_pts)],
            "Vol": [125000.0] * (200 + n_pts),
            "f_viscosity_3": [slope * i * 1000.0 for i in range(n_pts)],
        }

        calc = MetricCalculator(dt_fs=1.0, thermo_interval=1000)
        run_result = LAMMPSRunResult(
            success=True,
            log_file=str(log_path),
            dump_files=[],
            wall_time_seconds=300.0,
            exit_code=0,
        )

        metrics, metadata = calc._calculate_viscosity(
            thermo_data=thermo_data,
            log_path=log_path,
            run_result=run_result,
        )

        assert metadata["viscosity_parse_status"] == "success"
        assert len(metrics) == 1
        assert metrics[0].metric_name == "viscosity"
        assert metrics[0].unit == "mPa.s"
        assert metrics[0].value > 0

    def test_no_f_viscosity_column(self, tmp_path):
        """When f_viscosity column is absent, should skip gracefully."""
        from contracts.schemas import LAMMPSRunResult
        from metrics.calculator import MetricCalculator

        log_path = tmp_path / "log.lammps"
        log_path.write_text("LAMMPS\nTotal wall time: 0:01:00\n")

        thermo_data = {"Step": [0, 1000], "Temp": [300.0, 300.0]}

        calc = MetricCalculator(dt_fs=1.0)
        run_result = LAMMPSRunResult(
            success=True,
            log_file=str(log_path),
            dump_files=[],
            wall_time_seconds=60.0,
            exit_code=0,
        )

        metrics, metadata = calc._calculate_viscosity(
            thermo_data=thermo_data,
            log_path=log_path,
            run_result=run_result,
        )

        assert len(metrics) == 0
        assert "not found" in metadata.get("viscosity_error", "")

    def test_no_velocity_profile_partial_result(self, tmp_path):
        """With f_viscosity but no profile file, should record metadata but no metric."""
        from contracts.schemas import LAMMPSRunResult
        from metrics.calculator import MetricCalculator

        log_content = "LAMMPS\northogonal box = (0 0 0) to (50 50 50)\nTotal wall time: 0:01:00\n"
        log_path = tmp_path / "log.lammps"
        log_path.write_text(log_content)

        n_pts = 50
        thermo_data = {
            "Step": [float(i * 1000) for i in range(n_pts)],
            "Vol": [125000.0] * n_pts,
            "f_viscosity_3": [1e-3 * i * 1000.0 for i in range(n_pts)],
        }

        calc = MetricCalculator(dt_fs=1.0)
        run_result = LAMMPSRunResult(
            success=True,
            log_file=str(log_path),
            dump_files=[],
            wall_time_seconds=60.0,
            exit_code=0,
        )

        metrics, metadata = calc._calculate_viscosity(
            thermo_data=thermo_data,
            log_path=log_path,
            run_result=run_result,
        )

        assert len(metrics) == 0
        assert metadata["viscosity_parse_status"] == "failed"
        assert metadata.get("viscosity_momentum_flux_rate") is not None


# ======================================================================
# Helper for generating velocity profile file content
# ======================================================================


def _make_vprofile_file_content(
    n_bins: int = 20,
    lz: float = 50.0,
    gradient: float = 1e-6,
    n_blocks: int = 10,
) -> str:
    """Generate synthetic fix ave/chunk velocity profile file content."""
    lines = [
        "# Time-averaged data for fix vprof",
        "# Timestep Number-of-chunks Total-count",
        "# Chunk Coord1 Ncount vx",
    ]
    dz = lz / n_bins
    for block_idx in range(n_blocks):
        ts = (block_idx + 1) * 1000
        lines.append(f"{ts} {n_bins} {n_bins * 100}")
        for i in range(n_bins):
            z = (i + 0.5) * dz
            if z <= lz / 2:
                vx = gradient * z
            else:
                vx = gradient * (lz - z)
            lines.append(f"{i + 1} {z:.4f} 100 {vx:.10e}")
    return "\n".join(lines)


# ======================================================================
# Metadata propagation through calculate() → pipeline
# ======================================================================


class TestMetadataPropagation:
    """Verify visc_metadata is accessible via get_calculation_metadata()."""

    def test_metadata_available_after_calculate_success(self, tmp_path):
        """After calculate(), get_calculation_metadata() returns viscosity info."""
        from contracts.schemas import LAMMPSRunResult
        from metrics.calculator import MetricCalculator

        log_content = "LAMMPS\northogonal box = (0 0 0) to (50 50 50)\nTotal wall time: 0:05:00\n"
        log_path = tmp_path / "log.lammps"
        log_path.write_text(log_content)

        vprofile_content = _make_vprofile_file_content(
            n_bins=20,
            lz=50.0,
            gradient=1e-6,
            n_blocks=10,
        )
        (tmp_path / "vprofile_viscosity_nemd.dat").write_text(vprofile_content)

        n_pts = 100
        slope = 1e-3
        thermo_data = {
            "Step": [float(i * 1000) for i in range(200 + n_pts)],
            "Temp": [300.0] * (200 + n_pts),
            "Press": [1.0] * (200 + n_pts),
            "Density": [1.0] * (200 + n_pts),
            "PotEng": [-1000.0] * (200 + n_pts),
            "KinEng": [500.0] * (200 + n_pts),
            "TotEng": [-500.0] * (200 + n_pts),
            "Vol": [125000.0] * (200 + n_pts),
            "f_viscosity_3": [slope * i * 1000.0 for i in range(n_pts)],
        }

        # Patch log parser to return our synthetic thermo
        calc = MetricCalculator(dt_fs=1.0, thermo_interval=1000)

        from unittest.mock import MagicMock

        mock_log_result = MagicMock()
        mock_log_result.thermo_data = thermo_data
        calc.log_parser.parse = MagicMock(return_value=mock_log_result)

        run_result = LAMMPSRunResult(
            success=True,
            log_file=str(log_path),
            dump_files=[],
            wall_time_seconds=300.0,
            exit_code=0,
        )

        metrics = calc.calculate(run_result)
        metadata = calc.get_calculation_metadata()

        assert "viscosity_method" in metadata
        assert metadata["viscosity_parse_status"] == "success"
        assert metadata.get("viscosity_momentum_flux_rate") is not None
        # Viscosity metric should be in the returned metrics list
        visc_metrics = [m for m in metrics if m.metric_name == "viscosity"]
        assert len(visc_metrics) == 1

    def test_metadata_available_after_calculate_no_viscosity(self, tmp_path):
        """When f_viscosity is absent, metadata still records the skip reason."""
        from contracts.schemas import LAMMPSRunResult
        from metrics.calculator import MetricCalculator

        log_path = tmp_path / "log.lammps"
        log_path.write_text("LAMMPS\nTotal wall time: 0:01:00\n")

        thermo_data = {
            "Step": [0.0, 1000.0],
            "Temp": [300.0, 300.0],
            "Press": [1.0, 1.0],
            "Density": [1.0, 1.0],
            "Vol": [125000.0, 125000.0],
        }

        calc = MetricCalculator(dt_fs=1.0)

        from unittest.mock import MagicMock

        mock_log_result = MagicMock()
        mock_log_result.thermo_data = thermo_data
        calc.log_parser.parse = MagicMock(return_value=mock_log_result)

        run_result = LAMMPSRunResult(
            success=True,
            log_file=str(log_path),
            dump_files=[],
            wall_time_seconds=60.0,
            exit_code=0,
        )

        calc.calculate(run_result)
        metadata = calc.get_calculation_metadata()

        assert metadata["viscosity_parse_status"] == "skipped"
        assert "not found" in metadata.get("viscosity_error", "")

    def test_metadata_reset_between_calls(self, tmp_path):
        """Each calculate() call resets metadata (no stale data)."""
        from contracts.schemas import LAMMPSRunResult
        from metrics.calculator import MetricCalculator

        log_path = tmp_path / "log.lammps"
        log_path.write_text("LAMMPS\nTotal wall time: 0:01:00\n")

        thermo_data = {
            "Step": [0.0, 1000.0],
            "Temp": [300.0, 300.0],
            "Press": [1.0, 1.0],
            "Density": [1.0, 1.0],
            "Vol": [125000.0, 125000.0],
        }

        calc = MetricCalculator(dt_fs=1.0)

        from unittest.mock import MagicMock

        mock_log_result = MagicMock()
        mock_log_result.thermo_data = thermo_data
        calc.log_parser.parse = MagicMock(return_value=mock_log_result)

        run_result = LAMMPSRunResult(
            success=True,
            log_file=str(log_path),
            dump_files=[],
            wall_time_seconds=60.0,
            exit_code=0,
        )

        # First call
        calc.calculate(run_result)
        meta1 = calc.get_calculation_metadata()
        assert "viscosity_parse_status" in meta1

        # Second call — should be fresh, not accumulated
        calc.calculate(run_result)
        meta2 = calc.get_calculation_metadata()
        assert meta2 == meta1  # same input → same result, no accumulation
