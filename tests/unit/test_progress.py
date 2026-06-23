"""Tests for features.jobs.progress -- stage progress calculation."""

import pytest

from features.jobs.progress import (
    compute_total_steps_with_overrides,
    get_stage_info_with_overrides,
)

# ---------------------------------------------------------------------------
# Screening chain (3 stages): minimize(1000 steps) + nvt(300ps) + npt(2000ps)
# With minimize=0: total = 300K + 2000K = 2_300_000 steps
# ---------------------------------------------------------------------------


class TestScreeningChain:
    """Screening chain: minimize + nvt + npt."""

    def test_total_steps_excludes_minimize(self):
        total = compute_total_steps_with_overrides("screening", [])
        # 300ps + 2000ps = 2300ps -> 2_300_000 steps at 1fs
        assert total == 2_300_000

    def test_stage_count(self):
        info = get_stage_info_with_overrides("screening", 0, None)
        assert info["total_stages"] == 3

    def test_step_0_is_nvt(self):
        """Step 0 should land on nvt (minimize has 0 cumulative steps)."""
        info = get_stage_info_with_overrides("screening", 0, None)
        # With minimize=0, the cumulative boundaries are:
        #   minimize: cumulative=0
        #   nvt: cumulative=300000
        #   npt: cumulative=2300000
        # current_step=0 < 0 is False -> check nvt: 0 < 300000 -> True
        assert info["current_stage"] == "nvt_equilibration"
        assert info["stage_index"] == 2

    def test_nvt_midpoint(self):
        info = get_stage_info_with_overrides("screening", 150_000, None)
        assert info["current_stage"] == "nvt_equilibration"
        assert info["stage_step"] == 150_000
        assert info["stage_total_steps"] == 300_000
        assert info["stage_percent"] == 50.0

    def test_npt_start(self):
        info = get_stage_info_with_overrides("screening", 300_000, None)
        assert info["current_stage"] == "npt_production"
        assert info["stage_step"] == 0
        assert info["stage_index"] == 3

    def test_beyond_total_returns_100(self):
        info = get_stage_info_with_overrides("screening", 3_000_000, None)
        assert info["stage_percent"] == 100.0
        assert info["current_stage"] == "npt_production"


# ---------------------------------------------------------------------------
# Layer chain (5 stages): minimize + high_temp_nvt + annealing + nvt + npt
# With minimize=0: total = 100K + 1000K + 500K + 2000K = 3_600_000 steps
# ---------------------------------------------------------------------------


class TestLayerChain:
    """Layer chain: minimize + high_temp_nvt + annealing + nvt + npt."""

    def test_total_steps_layer(self):
        total = compute_total_steps_with_overrides("layer", [])
        # 100ps + 1000ps + 500ps + 2000ps = 3600ps -> 3_600_000 steps
        assert total == 3_600_000

    def test_stage_count_layer(self):
        info = get_stage_info_with_overrides("layer", 0, None)
        assert info["total_stages"] == 5

    def test_layer_stage_names(self):
        """Verify all 4 non-minimize stages are present in correct order."""
        expected = [
            "high_temp_nvt",
            "annealing_cycles",
            "nvt_equilibration",
            "npt_equilibration",
        ]
        # Walk through stages
        steps = [0, 100_000, 1_100_000, 1_600_000]
        for step, expected_name in zip(steps, expected, strict=True):
            info = get_stage_info_with_overrides("layer", step, None)
            assert info["current_stage"] == expected_name, (
                f"At step {step}, expected '{expected_name}', got '{info['current_stage']}'"
            )

    def test_layer_annealing_midpoint(self):
        # annealing starts at step 100_000, lasts 1_000_000 steps
        info = get_stage_info_with_overrides("layer", 600_000, None)
        assert info["current_stage"] == "annealing_cycles"
        assert info["stage_step"] == 500_000
        assert info["stage_total_steps"] == 1_000_000

    def test_layer_npt_last(self):
        info = get_stage_info_with_overrides("layer", 1_700_000, None)
        assert info["current_stage"] == "npt_equilibration"
        assert info["stage_index"] == 5
        assert info["total_stages"] == 5

    def test_post_annealing_no_regression(self):
        """Step just past annealing must land on nvt_equilibration, not regress.

        Regression guard: before the fix, annealing ended with reset_timestep 0
        which sent step back to 0 and caused progress to report high_temp_nvt.
        With reset removed, steps are cumulative: annealing ends at 1_100_000
        so step 1_100_001 must be nvt_equilibration.
        """
        info = get_stage_info_with_overrides("layer", 1_100_001, None)
        assert info["current_stage"] == "nvt_equilibration", (
            f"Expected nvt_equilibration at step 1_100_001, got {info['current_stage']}"
        )


