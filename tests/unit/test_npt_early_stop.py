"""Tests for opt-in NPT convergence early-stop (v01.05.12, RadonPy-style).

The feature is OFF by default — the rendered NPT must be byte-identical to
the legacy fixed-duration run unless ``ConvergenceCriteria.enable_early_stop``
is explicitly turned on. When on, a ``fix halt`` monitored segment is emitted
with a floor so a premature (non-equilibrated) dip cannot end the run early.
The LAMMPS ``fix halt`` + ``fix ave/time`` syntax was validated against a
local argon NPT run.
"""

from __future__ import annotations

import pytest

from contracts.policies.tier import DEFAULT_TIER_POLICY
from contracts.schemas import StudyType
from protocols.lammps_steps import generate_npt
from protocols.protocol_chain import ProtocolStep


def _npt_step(duration: str = "2000 ps", thermo_interval: int = 1000) -> ProtocolStep:
    return ProtocolStep(
        step_type="npt",
        name="npt_production",
        duration=duration,
        timestep_fs=1.0,
        temperature_K=298.0,
        pressure_atm=1.0,
        thermo_interval=thermo_interval,
    )


@pytest.fixture
def _restore_early_stop():
    """Snapshot/restore the global flag so tests never leak state."""
    crit = DEFAULT_TIER_POLICY.convergence_criteria
    saved = crit.enable_early_stop
    yield
    crit.enable_early_stop = saved


class TestEarlyStopOffByDefault:
    def test_default_is_off(self):
        assert DEFAULT_TIER_POLICY.convergence_criteria.enable_early_stop is False

    def test_rendered_npt_is_single_fixed_run(self):
        out = generate_npt(_npt_step(), 2, StudyType.BULK)
        assert "fix halt" not in out
        assert out.count("\nrun ") == 1
        assert "write_restart restart.npt_production" in out


class TestEarlyStopEnabled:
    def test_emits_halt_and_two_segments(self, _restore_early_stop):
        DEFAULT_TIER_POLICY.convergence_criteria.enable_early_stop = True
        out = generate_npt(_npt_step(), 2, StudyType.BULK)
        assert "fix npt_2_halt all halt" in out
        # floor run + remaining run
        assert out.count("\nrun ") == 2
        # density coefficient-of-variation monitor
        assert "v_npt_2_dcv <" in out
        assert "fix npt_2_dm all ave/time" in out
        # fixes are cleaned up
        assert "unfix npt_2_halt" in out
        assert "unfix npt_2_dm" in out
        assert "unfix npt_2_dm2" in out

    def test_floor_below_remaining(self, _restore_early_stop):
        DEFAULT_TIER_POLICY.convergence_criteria.enable_early_stop = True
        DEFAULT_TIER_POLICY.convergence_criteria.early_stop_min_fraction = 0.5
        out = generate_npt(_npt_step(duration="2000 ps"), 2, StudyType.BULK)
        runs = [int(line.split()[1]) for line in out.splitlines() if line.startswith("run ")]
        assert len(runs) == 2
        floor, remaining = runs
        # 2000 ps / 1 fs = 2_000_000 steps; floor = 0.5 → 1_000_000 each
        assert floor == 1_000_000
        assert remaining == 1_000_000

    def test_short_run_falls_back_to_fixed(self, _restore_early_stop):
        """A run too short for a meaningful trailing window keeps the fixed run."""
        DEFAULT_TIER_POLICY.convergence_criteria.enable_early_stop = True
        # 10 ps / 1 fs = 10_000 steps; floor 5_000 < nfreq*window (10_000*5)
        out = generate_npt(_npt_step(duration="10 ps"), 2, StudyType.BULK)
        assert "fix halt" not in out
        assert out.count("\nrun ") == 1

    def test_threshold_value_is_policy_driven(self, _restore_early_stop):
        crit = DEFAULT_TIER_POLICY.convergence_criteria
        crit.enable_early_stop = True
        crit.early_stop_density_cv = 0.005
        out = generate_npt(_npt_step(), 2, StudyType.BULK)
        assert "v_npt_2_dcv < 0.005" in out
