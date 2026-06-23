"""Tests for contracts.policies.build_progress + features.dashboard.build_progress."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from contracts.policies.build_progress import DEFAULT_BUILD_PROGRESS_POLICY  # noqa: E402
from features.dashboard.build_progress import compute_build_percent  # noqa: E402


class TestCoarsePhaseMapping:
    def test_known_phase_returns_weight(self):
        policy = DEFAULT_BUILD_PROGRESS_POLICY
        assert compute_build_percent(status="composition_validation", label=None) == 2.0
        assert compute_build_percent(status="structure_build", label=None) == 5.0
        assert compute_build_percent(status="building_structure", label=None) == 5.0
        assert compute_build_percent(status="packing_molecules", label=None) == 20.0
        assert compute_build_percent(status="loading_molecule_topologies", label=None) == 30.0
        assert compute_build_percent(status="loading_topologies", label=None) == 30.0
        assert compute_build_percent(status="assigning_types_charges", label=None) == 35.0
        assert compute_build_percent(status="generating_ff_params", label=None) == 35.0
        assert compute_build_percent(status="protocol_generation", label=None) == 95.0
        assert compute_build_percent(status="build_complete", label=None) == 100.0
        # sanity: policy instance not mutated
        assert policy.phase_weights["composition_validation"] == 2.0

    def test_unknown_phase_returns_none(self):
        assert compute_build_percent(status="totally_unknown_xyz", label=None) is None
        assert compute_build_percent(status="", label=None) is None


class TestArtifactSubstepFormula:
    @pytest.mark.parametrize(
        "status, expected",
        [
            ("artifact_antechamber", 51.25),
            ("artifact_parmchk2", 62.5),
            ("artifact_tleap", 73.75),
            ("artifact_parmed", 85.0),
        ],
    )
    def test_single_molecule_prefix(self, status, expected):
        got = compute_build_percent(status=status, label="[1/1 MOL] whatever")
        assert got == pytest.approx(expected)

    def test_multi_molecule_prefix(self):
        # Second molecule, parmchk2 substep (index 1). N=3, so total_substeps=12,
        # completed_substeps = (2-1)*4 + (1+1) = 6. fraction = 6/12 = 0.5.
        # percent = 40 + 0.5*(85-40) = 62.5
        got = compute_build_percent(status="artifact_parmchk2", label="[2/3 MOL_B] label")
        assert got == pytest.approx(62.5)

    def test_malformed_label_fallback_to_single(self):
        got = compute_build_percent(status="artifact_antechamber", label="no-prefix-here")
        assert got == pytest.approx(51.25)

    def test_missing_label_fallback_to_single(self):
        got = compute_build_percent(status="artifact_antechamber", label=None)
        assert got == pytest.approx(51.25)

    def test_zero_or_negative_counts_fallback_to_single(self):
        got = compute_build_percent(status="artifact_parmchk2", label="[0/0 X] x")
        assert got == pytest.approx(62.5)
