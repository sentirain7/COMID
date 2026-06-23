"""Unit tests for restart-from-checkpoint discovery logic."""

import sys

import pytest

sys.path.insert(0, "src")

from protocols.restart_discovery import discover_restart_point

# Typical screening chain stages
SCREENING_PLAN = {
    "stages": [
        {"stage_key": "minimize"},
        {"stage_key": "nvt_equilibration"},
        {"stage_key": "npt_production"},
    ],
    "total_steps": 3300000,
}

# Typical tensile_layer chain stages
TENSILE_LAYER_PLAN = {
    "stages": [
        {"stage_key": "minimize"},
        {"stage_key": "high_temp_nvt"},
        {"stage_key": "annealing_cycles"},
        {"stage_key": "nvt_equilibration"},
        {"stage_key": "npt_equilibration"},
        {"stage_key": "pre_tensile_nvt"},
        {"stage_key": "tensile_pull"},
    ],
    "total_steps": 5700000,
}


class TestDiscoverRestartPoint:
    """Test discover_restart_point()."""

    def test_finds_latest_stage(self, tmp_path):
        """Should find the latest completed stage restart file."""
        attempt = tmp_path / "attempt_abc"
        attempt.mkdir()
        (attempt / "restart.minimize").touch()
        (attempt / "restart.nvt_equilibration").touch()

        result = discover_restart_point("test_exp", SCREENING_PLAN, [attempt])

        assert result is not None
        assert result.completed_stage_index == 1
        assert result.completed_stage_name == "nvt_equilibration"
        assert result.remaining_stage_indices == [2]
        assert result.source_attempt_dir == attempt
        assert result.restart_file == (attempt / "restart.nvt_equilibration").resolve()

    def test_returns_none_when_no_restart_files(self, tmp_path):
        """Should return None when no restart files exist."""
        attempt = tmp_path / "attempt_abc"
        attempt.mkdir()

        result = discover_restart_point("test_exp", SCREENING_PLAN, [attempt])
        assert result is None

    def test_returns_none_when_final_restart_exists(self, tmp_path):
        """Should return None when final.restart exists (simulation completed)."""
        attempt = tmp_path / "attempt_abc"
        attempt.mkdir()
        (attempt / "restart.minimize").touch()
        (attempt / "restart.nvt_equilibration").touch()
        (attempt / "restart.npt_production").touch()
        (attempt / "final.restart").touch()

        result = discover_restart_point("test_exp", SCREENING_PLAN, [attempt])
        assert result is None

    def test_returns_none_all_stages_complete_no_remaining(self, tmp_path):
        """All stage restarts exist but no remaining stages."""
        attempt = tmp_path / "attempt_abc"
        attempt.mkdir()
        (attempt / "restart.minimize").touch()
        (attempt / "restart.nvt_equilibration").touch()
        (attempt / "restart.npt_production").touch()

        result = discover_restart_point("test_exp", SCREENING_PLAN, [attempt])
        assert result is None

    def test_returns_none_when_no_compiled_plan(self, tmp_path):
        """Should return None when compiled_plan is None."""
        attempt = tmp_path / "attempt_abc"
        attempt.mkdir()
        (attempt / "restart.minimize").touch()

        assert discover_restart_point("test_exp", None, [attempt]) is None

    def test_returns_none_for_empty_stages(self, tmp_path):
        """Should return None when stages list is empty."""
        attempt = tmp_path / "attempt_abc"
        attempt.mkdir()

        result = discover_restart_point("test_exp", {"stages": []}, [attempt])
        assert result is None

    def test_candidate_dir_priority(self, tmp_path):
        """First candidate dir with restart files wins."""
        dir1 = tmp_path / "attempt_priority"
        dir1.mkdir()
        (dir1 / "restart.minimize").touch()
        (dir1 / "restart.nvt_equilibration").touch()

        dir2 = tmp_path / "attempt_secondary"
        dir2.mkdir()
        (dir2 / "restart.minimize").touch()

        # dir1 is listed first -> should find nvt_equilibration
        result = discover_restart_point("test_exp", SCREENING_PLAN, [dir1, dir2])
        assert result is not None
        assert result.completed_stage_name == "nvt_equilibration"
        assert result.source_attempt_dir == dir1

    def test_skips_nonexistent_candidate_dirs(self, tmp_path):
        """Should skip candidate dirs that don't exist."""
        nonexistent = tmp_path / "does_not_exist"
        real = tmp_path / "attempt_real"
        real.mkdir()
        (real / "restart.minimize").touch()

        result = discover_restart_point("test_exp", SCREENING_PLAN, [nonexistent, real])
        assert result is not None
        assert result.completed_stage_name == "minimize"
        assert result.remaining_stage_indices == [1, 2]

    def test_tensile_layer_mid_chain(self, tmp_path):
        """Tensile layer chain with crash after npt_equilibration."""
        attempt = tmp_path / "attempt_tensile"
        attempt.mkdir()
        for name in ["minimize", "high_temp_nvt", "annealing_cycles", "nvt_equilibration"]:
            (attempt / f"restart.{name}").touch()

        result = discover_restart_point("test_exp", TENSILE_LAYER_PLAN, [attempt])
        assert result is not None
        assert result.completed_stage_index == 3
        assert result.completed_stage_name == "nvt_equilibration"
        assert result.remaining_stage_indices == [4, 5, 6]

    def test_only_minimize_completed(self, tmp_path):
        """Only minimize completed - should restart from first dynamics stage."""
        attempt = tmp_path / "attempt_min"
        attempt.mkdir()
        (attempt / "restart.minimize").touch()

        result = discover_restart_point("test_exp", SCREENING_PLAN, [attempt])
        assert result is not None
        assert result.completed_stage_index == 0
        assert result.completed_stage_name == "minimize"
        assert result.remaining_stage_indices == [1, 2]

    def test_compositions_input_as_fallback(self, tmp_path):
        """When attempt dirs are empty, compositions/input/ fallback should work."""
        # Empty attempt dir (no restart files)
        empty_attempt = tmp_path / "attempt_empty"
        empty_attempt.mkdir()

        # compositions/.../input/ has restart files (simulating real layout)
        compositions_input = tmp_path / "compositions_input"
        compositions_input.mkdir()
        (compositions_input / "restart.minimize").touch()
        (compositions_input / "restart.nvt_equilibration").touch()

        # attempt first (empty), then compositions fallback
        result = discover_restart_point(
            "test_exp", SCREENING_PLAN, [empty_attempt, compositions_input]
        )
        assert result is not None
        assert result.completed_stage_name == "nvt_equilibration"
        assert result.source_attempt_dir == compositions_input

    def test_attempt_dir_preferred_over_compositions(self, tmp_path):
        """Attempt dir with restart files should be preferred over compositions."""
        attempt = tmp_path / "attempt_real"
        attempt.mkdir()
        (attempt / "restart.minimize").touch()

        compositions = tmp_path / "compositions_input"
        compositions.mkdir()
        (compositions / "restart.minimize").touch()
        (compositions / "restart.nvt_equilibration").touch()

        # attempt has only minimize, compositions has more — but attempt wins
        result = discover_restart_point("test_exp", SCREENING_PLAN, [attempt, compositions])
        assert result is not None
        # Should find minimize from attempt (first candidate with any restart)
        assert result.source_attempt_dir == attempt
        assert result.completed_stage_name == "minimize"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
