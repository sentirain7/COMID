"""Additive effectiveness analyzer — compare additive vs control groups.

Phase 5.1: Reuses ReplicateAggregator.welch_ttest() for statistical
hypothesis testing of additive effects on MD-computed properties.

# ORPHANED: production 미참조, 제품 의도 확인 전까지 유지
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from common.logging import get_logger
from metrics.statistics import ReplicateAggregator, TTestResult

if TYPE_CHECKING:
    from database.repositories.experiment_repo import ExperimentRepository
    from database.repositories.metric_repo import MetricRepository

logger = get_logger("orchestrator.additive_analyzer")


@dataclass
class AdditiveEffect:
    """Effect of a single additive treatment relative to control.

    Attributes:
        additive_type: Additive type name.
        concentration: Additive weight percent.
        metric_name: Name of the compared metric.
        ttest: Full Welch's t-test result.
        delta_mean: Mean difference (treatment - control).
        delta_ci_lower: Lower bound of delta CI.
        delta_ci_upper: Upper bound of delta CI.
        significant: Whether p < alpha.
    """

    additive_type: str
    concentration: float
    metric_name: str
    ttest: TTestResult
    delta_mean: float
    delta_ci_lower: float
    delta_ci_upper: float
    significant: bool


@dataclass
class BatchJobAnalysisResult:
    """Aggregate analysis result for an additive batch job.

    Attributes:
        batch_job_exp_ids: List of experiment IDs in the batch job.
        effects: All computed additive effects.
        control_count: Number of control experiments.
        treatment_groups: Number of unique treatment groups.
    """

    batch_job_exp_ids: list[str]
    effects: list[AdditiveEffect] = field(default_factory=list)
    control_count: int = 0
    treatment_groups: int = 0


class AdditiveEffectivenessAnalyzer:
    """Analyze additive effectiveness from DOE batch-job results.

    Compares each (additive_type, concentration) group against the control
    group (no additive) using Welch's t-test.

    Args:
        experiment_repo: Repository for experiment record lookup.
        metric_repo: Repository for metric value lookup.
        aggregator: ReplicateAggregator instance (uses default if None).
    """

    def __init__(
        self,
        experiment_repo: ExperimentRepository,
        metric_repo: MetricRepository,
        aggregator: ReplicateAggregator | None = None,
    ) -> None:
        self.experiment_repo = experiment_repo
        self.metric_repo = metric_repo
        self.aggregator = aggregator or ReplicateAggregator()

    def _group_by_treatment(self, exp_ids: list[str]) -> dict[tuple[str | None, float], list[str]]:
        """Group experiment IDs by (additive_type, additive_wt).

        Args:
            exp_ids: Batch-job experiment IDs.

        Returns:
            Dict mapping (additive_type, additive_wt) to list of exp_ids.
        """
        groups: dict[tuple[str | None, float], list[str]] = {}

        for exp_id in exp_ids:
            record = self.experiment_repo.get_by_id(exp_id)
            if record is None:
                logger.warning(f"Experiment not found: {exp_id}")
                continue

            key = (
                getattr(record, "additive_type", None),
                getattr(record, "additive_wt", 0.0) or 0.0,
            )
            groups.setdefault(key, []).append(exp_id)

        return groups

    def _get_metric_values(self, exp_ids: list[str], metric_name: str) -> list[float]:
        """Retrieve scalar metric values for a set of experiments.

        Args:
            exp_ids: Experiment IDs.
            metric_name: Name of the metric to retrieve.

        Returns:
            List of metric values (experiments without the metric are skipped).
        """
        values: list[float] = []
        for exp_id in exp_ids:
            metric = self.metric_repo.get_by_name(exp_id, metric_name)
            if metric is not None and metric.value is not None:
                values.append(metric.value)
        return values

    def _compute_delta(
        self,
        metric_name: str,
        control_vals: list[float],
        treatment_vals: list[float],
    ) -> TTestResult | None:
        """Compute Welch's t-test between treatment and control.

        Args:
            metric_name: Metric name for reporting.
            control_vals: Control group metric values.
            treatment_vals: Treatment group metric values.

        Returns:
            TTestResult or None if insufficient data.
        """
        if len(control_vals) < 2 or len(treatment_vals) < 2:
            logger.warning(
                f"Insufficient replicates for {metric_name}: "
                f"control={len(control_vals)}, treatment={len(treatment_vals)}"
            )
            return None

        return self.aggregator.welch_ttest(
            metric_name=metric_name,
            group_a_values=treatment_vals,
            group_b_values=control_vals,
        )

    def analyze_batch_job(
        self,
        batch_job_exp_ids: list[str],
        metric_names: list[str] | None = None,
    ) -> BatchJobAnalysisResult:
        """Analyze additive effects across a DOE batch job.

        Groups experiments by treatment, compares each treatment to control.

        Args:
            batch_job_exp_ids: All experiment IDs in the batch job.
            metric_names: Metrics to analyze (None = ["density", "cohesive_energy_density"]).

        Returns:
            BatchJobAnalysisResult with all computed effects.
        """
        if metric_names is None:
            metric_names = ["density", "cohesive_energy_density"]

        groups = self._group_by_treatment(batch_job_exp_ids)
        control_key = (None, 0.0)
        control_ids = groups.get(control_key, [])

        result = BatchJobAnalysisResult(
            batch_job_exp_ids=batch_job_exp_ids,
            control_count=len(control_ids),
            treatment_groups=len(groups) - (1 if control_key in groups else 0),
        )

        if not control_ids:
            logger.warning("No control group found in batch job")
            return result

        for (add_type, add_conc), treatment_ids in groups.items():
            if add_type is None and add_conc == 0.0:
                continue  # skip control vs control

            for metric_name in metric_names:
                control_vals = self._get_metric_values(control_ids, metric_name)
                treatment_vals = self._get_metric_values(treatment_ids, metric_name)

                ttest = self._compute_delta(metric_name, control_vals, treatment_vals)
                if ttest is None:
                    continue

                result.effects.append(
                    AdditiveEffect(
                        additive_type=add_type or "unknown",
                        concentration=add_conc,
                        metric_name=metric_name,
                        ttest=ttest,
                        delta_mean=ttest.delta_mean,
                        delta_ci_lower=ttest.delta_ci_lower,
                        delta_ci_upper=ttest.delta_ci_upper,
                        significant=ttest.significant,
                    )
                )

        return result

    def rank_additives(
        self,
        result: BatchJobAnalysisResult,
        target_metric: str,
        maximize: bool = False,
    ) -> list[AdditiveEffect]:
        """Rank additives by effect size on a target metric.

        Args:
            result: Batch-job analysis result.
            target_metric: Metric to rank by.
            maximize: If True, rank by largest positive delta; else smallest.

        Returns:
            Sorted list of AdditiveEffect for the target metric.
        """
        effects = [e for e in result.effects if e.metric_name == target_metric]

        if maximize:
            effects.sort(key=lambda e: e.delta_mean, reverse=True)
        else:
            effects.sort(key=lambda e: e.delta_mean)

        return effects
