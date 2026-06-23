"""
Tests for mock-based pipeline.

These tests verify that the pipeline skeleton works correctly
with mock implementations.
"""

import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, "src")
sys.path.insert(0, "mocks")

from contracts.schemas import (
    ArrayMetricStorage,
    BuildRequest,
    ExperimentStatus,
    FFType,
    MetricResult,
    ProtocolRequest,
    RunTier,
)
from mocks.builder_mock import MockBuilder
from mocks.calculator_mock import MockMetricCalculator
from mocks.protocol_mock import MockProtocolGenerator
from mocks.repository_mock import MockExperimentRepository
from orchestrator.pipeline import Pipeline


class TestPipelineBasic:
    """Basic pipeline tests with mocks."""

    @pytest.fixture
    def pipeline(self):
        """Create pipeline with mock dependencies."""
        return Pipeline(
            builder=MockBuilder(),
            protocol=MockProtocolGenerator(),
            calculator=MockMetricCalculator(),
            repository=MockExperimentRepository(),
        )

    @pytest.fixture
    def build_request(self):
        """Create valid build request."""
        return BuildRequest(
            composition={
                "asphaltene": 20.0,
                "resin": 30.0,
                "aromatic": 35.0,
                "saturate": 15.0,
            },
            target_atoms=100000,
            atom_count_tolerance=0.10,
            initial_density=1.0,
            seed=12345,
        )

    @pytest.fixture
    def protocol_request(self):
        """Create valid protocol request."""
        return ProtocolRequest(
            ff_type=FFType.BULK_FF_GAFF2,
            run_tier=RunTier.SCREENING,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path="",  # Will be set by pipeline
        )

    def test_pipeline_success(self, pipeline, build_request, protocol_request):
        """Test successful pipeline execution."""
        exp_id = pipeline.run(build_request, protocol_request)

        assert exp_id is not None
        assert isinstance(exp_id, str)
        assert len(exp_id) > 0
        # exp_id format: {binder}_{size}_{aging}_{additive}_{temp}K_{hash6}
        # ff_type and tier are embedded in hash only, not visible in the ID.
        assert "298K" in exp_id

        # Check experiment was saved
        record = pipeline.repository.get(exp_id)
        assert record is not None
        assert record.status == ExperimentStatus.COMPLETED
        assert len(record.metrics) > 0

    def test_pipeline_generates_metrics(self, pipeline, build_request, protocol_request):
        """Test that pipeline generates expected metrics."""
        exp_id = pipeline.run(build_request, protocol_request)
        record = pipeline.repository.get(exp_id)

        metric_names = [m.metric_name for m in record.metrics]
        assert "density" in metric_names
        assert "cohesive_energy_density" in metric_names
        assert "rdf_first_peak_r" in metric_names

    def test_pipeline_validates_composition(self, pipeline, protocol_request):
        """Test that pipeline validates composition in wt_percent mode."""
        invalid_request = BuildRequest(
            composition={
                "asphaltene": 50.0,  # Out of bounds
                "resin": 30.0,
                "aromatic": 35.0,
                "saturate": 15.0,
            },
            composition_mode="wt_percent",
            seed=12345,
        )

        with pytest.raises(ValueError) as exc_info:
            pipeline.run(invalid_request, protocol_request)
        assert "Composition validation failed" in str(exc_info.value)

    def test_pipeline_stores_build_result(self, pipeline, build_request, protocol_request):
        """Test that pipeline stores build result."""
        exp_id = pipeline.run(build_request, protocol_request)
        record = pipeline.repository.get(exp_id)

        assert record.build_result is not None
        assert record.build_result.composition_error_l1 < 1.0
        assert record.build_result.actual_atoms > 0

    def test_pipeline_stores_protocol_result(self, pipeline, build_request, protocol_request):
        """Test that pipeline stores protocol result."""
        exp_id = pipeline.run(build_request, protocol_request)
        record = pipeline.repository.get(exp_id)

        assert record.protocol_result is not None
        assert record.protocol_result.protocol_hash is not None
        assert len(record.protocol_result.stabilization_chain) == 3


