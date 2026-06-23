"""Unit tests for LayerPipelineRunner (Phase 4.3)."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from builder.layer_builder import LayerBuildResult
from orchestrator.layer_pipeline import LayerPipelineRunner


class TestExtractBoundaryZ:
    """Tests for LayerPipelineRunner._extract_boundary_z()."""

    def _make_result(self, layer_info: dict) -> LayerBuildResult:
        """Helper to create LayerBuildResult with given layer_info."""
        return LayerBuildResult(
            success=True,
            data_file_path=Path("/tmp/test.data"),
            total_atoms=1000,
            box_dimensions=(50.0, 50.0, 100.0),
            layer_info=layer_info,
        )

    def test_normal_two_layers(self):
        """Normal case: crystal + binder."""
        result = self._make_result(
            {
                "crystal": (0.0, 25.0),
                "binder": (25.0, 75.0),
            }
        )
        bz = LayerPipelineRunner._extract_boundary_z(result)
        assert bz == [0.0, 25.0, 75.0]

    def test_three_layers(self):
        """Three layers: crystal + water + binder."""
        result = self._make_result(
            {
                "crystal": (0.0, 25.0),
                "water": (25.0, 35.0),
                "binder": (35.0, 85.0),
            }
        )
        bz = LayerPipelineRunner._extract_boundary_z(result)
        assert bz == [0.0, 25.0, 35.0, 85.0]

    def test_mixed_input_ignores_non_numeric(self):
        """Mixed input: ignores non-tuple values."""
        result = self._make_result(
            {
                "crystal": (0.0, 25.0),
                "metadata": "string_value",
                "binder": (25.0, 75.0),
            }
        )
        bz = LayerPipelineRunner._extract_boundary_z(result)
        assert bz == [0.0, 25.0, 75.0]

    def test_empty_layer_info(self):
        """Empty layer_info returns empty list."""
        result = self._make_result({})
        bz = LayerPipelineRunner._extract_boundary_z(result)
        assert bz == []

    def test_single_tuple_returns_empty(self):
        """Single 1-tuple is ignored, returns empty."""
        result = self._make_result({"only": (5.0,)})
        bz = LayerPipelineRunner._extract_boundary_z(result)
        assert bz == []

    def test_deduplication(self):
        """Duplicate z-values are deduplicated."""
        result = self._make_result(
            {
                "crystal": (0.0, 25.0),
                "binder": (25.0, 25.0),  # same z_lo and z_hi
            }
        )
        bz = LayerPipelineRunner._extract_boundary_z(result)
        assert bz == [0.0, 25.0]


class TestCalcOriginalGap:
    """Tests for LayerPipelineRunner._calc_original_gap()."""

    def test_normal_gap(self):
        """Normal gap calculation."""
        gap = LayerPipelineRunner._calc_original_gap([0.0, 25.0, 75.0], 10.0)
        # (75 - 0) - 2 * 10 = 55.0
        assert gap == pytest.approx(55.0)

    def test_empty_boundary_returns_none(self):
        """Empty boundary_z returns None."""
        assert LayerPipelineRunner._calc_original_gap([], 20.0) is None

    def test_single_boundary_returns_none(self):
        """Single boundary point returns None."""
        assert LayerPipelineRunner._calc_original_gap([10.0], 5.0) is None

    def test_grip_larger_than_gap_returns_none(self):
        """Grip thickness larger than total span returns None."""
        gap = LayerPipelineRunner._calc_original_gap([0.0, 30.0], 20.0)
        # (30 - 0) - 2*20 = -10 → None
        assert gap is None


class TestLayerPipelineRunnerIntegration:
    """Integration tests for LayerPipelineRunner."""

    def test_run_mock_mode(self):
        """Test pipeline execution in mock mode (no runner)."""
        from contracts.schemas import LayerSpec, ProtocolRequest, ProtocolResult

        # Mock dependencies
        mock_builder = MagicMock()
        mock_builder.build.return_value = LayerBuildResult(
            success=True,
            data_file_path=Path("/tmp/test.data"),
            total_atoms=5000,
            box_dimensions=(50.0, 50.0, 100.0),
            layer_info={"crystal": (0.0, 25.0), "binder": (25.0, 75.0)},
            interface_area_nm2=25.0,
        )

        mock_protocol = MagicMock()
        mock_protocol.generate.return_value = ProtocolResult(
            input_script_path="/tmp/test.in",
            expected_outputs=["log.lammps"],
            protocol_hash="abc123",
            estimated_steps=10000,
            stabilization_chain=["minimize", "nvt", "npt"],
        )

        mock_calculator = MagicMock()
        mock_calculator.calculate.return_value = []

        mock_repo = MagicMock()

        runner = LayerPipelineRunner(
            layer_builder=mock_builder,
            protocol=mock_protocol,
            calculator=mock_calculator,
            repository=mock_repo,
            runner=None,  # Mock mode
        )

        layer_spec = LayerSpec()
        protocol_request = ProtocolRequest(data_file_path="/tmp/placeholder.data")

        exp_id = runner.run(
            layer_spec=layer_spec,
            protocol_request=protocol_request,
            material_id="test_material",
            exp_id="test_exp_001",
        )

        assert exp_id == "test_exp_001"
        mock_builder.build.assert_called_once_with(layer_spec)
        mock_protocol.generate.assert_called_once()
        mock_calculator.calculate.assert_called_once()
        mock_repo.save.assert_called_once()

    def test_build_failure_raises(self):
        """Test pipeline raises on build failure."""
        from contracts.schemas import LayerSpec, ProtocolRequest

        mock_builder = MagicMock()
        mock_builder.build.return_value = LayerBuildResult(
            success=False,
            error_message="Crystal build failed",
        )

        runner = LayerPipelineRunner(
            layer_builder=mock_builder,
            protocol=MagicMock(),
            calculator=MagicMock(),
            repository=MagicMock(),
        )

        with pytest.raises(RuntimeError, match="Layer build failed"):
            runner.run(
                layer_spec=LayerSpec(),
                protocol_request=ProtocolRequest(data_file_path="/tmp/test.data"),
            )

    def test_study_type_set_to_layer_bulkff(self):
        """Verify ProtocolRequest.study_type is set to LAYER_BULKFF."""
        from contracts.schemas import LayerSpec, ProtocolRequest, ProtocolResult, StudyType

        mock_builder = MagicMock()
        mock_builder.build.return_value = LayerBuildResult(
            success=True,
            data_file_path=Path("/tmp/test.data"),
            total_atoms=5000,
            box_dimensions=(50.0, 50.0, 100.0),
            layer_info={"crystal": (0.0, 25.0), "binder": (25.0, 75.0)},
        )

        mock_protocol = MagicMock()
        mock_protocol.generate.return_value = ProtocolResult(
            input_script_path="/tmp/test.in",
            expected_outputs=[],
            protocol_hash="abc",
            estimated_steps=10000,
            stabilization_chain=["minimize", "nvt", "npt"],
        )

        mock_calculator = MagicMock()
        mock_calculator.calculate.return_value = []

        runner = LayerPipelineRunner(
            layer_builder=mock_builder,
            protocol=mock_protocol,
            calculator=mock_calculator,
            repository=MagicMock(),
        )

        protocol_request = ProtocolRequest(data_file_path="/tmp/test.data")
        runner.run(
            layer_spec=LayerSpec(),
            protocol_request=protocol_request,
            exp_id="test_exp",
        )

        # Verify study_type was set
        assert protocol_request.study_type == StudyType.LAYER_BULKFF

    def test_exp_id_forwarded_to_lammps_runner(self):
        """LayerPipelineRunner should forward exp_id to ILAMMPSRunner.run()."""
        from contracts.schemas import (
            LAMMPSRunResult,
            LayerSpec,
            ProtocolRequest,
            ProtocolResult,
        )

        mock_builder = MagicMock()
        mock_builder.build.return_value = LayerBuildResult(
            success=True,
            data_file_path=Path("/tmp/test.data"),
            total_atoms=5000,
            box_dimensions=(50.0, 50.0, 100.0),
            layer_info={"crystal": (0.0, 25.0), "binder": (25.0, 75.0)},
        )

        mock_protocol = MagicMock()
        mock_protocol.generate.return_value = ProtocolResult(
            input_script_path="/tmp/test.in",
            expected_outputs=[],
            protocol_hash="abc",
            estimated_steps=10000,
            stabilization_chain=["minimize", "nvt", "npt"],
        )

        mock_runner = MagicMock()
        mock_runner.run.return_value = LAMMPSRunResult(
            success=True,
            log_file="/tmp/log.lammps",
            wall_time_seconds=1.0,
            exit_code=0,
        )

        runner = LayerPipelineRunner(
            layer_builder=mock_builder,
            protocol=mock_protocol,
            calculator=MagicMock(calculate=MagicMock(return_value=[])),
            repository=MagicMock(),
            runner=mock_runner,
        )

        runner.run(
            layer_spec=LayerSpec(),
            protocol_request=ProtocolRequest(data_file_path="/tmp/test.data"),
            exp_id="layer_exp_123",
        )

        mock_runner.run.assert_called_once()
        _args, kwargs = mock_runner.run.call_args
        assert kwargs["exp_id"] == "layer_exp_123"
