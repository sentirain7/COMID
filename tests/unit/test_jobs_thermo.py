"""Unit tests for job thermo parsing helpers."""

from types import SimpleNamespace

from features.jobs.thermo import parse_stage_marker, parse_thermo_tail


def test_parse_thermo_tail_handles_mismatched_column_lengths(monkeypatch, tmp_path) -> None:
    """Thermo parser should not fail when columns have different lengths."""
    log_file = tmp_path / "log.lammps"
    log_file.write_text("dummy")

    class _FakeLogParser:
        def parse_tail(self, _path, bytes_to_read=102400, max_points=50):
            return SimpleNamespace(
                thermo_data={
                    "Step": [1000, 2000],
                    "Temp": [301.5],  # shorter than Step
                    "Press": [],  # empty
                    "Density": [0.91, 0.92],
                    "PotEng": [-1234.5],  # shorter than Step
                }
            )

    monkeypatch.setattr("parsers.log_parser.LogParser", _FakeLogParser)

    thermo_data, current_step, temp, press, density, energy = parse_thermo_tail(str(log_file))

    assert current_step == 2000
    assert temp == 301.5
    assert press is None
    assert density == 0.92
    assert energy == -1234.5
    assert len(thermo_data) == 2
    assert thermo_data[1]["temperature"] is None
    assert thermo_data[1]["pressure"] is None
    assert thermo_data[1]["energy"] is None


class TestParseStageMarker:
    """Tests for parse_stage_marker()."""

    def test_parses_last_marker(self, tmp_path) -> None:
        log = tmp_path / "log.lammps"
        log.write_text(
            "@@STAGE 2 annealing_cycles\n"
            "Step Temp Press\n"
            "1000 300.0 1.0\n"
            "@@STAGE 3 nvt_equilibration\n"
            "2000 300.0 1.0\n"
        )
        result = parse_stage_marker(str(log))
        assert result == (3, "nvt_equilibration")

    def test_no_markers(self, tmp_path) -> None:
        log = tmp_path / "log.lammps"
        log.write_text("Step Temp Press\n1000 300.0 1.0\n")
        assert parse_stage_marker(str(log)) is None

    def test_missing_file(self) -> None:
        assert parse_stage_marker("/nonexistent/path/log.lammps") is None

    def test_none_path(self) -> None:
        assert parse_stage_marker(None) is None

    def test_malformed_marker(self, tmp_path) -> None:
        log = tmp_path / "log.lammps"
        log.write_text("@@STAGE abc xyz\n@@STAGE not_a_number bad\n")
        assert parse_stage_marker(str(log)) is None