class TestPipelineFailure:
    """Pipeline failure handling tests."""

    def test_builder_failure(self):
        """Test pipeline handles builder failure."""
        pipeline = Pipeline(
            builder=MockBuilder(fail_on_call=1),
            protocol=MockProtocolGenerator(),
            calculator=MockMetricCalculator(),
            repository=MockExperimentRepository(),
        )

        request = BuildRequest(
            composition={"asphaltene": 20, "resin": 30, "aromatic": 35, "saturate": 15},
            seed=12345,
        )
        protocol = ProtocolRequest(
            ff_type=FFType.BULK_FF_GAFF2,
            run_tier=RunTier.SCREENING,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path="",
        )

        with pytest.raises(RuntimeError):
            pipeline.run(request, protocol)

        # Check failure was recorded
        records = pipeline.repository.find_by_status("failed")
        assert len(records) == 1

    def test_calculator_failure(self):
        """Test pipeline handles calculator failure."""
        pipeline = Pipeline(
            builder=MockBuilder(),
            protocol=MockProtocolGenerator(),
            calculator=MockMetricCalculator(fail_on_call=1),
            repository=MockExperimentRepository(),
        )

        request = BuildRequest(
            composition={"asphaltene": 20, "resin": 30, "aromatic": 35, "saturate": 15},
            seed=12345,
        )
        protocol = ProtocolRequest(
            ff_type=FFType.BULK_FF_GAFF2,
            run_tier=RunTier.SCREENING,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path="",
        )

        with pytest.raises(RuntimeError):
            pipeline.run(request, protocol)


class TestPipelineTiers:
    """Pipeline tier-specific tests."""

    @pytest.fixture
    def pipeline(self):
        return Pipeline(
            builder=MockBuilder(),
            protocol=MockProtocolGenerator(),
            calculator=MockMetricCalculator(),
            repository=MockExperimentRepository(),
        )

    def test_screening_tier(self, pipeline):
        """Test screening tier execution."""
        request = BuildRequest(
            composition={"asphaltene": 20, "resin": 30, "aromatic": 35, "saturate": 15},
            target_atoms=100000,
            seed=12345,
        )
        protocol = ProtocolRequest(
            ff_type=FFType.BULK_FF_GAFF2,
            run_tier=RunTier.SCREENING,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path="",
        )

        exp_id = pipeline.run(request, protocol)
        record = pipeline.repository.get(exp_id)

        assert record.run_tier == RunTier.SCREENING
        assert "298K" in exp_id

    def test_confirm_tier(self, pipeline):
        """Test confirm tier execution."""
        request = BuildRequest(
            composition={"asphaltene": 20, "resin": 30, "aromatic": 35, "saturate": 15},
            target_atoms=200000,
            seed=12345,
        )
        protocol = ProtocolRequest(
            ff_type=FFType.BULK_FF_GAFF2,
            run_tier=RunTier.CONFIRM,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path="",
        )

        exp_id = pipeline.run(request, protocol)
        record = pipeline.repository.get(exp_id)

        assert record.run_tier == RunTier.CONFIRM
        assert "298K" in exp_id


