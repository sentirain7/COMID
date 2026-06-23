"""Feasibility pre-screening for inverse design.

Before launching the (expensive) Bayesian-optimization loop, sample the
composition space randomly and estimate how achievable the requested property
targets are.  This lets the API fail fast on infeasible requests and warn on
difficult ones, instead of silently returning an empty/poor result after a
full optimization run.

The scout reuses existing building blocks rather than re-implementing them:

- ``CompositionValidator.generate_random_composition`` — valid random samples.
- ``PropertyTargetSet.are_all_satisfied`` / per-target ``is_satisfied`` — the
  exact same satisfaction logic used by the optimizer ranking.

Thresholds and sample count come from
``DEFAULT_RECOMMENDATION_POLICY.inverse_design`` (SSOT), never hardcoded.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from common.logging import get_logger
from contracts.policies.recommendation_policy import DEFAULT_RECOMMENDATION_POLICY
from recommendation.composition_validator import CompositionValidator
from recommendation.property_targets import PropertyTargetSet

logger = get_logger("recommendation.feasibility_scout")

# Feasibility classification labels.
FEASIBLE = "feasible"
DIFFICULT = "difficult"
INFEASIBLE = "infeasible"
UNKNOWN = "unknown"


@dataclass
class FeasibilityReport:
    """Outcome of a feasibility pre-screening pass."""

    status: str = UNKNOWN
    n_samples: int = 0
    n_evaluated: int = 0
    all_targets_satisfied_pct: float = 0.0
    per_target: dict[str, dict[str, float | bool]] = field(default_factory=dict)
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable representation for API responses / error details."""
        return {
            "status": self.status,
            "n_samples": self.n_samples,
            "n_evaluated": self.n_evaluated,
            "all_targets_satisfied_pct": round(self.all_targets_satisfied_pct, 2),
            "per_target": self.per_target,
            "message": self.message,
        }


class FeasibilityScout:
    """Estimate whether a PropertyTargetSet is achievable in the composition space.

    Args:
        predictor_fn: Composition dict -> predicted properties.  Accepts both
            the plain ``{metric: value}`` format and the uncertainty-aware
            ``{"predictions": {...}, "uncertainties": {...}}`` format used by
            the inverse designer.
        target_set: The property targets to screen against.
        validator: Optional CompositionValidator (defaults to SSOT constraints).
        additive_type: Fixed additive type to include in sampling/prediction.
        temperature_k: Optional fixed temperature injected into predictor input.
        n_samples / infeasible_pct / difficult_pct: Optional overrides; default
            to the inverse-design policy.
    """

    def __init__(
        self,
        predictor_fn: Callable[[dict[str, float]], Any],
        target_set: PropertyTargetSet,
        *,
        validator: CompositionValidator | None = None,
        additive_type: str | None = None,
        temperature_k: float | None = None,
        n_samples: int | None = None,
        infeasible_pct: float | None = None,
        difficult_pct: float | None = None,
        seed: int | None = None,
    ) -> None:
        policy = DEFAULT_RECOMMENDATION_POLICY.inverse_design
        self.predictor_fn = predictor_fn
        self.target_set = target_set
        self.validator = validator or CompositionValidator(auto_fix=True)
        self.additive_type = additive_type
        self.temperature_k = temperature_k
        # P1-9: deterministic sampling for reproducible feasibility verdicts near
        # the threshold (None → non-deterministic, legacy behaviour).
        self.seed = seed
        self.n_samples = int(n_samples if n_samples is not None else policy.feasibility_n_samples)
        self.infeasible_pct = float(
            infeasible_pct if infeasible_pct is not None else policy.feasibility_infeasible_pct
        )
        self.difficult_pct = float(
            difficult_pct if difficult_pct is not None else policy.feasibility_difficult_pct
        )

    def scout(self) -> FeasibilityReport:
        """Sample the composition space and estimate target achievability."""
        include_additive = self.additive_type is not None
        target_names = [t.metric_name for t in self.target_set.targets]

        per_target_hits: dict[str, int] = dict.fromkeys(target_names, 0)
        all_hits = 0
        n_evaluated = 0

        for i in range(self.n_samples):
            composition = self.validator.generate_random_composition(
                include_additive=include_additive,
                seed=(self.seed + i) if self.seed is not None else None,
            )
            properties = self._predict(composition)
            if properties is None:
                continue
            n_evaluated += 1

            for t in self.target_set.targets:
                value = properties.get(t.metric_name)
                if value is not None and t.is_satisfied(value):
                    per_target_hits[t.metric_name] += 1

            if self.target_set.are_all_satisfied(properties):
                all_hits += 1

        return self._build_report(per_target_hits, all_hits, n_evaluated)

    # ------------------------------------------------------------------

    def _predict(self, composition: dict[str, float]) -> dict[str, float] | None:
        """Run the predictor for one composition, normalising the output format."""
        pred_input = dict(composition)
        if self.additive_type is not None:
            pred_input["additive_type"] = self.additive_type
        if self.temperature_k is not None:
            pred_input["temperature_k"] = float(self.temperature_k)

        try:
            result = self.predictor_fn(pred_input)
        except Exception as exc:  # pragma: no cover - defensive; failures are skipped
            logger.debug("Feasibility prediction failed for a sample: %s", exc)
            return None

        if isinstance(result, Mapping) and "predictions" in result:
            return dict(result.get("predictions", {}))
        if isinstance(result, Mapping):
            return dict(result)
        return None

    def _build_report(
        self,
        per_target_hits: dict[str, int],
        all_hits: int,
        n_evaluated: int,
    ) -> FeasibilityReport:
        if n_evaluated == 0:
            return FeasibilityReport(
                status=UNKNOWN,
                n_samples=self.n_samples,
                n_evaluated=0,
                message=(
                    "Feasibility pre-screening produced no predictions; "
                    "proceeding without a feasibility verdict."
                ),
            )

        all_pct = 100.0 * all_hits / n_evaluated
        per_target = {
            name: {
                "satisfied_pct": round(100.0 * hits / n_evaluated, 2),
                "achievable": (100.0 * hits / n_evaluated) >= self.difficult_pct,
            }
            for name, hits in per_target_hits.items()
        }

        if all_pct < self.infeasible_pct:
            status = INFEASIBLE
            message = (
                f"Targets appear infeasible: only {all_pct:.1f}% of sampled compositions "
                f"satisfy all targets (threshold {self.infeasible_pct:.1f}%). "
                "Relax bounds/targets, or set allow_infeasible_exploration=true."
            )
        elif all_pct < self.difficult_pct:
            status = DIFFICULT
            message = (
                f"Targets appear difficult: {all_pct:.1f}% of sampled compositions satisfy "
                f"all targets (threshold {self.difficult_pct:.1f}%). "
                "Expect slow convergence; consider increasing max_iterations."
            )
        else:
            status = FEASIBLE
            message = (
                f"Targets appear feasible: {all_pct:.1f}% of sampled compositions satisfy "
                "all targets."
            )

        return FeasibilityReport(
            status=status,
            n_samples=self.n_samples,
            n_evaluated=n_evaluated,
            all_targets_satisfied_pct=all_pct,
            per_target=per_target,
            message=message,
        )
