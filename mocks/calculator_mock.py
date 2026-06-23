"""
Mock metric calculator for testing.

Implements IMetricCalculator interface with mock data.
"""

import sys

sys.path.insert(0, "src")

from contracts.interfaces import IMetricCalculator
from contracts.policies.metrics import DEFAULT_METRICS_REGISTRY
from contracts.schemas import (
    ArrayMetricStorage,
    LAMMPSRunResult,
    MetricResult,
    ThermoData,
)


class MockMetricCalculator(IMetricCalculator):
    """Mock implementation of metric calculator."""

    def __init__(
        self,
        fail_on_call: int = -1,
        density_value: float = 1.02,
        ced_value: float = 350.0,
    ):
        """
        Initialize mock metric calculator.

        Args:
            fail_on_call: Fail on this call number (-1 = never fail)
            density_value: Mock density value to return
            ced_value: Mock CED value to return
        """
        self.call_count = 0
        self.fail_on_call = fail_on_call
        self.density_value = density_value
        self.ced_value = ced_value
        self.calculate_history: list[LAMMPSRunResult] = []
        self.registry = DEFAULT_METRICS_REGISTRY

    def calculate(self, run_result: LAMMPSRunResult) -> list[MetricResult]:
        """
        Mock metric calculation.

        Args:
            run_result: LAMMPS run result

        Returns:
            List of mock metric results
        """
        self.call_count += 1
        self.calculate_history.append(run_result)

        if self.fail_on_call == self.call_count:
            raise RuntimeError("Mock calculator failure")

        # Generate mock experiment ID from log file path
        exp_id = run_result.log_file.split("/")[-2] if "/" in run_result.log_file else "mock_exp"

        metrics = []

        # Density
        metrics.append(
            MetricResult(
                exp_id=exp_id,
                metric_name="density",
                value=self.density_value,
                unit="g/cm3",
                namespace="bulk_ff",
            )
        )

        # CED
        metrics.append(
            MetricResult(
                exp_id=exp_id,
                metric_name="cohesive_energy_density",
                value=self.ced_value,
                unit="MJ/m3",
                namespace="bulk_ff",
            )
        )

        # RDF metrics
        metrics.append(
            MetricResult(
                exp_id=exp_id,
                metric_name="rdf_first_peak_r",
                value=3.5,
                unit="angstrom",
                namespace="bulk_ff",
            )
        )

        metrics.append(
            MetricResult(
                exp_id=exp_id,
                metric_name="rdf_first_peak_g",
                value=2.1,
                unit="dimensionless",
                namespace="bulk_ff",
            )
        )

        # MSD metric
        metrics.append(
            MetricResult(
                exp_id=exp_id,
                metric_name="msd_diffusion_coefficient",
                value=1.5e-5,
                unit="cm2/s",
                namespace="bulk_ff",
            )
        )

        # Array metric (RDF curve) with mock storage info
        metrics.append(
            MetricResult(
                exp_id=exp_id,
                metric_name="rdf_curve",
                unit="[angstrom, dimensionless]",
                namespace="bulk_ff",
                array_storage=ArrayMetricStorage(
                    file_path=f"/mock/data/arrays/{exp_id}/rdf_curve.parquet",
                    file_hash="mock_hash_12345",
                    shape=(500, 2),
                    summary={"min": 0.0, "max": 3.5, "mean": 1.0},
                ),
                array_summary={
                    "first_peak_r": 3.5,
                    "first_peak_g": 2.1,
                    "coordination_number": 12.0,
                },
            )
        )

        return metrics

    def get_calculation_metadata(self) -> dict[str, str | float | None]:
        """Return mock calculation metadata."""
        return {
            "viscosity_method": "rnemd_muller_plathe",
            "viscosity_parse_status": "skipped",
            "viscosity_error": "mock — no f_viscosity column",
        }

    def calculate_density(self, thermo_data: ThermoData) -> MetricResult:
        """Mock density calculation."""
        return MetricResult(
            exp_id="mock_exp",
            metric_name="density",
            value=self.density_value,
            unit="g/cm3",
            namespace="bulk_ff",
        )

    def calculate_ced(
        self, thermo_data: ThermoData, mol_counts: dict[str, int], ff_name: str, ff_version: str
    ) -> MetricResult:
        """Mock CED calculation."""
        return MetricResult(
            exp_id="mock_exp",
            metric_name="cohesive_energy_density",
            value=self.ced_value,
            unit="MJ/m3",
            namespace="bulk_ff",
        )

    def reset(self) -> None:
        """Reset mock state."""
        self.call_count = 0
        self.calculate_history.clear()
