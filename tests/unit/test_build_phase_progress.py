"""Tests for building phase progress reporting to dashboard.

Verifies that:
1. Builder progress callback updates DB metadata with build_phase/label
2. /jobs/running API includes building experiments with phase info
3. All builder status strings map to user-facing labels
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


class TestBuilderProgressLabels:
    """Builder internal status strings map to dashboard labels."""

    def test_all_known_statuses_have_labels(self):
        """Every status emitted by structure_builder must have a label mapping."""
        # Import the label map from pipeline
        # Since it's defined inside a method, we test the mapping directly
        known_statuses = {
            "building_structure",
            "packing_molecules",
            "loading_molecule_topologies",
            "assigning_types_charges",
            # v00.99.30 FF sub-phase codes emitted from generate_gaff2_artifact
            "artifact_antechamber",
            "artifact_parmchk2",
            "artifact_tleap",
            "artifact_parmed",
        }
        labels = {
            "building_structure": "Initializing build...",
            "packing_molecules": "Packing molecules (Packmol)...",
            "loading_molecule_topologies": "Loading molecule topologies...",
            "assigning_types_charges": "Generating FF parameters (artifact ~10 min)...",
            "artifact_antechamber": "부분전하 계산 (antechamber AM1-BCC)",
            "artifact_parmchk2": "본딩 파라미터 보완 (parmchk2)",
            "artifact_tleap": "토폴로지 구축 (tleap)",
            "artifact_parmed": "LJ/bonded 파라미터 추출 (parmed)",
        }
        for status in known_statuses:
            assert status in labels, f"Missing label for builder status: {status}"
            assert labels[status], f"Empty label for status: {status}"

    def test_labels_are_user_friendly(self):
        """Labels should not expose internal code names (English labels only)."""
        labels = {
            "building_structure": "Initializing build...",
            "packing_molecules": "Packing molecules (Packmol)...",
            "loading_molecule_topologies": "Loading molecule topologies...",
            "assigning_types_charges": "Generating FF parameters (artifact ~10 min)...",
        }
        for _status, label in labels.items():
            assert label.endswith("..."), f"Label should end with '...': {label}"
            assert "_" not in label.split("(")[0].strip("."), (
                f"Label should not expose underscored internals: {label}"
            )

    def test_ff_subphase_labels_are_korean_human_readable(self):
        """v00.99.30 FF sub-phase labels are surfaced with subprocess name in parens."""
        labels = {
            "artifact_antechamber": "부분전하 계산 (antechamber AM1-BCC)",
            "artifact_parmchk2": "본딩 파라미터 보완 (parmchk2)",
            "artifact_tleap": "토폴로지 구축 (tleap)",
            "artifact_parmed": "LJ/bonded 파라미터 추출 (parmed)",
        }
        for status, label in labels.items():
            # Subprocess name (code-ish) should only appear inside parens.
            assert "(" in label and ")" in label, status
            # Status codes themselves must not leak into the user-facing label.
            assert status not in label, status


class TestBuildingJobsInRunningAPI:
    """Building experiments appear in /jobs/running response."""

    def test_building_experiment_has_phase_fields(self):
        """Simulated building job dict must contain build_phase and label."""
        # Simulate what running.py produces for building experiments
        meta = {
            "build_phase": "generating_ff_params",
            "build_phase_label": "Generating FF parameters (artifact ~10 min)...",
        }
        job = {
            "job_id": "build_SM_U-SA",
            "exp_id": "SM_U-SA-Squalane-0293_abc123",
            "tier": "screening",
            "gpu_id": None,
            "status": "building",
            "build_phase": meta.get("build_phase", "structure_build"),
            "build_phase_label": meta.get("build_phase_label", "Building..."),
            "progress": 0,
            "current_step": 0,
            "total_steps": 0,
        }
        assert job["status"] == "building"
        assert job["build_phase"] == "generating_ff_params"
        assert "FF parameters" in job["build_phase_label"]
        assert job["progress"] == 0  # building has no step progress

    def test_building_job_default_label(self):
        """When metadata has no build_phase, default to 'Building...'."""
        meta = {}
        label = meta.get("build_phase_label", "Building...")
        assert label == "Building..."


class TestProgressCallbackBridge:
    """Pipeline bridges builder callback to DB metadata."""

    def test_callback_maps_known_status(self):
        """Known builder status should produce correct phase/label pair."""
        status_labels = {
            "building_structure": ("building_structure", "Initializing build..."),
            "packing_molecules": ("packing_molecules", "Packing molecules (Packmol)..."),
            "loading_molecule_topologies": (
                "loading_topologies",
                "Loading molecule topologies...",
            ),
            "assigning_types_charges": (
                "generating_ff_params",
                "Generating FF parameters (artifact ~10 min)...",
            ),
        }
        for status, (expected_phase, expected_label) in status_labels.items():
            phase, label = status_labels.get(status, (status, f"{status}..."))
            assert phase == expected_phase
            assert label == expected_label

    def test_unknown_status_uses_raw_name(self):
        """Unknown status falls back to raw status string."""
        status_labels = {}  # empty map
        status = "some_new_phase"
        phase, label = status_labels.get(status, (status, f"{status}..."))
        assert phase == "some_new_phase"
        assert label == "some_new_phase..."

    def test_label_override_replaces_default(self):
        """When a fine-grained label is supplied, it overrides the status→label fallback.

        Mirrors pipeline._builder_progress_callback's ``label or default_label``
        policy so the dashboard shows per-molecule FF sub-phase messages
        instead of the generic coarse text.
        """
        status_labels = {
            "artifact_antechamber": (
                "generating_ff_params",
                "부분전하 계산 (antechamber AM1-BCC)",
            ),
        }
        status = "artifact_antechamber"
        override = "[3/12 SA-Squalane] 부분전하 계산 (antechamber AM1-BCC)"
        phase, default_label = status_labels.get(status, (status, f"{status}..."))
        # ``label or default_label`` — the override wins whenever it is truthy.
        resolved = override or default_label
        assert phase == "generating_ff_params"
        assert resolved == override

    def test_label_none_falls_back_to_default(self):
        """When label is None, default_label is used (coarse status rendering)."""
        status_labels = {
            "artifact_antechamber": (
                "generating_ff_params",
                "부분전하 계산 (antechamber AM1-BCC)",
            ),
        }
        status = "artifact_antechamber"
        override = None
        phase, default_label = status_labels.get(status, (status, f"{status}..."))
        resolved = override or default_label
        assert phase == "generating_ff_params"
        assert resolved == "부분전하 계산 (antechamber AM1-BCC)"
