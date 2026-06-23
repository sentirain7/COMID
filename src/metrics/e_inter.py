"""
Intermolecular energy (E_inter) calculator.

Extracts pairwise intermolecular energies from thermo data produced by
LAMMPS compute group/group. Columns are expected as `c_gg_{pair_label}`.

Reference: Li & Greenfield (2014) — E_inter decomposition for colloidal
structure stability analysis in asphalt binders.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from common.logging import get_logger
from contracts.policies.metrics import MetricsRegistry
from contracts.schemas import EInterResult, MetricResult
from parsers.stats_utils import (
    apply_time_window,
    compute_mean_std,
    get_default_dt_fs,
    get_default_thermo_interval,
    get_default_window_ps,
)

logger = get_logger("metrics.e_inter")

# Regex for group/group thermo column names
_GG_COLUMN_PATTERN = re.compile(r"^c_gg_(.+)$")


@dataclass
class EInterPairResult:
    """Result for a single group pair."""

    pair_label: str
    energy_kcal_mol: float
    energy_std: float
    n_samples: int


@dataclass
class EInterFullResult:
    """Full E_inter decomposition result."""

    total_e_inter: float
    total_e_inter_std: float
    pair_results: list[EInterPairResult] = field(default_factory=list)
    normalized_per_atom: dict[str, float] = field(default_factory=dict)


class EInterCalculator:
    """Calculator for intermolecular energy decomposition.

    Parses c_gg_* columns from LAMMPS thermo output to extract
    pairwise intermolecular energies between molecular groups.

    Args:
        registry: MetricsRegistry for SSOT name/unit validation.
        window_ps: Time window from end for averaging (ps).
        dt_fs: Timestep in femtoseconds.
        thermo_interval: Steps between thermo outputs.
    """

    def __init__(
        self,
        registry: MetricsRegistry | None = None,
        window_ps: float | None = None,
        dt_fs: float | None = None,
        thermo_interval: int | None = None,
    ) -> None:
        self.registry = registry or MetricsRegistry()
        self.window_ps = window_ps if window_ps is not None else get_default_window_ps()
        self.dt_fs = dt_fs if dt_fs is not None else get_default_dt_fs()
        self.thermo_interval = (
            thermo_interval if thermo_interval is not None else get_default_thermo_interval()
        )

    # ------------------------------------------------------------------
    # Column detection
    # ------------------------------------------------------------------

    @staticmethod
    def find_gg_columns(thermo_data: dict[str, list[float]]) -> dict[str, str]:
        """Find all c_gg_* columns in thermo data.

        Args:
            thermo_data: Parsed thermo data dictionary.

        Returns:
            Dict mapping pair_label -> column_name.
        """
        gg_cols: dict[str, str] = {}
        for col_name in thermo_data:
            match = _GG_COLUMN_PATTERN.match(col_name)
            if match:
                pair_label = match.group(1)
                gg_cols[pair_label] = col_name
        return gg_cols

    # ------------------------------------------------------------------
    # Core computation
    # ------------------------------------------------------------------

    def compute(
        self,
        thermo_data: dict[str, list[float]],
        atom_counts: dict[str, int] | None = None,
    ) -> EInterFullResult | None:
        """Compute E_inter from thermo data containing c_gg_* columns.

        Args:
            thermo_data: Parsed thermo data with c_gg_* columns.
            atom_counts: Optional {group_name: n_atoms} for per-atom normalization.

        Returns:
            EInterFullResult or None if no c_gg_* columns found.
        """
        gg_cols = self.find_gg_columns(thermo_data)
        if not gg_cols:
            return None

        pair_results: list[EInterPairResult] = []
        total_sum = 0.0

        for pair_label, col_name in sorted(gg_cols.items()):
            values = thermo_data[col_name]
            if not values:
                continue

            windowed = apply_time_window(
                values,
                window_ps=self.window_ps,
                dt_fs=self.dt_fs,
                thermo_interval=self.thermo_interval,
            )

            if not windowed:
                continue

            mean, std = compute_mean_std(windowed)
            pair_results.append(
                EInterPairResult(
                    pair_label=pair_label,
                    energy_kcal_mol=mean,
                    energy_std=std,
                    n_samples=len(windowed),
                )
            )
            total_sum += mean

        if not pair_results:
            return None

        # Per-atom normalization
        normalized: dict[str, float] = {}
        if atom_counts:
            for pr in pair_results:
                # Parse pair label (e.g., "saturate_aromatic" -> groups)
                parts = pr.pair_label.split("_", 1)
                total_atoms = 0
                for part in parts:
                    total_atoms += atom_counts.get(part, 0)
                if total_atoms > 0:
                    normalized[pr.pair_label] = pr.energy_kcal_mol / total_atoms

        # Total E_inter std (conservative: root sum of squares)
        total_std = sum(pr.energy_std**2 for pr in pair_results) ** 0.5

        return EInterFullResult(
            total_e_inter=total_sum,
            total_e_inter_std=total_std,
            pair_results=pair_results,
            normalized_per_atom=normalized,
        )

    # ------------------------------------------------------------------
    # Metric creation
    # ------------------------------------------------------------------

    def create_metrics(
        self,
        result: EInterFullResult,
        additive_pair_label: str | None = None,
        namespace: str = "bulk_ff_gaff2",
        layer_index: int | None = None,
        interface_index: int | None = None,
    ) -> list[MetricResult]:
        """Create MetricResult objects from E_inter computation.

        Args:
            result: E_inter computation result.
            additive_pair_label: Optional pair label for additive-binder metric
                                (e.g., "additive_binder").
            namespace: Metric namespace.

        Returns:
            List of MetricResult objects.
        """
        metrics: list[MetricResult] = []

        # Total E_inter
        metrics.append(
            MetricResult(
                metric_name="e_inter_total",
                value=result.total_e_inter,
                unit=self.registry.get_unit("e_inter_total"),
                namespace=namespace,
                uncertainty=result.total_e_inter_std,
                layer_index=layer_index,
                interface_index=interface_index,
            )
        )

        # Additive-binder E_inter (if pair exists)
        if additive_pair_label:
            for pr in result.pair_results:
                if pr.pair_label == additive_pair_label:
                    metrics.append(
                        MetricResult(
                            metric_name="e_inter_additive_binder",
                            value=pr.energy_kcal_mol,
                            unit=self.registry.get_unit("e_inter_additive_binder"),
                            namespace=namespace,
                            uncertainty=pr.energy_std,
                            layer_index=layer_index,
                            interface_index=interface_index,
                        )
                    )
                    break

        return metrics

    def to_schema(self, result: EInterFullResult) -> EInterResult:
        """Convert internal result to Pydantic schema.

        Args:
            result: Internal computation result.

        Returns:
            EInterResult schema object.
        """
        pair_energies = {pr.pair_label: pr.energy_kcal_mol for pr in result.pair_results}
        return EInterResult(
            total_e_inter=result.total_e_inter,
            pair_energies=pair_energies,
            normalized_per_atom=result.normalized_per_atom,
        )
