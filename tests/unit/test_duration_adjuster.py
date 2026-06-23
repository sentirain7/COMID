"""
Unit tests for protocols.duration_adjuster module.

Tests ProtocolChainAdjuster: validation, overrides, stage listing,
default durations, and merge_with_defaults.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from protocols.duration_adjuster import ProtocolChainAdjuster, StageDurationOverride


@pytest.fixture
def adjuster():
    return ProtocolChainAdjuster()


# ── StageDurationOverride model ───────────────────────────────────


class TestStageDurationOverride:
    def test_create_with_ps(self):
        o = StageDurationOverride(stage_name="npt_production", duration_ps=2000)
        assert o.stage_name == "npt_production"
        assert o.duration_ps == 2000
        assert o.duration_steps is None

    def test_create_with_steps(self):
        o = StageDurationOverride(stage_name="minimize", duration_steps=50000)
        assert o.duration_steps == 50000
        assert o.duration_ps is None

    def test_negative_duration_rejected(self):
        with pytest.raises(ValueError):
            StageDurationOverride(stage_name="nvt_equilibration", duration_ps=-100)


# ── get_valid_stages ──────────────────────────────────────────────


class TestGetValidStages:
    def test_screening_stages(self, adjuster):
        stages = adjuster.get_valid_stages("screening")
        assert "minimize" in stages
        assert "nvt_equilibration" in stages
        assert "npt_production" in stages

    def test_confirm_stages(self, adjuster):
        stages = adjuster.get_valid_stages("confirm")
        assert len(stages) >= 3

    def test_viscosity_has_nemd_stage(self, adjuster):
        stages = adjuster.get_valid_stages("viscosity")
        nemd_stages = [s for s in stages if "nemd" in s or "viscosity" in s]
        assert len(nemd_stages) >= 1


# ── get_default_durations ─────────────────────────────────────────


class TestGetDefaultDurations:
    def test_screening_defaults(self, adjuster):
        defaults = adjuster.get_default_durations("screening")
        assert "minimize" in defaults
        assert "npt_production" in defaults

        npt = defaults["npt_production"]
        assert npt["duration_ps"] is not None
        assert npt["duration_ps"] > 0

    def test_minimize_has_steps(self, adjuster):
        defaults = adjuster.get_default_durations("screening")
        minimize = defaults["minimize"]
        assert minimize["type"] == "minimize"
        assert minimize["duration_steps"] is not None


# ── validate_overrides ────────────────────────────────────────────


class TestValidateOverrides:
    def test_valid_override_no_errors(self, adjuster):
        overrides = [
            StageDurationOverride(stage_name="npt_production", duration_ps=2000),
        ]
        errors = adjuster.validate_overrides("screening", overrides)
        assert errors == []

    def test_invalid_stage_name(self, adjuster):
        overrides = [
            StageDurationOverride(stage_name="nonexistent_stage", duration_ps=100),
        ]
        errors = adjuster.validate_overrides("screening", overrides)
        assert len(errors) == 1
        assert "nonexistent_stage" in errors[0]

    def test_no_duration_specified(self, adjuster):
        overrides = [
            StageDurationOverride(stage_name="npt_production"),
        ]
        errors = adjuster.validate_overrides("screening", overrides)
        assert len(errors) == 1
        assert "No duration" in errors[0]

    def test_ps_for_minimize_warns(self, adjuster):
        overrides = [
            StageDurationOverride(stage_name="minimize", duration_ps=100),
        ]
        errors = adjuster.validate_overrides("screening", overrides)
        assert len(errors) == 1
        assert "duration_steps" in errors[0]

    def test_steps_for_md_warns(self, adjuster):
        overrides = [
            StageDurationOverride(stage_name="npt_production", duration_steps=5000),
        ]
        errors = adjuster.validate_overrides("screening", overrides)
        assert len(errors) == 1
        assert "duration_ps" in errors[0]

    def test_multiple_overrides(self, adjuster):
        overrides = [
            StageDurationOverride(stage_name="nvt_equilibration", duration_ps=500),
            StageDurationOverride(stage_name="npt_production", duration_ps=2000),
        ]
        errors = adjuster.validate_overrides("screening", overrides)
        assert errors == []

    def test_equilibration_overrides_allowed_for_bulk_tiers(self, adjuster):
        overrides = [
            StageDurationOverride(stage_name="high_temp_nvt", duration_ps=150),
            StageDurationOverride(stage_name="high_pressure_npt", duration_ps=250),
        ]
        errors = adjuster.validate_overrides("screening", overrides)
        assert errors == []


# ── apply_overrides ───────────────────────────────────────────────


class TestApplyOverrides:
    def _build_chain(self):
        from contracts.schemas import FFType, RunTier, StudyType
        from protocols.protocol_chain import ProtocolChain, ProtocolStep

        steps = [
            ProtocolStep(name="minimize", step_type="minimize", duration="10000 steps"),
            ProtocolStep(name="nvt_equilibration", step_type="nvt", duration="300 ps"),
            ProtocolStep(name="npt_production", step_type="npt", duration="1000 ps"),
        ]
        return ProtocolChain(
            tier=RunTier.SCREENING,
            steps=steps,
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            pressure_atm=1.0,
            study_type=StudyType.BULK,
        )

    def test_apply_ps_override(self, adjuster):
        chain = self._build_chain()
        overrides = [
            StageDurationOverride(stage_name="npt_production", duration_ps=2000),
        ]
        result = adjuster.apply_overrides(chain, overrides)
        npt = next(s for s in result.steps if s.name == "npt_production")
        assert "2000" in npt.duration and "ps" in npt.duration

    def test_apply_steps_override(self, adjuster):
        chain = self._build_chain()
        overrides = [
            StageDurationOverride(stage_name="minimize", duration_steps=50000),
        ]
        result = adjuster.apply_overrides(chain, overrides)
        minimize = next(s for s in result.steps if s.name == "minimize")
        assert minimize.duration == "50000 steps"

    def test_unmatched_override_is_noop(self, adjuster):
        chain = self._build_chain()
        overrides = [
            StageDurationOverride(stage_name="no_such_stage", duration_ps=100),
        ]
        original_durations = [s.duration for s in chain.steps]
        adjuster.apply_overrides(chain, overrides)
        assert [s.duration for s in chain.steps] == original_durations

    def test_multiple_overrides(self, adjuster):
        chain = self._build_chain()
        overrides = [
            StageDurationOverride(stage_name="nvt_equilibration", duration_ps=500),
            StageDurationOverride(stage_name="npt_production", duration_ps=5000),
        ]
        adjuster.apply_overrides(chain, overrides)
        nvt = next(s for s in chain.steps if s.name == "nvt_equilibration")
        npt = next(s for s in chain.steps if s.name == "npt_production")
        assert "500" in nvt.duration and "ps" in nvt.duration
        assert "5000" in npt.duration and "ps" in npt.duration


# ── merge_with_defaults ───────────────────────────────────────────


class TestMergeWithDefaults:
    def test_no_overrides(self, adjuster):
        result = adjuster.merge_with_defaults("screening", [])
        assert len(result) >= 3
        assert all(not item["is_override"] for item in result)

    def test_with_one_override(self, adjuster):
        overrides = [
            StageDurationOverride(stage_name="npt_production", duration_ps=5000),
        ]
        result = adjuster.merge_with_defaults("screening", overrides)
        npt = next(r for r in result if r["stage_name"] == "npt_production")
        assert npt["is_override"]
        assert npt["duration_ps"] == 5000

    def test_non_overridden_keep_defaults(self, adjuster):
        overrides = [
            StageDurationOverride(stage_name="npt_production", duration_ps=5000),
        ]
        result = adjuster.merge_with_defaults("screening", overrides)
        nvt = next(r for r in result if r["stage_name"] == "nvt_equilibration")
        assert not nvt["is_override"]
        assert nvt["duration_ps"] is not None

    def test_equilibration_override_included_in_merge(self, adjuster):
        overrides = [
            StageDurationOverride(stage_name="high_pressure_npt", duration_ps=250),
        ]
        result = adjuster.merge_with_defaults("screening", overrides)
        eq = next(r for r in result if r["stage_name"] == "high_pressure_npt")
        assert eq["is_override"]
        assert eq["duration_ps"] == 250
