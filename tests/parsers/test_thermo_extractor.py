"""Tests for thermo extractor."""

import sys

import pytest

sys.path.insert(0, "src")

from parsers.thermo_extractor import ThermoExtractor, ThermoSummary


class TestThermoExtractor:
    """Test thermo extractor."""

    @pytest.fixture
    def extractor(self):
        return ThermoExtractor(
            window_ps=200.0,
            dt_fs=1.0,
            thermo_interval=1000,  # 1 ps per sample
        )

    @pytest.fixture
    def sample_thermo_data(self):
        """Create sample thermo data mimicking NVT + NPT phases."""
        # NVT phase (300 ps): higher variation in density
        nvt_samples = 300  # 300 ps
        nvt_density = [1.15 + 0.05 * (i % 3 - 1) for i in range(nvt_samples)]
        nvt_temp = [300.0 + 2.0 * (i % 5 - 2) for i in range(nvt_samples)]
        nvt_press = [1.0 + 0.5 * (i % 3 - 1) for i in range(nvt_samples)]

        # NPT phase (1000 ps): stable density at 1.02
        npt_samples = 1000  # 1000 ps
        npt_density = [1.02 + 0.002 * (i % 3 - 1) for i in range(npt_samples)]
        npt_temp = [298.0 + 0.5 * (i % 3 - 1) for i in range(npt_samples)]
        npt_press = [1.0 + 0.1 * (i % 3 - 1) for i in range(npt_samples)]

        return {
            "Density": nvt_density + npt_density,
            "Temp": nvt_temp + npt_temp,
            "Press": nvt_press + npt_press,
            "PotEng": [-50000.0] * (nvt_samples + npt_samples),
            "KinEng": [25000.0] * (nvt_samples + npt_samples),
            "TotEng": [-25000.0] * (nvt_samples + npt_samples),
            "Volume": [1e6] * (nvt_samples + npt_samples),
        }

    def test_extract_summary_uses_window(self, extractor, sample_thermo_data):
        """Test that extract_summary uses last window_ps data."""
        summary = extractor.extract_summary(sample_thermo_data)

        # With window_ps=200, dt_fs=1.0, interval=1000 -> 200 samples
        # Should use last 200 ps (NPT phase, density ~1.02)
        assert summary.density_gcc == pytest.approx(1.02, rel=0.01)
        assert summary.temperature_K == pytest.approx(298.0, rel=0.01)

    def test_extract_summary_backward_compat(self, extractor, sample_thermo_data):
        """Test backward compatibility with skip_fraction."""
        # Total 1300 samples, skip 20% = skip 260, use remaining 1040
        summary = extractor.extract_summary(sample_thermo_data, skip_fraction=0.2)

        # With skip_fraction, includes some NVT data (40 samples out of 300)
        # Plus all NPT data, so density should be closer to NPT but not exact
        assert summary.n_samples == 1040

    def test_extract_column_uses_window(self, extractor, sample_thermo_data):
        """Test that extract_column uses last window_ps data."""
        density = extractor.extract_column(
            sample_thermo_data,
            ["Density"],
        )

        # Should return last 200 samples (200 ps window)
        assert len(density) == 200

        # All values should be from NPT phase (~1.02)
        avg = sum(density) / len(density)
        assert avg == pytest.approx(1.02, rel=0.01)

    def test_extract_column_backward_compat(self, extractor, sample_thermo_data):
        """Test backward compatibility with skip_fraction."""
        density = extractor.extract_column(
            sample_thermo_data,
            ["Density"],
            skip_fraction=0.2,
        )

        # Total 1300, skip 260 -> 1040 samples
        assert len(density) == 1040

    def test_extract_energy_components_uses_window(self, extractor, sample_thermo_data):
        """Test that extract_energy_components uses window."""
        components = extractor.extract_energy_components(sample_thermo_data)

        assert "PotEng" in components
        assert "KinEng" in components
        assert "TotEng" in components

    def test_is_equilibrated(self, extractor, sample_thermo_data):
        """Test equilibration check."""
        # NPT phase is stable
        is_eq = extractor.is_equilibrated(
            sample_thermo_data,
            property_name="Density",
            window_size=100,
            tolerance=0.05,
        )

        # Should be equilibrated (first and last windows have similar density)
        assert isinstance(is_eq, bool)

    def test_window_larger_than_data(self):
        """Test handling when window is larger than available data."""
        extractor = ThermoExtractor(
            window_ps=1000.0,  # Large window
            dt_fs=1.0,
            thermo_interval=1000,
        )

        # Only 100 ps of data
        thermo_data = {
            "Density": [1.0] * 100,
        }

        summary = extractor.extract_summary(thermo_data)

        # Should use all available data
        assert summary.n_samples == 100
        assert summary.density_gcc == pytest.approx(1.0, rel=0.01)

    def test_different_thermo_intervals(self):
        """Test with different thermo intervals."""
        # 10000 steps between outputs = 10 ps per sample at dt=1.0 fs
        extractor = ThermoExtractor(
            window_ps=200.0,
            dt_fs=1.0,
            thermo_interval=10000,  # 10 ps per sample
        )

        # 50 samples at 10 ps each = 500 ps total
        # Window of 200 ps = 20 samples
        thermo_data = {
            "Density": [1.2] * 30 + [1.0] * 20,  # 30 unstable + 20 stable
        }

        density = extractor.extract_column(thermo_data, ["Density"])

        # Should use last 20 samples (200 ps window at 10 ps/sample)
        assert len(density) == 20
        assert all(d == pytest.approx(1.0, rel=0.001) for d in density)


