"""Unit tests for StressStrainParser (Phase 4.3)."""

import numpy as np
import pytest

from contracts.errors import ParserError
from parsers.stress_strain_parser import StressStrainData, StressStrainParser


class TestStressStrainData:
    """Tests for StressStrainData properties."""

    def test_peak_stress(self):
        """Test peak stress calculation."""
        data = StressStrainData(
            strain=np.array([0.0, 0.01, 0.02, 0.03]),
            stress_MPa=np.array([0.0, 10.0, 20.0, 15.0]),
            n_points=4,
        )
        assert data.peak_stress_MPa == pytest.approx(20.0)

    def test_peak_strain(self):
        """Test strain at peak stress."""
        data = StressStrainData(
            strain=np.array([0.0, 0.01, 0.02, 0.03]),
            stress_MPa=np.array([0.0, 10.0, 20.0, 15.0]),
            n_points=4,
        )
        assert data.peak_strain == pytest.approx(0.02)

    def test_elastic_modulus_linear(self):
        """Test elastic modulus from linear region."""
        # Linear stress-strain: E = 2000 MPa = 2.0 GPa
        strain = np.array([0.0, 0.005, 0.01, 0.015, 0.02])
        stress = np.array([0.0, 10.0, 20.0, 30.0, 40.0])
        data = StressStrainData(strain=strain, stress_MPa=stress, n_points=5)
        assert data.elastic_modulus_GPa == pytest.approx(2.0, rel=0.01)

    def test_elastic_modulus_insufficient_data(self):
        """Test elastic modulus returns None with insufficient data in linear region."""
        # Only 2 points <= 0.02 strain (need 3)
        data = StressStrainData(
            strain=np.array([0.0, 0.01, 0.05, 0.10]),
            stress_MPa=np.array([0.0, 10.0, 30.0, 20.0]),
            n_points=4,
        )
        assert data.elastic_modulus_GPa is None

    def test_toughness_trapezoid(self):
        """Test toughness calculation (area under curve)."""
        # Rectangle: strain 0 to 0.1, stress = 100 MPa
        # Area = 0.1 * 100 = 10 MJ/m3
        strain = np.array([0.0, 0.1])
        stress = np.array([100.0, 100.0])
        data = StressStrainData(strain=strain, stress_MPa=stress, n_points=2)
        assert data.toughness_MJ_m3 == pytest.approx(10.0)

    def test_toughness_triangle(self):
        """Test toughness for triangular stress-strain."""
        # Triangle: strain 0 to 0.1, stress 0 to 100 MPa
        # Area = 0.5 * 0.1 * 100 = 5.0 MJ/m3
        strain = np.array([0.0, 0.05, 0.1])
        stress = np.array([0.0, 50.0, 100.0])
        data = StressStrainData(strain=strain, stress_MPa=stress, n_points=3)
        assert data.toughness_MJ_m3 == pytest.approx(5.0)


class TestStressStrainParser:
    """Tests for StressStrainParser."""

    def test_parse_basic(self, tmp_path):
        """Test basic parsing of stress-strain file."""
        ss_file = tmp_path / "stress_strain.dat"
        ss_file.write_text("# strain stress_MPa\n0.001 12.5\n0.002 25.1\n0.003 37.2\n")

        parser = StressStrainParser()
        data = parser.parse(ss_file)

        assert data.n_points == 3
        assert data.strain[0] == pytest.approx(0.001)
        assert data.stress_MPa[1] == pytest.approx(25.1)

    def test_parse_peak_values(self, tmp_path):
        """Test peak stress and strain from parsed file."""
        ss_file = tmp_path / "stress_strain.dat"
        ss_file.write_text(
            "# strain stress_MPa\n0.01 50.0\n0.02 100.0\n0.03 150.0\n0.04 120.0\n0.05 80.0\n"
        )

        parser = StressStrainParser()
        data = parser.parse(ss_file)

        assert data.peak_stress_MPa == pytest.approx(150.0)
        assert data.peak_strain == pytest.approx(0.03)

    def test_parse_file_not_found(self, tmp_path):
        """Test ParserError on missing file."""
        parser = StressStrainParser()
        with pytest.raises(ParserError):
            parser.parse(tmp_path / "nonexistent.dat")

    def test_parse_empty_file(self, tmp_path):
        """Test ParserError on empty file."""
        ss_file = tmp_path / "empty.dat"
        ss_file.write_text("# strain stress_MPa\n")

        parser = StressStrainParser()
        with pytest.raises(ParserError):
            parser.parse(ss_file)

    def test_parse_single_row(self, tmp_path):
        """Test parsing single-row file."""
        ss_file = tmp_path / "single.dat"
        ss_file.write_text("# strain stress_MPa\n0.01 50.0\n")

        parser = StressStrainParser()
        data = parser.parse(ss_file)

        assert data.n_points == 1
        assert data.strain[0] == pytest.approx(0.01)
        assert data.stress_MPa[0] == pytest.approx(50.0)

    def test_parse_malformed_data(self, tmp_path):
        """Test ParserError on malformed data."""
        ss_file = tmp_path / "bad.dat"
        ss_file.write_text("# strain stress_MPa\nnot_a_number also_bad\n")

        parser = StressStrainParser()
        with pytest.raises(ParserError):
            parser.parse(ss_file)

    def test_parse_non_comment_header_line(self, tmp_path):
        """Parser should handle files whose first line is plain title text."""
        ss_file = tmp_path / "plain_header.dat"
        ss_file.write_text("strain stress_MPa\n0.01 50.0\n0.02 100.0\n")

        parser = StressStrainParser()
        data = parser.parse(ss_file)

        assert data.n_points == 2
        assert data.strain[0] == pytest.approx(0.01)
        assert data.stress_MPa[1] == pytest.approx(100.0)

    def test_parse_single_value(self, tmp_path):
        """Test ParserError on file with single value (< 2 columns)."""
        ss_file = tmp_path / "one_val.dat"
        ss_file.write_text("# data\n0.01\n")

        parser = StressStrainParser()
        with pytest.raises(ParserError):
            parser.parse(ss_file)
