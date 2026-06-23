"""
Unit tests for parsers module.

Tests LAMMPS log parsing, thermo extraction, and data validation.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


class TestLogParser:
    """Tests for LogParser class."""

    @pytest.fixture
    def simple_log(self, tmp_path):
        """Create a simple LAMMPS log file."""
        log_content = """LAMMPS (29 Aug 2024)
Reading data file ...
  10000 atoms

Step Temp PotEng KinEng TotEng Press Volume Density
       0     300.0   -5000.0    2000.0   -3000.0    500.0   512000.0    1.00
     100     298.0   -4900.0    1990.0   -2910.0    490.0   510000.0    1.01
     200     299.0   -4850.0    1995.0   -2855.0    495.0   508000.0    1.02
Loop time of 60.0 on 1 procs for 200 steps with 10000 atoms

Total wall time: 0:01:00
"""
        log_file = tmp_path / "log.lammps"
        log_file.write_text(log_content)
        return log_file

    def test_parse_basic_log(self, simple_log):
        """Test parsing a basic log file."""
        from parsers import LogParser

        parser = LogParser()
        result = parser.parse(simple_log)

        assert result.completed
        assert result.total_atoms == 10000
        assert len(result.errors) == 0

    def test_parse_thermo_data(self, simple_log):
        """Test extraction of thermo data."""
        from parsers import LogParser

        parser = LogParser()
        result = parser.parse(simple_log)

        assert "Step" in result.thermo_data
        assert "Temp" in result.thermo_data
        assert "Density" in result.thermo_data

        # Verify values
        assert len(result.thermo_data["Step"]) == 3
        assert result.thermo_data["Density"][-1] == 1.02

    def test_get_final_values(self, simple_log):
        """Test getting final thermo values."""
        from parsers import LogParser

        parser = LogParser()
        result = parser.parse(simple_log)
        final = parser.get_final_values(result)

        assert final["Density"] == 1.02
        assert final["Temp"] == 299.0

    def test_get_average_values(self, simple_log):
        """Test getting average thermo values."""
        from parsers import LogParser

        parser = LogParser()
        result = parser.parse(simple_log)
        avg = parser.get_average_values(result)

        # Average density of [1.00, 1.01, 1.02] = 1.01
        assert 1.00 <= avg["Density"] <= 1.02

    def test_parse_missing_file(self, tmp_path):
        """Test parsing non-existent file."""
        from parsers import LogParser

        parser = LogParser()
        result = parser.parse(tmp_path / "nonexistent.log")

        assert not result.completed
        assert len(result.errors) > 0
        assert "not found" in result.errors[0].lower()

    @pytest.fixture
    def error_log(self, tmp_path):
        """Create a log file with errors."""
        log_content = """LAMMPS (29 Aug 2024)
Reading data file ...
  5000 atoms

ERROR: Bond atoms 123 456 missing
"""
        log_file = tmp_path / "log.lammps"
        log_file.write_text(log_content)
        return log_file

    def test_parse_error_log(self, error_log):
        """Test parsing log with errors."""
        from parsers import LogParser

        parser = LogParser()
        result = parser.parse(error_log)

        assert not result.completed
        assert len(result.errors) > 0
        assert "Bond atoms" in result.errors[0]


class TestThermoHeader:
    """Tests for thermo header detection."""

    def test_detect_standard_header(self):
        """Test detection of standard thermo header."""
        from parsers.log_parser import LogParser

        parser = LogParser()

        # Standard LAMMPS header
        assert parser._is_thermo_header("Step Temp PotEng KinEng TotEng Press Volume Density")

        # Not a header
        assert not parser._is_thermo_header("This is a comment")
        assert not parser._is_thermo_header("0 300.0 -5000.0 2000.0")

    def test_detect_custom_header(self):
        """Test detection of custom thermo header."""
        from parsers.log_parser import LogParser

        parser = LogParser()

        # Custom but valid header
        assert parser._is_thermo_header("Step Temp Volume Density")

        # Invalid header (no Step)
        assert not parser._is_thermo_header("Temp Volume Density")


class TestThermoExtractor:
    """Tests for ThermoExtractor class."""

    @pytest.fixture
    def extractor_log(self, tmp_path):
        """Create a log file for thermo extraction."""
        log_content = """LAMMPS (29 Aug 2024)

Step Temp PotEng KinEng TotEng Press Volume Density
       0     300.0   -5000.0    2000.0   -3000.0    500.0   512000.0    0.95
    1000     298.0   -4800.0    1990.0   -2810.0    480.0   500000.0    0.98
    2000     298.5   -4750.0    1992.0   -2758.0    490.0   495000.0    1.00
    3000     299.0   -4700.0    1995.0   -2705.0    500.0   490000.0    1.02
    4000     298.0   -4680.0    1990.0   -2690.0    505.0   488000.0    1.02
    5000     298.2   -4670.0    1991.0   -2679.0    508.0   487000.0    1.03

