"""
Unit tests for Process Tracking and Recovery.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from contracts.policies.recovery import (
    DEFAULT_RECOVERY_POLICY,
    ProcessRecoveryPolicy,
)
from contracts.schemas import (
    ProcessInfo,
    ProcessState,
    RecoveryAction,
    RecoveryCandidate,
    RecoveryResult,
)


class TestProcessSchemas:
    """Tests for process tracking schemas."""

    def test_process_state_enum(self):
        """Test ProcessState enum values."""
        assert ProcessState.RUNNING.value == "running"
        assert ProcessState.STALE.value == "stale"
        assert ProcessState.ORPHANED.value == "orphaned"
        assert ProcessState.TERMINATED.value == "terminated"
        assert ProcessState.UNKNOWN.value == "unknown"

    def test_recovery_action_enum(self):
        """Test RecoveryAction enum values."""
        assert RecoveryAction.RESUME.value == "resume"
        assert RecoveryAction.RECOVER_RESULTS.value == "recover"
        assert RecoveryAction.RESTART.value == "restart"
        assert RecoveryAction.ABANDON.value == "abandon"
        assert RecoveryAction.IGNORE.value == "ignore"

    def test_process_info_creation(self):
        """Test ProcessInfo schema."""
        info = ProcessInfo(
            exp_id="test_exp_001",
            pid=12345,
            hostname="compute01",
            working_dir="/data/runs/test",
            gpu_id=2,
            started_at=datetime.utcnow(),
            current_step=50000,
            total_steps=100000,
        )

        assert info.exp_id == "test_exp_001"
        assert info.pid == 12345
        assert info.hostname == "compute01"
        assert info.gpu_id == 2

    def test_process_info_progress(self):
        """Test progress calculation."""
        info = ProcessInfo(
            exp_id="test_exp",
            pid=1234,
            hostname="host",
            working_dir="/tmp",
            current_step=50000,
            total_steps=100000,
        )

        assert info.progress_percent == 50.0

    def test_process_info_progress_none(self):
        """Test progress when steps unknown."""
        info = ProcessInfo(
            exp_id="test_exp",
            pid=1234,
            hostname="host",
            working_dir="/tmp",
        )

        assert info.progress_percent is None

    def test_recovery_candidate_creation(self):
        """Test RecoveryCandidate schema."""
        candidate = RecoveryCandidate(
            exp_id="test_exp_001",
            pid=12345,
            hostname="compute01",
            state=ProcessState.STALE,
            db_status="running",
            last_seen=datetime.utcnow() - timedelta(minutes=10),
            progress_percent=75.0,
            gpu_id=2,
            working_dir="/data/runs/test",
            available_actions=[RecoveryAction.RESUME, RecoveryAction.RESTART],
            recommended_action=RecoveryAction.RESUME,
            reason="Stale heartbeat but 75.0% complete - resume recommended",
        )

        assert candidate.state == ProcessState.STALE
        assert candidate.progress_percent == 75.0
        assert RecoveryAction.RESUME in candidate.available_actions

    def test_recovery_result_success(self):
        """Test RecoveryResult for success."""
        result = RecoveryResult(
            success=True,
            action=RecoveryAction.RESUME,
            exp_id="test_exp_001",
            message="Process monitoring resumed successfully",
        )

        assert result.success is True
        assert result.error is None

    def test_recovery_result_failure(self):
        """Test RecoveryResult for failure."""
        result = RecoveryResult(
            success=False,
            action=RecoveryAction.RESTART,
            exp_id="test_exp_001",
            message="Failed to restart",
            error="Process not found",
        )

        assert result.success is False
        assert result.error == "Process not found"


class TestRecoveryPolicy:
    """Tests for ProcessRecoveryPolicy."""

    def test_default_policy_values(self):
        """Test default policy values."""
        policy = DEFAULT_RECOVERY_POLICY

        assert policy.heartbeat_timeout_minutes == 30
        assert policy.auto_recovery_max_retries == 2
        assert policy.min_progress_for_result_recovery == 30.0
        assert policy.stale_threshold_minutes == 5

    def test_should_auto_resume(self):
        """Test auto resume decision."""
        policy = ProcessRecoveryPolicy()

        # High progress stale process should auto resume
        assert policy.should_auto_resume("stale", 75.0) is True

        # Low progress should not auto resume
        assert policy.should_auto_resume("stale", 30.0) is False

        # Non-stale states should not auto resume
        assert policy.should_auto_resume("running", 75.0) is False
        assert policy.should_auto_resume("terminated", 75.0) is False

    def test_should_recover_results(self):
        """Test result recovery decision."""
        policy = ProcessRecoveryPolicy()

        # Terminated with high progress should recover
        assert policy.should_recover_results("terminated", 50.0) is True

        # Low progress should not recover
        assert policy.should_recover_results("terminated", 20.0) is False

        # Non-terminated states should not recover
        assert policy.should_recover_results("running", 50.0) is False

    def test_get_recommended_action_running(self):
        """Test recommendation for running state."""
        policy = ProcessRecoveryPolicy()

        assert policy.get_recommended_action("running", 50.0) == "resume"

    def test_get_recommended_action_stale(self):
        """Test recommendation for stale state."""
        policy = ProcessRecoveryPolicy()

        # High progress: resume
        assert policy.get_recommended_action("stale", 75.0) == "resume"

        # Low progress: restart
        assert policy.get_recommended_action("stale", 25.0) == "restart"

    def test_get_recommended_action_terminated(self):
        """Test recommendation for terminated state."""
        policy = ProcessRecoveryPolicy()

        # High progress: recover results
        assert policy.get_recommended_action("terminated", 50.0) == "recover"

        # Low progress: restart
        assert policy.get_recommended_action("terminated", 20.0) == "restart"

    def test_get_recommended_action_orphaned(self):
        """Test recommendation for orphaned state."""
        policy = ProcessRecoveryPolicy()

        assert policy.get_recommended_action("orphaned", 50.0) == "abandon"

    def test_get_available_actions(self):
        """Test available actions by state."""
        policy = ProcessRecoveryPolicy()

        running_actions = policy.get_available_actions("running")
        assert "resume" in running_actions
        assert "restart" in running_actions
        assert "abandon" in running_actions

        stale_actions = policy.get_available_actions("stale")
        assert "resume" in stale_actions
        assert "restart" in stale_actions

        terminated_actions = policy.get_available_actions("terminated")
        assert "recover" in terminated_actions
        assert "restart" in terminated_actions
        assert "abandon" in terminated_actions

        orphaned_actions = policy.get_available_actions("orphaned")
        assert "abandon" in orphaned_actions
        assert "ignore" in orphaned_actions

    def test_pid_file_pattern(self):
        """Test PID file pattern."""
        policy = ProcessRecoveryPolicy()

        exp_id = "test_exp_123"
        filename = policy.pid_file_pattern.format(exp_id=exp_id)

        assert filename == ".lammps.test_exp_123.pid"


class TestProcessTrackerMocked:
    """Tests for ProcessTracker with mocked dependencies."""

    def test_hostname_detection(self):
        """Test hostname is detected on init."""
        with (
            patch("database.connection.session_scope"),
            patch("socket.gethostname", return_value="test-host"),
            patch("pathlib.Path.mkdir"),
        ):
            from orchestrator.process_tracker import ProcessTracker

            tracker = ProcessTracker()
            assert tracker.hostname == "test-host"

    def test_server_instance_id_generated(self):
        """Test server instance ID is generated."""
        with patch("database.connection.session_scope"), patch("pathlib.Path.mkdir"):
            from orchestrator.process_tracker import ProcessTracker

            tracker = ProcessTracker()

            assert tracker.server_instance_id is not None
            assert len(tracker.server_instance_id) == 8

    def test_detect_process_state_running(self):
        """Test detecting running process."""
        with (
            patch("database.connection.session_scope"),
            patch("pathlib.Path.mkdir"),
            patch("socket.gethostname", return_value="test-host"),
        ):
            import psutil

            from orchestrator.process_tracker import ProcessTracker

            tracker = ProcessTracker()

            with patch.object(psutil, "Process") as mock_process_cls:
                # Mock process that is running
                mock_process = MagicMock()
                mock_process.is_running.return_value = True
                mock_process.cmdline.return_value = ["mpirun", "lmp", "-in", "input.lammps"]
                mock_process_cls.return_value = mock_process

                state = tracker.detect_process_state("exp_1", 1234, "test-host")
                assert state == ProcessState.RUNNING

    def test_detect_process_state_terminated(self):
        """Test detecting terminated process."""
        with (
            patch("database.connection.session_scope"),
            patch("pathlib.Path.mkdir"),
            patch("socket.gethostname", return_value="test-host"),
        ):
            import psutil

            from orchestrator.process_tracker import ProcessTracker

            tracker = ProcessTracker()

            with patch.object(psutil, "Process") as mock_process_cls:
                mock_process_cls.side_effect = psutil.NoSuchProcess(1234)

                state = tracker.detect_process_state("exp_1", 1234, "test-host")
                assert state == ProcessState.TERMINATED

    def test_detect_process_state_remote_host(self):
        """Test detecting process on remote host."""
        with (
            patch("database.connection.session_scope"),
            patch("pathlib.Path.mkdir"),
            patch("socket.gethostname", return_value="local-host"),
        ):
            from orchestrator.process_tracker import ProcessTracker

            tracker = ProcessTracker()
            state = tracker.detect_process_state("exp_1", 1234, "remote-host")
            assert state == ProcessState.UNKNOWN


class TestProcessRecoveryServiceMocked:
    """Tests for ProcessRecoveryService with mocked dependencies."""

    @pytest.fixture
    def mock_tracker(self):
        """Create mock ProcessTracker."""
        tracker = MagicMock()
        tracker.hostname = "test-host"
        tracker.server_instance_id = "abcd1234"
        return tracker

    def test_needs_recovery_dialog_empty(self, mock_tracker):
        """Test needs_recovery_dialog when no candidates."""
        from orchestrator.process_recovery import ProcessRecoveryService

        mock_tracker.detect_orphaned_processes.return_value = []
        service = ProcessRecoveryService(mock_tracker)

        assert service.needs_recovery_dialog() is False

    def test_needs_recovery_dialog_with_candidates(self, mock_tracker):
        """Test needs_recovery_dialog with candidates."""
        from orchestrator.process_recovery import ProcessRecoveryService

        candidate = RecoveryCandidate(
            exp_id="test_exp",
            pid=1234,
            hostname="test-host",
            state=ProcessState.STALE,
            db_status="running",
            working_dir="/tmp",
            available_actions=[RecoveryAction.RESUME],
            recommended_action=RecoveryAction.RESUME,
            reason="Stale process",
        )
        mock_tracker.detect_orphaned_processes.return_value = [candidate]
        service = ProcessRecoveryService(mock_tracker)

        assert service.needs_recovery_dialog() is True

    def test_check_for_recovery_needed(self, mock_tracker):
        """Test checking for recovery needed."""
        from orchestrator.process_recovery import ProcessRecoveryService

        candidates = [
            RecoveryCandidate(
                exp_id="exp_1",
                pid=1234,
                hostname="host",
                state=ProcessState.STALE,
                db_status="running",
                working_dir="/tmp",
                available_actions=[RecoveryAction.RESUME],
                recommended_action=RecoveryAction.RESUME,
                reason="Test",
            ),
            RecoveryCandidate(
                exp_id="exp_2",
                pid=5678,
                hostname="host",
                state=ProcessState.TERMINATED,
                db_status="running",
                working_dir="/tmp",
                available_actions=[RecoveryAction.RESTART],
                recommended_action=RecoveryAction.RESTART,
                reason="Test",
            ),
        ]
        mock_tracker.detect_orphaned_processes.return_value = candidates
        service = ProcessRecoveryService(mock_tracker)

        result = service.check_for_recovery_needed()

        assert len(result) == 2
        assert result[0].exp_id == "exp_1"
        assert result[1].exp_id == "exp_2"


class TestIntegrationScenarios:
    """Integration tests for recovery scenarios."""

    def test_recovery_recommendation_scenarios(self):
        """Test various recovery scenarios produce correct recommendations."""
        policy = ProcessRecoveryPolicy()

        # Scenario 1: Running process with stale heartbeat but high progress
        state = "stale"
        progress = 80.0
        assert policy.get_recommended_action(state, progress) == "resume"

        # Scenario 2: Terminated process with decent progress
        state = "terminated"
        progress = 45.0
        assert policy.get_recommended_action(state, progress) == "recover"

        # Scenario 3: Terminated process with low progress
        state = "terminated"
        progress = 10.0
        assert policy.get_recommended_action(state, progress) == "restart"

        # Scenario 4: Orphaned process
        state = "orphaned"
        progress = 0.0
        assert policy.get_recommended_action(state, progress) == "abandon"

    def test_available_actions_consistency(self):
        """Test available actions are consistent with recommendations."""
        policy = ProcessRecoveryPolicy()

        for state in ["running", "stale", "terminated", "orphaned", "unknown"]:
            actions = policy.get_available_actions(state)
            recommended = policy.get_recommended_action(state, 50.0)

            # Recommended action should be in available actions
            assert recommended in actions, (
                f"Recommended '{recommended}' not in available {actions} for state '{state}'"
            )


class TestProcessTrackerWithDB:
    """DB-backed guard tests for ProcessTracker GPU SSOT behavior."""

    def test_register_process_does_not_override_gpu_allocation(self, db_session):
        from database.models import ExperimentModel
        from orchestrator.process_tracker import ProcessTracker

        exp = ExperimentModel(
            exp_id="exp_tracker_guard",
            celery_task_id="task-tracker-guard",
            run_tier="screening",
            ff_type="bulk_ff_gaff2",
            status="building",
            comp_asphaltene_wt=20.0,
            comp_resin_wt=30.0,
            comp_aromatic_wt=35.0,
            comp_saturate_wt=15.0,
            gpu_id_allocated=1,
            active_attempt_id="task-tracker-guard",
        )
        db_session.add(exp)
        db_session.commit()

        tracker = ProcessTracker()
        with patch.object(tracker, "_write_pid_file", return_value=None):
            with pytest.raises(RuntimeError):
                tracker.register_process(
                    exp_id="exp_tracker_guard",
                    pid=12345,
                    hostname="test-host",
                    working_dir="/tmp",
                    gpu_id=2,  # mismatched GPU should be blocked
                )

        db_session.refresh(exp)
        assert exp.gpu_id_allocated == 1
