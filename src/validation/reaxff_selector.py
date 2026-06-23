"""
ReaxFF Selector for Identifying Outliers.

Selects candidates for ReaxFF validation based on z-scores and stability flags.
"""

import statistics
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from common.logging import get_logger

logger = get_logger("validation.reaxff_selector")


class SelectionReason(Enum):
    """Reason for selecting a candidate for validation."""

    HIGH_DENSITY_ZSCORE = "density_zscore_high"
    LOW_DENSITY_ZSCORE = "density_zscore_low"
    HIGH_CED_ZSCORE = "ced_zscore_high"
    LOW_CED_ZSCORE = "ced_zscore_low"
    ENERGY_DRIFT = "energy_drift"
    PRESSURE_BLOWUP = "pressure_blowup"
    PACKING_OVERLAP = "packing_overlap_suspected"
    MANUAL = "manual_selection"


@dataclass
class SelectionCriteria:
    """
    Criteria for selecting candidates for ReaxFF validation.

    Based on INTEGRATED_PLAN.md section 1-4.
    """

    # Z-score thresholds
    density_zscore_threshold: float = 2.0
    ced_zscore_threshold: float = 2.0

    # Stability flags that trigger selection
    stability_flags: list[str] = field(
        default_factory=lambda: [
            "energy_drift",
            "pressure_blowup",
            "packing_overlap_suspected",
        ]
    )

    # Selection limits
    max_selections_per_batch: int = 5
    minimum_bulk_ff_runs: int = 50  # Need enough data for z-score

    # Trigger mode: "OR" means any condition triggers, "AND" means all
    trigger_mode: str = "OR"


@dataclass
class OutlierCandidate:
    """A candidate selected for ReaxFF validation."""

    exp_id: str
    run_tier: str
    composition: dict[str, float]

    # Metrics that triggered selection
    density: float | None = None
    density_zscore: float | None = None
    ced: float | None = None
    ced_zscore: float | None = None
    stability_flag: str | None = None

    # Selection metadata
    selection_reasons: list[SelectionReason] = field(default_factory=list)
    priority_score: float = 0.0  # Higher = more important to validate
    selected_at: datetime = field(default_factory=datetime.now)


@dataclass
class SelectionResult:
    """Result of outlier selection."""

    candidates: list[OutlierCandidate]
    total_evaluated: int
    total_selected: int
    selection_cap_reached: bool
    statistics: dict[str, Any]


