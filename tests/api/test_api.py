"""Tests for API endpoints."""

import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

sys.path.insert(0, "src")

# Check if fastapi/httpx are available for testing
try:
    from fastapi.testclient import TestClient

    from api.application import app

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


@pytest.mark.skipif(not HAS_FASTAPI, reason="FastAPI not installed")
class TestAPIEndpoints:
    """Test API endpoints."""

    @pytest.fixture
    def client(self):
        @asynccontextmanager
        async def _lifespan(_app):
            yield

        app.router.lifespan_context = _lifespan
        return TestClient(app)

    @pytest.fixture
    def mock_celery_task(self):
        """Mock Celery task to avoid Redis connection."""
        mock_result = MagicMock()
        mock_result.id = "mock-task-id-12345"
        with patch("orchestrator.tasks.run_simulation.apply_async", return_value=mock_result):
            yield mock_result

    def test_root(self, client):
        """Test root endpoint."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "version" in data

    def test_health(self, client):
        """Test health endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in {"ready", "limited", "down"}
        assert data["severity"] in {"ok", "warn", "critical"}

    def test_submit_experiment(self, client, mock_celery_task):
        """Test experiment submission."""
        response = client.post(
            "/experiments",
            json={
                "composition": {
                    "asphaltene_wt": 0.2,
                    "resin_wt": 0.3,
                    "aromatic_wt": 0.35,
                    "saturate_wt": 0.15,
                },
                "target_atoms": 100000,
                "temperature_K": 298.0,
                "run_tier": "screening",
                "ff_type": "bulk_ff_gaff2",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "exp_id" in data
        assert "job_id" in data
        assert data["status"] == "queued"

    def test_submit_experiment_invalid_composition(self, client):
        """Test experiment submission with invalid composition."""
        response = client.post(
            "/experiments",
            json={
                "composition": {
                    "asphaltene_wt": 0.5,
                    "resin_wt": 0.3,
                    "aromatic_wt": 0.35,
                    "saturate_wt": 0.15,
                },  # Sum > 1
                "target_atoms": 100000,
                "temperature_K": 298.0,
                "run_tier": "screening",
                "ff_type": "bulk_ff_gaff2",
            },
        )
        assert response.status_code == 400

    def test_submit_experiment_invalid_tier(self, client):
        """Test experiment submission with invalid tier."""
        response = client.post(
            "/experiments",
            json={
                "composition": {
                    "asphaltene_wt": 0.2,
                    "resin_wt": 0.3,
                    "aromatic_wt": 0.35,
                    "saturate_wt": 0.15,
                },
                "target_atoms": 100000,
                "temperature_K": 298.0,
                "run_tier": "invalid_tier",
                "ff_type": "bulk_ff_gaff2",
            },
        )
        assert response.status_code == 400

    def test_get_experiment_not_found(self, client):
        """Test getting non-existent experiment returns 404."""
        response = client.get("/experiments/exp_12345")
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()

    def test_list_experiments(self, client):
        """Test listing experiments."""
        response = client.get("/experiments")
        assert response.status_code == 200
        data = response.json()
        assert "experiments" in data

    @pytest.mark.asyncio
    async def test_preview_molecule_composition(self):
        """Preview molecule-based composition."""
        from api.schemas import MoleculeCompositionPreviewRequest
        from features.experiments.composition_builder import MoleculeCompositionBuildResult
        from features.experiments.submission import preview_molecule_composition

        mock_db = SimpleNamespace(get_temperature_code=lambda _config, _temp: "0293")

        with (
            patch("api.deps.get_molecule_db", return_value=mock_db),
            patch("api.deps.get_aging_config", return_value={}),
            patch("features.experiments.submission.validate_molecule_request_config"),
            patch("features.experiments.submission.build_molecule_composition") as mock_build,
        ):
            mock_build.return_value = MoleculeCompositionBuildResult(
                mol_composition={},
                sara_composition={
                    "saturate": 0.2,
                    "aromatic": 0.3,
                    "resin": 0.3,
                    "asphaltene": 0.2,
                },
                estimated_atoms=1200,
                total_molecules=20,
            )

            result = await preview_molecule_composition(
                MoleculeCompositionPreviewRequest(
                    binder_type="custom",
                    structure_size="X1",
                    aging_state="non_aging",
                    temperature_K=298,
                    molecule_counts=[{"mol_id": "SA-Squalane", "count": 10}],
                    additives=[{"mol_id": "SiO2", "count": 2}],
                )
            )

            assert result.total_molecules == 20
            assert result.estimated_atoms == 1200
            assert result.sara_fractions["saturate"] == 0.2

    def test_get_job(self, client):
        """Test getting job status."""
        response = client.get("/jobs/job_12345")
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == "job_12345"

    def test_queue_stats(self, client):
        """Test queue statistics."""
        response = client.get("/queue/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_pending" in data
        assert "total_running" in data

    def test_cancel_job(self, client):
        """Test job cancellation."""
        response = client.delete("/jobs/job_12345")
        assert response.status_code == 200
        data = response.json()
        assert data["cancelled"] is True

    def test_retry_job(self, client):
        """Test job retry."""
        response = client.post("/jobs/job_12345/retry")
        assert response.status_code == 200
        data = response.json()
        assert data["requeued"] is True

    def test_get_metrics(self, client):
        """Test getting metrics."""
        response = client.get("/metrics/exp_12345")
        assert response.status_code == 200
        data = response.json()
        assert "metrics" in data

    def test_get_metric_values_rejects_array_metric(self, client):
        """Array metrics should not be served via scalar values endpoint."""
        response = client.get("/metrics/values/rdf_curve")
        assert response.status_code == 400
        assert "array metric" in response.json()["detail"].lower()

    def test_get_metric_statistics_rejects_array_metric(self, client):
        """Array metrics should not be served via scalar statistics endpoint."""
        response = client.get("/metrics/statistics/msd_curve")
        assert response.status_code == 400
        assert "array metric" in response.json()["detail"].lower()

    def test_list_molecules(self, client):
        """Test listing molecules."""
        response = client.get("/molecules")
        assert response.status_code == 200
        data = response.json()
        assert "molecules" in data

    def test_get_e_intra(self, client):
        """Test getting E_intra value."""
        response = client.get("/e_intra/mol_001")
        assert response.status_code == 200
        data = response.json()
        assert data["mol_id"] == "mol_001"

    def test_validate_batch_job_binder_cell(self):
        """Batch job Binder Cell validate should run dry-run without job manager."""
        from api.main import validate_batch_job_binder_cell
        from api.schemas import BatchJobBinderCellRequest

        mock_session = MagicMock()
        mock_session_cm = MagicMock()
        mock_session_cm.__enter__.return_value = mock_session
        mock_session_cm.__exit__.return_value = None
        mock_repo = MagicMock()

        mock_result = SimpleNamespace(
            batch_job_id="batch_job_test",
            total=1,
            new=1,
            duplicates=0,
            submitted=0,
            errors=0,
            jobs=[
                SimpleNamespace(
                    exp_id="exp_001",
                    binder_type="AAA1",
                    structure_size="X1",
                    temperature_k=293.0,
                    aging_state="non_aging",
                    tier="screening",
                    status="pending",
                    error=None,
                )
            ],
        )
        mock_runner = MagicMock()
        mock_runner.validate.return_value = mock_result

        with (
            patch("database.connection.session_scope", return_value=mock_session_cm),
            patch(
                "database.repositories.experiment_repo.ExperimentRepository", return_value=mock_repo
            ),
            patch(
                "orchestrator.batch_job_binder_cell.BatchJobBinderCellRunner",
                return_value=mock_runner,
            ) as runner_cls,
        ):
            response = validate_batch_job_binder_cell(
                BatchJobBinderCellRequest(binder_types=["AAA1"])
            )

        runner_cls.assert_called_once_with(experiment_repo=mock_repo)
        mock_runner.validate.assert_called_once()
        data = response.model_dump()
        assert data["batch_job_id"] == "batch_job_test"
        assert data["total"] == 1
        assert data["submitted"] == 0

    def test_create_batch_job_binder_cell_injects_job_manager(self):
        """Batch job Binder Cell submit should inject and use job manager."""
        from api.main import create_batch_job_binder_cell
        from api.schemas import BatchJobBinderCellRequest

        mock_session = MagicMock()
        mock_session_cm = MagicMock()
        mock_session_cm.__enter__.return_value = mock_session
        mock_session_cm.__exit__.return_value = None
        mock_repo = MagicMock()
        mock_job_manager = MagicMock()

        mock_result = SimpleNamespace(
            batch_job_id="batch_job_submit",
            total=1,
            new=1,
            duplicates=0,
            submitted=1,
            errors=0,
            jobs=[
                SimpleNamespace(
                    exp_id="exp_001",
                    binder_type="AAA1",
                    structure_size="X1",
                    temperature_k=293.0,
                    aging_state="non_aging",
                    tier="screening",
                    status="submitted",
                    error=None,
                )
            ],
        )
        mock_runner = MagicMock()
        mock_runner.submit.return_value = mock_result

        with (
            patch("api.deps.get_job_manager", return_value=mock_job_manager),
            patch("database.connection.session_scope", return_value=mock_session_cm),
            patch(
                "database.repositories.experiment_repo.ExperimentRepository", return_value=mock_repo
            ),
            patch(
                "orchestrator.batch_job_binder_cell.BatchJobBinderCellRunner",
                return_value=mock_runner,
            ) as runner_cls,
        ):
            response = create_batch_job_binder_cell(
                BatchJobBinderCellRequest(binder_types=["AAA1"])
            )

        runner_cls.assert_called_once_with(
            experiment_repo=mock_repo,
            job_manager=mock_job_manager,
        )
        mock_runner.submit.assert_called_once()
        data = response.model_dump()
        assert data["batch_job_id"] == "batch_job_submit"
        assert data["submitted"] == 1

    def test_create_batch_job_binder_cell_invalid_tier(self):
        """Batch job Binder Cell request rejects invalid tier via schema validation."""
        from api.schemas import BatchJobBinderCellRequest

        with pytest.raises(ValidationError):
            BatchJobBinderCellRequest(binder_types=["AAA1"], tier="invalid_tier")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
