"""Inverse Designer — property-target-driven composition optimization.

Orchestrates the BayesianOptimizer / PropertyTargetSet / CompositionValidator
loop to find optimal SARA + additive compositions satisfying property targets.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from common.logging import get_logger
from contracts.policies.recommendation_policy import DEFAULT_RECOMMENDATION_POLICY
from ml.extrapolation import (
    COMBINATORIAL_GENERALIZATION,
    HARD_EXTRAPOLATION,
    IN_DOMAIN,
    assess_prediction_context,
)

from .bayesian_optimizer import (
    AcquisitionFunction,
    BayesianOptimizer,
    CandidateSolution,
    OptimizationConfig,
    OptimizationObjective,
)
from .composition_validator import CompositionValidator
from .pareto import ParetoCalculator, ParetoFront, ParetoPoint
from .property_targets import PropertyTargetSet

logger = get_logger("recommendation.inverse_designer")


@dataclass
class InverseDesignResult:
    """Result of an inverse design optimization run.

    Attributes:
        target_set: The property target set used.
        best_compositions: Top-k solutions found.
        pareto_front: Final Pareto front (if multi-objective).
        n_iterations: Total iterations executed.
        converged: Whether convergence was reached.
        feasibility_rate: Fraction of candidates passing constraints.
        ood_flagged_count: Number of OOD-flagged predictions.
        history: Per-iteration summary records.
    """

    target_set: PropertyTargetSet
    best_compositions: list[CandidateSolution] = field(default_factory=list)
    pareto_front: ParetoFront | None = None
    n_iterations: int = 0
    converged: bool = False
    feasibility_rate: float = 0.0
    ood_flagged_count: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)
    acquisition_function: str = ""
    acquisition_rationale: str = ""


class InverseDesigner:
    """Property-target-driven inverse design orchestrator.

    Args:
        predictor_fn: Composition dict -> predicted properties dict.
        target_set: Desired property targets.
        additive_type: Fixed additive type string (None = pure SARA).
        ood_detector: Optional OODDetector for soft OOD flagging.
    """

    def __init__(
        self,
        predictor_fn: Callable[[dict[str, float]], dict[str, float]],
        target_set: PropertyTargetSet,
        additive_type: str | None = None,
        bounds_overrides: dict[str, tuple[float, float]] | None = None,
        ood_detector: Any = None,
        optimize_temperature: bool = False,
        temperature_range_k: tuple[float, float] | None = None,
        temperature_k_fixed: float | None = None,
        pressure_atm_fixed: float | None = None,
        allow_extrapolation: bool = False,
        capability_manifest: Mapping[str, Any] | None = None,
    ) -> None:
        self.predictor_fn = predictor_fn
        self.target_set = target_set
        self.additive_type = additive_type
        self.bounds_overrides = bounds_overrides or {}
        self.ood_detector = ood_detector
        self.optimize_temperature = bool(optimize_temperature)
        self.temperature_range_k = temperature_range_k
        self.temperature_k_fixed = temperature_k_fixed
        self.pressure_atm_fixed = pressure_atm_fixed
        self.allow_extrapolation = allow_extrapolation
        self.capability_manifest = dict(capability_manifest or {})
        self.validator = CompositionValidator(auto_fix=True)
        self._policy = DEFAULT_RECOMMENDATION_POLICY.inverse_design
        self._composition_keys = {"asphaltene", "resin", "aromatic", "saturate", "additive"}

    def run(
        self,
        n_initial: int | None = None,
        max_iterations: int | None = None,
        n_top: int = 5,
    ) -> InverseDesignResult:
        """Execute the inverse design optimization loop.

        Args:
            n_initial: Initial random samples (default: from policy).
            max_iterations: Max iterations (default: from policy).
            n_top: Number of best solutions to return.

        Returns:
            InverseDesignResult summarising the optimization.
        """
        max_iter = max_iterations or self._policy.max_iterations
        n_candidates = self._policy.n_candidates_per_iteration

        # Keep API latency bounded for short interactive runs while preserving
        # full-search behavior for longer optimization jobs.
        is_short_run = max_iter <= 5
        if is_short_run:
            n_candidates = min(n_candidates, 5)

        n_init = n_initial or 10
        if n_initial is None and is_short_run:
            # For very short runs, keep sampling in cheap random mode.
            n_init = max(n_init, n_candidates * max_iter)

        # Setup optimizer
        objectives = self._build_objectives()
        acq_fn, acq_rationale = self._select_acquisition(len(objectives), max_iter)
        optimizer = self._create_optimizer(objectives, n_init, acq_fn)

        # Setup Pareto calculator
        obj_names = [o.name for o in objectives]
        obj_dirs = [o.direction for o in objectives]
        pareto_calc = ParetoCalculator(objectives=obj_names, directions=obj_dirs)

        # Tracking
        hv_history: list[float] = []
        all_candidates: list[CandidateSolution] = []
        total_feasible = 0
        total_generated = 0
        ood_count = 0
        history: list[dict[str, Any]] = []

        for iteration in range(max_iter):
            # 1. Generate candidates
            suggestions = optimizer.suggest(n_candidates)
            total_generated += len(suggestions)

            iter_candidates: list[CandidateSolution] = []
            for comp in suggestions:
                # 2. Validate composition
                design_context = {
                    key: value for key, value in comp.items() if key not in self._composition_keys
                }
                composition_only = {
                    key: value for key, value in comp.items() if key in self._composition_keys
                }
                if self._policy.feasibility_check_enabled:
                    vr = self.validator.validate(composition_only)
                    if not vr.valid and vr.corrected_composition is None:
                        continue
                    composition_only = vr.corrected_composition or composition_only

                pred_input = self._prepare_predictor_input(composition_only, design_context)
                extrapolation = self._assess_extrapolation(pred_input)
                if extrapolation.status == HARD_EXTRAPOLATION and not self.allow_extrapolation:
                    continue

                # Inject fixed additive_type for predictor
                if self.additive_type is not None:
                    pred_input["additive_type"] = self.additive_type

                # 3. Predict properties
                try:
                    pred_result = self.predictor_fn(pred_input)
                except Exception as e:
                    logger.warning(f"Prediction failed for composition: {e}")
                    continue

                total_feasible += 1

                # Handle both old (dict[str, float]) and new (dict with predictions/uncertainties) formats
                if isinstance(pred_result, dict) and "predictions" in pred_result:
                    # New format: {"predictions": {...}, "uncertainties": {...}}
                    properties = pred_result.get("predictions", {})
                    uncertainty = pred_result.get("uncertainties", {})
                else:
                    # Old format: dict[str, float] directly
                    properties = pred_result
                    uncertainty = {}

                max_uncertainty_ratio = self._compute_max_uncertainty_ratio(properties, uncertainty)
                high_uncertainty = self._is_high_uncertainty(max_uncertainty_ratio)

                # 4. OOD check (soft flag)
                is_ood = False
                if self.ood_detector is not None:
                    is_ood = self._check_ood(pred_input)
                    if is_ood:
                        ood_count += 1

                # Extract objective values
                obj_values = {obj.name: properties.get(obj.name, 0.0) for obj in objectives}
                target_distances = self.target_set.compute_distances(obj_values)

                candidate = CandidateSolution(
                    composition={**composition_only, **design_context},
                    predicted_objectives=obj_values,
                    acquisition_value=0.0,
                    uncertainty=uncertainty,
                    iteration=iteration,
                    is_ood=is_ood,
                    target_distances=target_distances,
                    extrapolation_status=extrapolation.status,
                    high_uncertainty=high_uncertainty,
                    capability_notes=list(extrapolation.reasons + extrapolation.warnings),
                    max_uncertainty_ratio=max_uncertainty_ratio,
                )
                candidate.rationale = self._build_rationale(candidate)
                iter_candidates.append(candidate)
                all_candidates.append(candidate)

                # 5. Tell optimizer
                optimizer.tell(comp, obj_values)

            # Compute Pareto front for all candidates so far
            pareto_points = [
                ParetoPoint(
                    objectives=np.array([c.predicted_objectives.get(n, 0.0) for n in obj_names]),
                    composition=c.composition,
                    predicted_properties=c.predicted_objectives,
                    index=i,
                )
                for i, c in enumerate(all_candidates)
            ]

            if pareto_points:
                pareto_front = pareto_calc.calculate_pareto_front(pareto_points)
                hv = pareto_calc.hypervolume_indicator(pareto_front)
            else:
                pareto_front = None
                hv = 0.0

            hv_history.append(hv)

            # Record iteration
            targets_met = sum(
                1
                for c in iter_candidates
                if self.target_set.are_all_satisfied(c.predicted_objectives)
            )
            history.append(
                {
                    "iteration": iteration,
                    "n_candidates": len(iter_candidates),
                    "targets_met": targets_met,
                    "hypervolume": hv,
                    "ood_flagged": ood_count,
                    "high_uncertainty": sum(1 for c in iter_candidates if c.high_uncertainty),
                }
            )

            logger.info(
                f"Iter {iteration}: {len(iter_candidates)} candidates, "
                f"HV={hv:.4f}, targets_met={targets_met}"
            )

            # 6. Convergence check
            if self._check_convergence(hv_history):
                logger.info(f"Converged at iteration {iteration}")
                break

        # Select top-k results
        best = self._select_top(all_candidates, obj_names, obj_dirs, n_top)

        # Final Pareto front
        final_pareto = None
        if pareto_points:
            final_pareto = pareto_calc.calculate_pareto_front(pareto_points)

        feasibility_rate = total_feasible / max(total_generated, 1)

        return InverseDesignResult(
            target_set=self.target_set,
            best_compositions=best,
            pareto_front=final_pareto,
            n_iterations=len(history),
            converged=self._check_convergence(hv_history),
            feasibility_rate=feasibility_rate,
            ood_flagged_count=ood_count,
            history=history,
            acquisition_function=acq_fn.value,
            acquisition_rationale=acq_rationale,
        )

    def _build_objectives(self) -> list[OptimizationObjective]:
        """Convert PropertyTargetSet to OptimizationObjective list."""
        objectives: list[OptimizationObjective] = []
        for t in self.target_set.targets:
            direction = t.direction if t.direction != "target" else "maximize"
            objectives.append(
                OptimizationObjective(
                    name=t.metric_name,
                    direction=direction,
                    weight=t.weight,
                )
            )
        return objectives

    def _select_acquisition(
        self, n_objectives: int, max_iter: int
    ) -> tuple[AcquisitionFunction, str]:
        """Select the acquisition function from policy (SSOT).

        ``acquisition_strategy='auto'`` reproduces the legacy rule (EHVI for
        multi-objective long runs, else EI).  An explicit strategy forces that
        acquisition function.  Returns ``(acq_fn, rationale)`` for audit.
        """
        strategy = str(getattr(self._policy, "acquisition_strategy", "auto")).lower()
        if strategy == "auto":
            if n_objectives >= 2 and max_iter > 5:
                return (
                    AcquisitionFunction.EHVI,
                    f"auto: n_objectives={n_objectives} >= 2 and max_iterations={max_iter} > 5",
                )
            return (
                AcquisitionFunction.EI,
                f"auto: n_objectives={n_objectives} < 2 or max_iterations={max_iter} <= 5",
            )

        explicit = {
            "ei": AcquisitionFunction.EI,
            "ucb": AcquisitionFunction.UCB,
            "ehvi": AcquisitionFunction.EHVI,
            "pi": AcquisitionFunction.PI,
        }
        acq = explicit.get(strategy, AcquisitionFunction.EI)
        return acq, f"policy: acquisition_strategy={strategy!r}"

    def _create_optimizer(
        self,
        objectives: list[OptimizationObjective],
        n_initial: int,
        acq_fn: AcquisitionFunction,
    ) -> BayesianOptimizer:
        """Create a BayesianOptimizer configured for this design task."""
        config = OptimizationConfig(
            objectives=objectives,
            n_initial_samples=n_initial,
            n_iterations=self._policy.max_iterations,
            acquisition_function=acq_fn,
            exploration_weight=float(getattr(self._policy, "exploration_weight", 0.1)),
        )

        from contracts.policies.composition import DEFAULT_COMPOSITION_CONSTRAINTS

        cc_bounds = DEFAULT_COMPOSITION_CONSTRAINTS.bounds
        bounds: dict[str, tuple[float, float]] = {
            "asphaltene": cc_bounds.get("asphaltene", (5.0, 30.0)),
            "resin": cc_bounds.get("resin", (10.0, 50.0)),
            "aromatic": cc_bounds.get("aromatic", (10.0, 60.0)),
            "saturate": cc_bounds.get("saturate", (5.0, 40.0)),
        }

        if self.additive_type is not None:
            add_bounds = cc_bounds.get("additive_total", (0.0, 10.0))
            bounds["additive"] = (0.0, add_bounds[1])
        if self.optimize_temperature:
            bounds["temperature_k"] = tuple(
                float(v)
                for v in (
                    self.temperature_range_k
                    or self.capability_manifest.get("supported_temperature_range_k")
                    or (233.0, 473.0)
                )
            )

        for name, override in self.bounds_overrides.items():
            if len(override) != 2:
                continue
            low, high = float(override[0]), float(override[1])
            if low > high:
                low, high = high, low
            bounds[name] = (low, high)

        return BayesianOptimizer(config=config, bounds=bounds)

    def _prepare_predictor_input(
        self,
        composition: dict[str, float],
        design_context: Mapping[str, float],
    ) -> dict[str, float]:
        """Merge composition and runtime context into predictor input."""
        pred_input = dict(composition)
        if self.temperature_k_fixed is not None:
            pred_input["temperature_k"] = float(self.temperature_k_fixed)
        elif "temperature_k" in design_context:
            pred_input["temperature_k"] = float(design_context["temperature_k"])
        elif self.optimize_temperature:
            low, _high = (
                self.temperature_range_k
                or self.capability_manifest.get("supported_temperature_range_k")
                or (233.0, 473.0)
            )
            pred_input["temperature_k"] = float(low)
        if self.pressure_atm_fixed is not None:
            pred_input["pressure_atm"] = float(self.pressure_atm_fixed)
        return pred_input

    def _assess_extrapolation(self, pred_input: dict[str, float]):
        """Assess request context against runtime capability manifest."""
        layer_count = None
        if isinstance(pred_input.get("stack_n_layers"), (int, float)):
            layer_count = int(pred_input["stack_n_layers"])
        return assess_prediction_context(
            capability_manifest=self.capability_manifest,
            temperature_k=pred_input.get("temperature_k"),
            layer_count=layer_count,
            additive_type=self.additive_type or pred_input.get("additive_type"),
            binder_type=pred_input.get("binder_type"),
            aging_state=pred_input.get("aging_state"),
        )

    @staticmethod
    def _compute_max_uncertainty_ratio(
        properties: Mapping[str, float],
        uncertainty: Mapping[str, float],
    ) -> float:
        ratios: list[float] = []
        for name, sigma in uncertainty.items():
            denom = max(abs(float(properties.get(name, 0.0))), 1e-8)
            ratios.append(abs(float(sigma)) / denom)
        return max(ratios, default=0.0)

    def _is_high_uncertainty(self, max_uncertainty_ratio: float) -> bool:
        threshold = float(self._policy.high_uncertainty_ratio_threshold or 0.0)
        return threshold > 0.0 and max_uncertainty_ratio > threshold

    def _check_ood(self, composition: dict[str, float]) -> bool:
        """Check OOD status using canonical V2 feature construction."""
        try:
            from contracts.policies.ml_policy import FeatureSetVersion
            from ml.feature_builder import FeatureBuildInput, build_feature_result

            built = build_feature_result(
                FeatureBuildInput.from_prediction_composition(
                    composition,
                    additive_type=self.additive_type,
                ),
                FeatureSetVersion.V2,
            )
            results = self.ood_detector.detect(built.values.reshape(1, -1))
            return results[0].is_ood
        except Exception as e:
            logger.warning(f"OOD check failed: {e}")
            return False

    def _check_convergence(self, hv_history: list[float]) -> bool:
        """Check if HV improvement is below threshold for convergence_window iters."""
        window = self._policy.convergence_window
        threshold = self._policy.convergence_threshold

        if len(hv_history) < window + 1:
            return False

        recent = hv_history[-window:]
        baseline = hv_history[-(window + 1)]

        if baseline == 0:
            return all(abs(v) < threshold for v in recent)

        max_improvement = max(abs(v - baseline) / max(abs(baseline), 1e-10) for v in recent)
        return max_improvement < threshold

    def _select_top(
        self,
        candidates: list[CandidateSolution],
        obj_names: list[str],
        obj_dirs: list[str],
        n_top: int,
    ) -> list[CandidateSolution]:
        """Select top-k candidates prioritising target satisfaction then scalarised score."""
        # Separate satisfied vs unsatisfied
        satisfied = [
            c for c in candidates if self.target_set.are_all_satisfied(c.predicted_objectives)
        ]
        unsatisfied = [
            c for c in candidates if not self.target_set.are_all_satisfied(c.predicted_objectives)
        ]

        def scalarised_score(c: CandidateSolution) -> float:
            score = 0.0
            for name, d in zip(obj_names, obj_dirs, strict=False):
                v = c.predicted_objectives.get(name, 0.0)
                score += v if d == "maximize" else -v
            if c.is_ood:
                score -= float(self._policy.ood_penalty)
            if c.high_uncertainty:
                score -= float(self._policy.uncertainty_penalty_lambda) * float(
                    c.max_uncertainty_ratio
                )
            if c.extrapolation_status == COMBINATORIAL_GENERALIZATION:
                score -= float(self._policy.extrapolation_penalty)
            return score

        satisfied = [
            c
            for c in satisfied
            if self.allow_extrapolation or c.extrapolation_status != HARD_EXTRAPOLATION
        ]
        unsatisfied = [
            c
            for c in unsatisfied
            if self.allow_extrapolation or c.extrapolation_status != HARD_EXTRAPOLATION
        ]
        satisfied.sort(key=scalarised_score, reverse=True)
        unsatisfied.sort(key=scalarised_score, reverse=True)

        result = satisfied[:n_top]
        if len(result) < n_top:
            result.extend(unsatisfied[: n_top - len(result)])

        return result

    def _build_rationale(self, candidate: CandidateSolution) -> str:
        """Build a compact rationale string for recommendation surfaces."""
        distance_bits = [
            f"{name}={value:.3g}" for name, value in sorted(candidate.target_distances.items())
        ]
        flags: list[str] = []
        if candidate.is_ood:
            flags.append("OOD")
        if candidate.high_uncertainty:
            flags.append(f"high_uncertainty({candidate.max_uncertainty_ratio:.2f})")
        if candidate.extrapolation_status != IN_DOMAIN:
            flags.append(candidate.extrapolation_status)
        if candidate.capability_notes:
            flags.extend(candidate.capability_notes[:2])
        parts = []
        if distance_bits:
            parts.append("target_distance: " + ", ".join(distance_bits))
        if flags:
            parts.append("flags: " + "; ".join(flags))
        return (
            " | ".join(parts)
            if parts
            else "Target distances satisfied without additional risk flags."
        )
