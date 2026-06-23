"""Tensile test metric calculator (Phase 4.3).

Calculates mechanical metrics from stress-strain data:
- interfacial_tensile_strength (peak stress)
- tensile_strength (compat alias)
- elastic_modulus
- ductility (peak strain)
- toughness
- work_of_separation

W_sep formula (review #4): W_sep [mJ/m2] = toughness [MJ/m3] * gap [A] * 0.1
Derivation: 1 MJ/m3 * 1 A = 1e6 J/m3 * 1e-10 m = 1e-4 J/m2 = 0.1 mJ/m2
No area division — stress is already F/A normalized.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from common.logging import get_logger
from contracts.schemas import MetricResult
from parsers.stress_strain_parser import StressStrainData, StressStrainParser

if TYPE_CHECKING:
    from metrics.array_storage import ArrayStorage

logger = get_logger("metrics.tensile_metrics")


class TensileMetricCalculator:
    """Calculate tensile metrics from stress-strain data."""

    def __init__(self) -> None:
        self.parser = StressStrainParser()

    def calculate_from_file(
        self,
        ss_file: Path,
        original_gap_angstrom: float | None = None,
        exp_id: str | None = None,
        layer_index: int | None = None,
        interface_index: int | None = None,
    ) -> list[MetricResult]:
        """Calculate all tensile metrics from a stress-strain file.

        Args:
            ss_file: Path to stress_strain_*.dat file.
            original_gap_angstrom: Original gap between grips for W_sep.
            exp_id: Experiment ID for metric tagging.

        Returns:
            List of MetricResult (scalar metrics).
        """
        data = self.parser.parse(ss_file)
        return self._build_metrics(
            data,
            original_gap_angstrom,
            exp_id,
            layer_index=layer_index,
            interface_index=interface_index,
        )

    def _build_metrics(
        self,
        data: StressStrainData,
        original_gap_angstrom: float | None = None,
        exp_id: str | None = None,
        layer_index: int | None = None,
        interface_index: int | None = None,
    ) -> list[MetricResult]:
        """Build MetricResult list from parsed data."""
        metrics: list[MetricResult] = []

        # 1. interfacial_tensile_strength (peak stress)
        metrics.append(
            MetricResult(
                exp_id=exp_id,
                metric_name="interfacial_tensile_strength",
                value=data.peak_stress_MPa,
                unit="MPa",
                namespace="mechanical",
                layer_index=layer_index,
                interface_index=interface_index,
            )
        )

        # 2. tensile_strength (compat alias)
        metrics.append(
            MetricResult(
                exp_id=exp_id,
                metric_name="tensile_strength",
                value=data.peak_stress_MPa,
                unit="MPa",
                namespace="mechanical",
                layer_index=layer_index,
                interface_index=interface_index,
            )
        )

        # 3. elastic_modulus
        e_mod = data.elastic_modulus_GPa
        if e_mod is not None:
            metrics.append(
                MetricResult(
                    exp_id=exp_id,
                    metric_name="elastic_modulus",
                    value=e_mod,
                    unit="GPa",
                    namespace="mechanical",
                    layer_index=layer_index,
                    interface_index=interface_index,
                )
            )

        # 4. ductility (peak strain)
        metrics.append(
            MetricResult(
                exp_id=exp_id,
                metric_name="ductility",
                value=data.peak_strain,
                unit="dimensionless",
                namespace="mechanical",
                layer_index=layer_index,
                interface_index=interface_index,
            )
        )

        # 5. toughness
        metrics.append(
            MetricResult(
                exp_id=exp_id,
                metric_name="toughness",
                value=data.toughness_MJ_m3,
                unit="MJ/m3",
                namespace="mechanical",
                layer_index=layer_index,
                interface_index=interface_index,
            )
        )

        # 6. work_of_separation (review #4: no area division)
        # W_sep [mJ/m2] = toughness [MJ/m3] * gap [A] * 0.1
        if original_gap_angstrom is not None and original_gap_angstrom > 0:
            w_sep = data.toughness_MJ_m3 * original_gap_angstrom * 0.1
            metrics.append(
                MetricResult(
                    exp_id=exp_id,
                    metric_name="work_of_separation",
                    value=w_sep,
                    unit="mJ/m2",
                    namespace="mechanical",
                    layer_index=layer_index,
                    interface_index=interface_index,
                )
            )

        return metrics

    def create_array_metric(
        self,
        data: StressStrainData,
        exp_id: str,
        array_storage: ArrayStorage,
    ) -> MetricResult | None:
        """Store stress-strain curve as Parquet via ArrayStorage.store_metric().

        Args:
            data: Parsed stress-strain data.
            exp_id: Experiment ID.
            array_storage: ArrayStorage instance.

        Returns:
            MetricResult with array_storage info, or None on failure.
        """
        try:
            arr_info = array_storage.store_metric(
                metric_name="stress_strain_curve",
                experiment_id=exp_id,
                data={
                    "strain": data.strain.tolist(),
                    "stress_MPa": data.stress_MPa.tolist(),
                },
                summary={
                    "peak_stress_MPa": data.peak_stress_MPa,
                    "peak_strain": data.peak_strain,
                    "n_points": float(data.n_points),
                },
            )
            return MetricResult(
                exp_id=exp_id,
                metric_name="stress_strain_curve",
                value=None,
                unit="[dimensionless, MPa]",
                namespace="mechanical",
                array_storage=arr_info,
            )
        except Exception as e:
            logger.warning(f"Stress-strain array storage failed: {e}")
            return None