class ReaxFFSelector:
    """
    Selects experiments for ReaxFF validation based on outlier detection.

    Uses z-scores and stability flags to identify candidates that
    may benefit from reactive force field validation.
    """

    def __init__(
        self,
        criteria: SelectionCriteria | None = None,
    ):
        """
        Initialize selector.

        Args:
            criteria: Selection criteria
        """
        self.criteria = criteria or SelectionCriteria()
        self._statistics: dict[str, Any] = {}

    def select_candidates(
        self,
        experiments: list[dict[str, Any]],
    ) -> SelectionResult:
        """
        Select candidates for ReaxFF validation from experiment results.

        Args:
            experiments: List of experiment dictionaries with metrics

        Returns:
            SelectionResult with candidates and statistics
        """
        if len(experiments) < self.criteria.minimum_bulk_ff_runs:
            logger.warning(
                f"Not enough bulk FF runs ({len(experiments)} < "
                f"{self.criteria.minimum_bulk_ff_runs}) for statistical analysis"
            )
            return SelectionResult(
                candidates=[],
                total_evaluated=len(experiments),
                total_selected=0,
                selection_cap_reached=False,
                statistics={"error": "insufficient_data"},
            )

        # Calculate statistics
        self._calculate_statistics(experiments)

        # Evaluate each experiment
        candidates = []
        for exp in experiments:
            candidate = self._evaluate_experiment(exp)
            if candidate:
                candidates.append(candidate)

        # Sort by priority score
        candidates.sort(key=lambda c: c.priority_score, reverse=True)

        # Apply selection cap
        selection_cap_reached = len(candidates) > self.criteria.max_selections_per_batch
        candidates = candidates[: self.criteria.max_selections_per_batch]

        logger.info(f"Selected {len(candidates)} candidates from {len(experiments)} experiments")

        return SelectionResult(
            candidates=candidates,
            total_evaluated=len(experiments),
            total_selected=len(candidates),
            selection_cap_reached=selection_cap_reached,
            statistics=self._statistics.copy(),
        )

    def _calculate_statistics(self, experiments: list[dict[str, Any]]) -> None:
        """Calculate population statistics for z-score computation."""
        densities = []
        ceds = []

        for exp in experiments:
            metrics = exp.get("metrics", {})
            if isinstance(metrics, dict):
                if "density" in metrics and metrics["density"] is not None:
                    densities.append(metrics["density"])
                if "ced" in metrics and metrics["ced"] is not None:
                    ceds.append(metrics["ced"])

        self._statistics = {
            "n_samples": len(experiments),
            "density": self._compute_stats(densities) if densities else None,
            "ced": self._compute_stats(ceds) if ceds else None,
        }

    def _compute_stats(self, values: list[float]) -> dict[str, float]:
        """Compute mean and std for a list of values."""
        if len(values) < 2:
            return {"mean": values[0] if values else 0, "std": 0}

        return {
            "mean": statistics.mean(values),
            "std": statistics.stdev(values),
            "min": min(values),
            "max": max(values),
            "n": len(values),
        }

    def _evaluate_experiment(
        self,
        exp: dict[str, Any],
    ) -> OutlierCandidate | None:
        """
        Evaluate a single experiment for selection.

        Args:
            exp: Experiment dictionary

        Returns:
            OutlierCandidate if selected, None otherwise
        """
        metrics = exp.get("metrics", {})
        if not isinstance(metrics, dict):
            return None

        selection_reasons = []
        priority_score = 0.0

        # Get values
        density = metrics.get("density")
        ced = metrics.get("ced")
        stability_flag = exp.get("stability_flag")

        # Calculate z-scores
        density_zscore = None
        ced_zscore = None

        if density is not None and self._statistics.get("density"):
            stats = self._statistics["density"]
            if stats["std"] > 0:
                density_zscore = (density - stats["mean"]) / stats["std"]

                if abs(density_zscore) > self.criteria.density_zscore_threshold:
                    if density_zscore > 0:
                        selection_reasons.append(SelectionReason.HIGH_DENSITY_ZSCORE)
                    else:
                        selection_reasons.append(SelectionReason.LOW_DENSITY_ZSCORE)
                    priority_score += abs(density_zscore)

        if ced is not None and self._statistics.get("ced"):
            stats = self._statistics["ced"]
            if stats["std"] > 0:
                ced_zscore = (ced - stats["mean"]) / stats["std"]

                if abs(ced_zscore) > self.criteria.ced_zscore_threshold:
                    if ced_zscore > 0:
                        selection_reasons.append(SelectionReason.HIGH_CED_ZSCORE)
                    else:
                        selection_reasons.append(SelectionReason.LOW_CED_ZSCORE)
                    priority_score += abs(ced_zscore)

        # Check stability flags
        if stability_flag and stability_flag in self.criteria.stability_flags:
            if stability_flag == "energy_drift":
                selection_reasons.append(SelectionReason.ENERGY_DRIFT)
                priority_score += 3.0
            elif stability_flag == "pressure_blowup":
                selection_reasons.append(SelectionReason.PRESSURE_BLOWUP)
                priority_score += 2.5
            elif stability_flag == "packing_overlap_suspected":
                selection_reasons.append(SelectionReason.PACKING_OVERLAP)
                priority_score += 2.0

        # Apply trigger mode
        if self.criteria.trigger_mode == "OR":
            is_selected = len(selection_reasons) > 0
        else:  # AND
            is_selected = len(selection_reasons) >= 2

        if not is_selected:
            return None

        return OutlierCandidate(
            exp_id=exp.get("exp_id", "unknown"),
            run_tier=exp.get("run_tier", "unknown"),
            composition=exp.get("composition", {}),
            density=density,
            density_zscore=density_zscore,
            ced=ced,
            ced_zscore=ced_zscore,
            stability_flag=stability_flag,
            selection_reasons=selection_reasons,
            priority_score=priority_score,
        )

    def get_statistics(self) -> dict[str, Any]:
        """Get computed statistics."""
        return self._statistics.copy()

    def select_manual(
        self,
        exp_ids: list[str],
        experiments: list[dict[str, Any]],
    ) -> list[OutlierCandidate]:
        """
        Manually select experiments for validation.

        Args:
            exp_ids: List of experiment IDs to select
            experiments: All experiments

        Returns:
            List of OutlierCandidate
        """
        exp_map = {exp.get("exp_id"): exp for exp in experiments}
        candidates = []

        for exp_id in exp_ids:
            exp = exp_map.get(exp_id)
            if exp:
                metrics = exp.get("metrics", {})
                candidates.append(
                    OutlierCandidate(
                        exp_id=exp_id,
                        run_tier=exp.get("run_tier", "unknown"),
                        composition=exp.get("composition", {}),
                        density=metrics.get("density") if isinstance(metrics, dict) else None,
                        ced=metrics.get("ced") if isinstance(metrics, dict) else None,
                        selection_reasons=[SelectionReason.MANUAL],
                        priority_score=0.0,
                    )
                )

        return candidates
