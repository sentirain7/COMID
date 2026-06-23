"""Cross-experiment Tg post-processor — density-temperature aggregation → bilinear fit → DB save.

Tg is a cross-experiment metric requiring density data from multiple temperature
experiments on the same material. This post-processor:
1. Gathers (T, ρ) pairs from completed experiments sharing a material_id and tier
2. Delegates to TgCalculator for bilinear breakpoint fitting
3. Persists the result (scalar + metadata) via IMetricRepository
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from common.logging import get_logger
from common.pathing import exp_id_to_material_id, parse_exp_id
from metrics.tg import DensityTemperaturePoint, TgCalculator, TgResult

if TYPE_CHECKING:
    from contracts.interfaces import IExperimentRepository, IMetricRepository

logger = get_logger("orchestrator.tg_post_processor")


class TgPostProcessor:
    """Cross-experiment Tg calculation — density-temperature data collection → fitting → storage.

    Args:
        metric_repo: Metric repository for density look-up and Tg metric save.
        experiment_repo: Experiment repository for material_id-based filtering.
        tg_calculator: Optional pre-configured TgCalculator instance.
        min_temperatures: Minimum distinct temperatures needed to attempt Tg fit.
    """

    def __init__(
        self,
        metric_repo: IMetricRepository,
        experiment_repo: IExperimentRepository,
        tg_calculator: TgCalculator | None = None,
        min_temperatures: int = 4,
    ) -> None:
        self.metric_repo = metric_repo
        self.experiment_repo = experiment_repo
        self.tg_calculator = tg_calculator or TgCalculator(bootstrap_n=200)
        self.min_temperatures = min_temperatures

    def try_compute_tg(
        self,
        exp_id: str,
        material_id: str,
        run_tier: str,
    ) -> TgResult | None:
        """Attempt Tg calculation from accumulated density-temperature data.

        Args:
            exp_id: Anchor experiment ID where the Tg metric will be stored.
            material_id: Material identifier for filtering sibling experiments.
            run_tier: Only aggregate experiments from the same tier.

        Returns:
            TgResult if computation succeeded, None if insufficient data.
        """
        points = self._gather_density_points(material_id, run_tier)

        n_temps = len({p.temperature_k for p in points})
        if n_temps < self.min_temperatures:
            logger.debug(
                f"Tg skipped for {material_id}: {n_temps} temperatures "
                f"< {self.min_temperatures} required"
            )
            return None

        result = self.tg_calculator.compute(points)

        if result.tg_k is not None:
            self._save_tg_metric(exp_id, result)

        return result

    def _gather_density_points(
        self,
        material_id: str,
        run_tier: str,
    ) -> list[DensityTemperaturePoint]:
        """Collect (T, ρ) observations from completed experiments.

        Strategy:
        1. Get experiments by tier via experiment_repo
        2. Filter by material_id (using exp_id_to_material_id or .material_id)
        3. Look up density metric for each matching experiment
        4. Extract temperature from exp_id via parse_exp_id

        Args:
            material_id: Target material identifier.
            run_tier: Tier to filter experiments.

        Returns:
            List of DensityTemperaturePoint.
        """
        points: list[DensityTemperaturePoint] = []

        # Get experiments by tier (handle both mock and real repo method names)
        experiments = self._get_experiments_by_tier(run_tier)

        for exp in experiments:
            exp_id = self._get_exp_id(exp)
            if exp_id is None:
                continue

            # Match material_id
            exp_material_id = self._extract_material_id(exp)
            if exp_material_id != material_id:
                continue

            # Extract temperature from exp_id
            parsed = parse_exp_id(exp_id)
            temperature_k = parsed.get("temperature_k")
            if temperature_k is None:
                continue

            # Look up density metric
            density_value = self._get_density_value(exp_id)
            if density_value is None:
                continue

            points.append(
                DensityTemperaturePoint(
                    temperature_k=temperature_k,
                    density_gcc=density_value,
                    exp_id=exp_id,
                )
            )

        logger.debug(
            f"Gathered {len(points)} density points for {material_id} "
            f"(tier={run_tier}, temperatures={len({p.temperature_k for p in points})})"
        )
        return points

    def _save_tg_metric(
        self,
        exp_id: str,
        result: TgResult,
    ) -> None:
        """Persist Tg as a MetricResult with metadata in array_summary.

        Args:
            exp_id: Anchor experiment ID.
            result: Tg calculation result.
        """
        metric = self.tg_calculator.create_metric(result)
        if metric is None:
            return

        # Attach metadata to array_summary (maps to metadata_json in DB)
        metadata = self.tg_calculator.get_metadata(result)
        metric = metric.model_copy(
            update={
                "exp_id": exp_id,
                "array_summary": metadata,
            }
        )

        self.metric_repo.save(metric)
        logger.info(
            f"Tg metric saved: exp_id={exp_id}, Tg={result.tg_k:.1f} K, R²={result.r_squared:.4f}"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_experiments_by_tier(self, run_tier: str) -> list:
        """Get experiments by tier, handling both mock and real repo interfaces."""
        # Try find_by_tier (mock / AbstractExperimentRepository)
        if hasattr(self.experiment_repo, "find_by_tier"):
            return self.experiment_repo.find_by_tier(run_tier)
        # Try get_by_tier (real ExperimentRepository)
        if hasattr(self.experiment_repo, "get_by_tier"):
            return self.experiment_repo.get_by_tier(run_tier)
        return []

    @staticmethod
    def _get_exp_id(experiment: object) -> str | None:
        """Extract exp_id from experiment object (ExperimentRecord or ExperimentModel)."""
        return getattr(experiment, "exp_id", None)

    @staticmethod
    def _extract_material_id(experiment: object) -> str:
        """Extract material_id from experiment (direct attribute or parsed from exp_id)."""
        # ExperimentRecord has material_id directly
        mid = getattr(experiment, "material_id", None)
        if mid:
            return mid

        # ExperimentModel: reconstruct from exp_id
        exp_id = getattr(experiment, "exp_id", "")
        return exp_id_to_material_id(exp_id)

    def _get_density_value(self, exp_id: str) -> float | None:
        """Look up density metric value for an experiment."""
        # Use get_by_name if available (more efficient)
        if hasattr(self.metric_repo, "get_by_name"):
            metric = self.metric_repo.get_by_name(exp_id, "density", "bulk_ff_gaff2")
            if metric is not None:
                return getattr(metric, "value", None)
            return None

        # Fallback: get_by_exp and filter
        metrics = self.metric_repo.get_by_exp(exp_id)
        for m in metrics:
            if getattr(m, "metric_name", None) == "density":
                return getattr(m, "value", None)
        return None
