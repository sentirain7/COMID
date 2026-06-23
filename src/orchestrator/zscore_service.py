"""Z-score calculation and tier promotion check service.

Calculates z-scores for density/CED metrics and delegates tier
promotion decisions to DEFAULT_TIER_POLICY.should_upgrade_tier().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from common.logging import get_logger
from contracts.policies.tier import DEFAULT_TIER_POLICY

if TYPE_CHECKING:
    from database.repositories.experiment_repo import ExperimentRepository
    from database.repositories.metric_repo import MetricRepository

logger = get_logger("orchestrator.zscore_service")

ZSCORE_METRICS = ["density", "cohesive_energy_density"]


@dataclass
class ZScoreResult:
    """Result of z-score calculation for an experiment."""

    exp_id: str
    zscores: dict[str, float] = field(default_factory=dict)
    population_counts: dict[str, int] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)


class ZScoreService:
    """Calculate z-scores and check tier promotion conditions.

    Args:
        metric_repo: MetricRepository instance
        experiment_repo: ExperimentRepository instance
        min_population: Minimum experiments needed for z-score calculation
    """

    def __init__(
        self,
        metric_repo: MetricRepository,
        experiment_repo: ExperimentRepository,
        min_population: int = 5,
    ) -> None:
        self.metric_repo = metric_repo
        self.experiment_repo = experiment_repo
        self.min_population = min_population

    def calculate_zscores(
        self,
        exp_id: str,
        run_tier: str,
        temperature_k: float,
    ) -> ZScoreResult:
        """Calculate density/CED z-scores for an experiment.

        Args:
            exp_id: Experiment ID to score
            run_tier: Current run tier (for population filtering)
            temperature_k: Temperature (for population filtering)

        Returns:
            ZScoreResult with z-scores per metric
        """
        result = ZScoreResult(exp_id=exp_id)

        for metric_name in ZSCORE_METRICS:
            metric = self.metric_repo.get_by_name(exp_id, metric_name)
            if metric is None:
                result.skipped.append(metric_name)
                logger.debug(f"Metric {metric_name} not found for {exp_id}")
                continue

            stats = self.metric_repo.get_statistics(
                metric_name=metric_name,
                run_tier=run_tier,
                temperature_k=temperature_k,
            )

            count = stats["count"]
            result.population_counts[metric_name] = count

            if count < self.min_population:
                result.skipped.append(metric_name)
                logger.debug(
                    f"Population too small for {metric_name}: {count} < {self.min_population}"
                )
                continue

            stddev = stats["stddev"]
            if stddev == 0 or stddev is None:
                result.zscores[metric_name] = 0.0
                continue

            zscore = (metric.value - stats["avg"]) / stddev
            result.zscores[metric_name] = zscore
            logger.debug(
                f"Z-score for {exp_id}/{metric_name}: {zscore:.3f} "
                f"(value={metric.value:.4f}, avg={stats['avg']:.4f}, "
                f"stddev={stddev:.4f}, n={count})"
            )

        return result

    def check_tier_promotion(
        self,
        exp_id: str,
        current_tier: str,
        temperature_k: float,
        flags: dict[str, bool] | None = None,
    ) -> str | None:
        """Check if experiment should be promoted to a higher tier.

        Calculates z-scores then delegates to DEFAULT_TIER_POLICY.should_upgrade_tier().

        Args:
            exp_id: Experiment ID
            current_tier: Current tier name
            temperature_k: Temperature in Kelvin
            flags: Optional boolean flags (candidate_for_recommendation, etc.)

        Returns:
            Next tier name if promotion warranted, None otherwise
        """
        zscore_result = self.calculate_zscores(exp_id, current_tier, temperature_k)

        metrics: dict[str, float] = {}
        if "density" in zscore_result.zscores:
            metrics["density_zscore"] = zscore_result.zscores["density"]
        if "cohesive_energy_density" in zscore_result.zscores:
            metrics["ced_zscore"] = zscore_result.zscores["cohesive_energy_density"]

        flags = flags or {}

        next_tier = DEFAULT_TIER_POLICY.should_upgrade_tier(
            current_tier=current_tier,
            metrics=metrics,
            flags=flags,
        )

        if next_tier:
            logger.info(
                f"Tier promotion recommended: {exp_id} "
                f"{current_tier} -> {next_tier} "
                f"(metrics={metrics}, flags={flags})"
            )

        return next_tier
