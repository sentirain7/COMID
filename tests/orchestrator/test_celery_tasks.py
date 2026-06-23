"""
Tests for Celery tasks and CeleryJobManager.

These tests use mocking to avoid requiring a running Redis/Celery instance.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from contracts.errors import OrchestrationError
from contracts.policies.budget import JobPriority
from contracts.schemas import BuildRequest, FFType, ProtocolRequest, RunTier
from database.models import ExperimentModel


class TestTaskResult:
    """Tests for TaskResult class."""

    def test_task_result_success(self):
        """Test successful task result."""
        from orchestrator.tasks import TaskResult

        result = TaskResult(
            success=True,
            exp_id="test_exp_001",
            duration_seconds=120.5,
        )

        assert result.success is True
        assert result.exp_id == "test_exp_001"
        assert result.error is None
        assert result.duration_seconds == 120.5

    def test_task_result_failure(self):
        """Test failed task result."""
        from orchestrator.tasks import TaskResult

        result = TaskResult(
            success=False,
            error="Simulation failed",
            duration_seconds=10.0,
        )

        assert result.success is False
        assert result.error == "Simulation failed"
        assert result.exp_id is None

    def test_task_result_to_dict(self):
        """Test TaskResult serialization."""
        from orchestrator.tasks import TaskResult

        result = TaskResult(
            success=True,
            exp_id="test_exp_001",
            metrics={"density": 1.02},
            duration_seconds=100.0,
        )

        d = result.to_dict()

        assert d["success"] is True
        assert d["exp_id"] == "test_exp_001"
        assert d["metrics"]["density"] == 1.02
        assert d["duration_seconds"] == 100.0


class TestCeleryJobManager:
    """Tests for CeleryJobManager."""

    @staticmethod
    def _add_experiment(
        db_session,
        *,
        exp_id: str,
        status: str,
        celery_task_id: str | None = None,
        active_attempt_id: str | None = None,
    ) -> None:
        db_session.add(
            ExperimentModel(
                exp_id=exp_id,
                run_tier="screening",
                ff_type="bulk_ff_gaff2",
                status=status,
                comp_asphaltene_wt=20.0,
                comp_resin_wt=30.0,
                comp_aromatic_wt=35.0,
                comp_saturate_wt=15.0,
                target_atoms=1000,
                temperature_K=298.0,
                pressure_atm=1.0,
                seed=1,
                created_at=datetime.utcnow(),
                celery_task_id=celery_task_id,
                active_attempt_id=active_attempt_id,
            )
        )
        db_session.commit()

    @pytest.fixture
    def mock_celery_app(self):
        """Create mock Celery app."""
        app = MagicMock()
        app.control.inspect.return_value.active.return_value = {}
        app.control.inspect.return_value.reserved.return_value = {}
        app.control.inspect.return_value.scheduled.return_value = {}
        return app

    @pytest.fixture
    def job_manager(self, mock_celery_app):
        """Create CeleryJobManager with mocked Celery."""
        from orchestrator.celery_job_manager import CeleryJobManager

        manager = CeleryJobManager(max_concurrent=4)
        manager._celery_app = mock_celery_app
        return manager

    def test_init(self, job_manager):
        """Test CeleryJobManager initialization."""
        assert job_manager.max_concurrent == 4
        assert job_manager.max_atoms_per_gpu == 500000
        assert len(job_manager._jobs) == 0

    def test_get_queue_for_tier(self, job_manager):
        """Test queue selection for different tiers."""
        assert job_manager._get_queue_for_tier(RunTier.SCREENING) == "simulation.screening"
        assert job_manager._get_queue_for_tier(RunTier.CONFIRM) == "simulation.confirm"
        assert job_manager._get_queue_for_tier(RunTier.VISCOSITY) == "simulation.viscosity"
        assert job_manager._get_queue_for_tier(RunTier.VALIDATION) == "simulation"

    @patch("orchestrator.tasks.run_simulation")
    def test_submit_job(self, mock_task, job_manager):
        """Test job submission."""
        mock_task.apply_async.return_value.id = "celery-task-123"

        # Mock budget policy to allow submission
        mock_policy = MagicMock()
        mock_policy.can_submit_job.return_value = (True, None)
        job_manager.budget_policy = mock_policy

        build_request = BuildRequest(
            composition={"asphaltene": 20, "resin": 30, "aromatic": 35, "saturate": 15},
            target_atoms=100000,
            seed=1,
        )

        protocol_request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            data_file_path="",
        )

        job_id = job_manager.submit(
            build_request=build_request,
            protocol_request=protocol_request,
            material_id="test_binder",
        )

        assert job_id is not None
        assert len(job_id) == 8
        assert job_id in job_manager._jobs

        job = job_manager._jobs[job_id]
        assert job.task_id == "celery-task-123"
        assert job.material_id == "test_binder"
        assert job.queue == "simulation.screening"

    @patch("orchestrator.tasks.run_simulation")
    def test_submit_allows_db_first_stub(self, mock_task, job_manager, db_session):
        """queued + no task/attempt id is a valid SubmissionFacade stub."""
        mock_task.apply_async.return_value.id = "celery-task-stub-ok"
        mock_policy = MagicMock()
        mock_policy.can_submit_job.return_value = (True, None)
        job_manager.budget_policy = mock_policy

        self._add_experiment(db_session, exp_id="exp_stub_ok", status="queued")

        build_request = BuildRequest(
            composition={"asphaltene": 20, "resin": 30, "aromatic": 35, "saturate": 15},
            target_atoms=100000,
            seed=1,
        )
        protocol_request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            data_file_path="",
        )

        job_id = job_manager.submit(
            build_request=build_request,
            protocol_request=protocol_request,
            material_id="test_stub",
            exp_id="exp_stub_ok",
        )
        assert job_id in job_manager._jobs

    @patch("orchestrator.tasks.run_simulation")
    def test_submit_blocks_active_experiment_with_task_or_attempt(
        self, mock_task, job_manager, db_session
    ):
        """Active state with task/attempt id must be blocked as duplicate."""
        mock_task.apply_async.return_value.id = "celery-task-dup"
        mock_policy = MagicMock()
        mock_policy.can_submit_job.return_value = (True, None)
        job_manager.budget_policy = mock_policy

        self._add_experiment(
            db_session,
            exp_id="exp_dup",
            status="queued",
            celery_task_id="existing-task-id",
        )

        build_request = BuildRequest(
            composition={"asphaltene": 20, "resin": 30, "aromatic": 35, "saturate": 15},
            target_atoms=100000,
            seed=1,
        )
        protocol_request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            data_file_path="",
        )

        with pytest.raises(ValueError, match="E8701"):
            job_manager.submit(
                build_request=build_request,
                protocol_request=protocol_request,
                material_id="test_dup",
                exp_id="exp_dup",
            )

    @patch("orchestrator.tasks.run_simulation")
    def test_submit_blocks_inconsistent_active_state_without_task_attempt(
        self, mock_task, job_manager, db_session
    ):
        """building/running/analyzing without task/attempt id must be blocked."""
        mock_task.apply_async.return_value.id = "celery-task-inconsistent"
        mock_policy = MagicMock()
        mock_policy.can_submit_job.return_value = (True, None)
        job_manager.budget_policy = mock_policy

        self._add_experiment(
            db_session,
            exp_id="exp_inconsistent",
            status="building",
            celery_task_id=None,
            active_attempt_id=None,
        )

        build_request = BuildRequest(
            composition={"asphaltene": 20, "resin": 30, "aromatic": 35, "saturate": 15},
            target_atoms=100000,
            seed=1,
        )
        protocol_request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            data_file_path="",
        )

        with pytest.raises(ValueError, match="E8701"):
            job_manager.submit(
                build_request=build_request,
                protocol_request=protocol_request,
                material_id="test_inconsistent",
                exp_id="exp_inconsistent",
            )

    def test_submission_facade_records_submit_error_metadata(self, db_session):
        """SubmissionFacade should persist normalized submit_error metadata on submit failure."""
        from database.repositories.experiment_repo import ExperimentRepository
        from orchestrator.submission_facade import SubmissionFacade

        failing_manager = MagicMock()
        failing_manager.submit.side_effect = ValueError(
            "[E8701] Duplicate execution blocked: exp_id=exp_meta_fail"
        )

        build_request = BuildRequest(
            composition={"asphaltene": 20, "resin": 30, "aromatic": 35, "saturate": 15},
            target_atoms=100000,
            seed=1,
        )
        protocol_request = ProtocolRequest(
            run_tier=RunTier.SCREENING,
            ff_type=FFType.BULK_FF_GAFF2,
            temperature_K=298.0,
            data_file_path="",
        )

        with pytest.raises(OrchestrationError):
            SubmissionFacade.submit_experiment(
                job_manager=failing_manager,
                exp_id="exp_meta_fail",
                run_tier="screening",
                ff_type="bulk_ff_gaff2",
                target_atoms=100000,
                temperature_k=298.0,
                pressure_atm=1.0,
                seed=1,
                comp_asphaltene_wt=20.0,
                comp_resin_wt=30.0,
                comp_aromatic_wt=35.0,
                comp_saturate_wt=15.0,
                build_request=build_request,
                protocol_request=protocol_request,
                material_id="meta_test",
                metadata_json={"source": "unit_test_submit"},
            )

        repo = ExperimentRepository(db_session)
        exp = repo.get_by_id("exp_meta_fail")
        assert exp is not None
        assert str(exp.status) == "failed"
        assert exp.error_code == "E8701"
        meta = dict(exp.metadata_json or {})
        assert meta.get("submission_context", {}).get("submit_flow") == "submission_facade"
        assert meta.get("submission_context", {}).get("submit_source") == "unit_test_submit"
        assert meta.get("submission_context", {}).get("submit_status") == "failed"
        assert meta.get("submit_error", {}).get("reason_code") == "E8701"

    @patch("orchestrator.tasks.run_simulation")
    def test_submit_screening(self, mock_task, job_manager):
        """Test screening simulation submission."""
        mock_task.apply_async.return_value.id = "celery-task-456"

        # Mock budget policy to allow submission
        mock_policy = MagicMock()
        mock_policy.can_submit_job.return_value = (True, None)
        job_manager.budget_policy = mock_policy

        job_id = job_manager.submit_screening(
            composition={"asphaltene": 20, "resin": 30, "aromatic": 35, "saturate": 15},
            temperature_K=298.0,
            target_atoms=100000,
        )

        assert job_id is not None
        job = job_manager._jobs[job_id]
        assert job.protocol_request.run_tier == RunTier.SCREENING
        assert job.priority == JobPriority.HIGH

    @patch("orchestrator.tasks.run_simulation")
    def test_submit_batch(self, mock_task, job_manager):
        """Test batch submission."""
        mock_task.apply_async.return_value.id = "celery-task-batch"

        # Mock budget policy to allow submission
        mock_policy = MagicMock()
        mock_policy.can_submit_job.return_value = (True, None)
        job_manager.budget_policy = mock_policy

        compositions = [
            {"asphaltene": 20, "resin": 30, "aromatic": 35, "saturate": 15},
            {"asphaltene": 25, "resin": 25, "aromatic": 35, "saturate": 15},
            {"asphaltene": 15, "resin": 35, "aromatic": 35, "saturate": 15},
        ]

        job_ids = job_manager.submit_batch(
            compositions=compositions,
            temperature_K=298.0,
            target_atoms=100000,
        )

        assert len(job_ids) == 3
        for job_id in job_ids:
            assert job_id in job_manager._jobs

    def test_get_job(self, job_manager, mock_celery_app):
        """Test getting job with status update."""
        from orchestrator.celery_job_manager import CeleryJob, CeleryJobStatus

        # Create a mock job
        job = CeleryJob(
            job_id="test-job-123",
            task_id="celery-task-789",
            build_request=BuildRequest(
                composition={"asphaltene": 20, "resin": 30, "aromatic": 35, "saturate": 15},
                target_atoms=100000,
                seed=1,
            ),
            protocol_request=ProtocolRequest(
                run_tier=RunTier.SCREENING,
                ff_type=FFType.BULK_FF_GAFF2,
                temperature_K=298.0,
                data_file_path="",
            ),
            material_id="test_binder",
        )
        job_manager._jobs["test-job-123"] = job

        # Mock AsyncResult
        with patch("orchestrator.celery_job_manager.AsyncResult") as mock_result_class:
            mock_result = MagicMock()
            mock_result.status = "SUCCESS"
            mock_result.result = {"exp_id": "result-exp-001", "success": True}
            mock_result_class.return_value = mock_result

            retrieved_job = job_manager.get_job("test-job-123")

            assert retrieved_job is not None
            assert retrieved_job.status == CeleryJobStatus.SUCCESS
            assert retrieved_job.result_exp_id == "result-exp-001"

    def test_cancel_job(self, job_manager, mock_celery_app):
        """Test job cancellation."""
        from orchestrator.celery_job_manager import CeleryJob, CeleryJobStatus

        job = CeleryJob(
            job_id="test-job-cancel",
            task_id="celery-task-cancel",
            build_request=BuildRequest(
                composition={"asphaltene": 20, "resin": 30, "aromatic": 35, "saturate": 15},
                target_atoms=100000,
                seed=1,
            ),
            protocol_request=ProtocolRequest(
                run_tier=RunTier.SCREENING,
                ff_type=FFType.BULK_FF_GAFF2,
                temperature_K=298.0,
                data_file_path="",
            ),
            material_id="test_binder",
            status=CeleryJobStatus.PENDING,
        )
        job_manager._jobs["test-job-cancel"] = job

        result = job_manager.cancel_job("test-job-cancel")

        assert result is True
        assert job.status == CeleryJobStatus.REVOKED
        mock_celery_app.control.revoke.assert_called_once_with("celery-task-cancel", terminate=True)

    def test_get_stats(self, job_manager, mock_celery_app):
        """Test getting queue statistics."""
        from orchestrator.celery_job_manager import CeleryJob, CeleryJobStatus

        # Define statuses and their corresponding Celery states
        job_configs = [
            (CeleryJobStatus.PENDING, "PENDING"),
            (CeleryJobStatus.RUNNING, "STARTED"),
            (CeleryJobStatus.SUCCESS, "SUCCESS"),
            (CeleryJobStatus.FAILURE, "FAILURE"),
        ]

        # Add some jobs with different statuses
        for i, (status, _celery_state) in enumerate(job_configs):
            job = CeleryJob(
                job_id=f"test-job-{i}",
                task_id=f"celery-task-{i}",
                build_request=BuildRequest(
                    composition={"asphaltene": 20, "resin": 30, "aromatic": 35, "saturate": 15},
                    target_atoms=100000,
                    seed=1,
                ),
                protocol_request=ProtocolRequest(
                    run_tier=RunTier.SCREENING,
                    ff_type=FFType.BULK_FF_GAFF2,
                    temperature_K=298.0,
                    data_file_path="",
                ),
                material_id="test_binder",
                status=status,
            )
            job_manager._jobs[f"test-job-{i}"] = job

        # Mock AsyncResult to return appropriate status based on task_id
        with patch("orchestrator.celery_job_manager.AsyncResult") as mock_result_class:

            def create_mock_result(task_id, app=None):
                mock_result = MagicMock()
                # Map task_id to celery state
                task_to_state = {
                    "celery-task-0": "PENDING",
                    "celery-task-1": "STARTED",
                    "celery-task-2": "SUCCESS",
                    "celery-task-3": "FAILURE",
                }
                mock_result.status = task_to_state.get(task_id, "PENDING")
                mock_result.result = (
                    {"exp_id": "test-exp"} if mock_result.status == "SUCCESS" else None
                )
                return mock_result

            mock_result_class.side_effect = create_mock_result

            stats = job_manager.get_stats()

            assert stats.total_pending >= 1
            assert stats.total_running >= 1
            assert stats.total_completed >= 1
            assert stats.total_failed >= 1

    def test_list_jobs(self, job_manager):
        """Test listing jobs."""
        from orchestrator.celery_job_manager import CeleryJob, CeleryJobStatus

        # Add jobs
        for i in range(5):
            job = CeleryJob(
                job_id=f"test-job-{i}",
                task_id=f"celery-task-{i}",
                build_request=BuildRequest(
                    composition={"asphaltene": 20, "resin": 30, "aromatic": 35, "saturate": 15},
                    target_atoms=100000,
                    seed=1,
                ),
                protocol_request=ProtocolRequest(
                    run_tier=RunTier.SCREENING,
                    ff_type=FFType.BULK_FF_GAFF2,
                    temperature_K=298.0,
                    data_file_path="",
                ),
                material_id="test_binder",
                status=CeleryJobStatus.PENDING if i < 3 else CeleryJobStatus.SUCCESS,
            )
            job_manager._jobs[f"test-job-{i}"] = job

        with patch("orchestrator.celery_job_manager.AsyncResult") as mock_result_class:
            mock_result = MagicMock()
            mock_result.status = "PENDING"
            mock_result_class.return_value = mock_result

            all_jobs = job_manager.list_jobs()
            assert len(all_jobs) == 5

            limited_jobs = job_manager.list_jobs(limit=3)
            assert len(limited_jobs) == 3

    def test_clear_completed(self, job_manager):
        """Test clearing completed jobs."""
        from datetime import timedelta

        from orchestrator.celery_job_manager import CeleryJob, CeleryJobStatus

        old_time = datetime.now() - timedelta(hours=48)
        recent_time = datetime.now() - timedelta(hours=1)

        # Add old completed job
        old_job = CeleryJob(
            job_id="old-job",
            task_id="celery-old",
            build_request=BuildRequest(
                composition={"asphaltene": 20, "resin": 30, "aromatic": 35, "saturate": 15},
                target_atoms=100000,
                seed=1,
            ),
            protocol_request=ProtocolRequest(
                run_tier=RunTier.SCREENING,
                ff_type=FFType.BULK_FF_GAFF2,
                temperature_K=298.0,
                data_file_path="",
            ),
            material_id="test_binder",
            status=CeleryJobStatus.SUCCESS,
            completed_at=old_time,
        )
        job_manager._jobs["old-job"] = old_job

        # Add recent completed job
        recent_job = CeleryJob(
            job_id="recent-job",
            task_id="celery-recent",
            build_request=BuildRequest(
                composition={"asphaltene": 20, "resin": 30, "aromatic": 35, "saturate": 15},
                target_atoms=100000,
                seed=1,
            ),
            protocol_request=ProtocolRequest(
                run_tier=RunTier.SCREENING,
                ff_type=FFType.BULK_FF_GAFF2,
                temperature_K=298.0,
                data_file_path="",
            ),
            material_id="test_binder",
            status=CeleryJobStatus.SUCCESS,
            completed_at=recent_time,
        )
        job_manager._jobs["recent-job"] = recent_job

        removed = job_manager.clear_completed(older_than_hours=24)

        assert removed == 1
        assert "old-job" not in job_manager._jobs
        assert "recent-job" in job_manager._jobs


class TestCeleryAppConfig:
    """Tests for Celery application configuration."""

    @patch("orchestrator.celery_app.get_settings")
    def test_celery_app_creation(self, mock_settings):
        """Test Celery app is created with correct settings."""
        from config.settings import CelerySettings

        mock_settings.return_value.celery = CelerySettings()

        from orchestrator.celery_app import create_celery_app

        app = create_celery_app()

        assert app.main == "asphalt_md"
        assert app.conf.task_serializer == "json"
        assert app.conf.result_serializer == "json"

    @patch("orchestrator.celery_app.get_settings")
    def test_queue_configuration(self, mock_settings):
        """Test queue configuration."""
        from config.settings import CelerySettings

        mock_settings.return_value.celery = CelerySettings()

        from orchestrator.celery_app import create_celery_app

        app = create_celery_app()

        queue_names = [q.name for q in app.conf.task_queues]

        assert "default" in queue_names
        assert "simulation" in queue_names
        assert "simulation.screening" in queue_names
        assert "simulation.confirm" in queue_names
        assert "simulation.viscosity" in queue_names
        assert "metrics" in queue_names
        assert "priority" in queue_names


class TestSettings:
    """Tests for settings module."""

    def test_celery_settings_defaults(self):
        """Test CelerySettings default values."""
        from config.settings import CelerySettings

        settings = CelerySettings()

        assert settings.broker_url == "redis://localhost:6379/0"
        assert settings.result_backend == "redis://localhost:6379/1"
        assert settings.task_serializer == "json"
        assert settings.worker_concurrency == 4

    def test_redis_settings_url(self):
        """Test Redis URL generation."""
        from config.settings import RedisSettings

        settings = RedisSettings()
        assert settings.url == "redis://localhost:6379/0"

        settings_with_password = RedisSettings(password="secret")
        assert settings_with_password.url == "redis://:secret@localhost:6379/0"

    def test_get_settings(self):
        """Test settings singleton."""
        from config.settings import get_settings, reset_settings

        reset_settings()
        settings1 = get_settings()
        settings2 = get_settings()

        assert settings1 is settings2

        reset_settings()
        settings3 = get_settings()

        # After reset, should be a new instance (though equal in content)
        assert settings3 is not settings1