# ---------------------------------------------------------------------------
# Minimize offset: minimize must contribute 0 to cumulative
# ---------------------------------------------------------------------------


class TestMinimizeZeroOffset:
    """Minimize stages have 0 cumulative contribution."""

    def test_minimize_zero_in_screening(self):
        # If minimize were nonzero (1000), total would be 2_301_000
        total = compute_total_steps_with_overrides("screening", [])
        assert total == 2_300_000  # not 2_301_000

    def test_minimize_zero_in_layer(self):
        # Layer minimize is 10000 steps in SSOT, but should be 0 in progress
        total = compute_total_steps_with_overrides("layer", [])
        assert total == 3_600_000  # not 3_610_000


# ---------------------------------------------------------------------------
# Equilibration injection for bulk chains
# ---------------------------------------------------------------------------


class TestEquilibrationInjection:
    """Test equilibration stage injection for bulk experiments."""

    def test_screening_with_equilibration_total_steps(self):
        total = compute_total_steps_with_overrides("screening", [], has_equilibration=True)
        # screening base: 2_300_000
        # + high_temp_nvt: 100ps -> 100_000
        # + high_pressure_npt: 200ps -> 200_000
        assert total == 2_600_000

    def test_screening_with_equilibration_stage_count(self):
        info = get_stage_info_with_overrides("screening", 0, None, has_equilibration=True)
        # 3 base + 2 injected = 5 stages
        assert info["total_stages"] == 5

    def test_equilibration_stages_after_minimize(self):
        """Equilibration stages should appear right after minimize."""
        info = get_stage_info_with_overrides("screening", 0, None, has_equilibration=True)
        # minimize has 0 steps, so step 0 should be in high_temp_nvt
        assert info["current_stage"] == "high_temp_nvt"
        assert info["stage_index"] == 2

    def test_equilibration_high_pressure_npt(self):
        info = get_stage_info_with_overrides("screening", 100_000, None, has_equilibration=True)
        assert info["current_stage"] == "high_pressure_npt"
        assert info["stage_index"] == 3

    def test_equilibration_nvt_after_injection(self):
        # After high_temp_nvt(100K) + high_pressure_npt(200K) = 300K
        info = get_stage_info_with_overrides("screening", 300_000, None, has_equilibration=True)
        assert info["current_stage"] == "nvt_equilibration"
        assert info["stage_index"] == 4

    def test_layer_chain_not_double_injected(self):
        """Layer chains already have equilibration in SSOT, should NOT double-inject."""
        total_without = compute_total_steps_with_overrides("layer", [])
        total_with = compute_total_steps_with_overrides("layer", [], has_equilibration=True)
        # Layer chain should NOT get extra equilibration stages
        assert total_with == total_without

    def test_equilibration_stage_order(self):
        """Verify full stage order: minimize -> HT_NVT -> HP_NPT -> NVT -> NPT."""
        expected_order = [
            ("high_temp_nvt", 0),
            ("high_pressure_npt", 100_000),
            ("nvt_equilibration", 300_000),
            ("npt_production", 600_000),
        ]
        for expected_name, step in expected_order:
            info = get_stage_info_with_overrides("screening", step, None, has_equilibration=True)
            assert info["current_stage"] == expected_name, (
                f"At step {step}, expected '{expected_name}', got '{info['current_stage']}'"
            )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases for progress calculation."""

    def test_unknown_tier_raises(self):
        with pytest.raises(ValueError, match="Unknown tier"):
            compute_total_steps_with_overrides("nonexistent_tier", [])

    def test_negative_step(self):
        """Negative step should still work (treated as before first stage)."""
        info = get_stage_info_with_overrides("screening", -1, None)
        # -1 < 0 (minimize cumulative) -> True, so it matches minimize
        assert info["current_stage"] == "minimize"
        assert info["stage_index"] == 1

    def test_format_elapsed_eta(self):
        from features.jobs.progress import format_elapsed_eta

        elapsed, eta = format_elapsed_eta(500_000, 2_300_000, 3600.0)
        assert elapsed == "1h 0m"
        assert "h" in eta


# ---------------------------------------------------------------------------
# Reset-timestep adjustment via @@STAGE markers
# ---------------------------------------------------------------------------
# tensile_layer stages (dt=1.0fs):
#   0: minimize        cumulative=0
#   1: high_temp_nvt   cumulative=100_000     (100ps)
#   2: annealing_cycles cumulative=1_100_000  (1000ps)
#   3: nvt_equilibration cumulative=1_600_000 (500ps)
#   4: npt_equilibration cumulative=3_600_000 (2000ps)
#   5: pre_tensile_nvt  cumulative=3_700_000  (100ps)
#   6: tensile_pull     cumulative=5_700_000  (2000ps) <- reset_timestep 0
# ---------------------------------------------------------------------------


class TestResetTimestepAdjustment:
    """Tests for _adjust_step_for_reset and marker integration."""

    def test_tensile_pull_with_marker(self):
        """raw=5000 + marker=(6, tensile_pull) -> tensile_pull stage."""
        info = get_stage_info_with_overrides(
            "tensile_layer", 5000, None, stage_marker=(6, "tensile_pull")
        )
        assert info["current_stage"] == "tensile_pull"
        assert info["stage_index"] == 7  # 1-based

    def test_no_marker_legacy_behavior(self):
        """marker=None -> raw step 기준 (high_temp_nvt로 오판)."""
        info = get_stage_info_with_overrides("tensile_layer", 5000, None)
        assert info["current_stage"] == "high_temp_nvt"

    def test_marker_no_reset_no_change(self):
        """Reset 없는 stage에서 marker 있어도 보정 안 됨."""
        # Step 150K is in annealing_cycles; marker says annealing_cycles
        # raw_step=150_000 >= pre_cumulative=100_000 -> no adjustment
        info = get_stage_info_with_overrides(
            "tensile_layer", 150_000, None, stage_marker=(2, "annealing_cycles")
        )
        assert info["current_stage"] == "annealing_cycles"

    def test_qs_tensile_with_marker(self):
        """tensile_layer_qs에서도 동일 동작."""
        info = get_stage_info_with_overrides(
            "tensile_layer_qs", 5000, None, stage_marker=(6, "tensile_pull")
        )
        assert info["current_stage"] == "tensile_pull"

    def test_marker_out_of_range(self):
        """index 범위 밖 -> fallback (보정 없음)."""
        info = get_stage_info_with_overrides(
            "tensile_layer", 5000, None, stage_marker=(99, "tensile_pull")
        )
        # Falls back to raw step -> high_temp_nvt
        assert info["current_stage"] == "high_temp_nvt"

    def test_marker_name_mismatch(self):
        """Index 유효하나 name 불일치 -> 보정 안 됨."""
        info = get_stage_info_with_overrides(
            "tensile_layer", 5000, None, stage_marker=(6, "wrong_name")
        )
        assert info["current_stage"] == "high_temp_nvt"

    def test_compiled_plan_with_marker(self):
        """compiled_plan 경로에서도 보정 동작."""
        compiled_plan = {
            "stages": [
                {
                    "stage_key": "minimize",
                    "type": "minimize",
                    "expected_steps": 0,
                    "cumulative_steps": 0,
                },
                {
                    "stage_key": "high_temp_nvt",
                    "type": "nvt",
                    "expected_steps": 100_000,
                    "cumulative_steps": 100_000,
                },
                {
                    "stage_key": "annealing_cycles",
                    "type": "annealing",
                    "expected_steps": 1_000_000,
                    "cumulative_steps": 1_100_000,
                },
                {
                    "stage_key": "nvt_equilibration",
                    "type": "nvt",
                    "expected_steps": 500_000,
                    "cumulative_steps": 1_600_000,
                },
                {
                    "stage_key": "npt_equilibration",
                    "type": "npt",
                    "expected_steps": 2_000_000,
                    "cumulative_steps": 3_600_000,
                },
                {
                    "stage_key": "pre_tensile_nvt",
                    "type": "nvt",
                    "expected_steps": 100_000,
                    "cumulative_steps": 3_700_000,
                },
                {
                    "stage_key": "tensile_pull",
                    "type": "tensile",
                    "expected_steps": 2_000_000,
                    "cumulative_steps": 5_700_000,
                },
            ]
        }
        info = get_stage_info_with_overrides(
            "tensile_layer",
            5000,
            None,
            compiled_plan=compiled_plan,
            stage_marker=(6, "tensile_pull"),
        )
        assert info["current_stage"] == "tensile_pull"

    def test_adjusted_step_in_return(self):
        """adjusted_step = pre_cumulative + raw_step."""
        info = get_stage_info_with_overrides(
            "tensile_layer", 5000, None, stage_marker=(6, "tensile_pull")
        )
        # pre_cumulative for index 6 = 3_700_000; adjusted = 3_700_000 + 5000 = 3_705_000
        assert info["adjusted_step"] == 3_705_000

    def test_adjusted_step_capped(self):
        """보정값이 stage 상한 초과하지 않음."""
        # raw_step large but still < pre_cumulative (3.7M): e.g. 2_500_000
        # adjusted = 3_700_000 + 2_500_000 = 6_200_000
        # but cap at stages[6].cumulative - 1 = 5_699_999
        info = get_stage_info_with_overrides(
            "tensile_layer", 2_500_000, None, stage_marker=(6, "tensile_pull")
        )
        assert info["adjusted_step"] <= 5_700_000
        assert info["current_stage"] == "tensile_pull"
