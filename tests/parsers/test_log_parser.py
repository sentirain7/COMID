"""Tests for LAMMPS log parser."""

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, "src")

from parsers.log_parser import LogParser


class TestLogParser:
    """Test log parser."""

    @pytest.fixture
    def parser(self):
        return LogParser()

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def sample_log(self, temp_dir):
        """Create a sample LAMMPS log file."""
        content = """LAMMPS (29 Oct 2020)
Reading data file ...
  100000 atoms
  90000 bonds
  60000 angles

Step Temp Press Volume PotEng KinEng TotEng Density
0 300.0 1.0 1000000.0 -50000.0 25000.0 -25000.0 1.05
1000 298.5 0.95 999500.0 -50100.0 24950.0 -25150.0 1.051
2000 299.0 1.02 999800.0 -50050.0 24970.0 -25080.0 1.050
3000 298.8 0.98 999700.0 -50080.0 24960.0 -25120.0 1.050
4000 299.2 1.01 999600.0 -50070.0 24980.0 -25090.0 1.051
5000 299.0 1.00 999750.0 -50060.0 24970.0 -25090.0 1.050

Loop time of 120.5 on 4 procs for 5000 steps with 100000 atoms

Performance: 3.587 ns/day

Total wall time: 0:02:00
"""
        log_file = temp_dir / "log.lammps"
        log_file.write_text(content)
        return log_file

    def test_parse_basic(self, parser, sample_log):
        """Test basic log parsing."""
        result = parser.parse(sample_log)

        assert result.total_atoms == 100000
        assert result.completed is True

    def test_parse_thermo_data(self, parser, sample_log):
        """Test thermo data extraction."""
        result = parser.parse(sample_log)

        assert "Step" in result.thermo_data
        assert "Temp" in result.thermo_data
        assert "Density" in result.thermo_data
        assert len(result.thermo_data["Step"]) == 6

    def test_final_step(self, parser, sample_log):
        """Test final step extraction."""
        result = parser.parse(sample_log)

        assert result.final_step == 5000

    def test_get_final_values(self, parser, sample_log):
        """Test getting final values."""
        result = parser.parse(sample_log)
        final = parser.get_final_values(result)

        assert "Density" in final
        assert final["Density"] == pytest.approx(1.050, rel=0.01)

    def test_get_average_values(self, parser, sample_log):
        """Test getting average values."""
        result = parser.parse(sample_log)
        avg = parser.get_average_values(result)

        assert "Temp" in avg
        assert avg["Temp"] == pytest.approx(299.0, rel=0.01)

    def test_nonexistent_file(self, parser, temp_dir):
        """Test handling of nonexistent file."""
        result = parser.parse(temp_dir / "nonexistent.log")

        assert result.completed is False
        assert len(result.errors) > 0


class TestLogParserErrors:
    """Test error detection in log parser."""

    @pytest.fixture
    def parser(self):
        return LogParser()

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_error_detection(self, parser, temp_dir):
        """Test error message detection."""
        content = """LAMMPS (29 Oct 2020)
Step Temp Press
0 300.0 1.0
ERROR: Lost atoms: original 1000 current 990
"""
        log_file = temp_dir / "log.lammps"
        log_file.write_text(content)

        result = parser.parse(log_file)

        assert len(result.errors) > 0
        assert any("Lost atoms" in e for e in result.errors)

    def test_warning_detection(self, parser, temp_dir):
        """Test warning message detection."""
        content = """LAMMPS (29 Oct 2020)
WARNING: Neighbor list overflow, atom 100
Step Temp Press
0 300.0 1.0
Total wall time: 0:00:01
"""
        log_file = temp_dir / "log.lammps"
        log_file.write_text(content)

        result = parser.parse(log_file)

        assert len(result.warnings) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