class TestPipelineValidityTags:
    """Pipeline validity domain tag tests."""

    @pytest.fixture
    def pipeline(self):
        return Pipeline(
            builder=MockBuilder(),
            protocol=MockProtocolGenerator(),
            calculator=MockMetricCalculator(),
            repository=MockExperimentRepository(),
        )

    def test_normal_validity_tags(self, pipeline):
        """Test normal composition gets correct tags."""
        request = BuildRequest(
            composition={"asphaltene": 20, "resin": 30, "aromatic": 35, "saturate": 15},
            seed=12345,
        )
        protocol = ProtocolRequest(
            ff_type=FFType.BULK_FF_GAFF2,
            run_tier=RunTier.SCREENING,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path="",
        )

        exp_id = pipeline.run(request, protocol)
        record = pipeline.repository.get(exp_id)

        assert "bulk_gaff2_ok" in [
            t.value if hasattr(t, "value") else t for t in record.validity_domain_tag
        ]

    def test_high_asphaltene_validity_tags(self, pipeline):
        """Test high asphaltene composition gets warning tag."""
        request = BuildRequest(
            composition={"asphaltene": 28, "resin": 25, "aromatic": 32, "saturate": 15},
            seed=12345,
        )
        protocol = ProtocolRequest(
            ff_type=FFType.BULK_FF_GAFF2,
            run_tier=RunTier.SCREENING,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path="",
        )

        exp_id = pipeline.run(request, protocol)
        record = pipeline.repository.get(exp_id)

        tags = [t.value if hasattr(t, "value") else t for t in record.validity_domain_tag]
        assert "high_asphaltene_sensitive" in tags


class TestPipelineMetricSave:
    """Tests for metric persistence behavior."""

    def test_save_metrics_includes_array_metrics(self):
        """_save_metrics_to_db should persist array-only metrics."""
        metric_repo = MagicMock()
        metric_repo.save_batch.return_value = 2

        pipeline = Pipeline(
            builder=MockBuilder(),
            protocol=MockProtocolGenerator(),
            calculator=MockMetricCalculator(),
            repository=MockExperimentRepository(),
            metric_repository=metric_repo,
        )

        metrics = [
            MetricResult(
                metric_name="density",
                value=1.05,
                unit="g/cm3",
                namespace="bulk_ff_gaff2",
            ),
            MetricResult(
                metric_name="rdf_curve",
                value=None,
                unit="[angstrom, dimensionless]",
                namespace="bulk_ff_gaff2",
                array_storage=ArrayMetricStorage(
                    file_path="/tmp/exp_arr_rdf_curve.parquet",
                    file_hash="abc123def4567890",
                    shape=(200, 2),
                    summary={"first_peak_r": 3.5},
                ),
                array_summary={"first_peak_r": 3.5},
            ),
        ]

        result = pipeline._save_metrics_to_db("exp_arr", metrics)

        assert result["status"] == "success"
        assert result["saved"] == 2
        metric_repo.save_batch.assert_called_once()

        saved_metrics = metric_repo.save_batch.call_args[0][0]
        saved_names = [m.metric_name for m in saved_metrics]
        assert "density" in saved_names
        assert "rdf_curve" in saved_names


class TestMockStateTracking:
    """Test that mocks track state correctly."""

    def test_builder_tracks_history(self):
        """Test builder tracks call history."""
        builder = MockBuilder()
        request = BuildRequest(
            composition={"asphaltene": 20, "resin": 30, "aromatic": 35, "saturate": 15},
            seed=12345,
        )

        builder.build(request)
        builder.build(request)

        assert builder.call_count == 2
        assert len(builder.build_history) == 2

    def test_repository_stores_experiments(self):
        """Test repository stores all experiments."""
        repo = MockExperimentRepository()
        pipeline = Pipeline(
            builder=MockBuilder(),
            protocol=MockProtocolGenerator(),
            calculator=MockMetricCalculator(),
            repository=repo,
        )

        request = BuildRequest(
            composition={"asphaltene": 20, "resin": 30, "aromatic": 35, "saturate": 15},
            seed=1,
        )
        protocol = ProtocolRequest(
            ff_type=FFType.BULK_FF_GAFF2,
            run_tier=RunTier.SCREENING,
            temperature_K=298.0,
            pressure_atm=1.0,
            data_file_path="",
        )

        # Run multiple experiments
        exp_id_1 = pipeline.run(request, protocol)
        request.seed = 2
        exp_id_2 = pipeline.run(request, protocol)

        assert repo.count() == 2
        assert repo.get(exp_id_1) is not None
        assert repo.get(exp_id_2) is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