Total wall time: 0:05:00
"""
        log_file = tmp_path / "log.lammps"
        log_file.write_text(log_content)
        return log_file

    def test_extract_summary(self, extractor_log):
        """Test thermo summary extraction."""
        from parsers import LogParser, ThermoExtractor

        # First parse the log file
        parser = LogParser()
        log_result = parser.parse(extractor_log)

        # Then extract summary
        extractor = ThermoExtractor()
        summary = extractor.extract_summary(log_result.thermo_data)

        assert summary.n_samples > 0
        assert 0.98 < summary.density_gcc < 1.05
        assert 295 < summary.temperature_K < 305

    def test_extract_column(self, extractor_log):
        """Test extraction of specific column."""
        from parsers import LogParser, ThermoExtractor

        # First parse the log file
        parser = LogParser()
        log_result = parser.parse(extractor_log)

        # Extract density column
        extractor = ThermoExtractor(skip_fraction=0.0)  # No skip for test
        densities = extractor.extract_column(log_result.thermo_data, ["Density", "density"])

        assert len(densities) == 6
        assert densities[-1] == 1.03

        # Average should be around 1.00-1.02
        avg = sum(densities) / len(densities)
        assert 0.98 < avg < 1.04


class TestStatsUtils:
    """Tests for stats_utils module."""

    def test_apply_time_window_basic(self):
        """Test basic time window application."""
        from parsers.stats_utils import apply_time_window

        # With default settings (dt_fs=1.0, thermo_interval=1000),
        # 1 sample = 1 ps, so window_ps=200 means last 200 samples
        data = list(range(500))  # 500 samples = 500 ps
        result = apply_time_window(data, window_ps=200.0)

        assert len(result) == 200
        assert result[0] == 300  # First of last 200
        assert result[-1] == 499

    def test_apply_time_window_skip_fraction(self):
        """Test deprecated skip_fraction mode."""
        from parsers.stats_utils import apply_time_window

        data = [0.9, 0.95, 1.0, 1.01, 1.02]  # 5 samples
        result = apply_time_window(data, skip_fraction=0.2)

        # Skip first 20% (1 sample)
        assert len(result) == 4
        assert result[0] == 0.95

    def test_apply_time_window_empty(self):
        """Test with empty input."""
        from parsers.stats_utils import apply_time_window

        result = apply_time_window([])
        assert result == []

    def test_apply_time_window_short_data(self):
        """Test when data is shorter than window."""
        from parsers.stats_utils import apply_time_window

        data = [1.0, 1.01, 1.02]  # Only 3 samples
        result = apply_time_window(data, window_ps=200.0)

        # Should return all data since it's shorter than window
        assert len(result) == 3
        assert result == data

    def test_apply_time_window_custom_params(self):
        """Test with custom dt_fs and thermo_interval."""
        from parsers.stats_utils import apply_time_window

        # With dt_fs=0.5, thermo_interval=500: 1 sample = 0.25 ps
        # window_ps=100 means 400 samples
        data = list(range(1000))
        result = apply_time_window(
            data,
            window_ps=100.0,
            dt_fs=0.5,
            thermo_interval=500,
        )

        assert len(result) == 400  # 100 ps / 0.25 ps per sample

    def test_compute_mean_std_basic(self):
        """Test mean and std calculation."""
        from parsers.stats_utils import compute_mean_std

        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        mean, std = compute_mean_std(data)

        assert mean == 3.0
        # Sample std with Bessel's correction
        # variance = sum((x-3)^2) / 4 = (4+1+0+1+4) / 4 = 2.5
        # std = sqrt(2.5) ≈ 1.5811
        assert abs(std - 1.5811) < 0.001

    def test_compute_mean_std_empty(self):
        """Test with empty input."""
        from parsers.stats_utils import compute_mean_std

        mean, std = compute_mean_std([])
        assert mean == 0.0
        assert std == 0.0

    def test_compute_mean_std_single(self):
        """Test with single value."""
        from parsers.stats_utils import compute_mean_std

        mean, std = compute_mean_std([5.0])
        assert mean == 5.0
        assert std == 0.0  # Can't compute std with single value

    def test_get_default_values(self):
        """Test SSOT default getters."""
        from parsers.stats_utils import (
            get_default_dt_fs,
            get_default_thermo_interval,
            get_default_window_ps,
        )

        # These should match SSOT values from tier policy
        assert get_default_window_ps() == 200.0
        assert get_default_dt_fs() == 1.0
        assert get_default_thermo_interval() == 1000
