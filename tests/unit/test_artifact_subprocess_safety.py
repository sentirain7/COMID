"""Tests for _run_subprocess_with_group_kill process group cleanup."""

import signal
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, "src")

from features.molecules.artifact_service import (
    _kill_process_group,
    _run_subprocess_with_group_kill,
)


class TestKillProcessGroup:
    """Verify _kill_process_group always sends both SIGTERM and SIGKILL."""

    def test_always_sends_sigterm_then_sigkill(self):
        """SIGKILL must always be sent, even if SIGTERM succeeds on parent."""
        mock_proc = MagicMock()
        mock_proc.pid = 100
        mock_proc.wait.return_value = 0

        with (
            patch("features.molecules.artifact_service.os.getpgid", return_value=42),
            patch("features.molecules.artifact_service.os.killpg") as mock_killpg,
            patch("features.molecules.artifact_service.time.sleep"),
        ):
            _kill_process_group(mock_proc, "antechamber", "mol1")

        # Both SIGTERM AND SIGKILL must be called, in order
        calls = mock_killpg.call_args_list
        assert len(calls) == 2
        assert calls[0].args == (42, signal.SIGTERM), "SIGTERM must come first"
        assert calls[1].args == (42, signal.SIGKILL), "SIGKILL must come second"

    def test_sigkill_sent_even_if_sigterm_raises(self):
        """SIGKILL must still fire if SIGTERM hits ProcessLookupError."""
        mock_proc = MagicMock()
        mock_proc.pid = 200
        mock_proc.wait.return_value = 0

        with (
            patch("features.molecules.artifact_service.os.getpgid", return_value=55),
            patch(
                "features.molecules.artifact_service.os.killpg",
                side_effect=[ProcessLookupError, None],  # SIGTERM fails, SIGKILL succeeds
            ) as mock_killpg,
            patch("features.molecules.artifact_service.time.sleep"),
        ):
            _kill_process_group(mock_proc, "test", "mol2")

        assert mock_killpg.call_count == 2

    def test_grace_period_between_signals(self):
        """5-second grace period must exist between SIGTERM and SIGKILL."""
        mock_proc = MagicMock()
        mock_proc.pid = 300
        mock_proc.wait.return_value = 0

        with (
            patch("features.molecules.artifact_service.os.getpgid", return_value=77),
            patch("features.molecules.artifact_service.os.killpg"),
            patch("features.molecules.artifact_service.time.sleep") as mock_sleep,
        ):
            _kill_process_group(mock_proc, "s", "m")

        mock_sleep.assert_called_once_with(5)


class TestRunSubprocessWithGroupKill:
    """Verify _run_subprocess_with_group_kill contract."""

    def test_uses_start_new_session(self):
        """Popen must be called with start_new_session=True."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("out", "err")
        mock_proc.returncode = 0

        with patch(
            "features.molecules.artifact_service.subprocess.Popen",
            return_value=mock_proc,
        ) as mock_popen:
            _run_subprocess_with_group_kill(
                ["echo"], cwd="/tmp", timeout=10, stage_name="s", mol_id="m"
            )

        _, kwargs = mock_popen.call_args
        assert kwargs["start_new_session"] is True

    def test_timeout_raises_runtime_error_with_context(self):
        """Timeout must produce RuntimeError with stage name and mol_id."""
        mock_proc = MagicMock()
        mock_proc.pid = 500
        mock_proc.communicate.side_effect = subprocess.TimeoutExpired(cmd="x", timeout=600)
        mock_proc.wait.return_value = 0

        with (
            patch("features.molecules.artifact_service.subprocess.Popen", return_value=mock_proc),
            patch("features.molecules.artifact_service.os.getpgid", return_value=1),
            patch("features.molecules.artifact_service.os.killpg"),
            patch("features.molecules.artifact_service.time.sleep"),
        ):
            with pytest.raises(RuntimeError, match="antechamber.*600s.*U-SA-Squalane"):
                _run_subprocess_with_group_kill(
                    ["antechamber"],
                    cwd="/tmp",
                    timeout=600,
                    stage_name="antechamber",
                    mol_id="U-SA-Squalane",
                )

    def test_base_exception_also_cleans_group(self):
        """KeyboardInterrupt must also trigger group cleanup."""
        mock_proc = MagicMock()
        mock_proc.pid = 600
        mock_proc.communicate.side_effect = KeyboardInterrupt
        mock_proc.wait.return_value = 0

        with (
            patch("features.molecules.artifact_service.subprocess.Popen", return_value=mock_proc),
            patch("features.molecules.artifact_service.os.getpgid", return_value=88),
            patch("features.molecules.artifact_service.os.killpg") as mock_killpg,
            patch("features.molecules.artifact_service.time.sleep"),
        ):
            with pytest.raises(KeyboardInterrupt):
                _run_subprocess_with_group_kill(
                    ["cmd"], cwd="/tmp", timeout=60, stage_name="s", mol_id="m"
                )

        # Must have attempted cleanup
        mock_killpg.assert_any_call(88, signal.SIGKILL)

    def test_normal_execution_returns_completed_process(self):
        """Normal execution returns CompletedProcess with correct fields."""
        mock_proc = MagicMock()
        mock_proc.pid = 700
        mock_proc.communicate.return_value = ("stdout_data", "stderr_data")
        mock_proc.returncode = 0

        with patch("features.molecules.artifact_service.subprocess.Popen", return_value=mock_proc):
            result = _run_subprocess_with_group_kill(
                ["echo", "hello"], cwd="/tmp", timeout=30, stage_name="echo", mol_id="test"
            )

        assert result.returncode == 0
        assert result.stdout == "stdout_data"
        assert result.stderr == "stderr_data"
