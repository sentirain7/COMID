"""Tests for features.dashboard.timing.compute_pipeline_elapsed_seconds."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from features.dashboard.timing import compute_pipeline_elapsed_seconds  # noqa: E402


def _iso(dt: datetime) -> str:
    return dt.isoformat()


class TestLegacyRows:
    def test_missing_build_started_at_returns_none(self):
        got = compute_pipeline_elapsed_seconds(
            status="completed",
            metadata_json={},
            lammps_start_time=None,
            wall_time_seconds=42.0,
        )
        assert got is None

    def test_none_metadata_returns_none(self):
        got = compute_pipeline_elapsed_seconds(
            status="running",
            metadata_json=None,
            lammps_start_time=datetime.now(UTC),
            wall_time_seconds=None,
        )
        assert got is None


class TestBuildingStage:
    def test_now_minus_build_started(self):
        now = datetime.now(UTC)
        build_started = now - timedelta(seconds=30)
        got = compute_pipeline_elapsed_seconds(
            status="building",
            metadata_json={"dashboard_build_started_at": _iso(build_started)},
            lammps_start_time=None,
            wall_time_seconds=None,
            now=now,
        )
        assert got == 30.0


class TestReadyFreeze:
    def test_build_done_but_lammps_not_started(self):
        now = datetime.now(UTC)
        build_started = now - timedelta(seconds=120)
        build_completed = now - timedelta(seconds=20)
        got = compute_pipeline_elapsed_seconds(
            status="running",  # status may flip before lammps_start_time fills in
            metadata_json={
                "dashboard_build_started_at": _iso(build_started),
                "dashboard_build_completed_at": _iso(build_completed),
            },
            lammps_start_time=None,
            wall_time_seconds=None,
            now=now,
        )
        # freeze = build_completed - build_started = 100s
        assert got == 100.0


class TestRunningStage:
    def test_running_cumulative(self):
        now = datetime.now(UTC)
        build_started = now - timedelta(seconds=200)
        build_completed = now - timedelta(seconds=150)  # build_duration=50
        lammps_started = now - timedelta(seconds=80)  # now-80 = 80s
        got = compute_pipeline_elapsed_seconds(
            status="running",
            metadata_json={
                "dashboard_build_started_at": _iso(build_started),
                "dashboard_build_completed_at": _iso(build_completed),
            },
            lammps_start_time=lammps_started,
            wall_time_seconds=None,
            now=now,
        )
        assert got == 130.0


class TestCompletedStage:
    def test_completed_uses_wall_time(self):
        now = datetime.now(UTC)
        build_started = now - timedelta(seconds=300)
        build_completed = now - timedelta(seconds=200)  # build=100
        got = compute_pipeline_elapsed_seconds(
            status="completed",
            metadata_json={
                "dashboard_build_started_at": _iso(build_started),
                "dashboard_build_completed_at": _iso(build_completed),
            },
            lammps_start_time=now - timedelta(seconds=199),
            wall_time_seconds=45.5,
            now=now,
        )
        assert got == 145.5

    def test_failed_with_null_wall_time(self):
        now = datetime.now(UTC)
        build_started = now - timedelta(seconds=100)
        build_completed = now - timedelta(seconds=30)
        got = compute_pipeline_elapsed_seconds(
            status="failed",
            metadata_json={
                "dashboard_build_started_at": _iso(build_started),
                "dashboard_build_completed_at": _iso(build_completed),
            },
            lammps_start_time=None,
            wall_time_seconds=None,
            now=now,
        )
        assert got == 70.0


class TestTerminalBeforeBuildComplete:
    """Cancel/fail during build must freeze elapsed, not keep ticking."""

    def test_cancelled_during_build_freezes_at_completed_at(self):
        now = datetime.now(UTC)
        build_started = now - timedelta(seconds=120)
        cancelled_at = now - timedelta(seconds=40)
        got = compute_pipeline_elapsed_seconds(
            status="cancelled",
            metadata_json={"dashboard_build_started_at": _iso(build_started)},
            lammps_start_time=None,
            wall_time_seconds=None,
            completed_at=cancelled_at,
            now=now,
        )
        assert got == 80.0

    def test_failed_during_build_uses_updated_at_fallback(self):
        now = datetime.now(UTC)
        build_started = now - timedelta(seconds=200)
        updated_at = now - timedelta(seconds=60)
        got = compute_pipeline_elapsed_seconds(
            status="failed",
            metadata_json={"dashboard_build_started_at": _iso(build_started)},
            lammps_start_time=None,
            wall_time_seconds=None,
            completed_at=None,
            updated_at=updated_at,
            now=now,
        )
        assert got == 140.0

    def test_terminal_without_any_freeze_caps_at_now(self):
        now = datetime.now(UTC)
        build_started = now - timedelta(seconds=50)
        got = compute_pipeline_elapsed_seconds(
            status="timeout",
            metadata_json={"dashboard_build_started_at": _iso(build_started)},
            lammps_start_time=None,
            wall_time_seconds=None,
            now=now,
        )
        assert got == 50.0


class TestRetryQueuedState:
    """Retry reuses the row; elapsed must be None while queued/pending."""

    def test_queued_returns_none_even_with_old_metadata(self):
        build_started = datetime.now(UTC) - timedelta(seconds=200)
        build_completed = datetime.now(UTC) - timedelta(seconds=100)
        got = compute_pipeline_elapsed_seconds(
            status="queued",
            metadata_json={
                "dashboard_build_started_at": _iso(build_started),
                "dashboard_build_completed_at": _iso(build_completed),
            },
            lammps_start_time=None,
            wall_time_seconds=None,
        )
        assert got is None

    def test_pending_returns_none(self):
        got = compute_pipeline_elapsed_seconds(
            status="pending",
            metadata_json={
                "dashboard_build_started_at": _iso(datetime.now(UTC) - timedelta(seconds=10)),
            },
            lammps_start_time=None,
            wall_time_seconds=None,
        )
        assert got is None

    def test_ready_freezes_at_build_duration(self):
        # ready is an intermediate state AFTER build completes; the ticker
        # must freeze (not hide) so the dashboard shows continuous elapsed.
        now = datetime.now(UTC)
        build_started = now - timedelta(seconds=240)
        build_completed = now - timedelta(seconds=30)  # build_duration=210
        got = compute_pipeline_elapsed_seconds(
            status="ready",
            metadata_json={
                "dashboard_build_started_at": _iso(build_started),
                "dashboard_build_completed_at": _iso(build_completed),
            },
            lammps_start_time=None,
            wall_time_seconds=None,
            now=now,
        )
        assert got == 210.0


class TestTzHandling:
    def test_naive_build_started_treated_as_utc(self):
        now = datetime.now(UTC)
        build_started_naive = now.replace(tzinfo=None) - timedelta(seconds=10)
        got = compute_pipeline_elapsed_seconds(
            status="building",
            metadata_json={"dashboard_build_started_at": build_started_naive.isoformat()},
            lammps_start_time=None,
            wall_time_seconds=None,
            now=now,
        )
        assert got == 10.0

    def test_malformed_iso_returns_none(self):
        got = compute_pipeline_elapsed_seconds(
            status="building",
            metadata_json={"dashboard_build_started_at": "not-a-date"},
            lammps_start_time=None,
            wall_time_seconds=None,
        )
        assert got is None
