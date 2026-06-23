"""Unit tests for restart script generation."""

import sys

import pytest

sys.path.insert(0, "src")

from protocols.lammps_input import LAMMPSInputGenerator
from protocols.restart_discovery import RestartPoint


@pytest.fixture
def generator():
    return LAMMPSInputGenerator()


@pytest.fixture
def _screening_request():
    """Minimal ProtocolRequest for screening tier."""
    from contracts.schemas import FFType, ProtocolRequest, RunTier, StudyType

    return ProtocolRequest(
        ff_type=FFType.BULK_FF_GAFF2,
        run_tier=RunTier.SCREENING,
        study_type=StudyType.BULK,
        temperature_K=298.0,
        pressure_atm=1.0,
        data_file_path="/tmp/dummy/data.lammps",
    )


@pytest.fixture
def restart_point(tmp_path):
    """A restart point after nvt_equilibration (stage index 1)."""
    restart_file = tmp_path / "restart.nvt_equilibration"
    restart_file.touch()
    return RestartPoint(
        restart_file=restart_file.resolve(),
        completed_stage_index=1,
        completed_stage_name="nvt_equilibration",
        remaining_stage_indices=[2],
        source_attempt_dir=tmp_path,
    )


class TestGenerateRestartScript:
    """Test LAMMPSInputGenerator.generate_restart_script()."""

    def test_contains_read_restart(self, generator, _screening_request, restart_point, tmp_path):
        """Script must use read_restart instead of read_data."""
        output_path = tmp_path / "output" / "in.restart.lammps"
        generator.generate_restart_script(
            request=_screening_request,
            restart_file=restart_point.restart_file,
            remaining_stage_indices=restart_point.remaining_stage_indices,
            output_path=output_path,
        )
        script = output_path.read_text()
        assert "read_restart" in script
        assert str(restart_point.restart_file) in script

    def test_no_read_data_command(self, generator, _screening_request, restart_point, tmp_path):
        """Script must NOT contain a read_data LAMMPS command."""
        output_path = tmp_path / "output" / "in.restart.lammps"
        generator.generate_restart_script(
            request=_screening_request,
            restart_file=restart_point.restart_file,
            remaining_stage_indices=restart_point.remaining_stage_indices,
            output_path=output_path,
        )
        script = output_path.read_text()
        # read_data should NOT appear as a LAMMPS command (at line start).
        # It may appear in comments like "# Pair coefficients read from data file"
        # or in write_data, which are fine.
        for line in script.splitlines():
            stripped = line.strip()
            assert not stripped.startswith("read_data "), f"Found read_data command: {stripped}"

    def test_original_stage_index_in_markers(
        self, generator, _screening_request, restart_point, tmp_path
    ):
        """@@STAGE markers must use original indices for progress consistency."""
        output_path = tmp_path / "output" / "in.restart.lammps"
        generator.generate_restart_script(
            request=_screening_request,
            restart_file=restart_point.restart_file,
            remaining_stage_indices=[2],  # npt_production is stage 2
            output_path=output_path,
        )
        script = output_path.read_text()
        # Original index for npt_production is 2
        assert "@@STAGE 2 npt_production" in script
        # Should NOT have stage 0 or 1
        assert "@@STAGE 0" not in script
        assert "@@STAGE 1" not in script

    def test_only_remaining_stages(self, generator, _screening_request, tmp_path):
        """Only remaining stages should appear in the script."""
        restart_file = tmp_path / "restart.minimize"
        restart_file.touch()
        output_path = tmp_path / "output" / "in.restart.lammps"
        generator.generate_restart_script(
            request=_screening_request,
            restart_file=restart_file,
            remaining_stage_indices=[1, 2],
            output_path=output_path,
        )
        script = output_path.read_text()
        # minimize should NOT appear as a step
        assert "Step 1: minimize" not in script
        # nvt_equilibration and npt_production should appear
        assert "nvt_equilibration" in script
        assert "npt_production" in script

    def test_returns_protocol_result(self, generator, _screening_request, restart_point, tmp_path):
        """Should return a valid ProtocolResult."""
        output_path = tmp_path / "output" / "in.restart.lammps"
        result = generator.generate_restart_script(
            request=_screening_request,
            restart_file=restart_point.restart_file,
            remaining_stage_indices=restart_point.remaining_stage_indices,
            output_path=output_path,
        )
        assert result.input_script_path == str(output_path)
        assert result.estimated_steps > 0
        assert result.protocol_hash
        assert result.stabilization_chain

    def test_contains_force_field(self, generator, _screening_request, restart_point, tmp_path):
        """Force field styles must be re-declared (not stored in restart)."""
        output_path = tmp_path / "output" / "in.restart.lammps"
        generator.generate_restart_script(
            request=_screening_request,
            restart_file=restart_point.restart_file,
            remaining_stage_indices=restart_point.remaining_stage_indices,
            output_path=output_path,
        )
        script = output_path.read_text()
        assert "pair_style" in script
        assert "units real" in script

    def test_final_write_commands(self, generator, _screening_request, restart_point, tmp_path):
        """Script must end with write_data and write_restart."""
        output_path = tmp_path / "output" / "in.restart.lammps"
        generator.generate_restart_script(
            request=_screening_request,
            restart_file=restart_point.restart_file,
            remaining_stage_indices=restart_point.remaining_stage_indices,
            output_path=output_path,
        )
        script = output_path.read_text()
        assert "write_data final.data" in script
        assert "write_restart final.restart" in script


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
