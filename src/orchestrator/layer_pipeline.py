"""Layer-specific pipeline runner for interface/tensile studies.

Separate from bulk Pipeline (src/orchestrator/pipeline.py) because:
1. LayerBuilder uses LayerSpec -> LayerBuildResult (not BuildRequest -> BuildResult)
2. BuildResult.actual_density(gt=0) etc bulk-only required fields are meaningless for layer
3. Contract separation ensures type safety for each path
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from common.logging import get_logger
from contracts.interfaces import (
    ILAMMPSRunner,
    IMetricCalculator,
    IProtocolGenerator,
)
from contracts.policies.forcefield import get_ff_display_label, get_ff_version
from contracts.schemas import (
    ExperimentRecord,
    ExperimentStatus,
    LAMMPSRunResult,
    LayerSpec,
    MetricResult,
    ProtocolRequest,
    ProtocolResult,
    StudyType,
)

if TYPE_CHECKING:
    from builder.layer_builder import LayerBuilder, LayerBuildResult
    from contracts.interfaces import IExperimentRepository, IMetricRepository

logger = get_logger("orchestrator.layer_pipeline")


class LayerPipelineRunner:
    """Layer study pipeline.

    Execution order:
    1. LayerBuilder.build(layer_spec)               -> LayerBuildResult
    2. ProtocolRequest metadata setup                (study_type=LAYER_BULKFF)
    3. IProtocolGenerator.generate(protocol_request) -> ProtocolResult
    4. ILAMMPSRunner.run(protocol_result)            -> LAMMPSRunResult
    5. IMetricCalculator.calculate(lammps_result)    -> list[MetricResult]
    6. Repository save (ExperimentRecord + metrics)
    """

    def __init__(
        self,
        layer_builder: LayerBuilder,
        protocol: IProtocolGenerator,
        calculator: IMetricCalculator,
        repository: IExperimentRepository,
        runner: ILAMMPSRunner | None = None,
        metric_repository: IMetricRepository | None = None,
    ) -> None:
        self.layer_builder = layer_builder
        self.protocol = protocol
        self.calculator = calculator
        self.repository = repository
        self.runner = runner
        self.metric_repository = metric_repository

    def run(
        self,
        layer_spec: LayerSpec,
        protocol_request: ProtocolRequest,
        material_id: str = "default_layer",
        exp_id: str | None = None,
    ) -> str:
        """Execute layer pipeline.

        Args:
            layer_spec: Layer system specification.
            protocol_request: Protocol config.
            material_id: Material identifier.
            exp_id: Optional pre-generated experiment ID.

        Returns:
            Experiment ID.
        """
        if exp_id is None:
            exp_id = f"layer_{material_id}"

        # Step 1: Build layer system
        logger.info(f"Building layer system: {layer_spec.layer_type}")
        build_result = self.layer_builder.build(layer_spec)
        if not build_result.success:
            raise RuntimeError(f"Layer build failed: {build_result.error_message}")

        # Step 2: Prepare ProtocolRequest with layer metadata
        protocol_request.data_file_path = str(build_result.data_file_path)
        protocol_request.study_type = StudyType.LAYER_BULKFF

        # Extract boundary_z from build result
        boundary_z = self._extract_boundary_z(build_result)
        layer_spec.layer_boundary_z = boundary_z
        protocol_request.layer_spec = layer_spec

        # Step 3: Generate protocol (IProtocolGenerator interface — shared)
        logger.info("Generating protocol")
        protocol_result: ProtocolResult = self.protocol.generate(protocol_request)

        # Step 4: Run LAMMPS (ILAMMPSRunner interface — shared)
        logger.info("Running LAMMPS")
        lammps_result = self._run_lammps(protocol_result, exp_id=exp_id)
        if not lammps_result.success:
            raise RuntimeError(f"LAMMPS failed: {lammps_result.error_message}")

        # Attach runtime provenance needed by shared metric calculation.
        lammps_result.exp_id = exp_id
        lammps_result.study_type = StudyType.LAYER_BULKFF.value
        lammps_result.temperature_K = protocol_request.temperature_K
        lammps_result.force_field = get_ff_display_label(protocol_request.ff_type.value)
        lammps_result.ff_version = get_ff_version(protocol_request.ff_type.value)
        lammps_result.group_energy_spec = protocol_request.group_energy_spec
        lammps_result.e_intra_method = getattr(protocol_request, "e_intra_method", None)
        if build_result.interface_area_nm2 is not None:
            lammps_result.interface_area_nm2 = build_result.interface_area_nm2
        elif build_result.box_dimensions:
            lx, ly, _lz = build_result.box_dimensions
            lammps_result.interface_area_nm2 = float(lx) * float(ly) / 100.0

        # Attach tensile metadata to LAMMPSRunResult
        if protocol_request.tensile_spec and protocol_request.tensile_spec.enabled:
            lammps_result.tensile_spec = protocol_request.tensile_spec
            lammps_result.original_gap_angstrom = self._calc_original_gap(
                boundary_z, protocol_request.tensile_spec.grip_thickness_angstrom
            )

        # Step 5: Calculate metrics (IMetricCalculator — shared)
        logger.info("Calculating metrics")
        metrics: list[MetricResult] = self.calculator.calculate(lammps_result)

        # Step 6: Save results
        record = ExperimentRecord(
            exp_id=exp_id,
            material_id=material_id,
            study_type=StudyType.LAYER_BULKFF,
            status=ExperimentStatus.COMPLETED,
            lammps_result=lammps_result,
            metrics=metrics,
            metadata={
                "layer_type": layer_spec.layer_type.value,
                "interface_area_nm2": build_result.interface_area_nm2,
                "boundary_z": boundary_z,
            },
        )
        self.repository.save(record)

        if self.metric_repository and metrics:
            self.metric_repository.save_batch(metrics)

        logger.info(f"Layer pipeline complete: {exp_id}, {len(metrics)} metrics")
        return exp_id

    def _run_lammps(
        self,
        protocol_result: ProtocolResult,
        exp_id: str | None = None,
    ) -> LAMMPSRunResult:
        """Run LAMMPS or return mock result."""
        if self.runner is not None:
            return self.runner.run(protocol_result, exp_id=exp_id)
        logger.warning("Running in mock mode — no ILAMMPSRunner provided")
        return LAMMPSRunResult(
            success=True,
            log_file="mock.log",
            wall_time_seconds=0.0,
            exit_code=0,
            exp_id=exp_id,
        )

    @staticmethod
    def _extract_boundary_z(build_result: LayerBuildResult) -> list[float]:
        """Extract sorted boundary_z from layer_info (z_min, z_max) pairs.

        layer_info structure: {"crystal": (0.0, 25.0), "binder": (25.0, 75.0)}
        -> boundary_z: [0.0, 25.0, 75.0] (deduplicated, sorted)

        Defense:
        - Only collects numeric 2-tuples (ignores non-numeric values)
        - Returns empty list if fewer than 2 valid boundary points
        """
        all_z: set[float] = set()
        for value in build_result.layer_info.values():
            if (
                isinstance(value, tuple | list)
                and len(value) == 2
                and all(isinstance(v, int | float) for v in value)
            ):
                all_z.add(float(value[0]))
                all_z.add(float(value[1]))
        result = sorted(all_z)
        if len(result) < 2:
            logger.warning(f"Insufficient boundary points ({len(result)}), returning empty")
            return []
        return result

    @staticmethod
    def _calc_original_gap(boundary_z: list[float], grip_thickness: float) -> float | None:
        """Calculate gap excluding grips from z-boundaries.

        Returns None if boundary_z has fewer than 2 points.
        """
        if len(boundary_z) < 2:
            return None
        z_lo, z_hi = boundary_z[0], boundary_z[-1]
        gap = (z_hi - z_lo) - 2 * grip_thickness
        return max(0.0, gap) if gap > 0 else None
