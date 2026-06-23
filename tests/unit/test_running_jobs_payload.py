"""Non-invasive tests for features.jobs.running._build_running_payload."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from features.jobs.running import _build_running_payload  # noqa: E402


def _stage_info() -> dict:
    return {
        "current_stage": "npt",
        "stage_type": "npt",
        "stage_index": 2,
        "total_stages": 3,
        "stage_step": 500,
        "stage_total_steps": 1000,
        "stage_percent": 50.0,
    }


class TestLegacyFieldsUnchanged:
    """Existing keys and values must survive the additive new fields."""

    def test_legacy_fields_stable_without_new_kwargs(self):
        payload = _build_running_payload(
            job_id="j1",
            exp_id="exp1",
            tier="screening",
            gpu_id=0,
            current_step=500,
            total_steps=1000,
            temperature=300.0,
            pressure=1.0,
            density=1.02,
            energy=-12345.0,
            thermo_data=[],
            elapsed_seconds=60.0,
            stage_info=_stage_info(),
        )

        for key in (
            "job_id",
            "exp_id",
            "tier",
            "gpu_id",
            "current_step",
            "total_steps",
            "progress",
            "temperature",
            "pressure",
            "density",
            "energy",
            "elapsed",
            "eta",
            "thermo_data",
            "current_stage",
            "stage_type",
            "stage_index",
            "total_stages",
            "stage_progress",
            "stage_step",
            "stage_total_steps",
            "stage_percent",
            "telemetry_age_sec",
            "telemetry_stale",
            "source",
        ):
            assert key in payload, f"Missing legacy key: {key}"
        assert payload["progress"] == 50.0
        assert payload["stage_percent"] == 50.0
        assert payload["pipeline_elapsed_seconds"] is None
        assert payload["build_progress_percent"] is None


class TestNewFieldsPresent:
    def test_kwargs_propagate(self):
        payload = _build_running_payload(
            job_id="j1",
            exp_id="exp1",
            tier="screening",
            gpu_id=0,
            current_step=500,
            total_steps=1000,
            temperature=300.0,
            pressure=1.0,
            density=1.02,
            energy=-12345.0,
            thermo_data=[],
            elapsed_seconds=60.0,
            stage_info=_stage_info(),
            pipeline_elapsed_seconds=234.5,
            build_progress_percent=72.5,
        )
        assert payload["pipeline_elapsed_seconds"] == 234.5
        assert payload["build_progress_percent"] == 72.5

    def test_elapsed_preserved_independent_of_new_field(self):
        """Ensure the legacy elapsed string does not change when new kwargs are set."""
        a = _build_running_payload(
            job_id="j1",
            exp_id="exp1",
            tier="screening",
            gpu_id=0,
            current_step=500,
            total_steps=1000,
            temperature=None,
            pressure=None,
            density=None,
            energy=None,
            thermo_data=[],
            elapsed_seconds=60.0,
            stage_info=_stage_info(),
        )
        b = _build_running_payload(
            job_id="j1",
            exp_id="exp1",
            tier="screening",
            gpu_id=0,
            current_step=500,
            total_steps=1000,
            temperature=None,
            pressure=None,
            density=None,
            energy=None,
            thermo_data=[],
            elapsed_seconds=60.0,
            stage_info=_stage_info(),
            pipeline_elapsed_seconds=999.9,
            build_progress_percent=30.0,
        )
        assert a["elapsed"] == b["elapsed"]
        assert a["eta"] == b["eta"]
        assert a["progress"] == b["progress"]
