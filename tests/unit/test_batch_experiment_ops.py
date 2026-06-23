"""Tests for batch experiment cancel/delete/retry operations."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from contracts.errors import ContractError, ErrorCode
from features.experiments.query import (
    _GPU_IMMEDIATE_RELEASE_STATUSES,
    CANCELABLE_STATUSES,
    DELETABLE_STATUSES,
    _cancel_one,
    _delete_one,
    batch_retry_experiments,
)


def _make_exp(exp_id: str, status: str, gpu_id=None, celery_task_id=None):
    """Create a mock experiment object."""
    exp = MagicMock()
    exp.exp_id = exp_id
    exp.status = status
    exp.gpu_id_allocated = gpu_id
    exp.celery_task_id = celery_task_id
    return exp


class TestStatusPolicies:
    def test_cancelable_statuses(self):
        assert CANCELABLE_STATUSES == {
            "pending",
            "queued",
            "building",
            "ready",
            "running",
            "analyzing",
        }

    def test_deletable_statuses(self):
        assert DELETABLE_STATUSES == {"ready", "completed", "failed", "cancelled", "timeout"}

    def test_gpu_immediate_release_excludes_running(self):
        assert "running" not in _GPU_IMMEDIATE_RELEASE_STATUSES
        assert "analyzing" not in _GPU_IMMEDIATE_RELEASE_STATUSES


class TestCancelOne:
    def _run_cancel(self, exp_id, exp_obj):
        """Run _cancel_one with properly mocked dependencies."""
        session = MagicMock()
        mock_repo = MagicMock()
        mock_repo.get_by_id.return_value = exp_obj

        with (
            patch(
                "database.repositories.experiment_repo.ExperimentRepository",
                return_value=mock_repo,
            ),
            patch("orchestrator.celery_app.celery_app", MagicMock()) as mock_celery,
            patch("orchestrator.gpu_service.get_gpu_service", MagicMock()) as mock_gpu_fn,
            patch("orchestrator.exp_lock_manager.clear_lock_for_experiment", MagicMock()),
        ):
            result = _cancel_one(session, exp_id)
            return result, mock_repo, mock_celery, mock_gpu_fn

    def test_cancel_not_found(self):
        result, *_ = self._run_cancel("nonexistent", None)
        assert result["success"] is False
        assert result["reason"] == "not_found"

    def test_cancel_wrong_status(self):
        exp = _make_exp("exp_001", "completed")
        result, *_ = self._run_cancel("exp_001", exp)
        assert result["success"] is False
        assert "status:completed" in result["reason"]

    def test_cancel_pending_succeeds(self):
        exp = _make_exp("exp_001", "pending", gpu_id=0)
        result, mock_repo, _, mock_gpu_fn = self._run_cancel("exp_001", exp)
        assert result["success"] is True
        mock_repo.update_status.assert_called_once_with(
            "exp_001", "cancelled", error_message="Cancelled by user"
        )
        # GPU should be released for pending status
        mock_gpu_fn.return_value.release.assert_called_once()

    def test_cancel_running_does_not_release_gpu_immediately(self):
        exp = _make_exp("exp_001", "running", gpu_id=0, celery_task_id="task_123")
        result, _, mock_celery, mock_gpu_fn = self._run_cancel("exp_001", exp)
        assert result["success"] is True
        # Celery task revoked
        mock_celery.control.revoke.assert_called_once()
        # GPU NOT released (running -> worker finally handles it)
        mock_gpu_fn.return_value.release.assert_not_called()

    def test_cancel_ready_releases_gpu(self):
        exp = _make_exp("exp_001", "ready", gpu_id=2)
        result, _, _, mock_gpu_fn = self._run_cancel("exp_001", exp)
        assert result["success"] is True
        mock_gpu_fn.return_value.release.assert_called_once()


class TestDeleteOne:
    def _run_delete(self, exp_id, exp_obj):
        """Run _delete_one with properly mocked dependencies."""
        session = MagicMock()
        mock_repo = MagicMock()
        mock_repo.get_by_id.return_value = exp_obj

        with (
            patch(
                "database.repositories.experiment_repo.ExperimentRepository",
                return_value=mock_repo,
            ),
            patch("database.models.MetricModel") as mock_metric,
            patch("database.models.JobDependencyModel"),
            patch("database.models.ProcessInfoModel"),
            patch("orchestrator.celery_app.celery_app", MagicMock()),
            patch("orchestrator.gpu_service.get_gpu_service", MagicMock()) as mock_gpu_fn,
            patch("orchestrator.exp_lock_manager.clear_lock_for_experiment", MagicMock()),
        ):
            result = _delete_one(session, exp_id)
            return result, mock_repo, session, mock_metric, mock_gpu_fn

    def test_delete_not_found(self):
        result, *_ = self._run_delete("nonexistent", None)
        assert result["success"] is False
        assert result["reason"] == "not_found"

    def test_delete_wrong_status(self):
        exp = _make_exp("exp_001", "running")
        result, *_ = self._run_delete("exp_001", exp)
        assert result["success"] is False
        assert "status:running" in result["reason"]

    def test_delete_completed_cleans_metrics(self):
        exp = _make_exp("exp_001", "completed")
        result, mock_repo, session, mock_metric, _ = self._run_delete("exp_001", exp)
        assert result["success"] is True
        mock_repo.delete.assert_called_once_with("exp_001")
        # Verify metrics query was issued
        session.query.assert_any_call(mock_metric)

    def test_delete_ready_releases_gpu(self):
        exp = _make_exp("exp_001", "ready", gpu_id=1)
        result, _, _, _, mock_gpu_fn = self._run_delete("exp_001", exp)
        assert result["success"] is True
        mock_gpu_fn.return_value.release.assert_called_once()

    def test_delete_cleans_layered_sources(self):
        """Verify layered_experiment_sources rows are deleted."""
        exp = _make_exp("exp_001", "completed")
        session = MagicMock()
        mock_repo = MagicMock()
        mock_repo.get_by_id.return_value = exp
        with (
            patch(
                "database.repositories.experiment_repo.ExperimentRepository",
                return_value=mock_repo,
            ),
            patch("database.models.MetricModel"),
            patch("database.models.JobDependencyModel"),
            patch("database.models.ProcessInfoModel"),
            patch("database.models.LayeredExperimentSourceModel") as mock_les,
            patch("orchestrator.exp_lock_manager.clear_lock_for_experiment", MagicMock()),
        ):
            result = _delete_one(session, "exp_001")
        assert result["success"] is True
        session.query.assert_any_call(mock_les)


class TestSingleApiErrorPropagation:
    """Verify single-experiment APIs raise on invalid status."""

    def test_cancel_wrong_status_raises(self):
        """cancel_experiment should raise when status is not cancelable."""
        import asyncio

        exp = _make_exp("exp_001", "completed")

        with (
            patch(
                "features.experiments.query.run_in_session",
                side_effect=lambda fn: fn(MagicMock()),
            ),
            patch(
                "database.repositories.experiment_repo.ExperimentRepository",
            ) as MockRepo,
            patch("orchestrator.celery_app.celery_app", MagicMock()),
            patch("orchestrator.gpu_service.get_gpu_service", MagicMock()),
            patch("orchestrator.exp_lock_manager.clear_lock_for_experiment", MagicMock()),
        ):
            MockRepo.return_value.get_by_id.return_value = exp
            from features.experiments.query import cancel_experiment

            try:
                asyncio.get_event_loop().run_until_complete(cancel_experiment("exp_001"))
                raised = False
            except Exception:
                raised = True
            assert raised, "cancel_experiment should raise for non-cancelable status"

    def test_delete_wrong_status_raises(self):
        """delete_experiment should raise when status is not deletable."""
        import asyncio

        exp = _make_exp("exp_001", "running")

        with (
            patch(
                "features.experiments.query.run_in_session",
                side_effect=lambda fn: fn(MagicMock()),
            ),
            patch(
                "database.repositories.experiment_repo.ExperimentRepository",
            ) as MockRepo,
            patch("orchestrator.celery_app.celery_app", MagicMock()),
            patch("orchestrator.gpu_service.get_gpu_service", MagicMock()),
            patch("orchestrator.exp_lock_manager.clear_lock_for_experiment", MagicMock()),
        ):
            MockRepo.return_value.get_by_id.return_value = exp
            from features.experiments.query import delete_experiment

            try:
                asyncio.get_event_loop().run_until_complete(delete_experiment("exp_001"))
                raised = False
            except Exception:
                raised = True
            assert raised, "delete_experiment should raise for non-deletable status"


class TestBatchRetry:
    """Tests for batch_retry_experiments behavior with partial success."""

    @pytest.mark.asyncio
    async def test_batch_retry_single_success(self):
        """Single successful retry returns succeeded=1."""
        mock_retry_result = {"exp_id": "exp_001", "job_id": "job_001", "status": "queued"}

        with patch(
            "features.experiments.experiment_lifecycle.retry_experiment",
            new_callable=AsyncMock,
            return_value=mock_retry_result,
        ):
            result = await batch_retry_experiments(["exp_001"])

        assert result["total"] == 1
        assert result["succeeded"] == 1
        assert result["skipped"] == 0
        assert result["failed"] == 0
        assert result["details"][0]["success"] is True

    @pytest.mark.asyncio
    async def test_batch_retry_contract_error_skipped(self):
        """ContractError (e.g., no restoration source) results in skipped."""
        with patch(
            "features.experiments.experiment_lifecycle.retry_experiment",
            new_callable=AsyncMock,
            side_effect=ContractError(
                ErrorCode.INVALID_REQUEST,
                "Cannot retry single-molecule experiment: resubmit required",
                {"exp_id": "SM_test_001"},
            ),
        ):
            result = await batch_retry_experiments(["SM_test_001"])

        assert result["total"] == 1
        assert result["succeeded"] == 0
        assert result["skipped"] == 1
        assert result["failed"] == 0
        assert "resubmit required" in result["details"][0]["reason"]

    @pytest.mark.asyncio
    async def test_batch_retry_other_exception_failed(self):
        """Non-ContractError exceptions result in failed."""
        with patch(
            "features.experiments.experiment_lifecycle.retry_experiment",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Database connection lost"),
        ):
            result = await batch_retry_experiments(["exp_001"])

        assert result["total"] == 1
        assert result["succeeded"] == 0
        assert result["skipped"] == 0
        assert result["failed"] == 1
        assert "Database connection lost" in result["details"][0]["reason"]

    @pytest.mark.asyncio
    async def test_batch_retry_mixed_results(self):
        """Mixed batch: success, skipped, failed."""
        call_count = 0

        async def _mock_retry(exp_id):
            nonlocal call_count
            call_count += 1
            if exp_id == "exp_success":
                return {"exp_id": exp_id, "job_id": "job_001", "status": "queued"}
            elif exp_id == "exp_skip":
                raise ContractError(
                    ErrorCode.INVALID_REQUEST,
                    "Cannot retry: resubmit required",
                    {"exp_id": exp_id},
                )
            else:
                raise RuntimeError("Unexpected error")

        with patch(
            "features.experiments.experiment_lifecycle.retry_experiment",
            new_callable=AsyncMock,
            side_effect=_mock_retry,
        ):
            result = await batch_retry_experiments(["exp_success", "exp_skip", "exp_fail"])

        assert result["total"] == 3
        assert result["succeeded"] == 1
        assert result["skipped"] == 1
        assert result["failed"] == 1