class TestThermoSummary:
    """Test ThermoSummary dataclass."""

    def test_summary_creation(self):
        """Test ThermoSummary creation."""
        summary = ThermoSummary(
            temperature_K=298.0,
            temperature_std=0.5,
            pressure_atm=1.0,
            pressure_std=0.1,
            density_gcc=1.02,
            density_std=0.002,
            total_energy=-25000.0,
            potential_energy=-50000.0,
            kinetic_energy=25000.0,
            volume_A3=1e6,
            n_samples=200,
        )

        assert summary.density_gcc == 1.02
        assert summary.n_samples == 200


class TestExtractFullTrajectory:
    """Test extract_full_trajectory method."""

    @pytest.fixture
    def extractor(self):
        return ThermoExtractor(
            window_ps=200.0,
            dt_fs=1.0,
            thermo_interval=1000,  # 1 ps per sample
        )

    def test_extract_full_trajectory_basic(self, extractor):
        """Test full trajectory extraction."""
        thermo_data = {
            "Step": [0, 1000, 2000, 3000, 4000],
            "Density": [1.0, 1.01, 1.02, 1.01, 1.0],
            "Temp": [298.0, 299.0, 298.5, 298.0, 298.5],
            "Press": [1.0, 1.1, 0.9, 1.0, 1.05],
        }

        result = extractor.extract_full_trajectory(thermo_data)

        # Should have time_ps calculated from steps
        assert "time_ps" in result
        assert len(result["time_ps"]) == 5

        # Should have all density values (no windowing)
        assert "density_gcc" in result
        assert len(result["density_gcc"]) == 5
        assert result["density_gcc"] == [1.0, 1.01, 1.02, 1.01, 1.0]

        # Should have temperature
        assert "temperature_K" in result
        assert len(result["temperature_K"]) == 5

    def test_extract_full_trajectory_time_calculation(self, extractor):
        """Test time calculation from steps."""
        thermo_data = {
            "Step": [0, 10000, 20000, 30000],  # 10 ps intervals
            "Density": [1.0, 1.0, 1.0, 1.0],
        }

        result = extractor.extract_full_trajectory(thermo_data)

        # With dt_fs=1.0, time = step * 1.0 / 1000 ps
        assert result["time_ps"] == [0.0, 10.0, 20.0, 30.0]

    def test_extract_full_trajectory_without_steps(self, extractor):
        """Test trajectory when Step column is missing."""
        thermo_data = {
            "Density": [1.0, 1.01, 1.02],
            "Temp": [298.0, 299.0, 298.5],
        }

        result = extractor.extract_full_trajectory(thermo_data)

        # Should estimate time from index
        assert "time_ps" in result
        assert len(result["time_ps"]) == 3
        # With dt_fs=1.0, thermo_interval=1000 -> 1 ps per sample
        assert result["time_ps"] == [0.0, 1.0, 2.0]

    def test_extract_full_trajectory_all_columns(self, extractor):
        """Test all thermo columns are extracted."""
        thermo_data = {
            "Step": [0, 1000],
            "Density": [1.0, 1.01],
            "Temp": [298.0, 299.0],
            "Press": [1.0, 1.1],
            "Volume": [1e6, 1.01e6],
            "TotEng": [-25000.0, -25100.0],
            "PotEng": [-50000.0, -50100.0],
            "KinEng": [25000.0, 25000.0],
        }

        result = extractor.extract_full_trajectory(thermo_data)

        assert "density_gcc" in result
        assert "temperature_K" in result
        assert "pressure_atm" in result
        assert "volume_A3" in result
        assert "total_energy" in result
        assert "potential_energy" in result
        assert "kinetic_energy" in result


class TestEnergyComponentCanonicalKey:
    """Verify canonical key for improper energy is E_imp."""

    @pytest.fixture
    def extractor(self):
        return ThermoExtractor(window_ps=200.0, dt_fs=1.0, thermo_interval=1000)

    def test_canonical_imp_key(self, extractor):
        """E_imp is the canonical key for improper energy."""
        data = {
            "E_bond": [100.0] * 300,
            "E_imp": [5.0] * 300,
            "E_vdwl": [-200.0] * 300,
            "E_coul": [-150.0] * 300,
            "PotEng": [-500.0] * 300,
        }
        components = extractor.extract_energy_components(data)
        assert "E_imp" in components
        assert "E_improp" not in components
        assert components["E_imp"] == pytest.approx(5.0)
        assert "E_bond" in components
        assert "E_vdwl" in components

    def test_legacy_alias_resolves_to_canonical(self, extractor):
        """Legacy E_improp alias should resolve to E_imp canonical key."""
        data = {"E_improp": [7.0] * 300}
        components = extractor.extract_energy_components(data)
        assert "E_imp" in components
        assert components["E_imp"] == pytest.approx(7.0)

    def test_all_nine_energy_components(self, extractor):
        """All 9 energy components are extracted when present."""
        data = {
            "E_bond": [10.0] * 300,
            "E_angle": [20.0] * 300,
            "E_dihed": [30.0] * 300,
            "E_imp": [1.0] * 300,
            "E_vdwl": [-100.0] * 300,
            "E_coul": [-200.0] * 300,
            "E_pair": [-350.0] * 300,
            "E_mol": [61.0] * 300,
            "E_long": [-50.0] * 300,
            "PotEng": [-500.0] * 300,
        }
        components = extractor.extract_energy_components(data)
        expected_keys = {
            "E_bond",
            "E_angle",
            "E_dihed",
            "E_imp",
            "E_vdwl",
            "E_coul",
            "E_pair",
            "E_mol",
            "E_long",
            "PotEng",
        }
        assert expected_keys.issubset(components.keys())


class TestFullTrajectoryEnergyColumns:
    """Verify extract_full_trajectory includes energy decomposition."""

    @pytest.fixture
    def extractor(self):
        return ThermoExtractor(window_ps=200.0, dt_fs=1.0, thermo_interval=1000)

    def test_energy_columns_present(self, extractor):
        """Energy columns are included when present in input data."""
        data = {
            "Step": [0, 1000, 2000],
            "Density": [1.0, 1.01, 1.02],
            "E_bond": [100.0, 101.0, 102.0],
            "E_vdwl": [-200.0, -201.0, -202.0],
        }
        result = extractor.extract_full_trajectory(data)
        assert "ebond" in result
        assert "evdwl" in result
        assert len(result["ebond"]) == 3
        assert "eimp" not in result  # absent, not filled with zeros

    def test_backward_compat_no_energy(self, extractor):
        """Old thermo data without energy columns still works."""
        data = {
            "Step": [0, 1000],
            "Density": [1.0, 1.01],
            "Temp": [298.0, 299.0],
        }
        result = extractor.extract_full_trajectory(data)
        assert "density_gcc" in result
        assert "ebond" not in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
