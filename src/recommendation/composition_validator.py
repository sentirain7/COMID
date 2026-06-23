"""
Composition Validator for Asphalt Binder formulations.

Validates that compositions meet physical and practical constraints.
Uses contracts SSOT for constraints, validation errors, and validity domain tags.
"""

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from common.logging import get_logger
from contracts.policies.binders import SARA_COMPONENTS as _SARA_COMPONENTS
from contracts.policies.composition import (
    DEFAULT_COMPOSITION_CONSTRAINTS,
    CompositionConstraints,
)
from contracts.schemas import ValidityDomainTag

logger = get_logger("recommendation.composition_validator")


def _get_bounds(bounds: dict[str, tuple[float, float]], component: str) -> tuple[float, float]:
    """Adapter to look up component bounds from contracts dict.

    Reproduces the behavior of the former CompositionBounds.get_bounds():
    - Known component -> return its bounds
    - Unknown component (e.g. individual additives) -> return additive_total bounds
    """
    if component in bounds:
        return bounds[component]
    return bounds.get("additive_total", (0.0, 10.0))


def _compute_additive_total(comp: dict[str, float], warnings: list[str]) -> float:
    """Compute additive total using SSOT rules with unclassified key detection.

    SSOT rule: sum keys starting with 'additive_' or equal to 'additive'.
    Hybrid: also detect and include unclassified keys (not SARA, not additive_*).
    """
    additive_total = sum(v for k, v in comp.items() if k.startswith("additive_") or k == "additive")
    # Detect unclassified keys (not SARA, not additive_* pattern)
    unclassified = {
        k: v
        for k, v in comp.items()
        if k not in _SARA_COMPONENTS and not k.startswith("additive_") and k != "additive"
    }
    if unclassified:
        warnings.append(
            f"Unclassified components (not SARA, not additive_*): {unclassified}. "
            f"Consider renaming with 'additive_' prefix for proper tracking."
        )
        additive_total += sum(unclassified.values())
    return additive_total


@dataclass
class ValidationResult:
    """Result of composition validation."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    original_composition: dict[str, float] = field(default_factory=dict)
    corrected_composition: dict[str, float] | None = None
    corrections_applied: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "original_composition": self.original_composition,
            "corrected_composition": self.corrected_composition,
            "corrections_applied": self.corrections_applied,
        }


class CompositionValidator:
    """
    Validates asphalt binder compositions against constraints.

    Can optionally auto-correct invalid compositions.
    """

    def __init__(
        self,
        constraints: CompositionConstraints | None = None,
        auto_fix: bool = True,
    ):
        """
        Initialize validator.

        Args:
            constraints: Validation constraints (defaults to SSOT)
            auto_fix: Whether to attempt auto-correction
        """
        self.constraints = constraints or DEFAULT_COMPOSITION_CONSTRAINTS
        self.auto_fix = auto_fix

    def validate(
        self,
        composition: dict[str, float],
        allow_auto_fix: bool | None = None,
    ) -> ValidationResult:
        """
        Validate a composition.

        Args:
            composition: Component name to weight percent mapping
            allow_auto_fix: Override auto_fix setting

        Returns:
            ValidationResult with validation status and any corrections
        """
        auto_fix = allow_auto_fix if allow_auto_fix is not None else self.auto_fix

        errors: list[str] = []
        warnings: list[str] = []
        corrections: list[str] = []

        # Make a copy for potential correction
        comp = dict(composition)

        # Check required components
        for required in _SARA_COMPONENTS:
            if required not in comp:
                errors.append(f"Missing required component: {required}")
                if auto_fix:
                    # Add with minimum value
                    min_val = _get_bounds(self.constraints.bounds, required)[0]
                    comp[required] = min_val
                    corrections.append(f"Added {required} with minimum value {min_val}")

        # Check bounds for each component
        for component, value in comp.items():
            bounds = _get_bounds(self.constraints.bounds, component)

            if value < bounds[0]:
                errors.append(f"{component} ({value:.2f}%) below minimum ({bounds[0]}%)")
                if auto_fix:
                    comp[component] = bounds[0]
                    corrections.append(f"Clipped {component} from {value:.2f} to {bounds[0]}")

            elif value > bounds[1]:
                errors.append(f"{component} ({value:.2f}%) above maximum ({bounds[1]}%)")
                if auto_fix:
                    comp[component] = bounds[1]
                    corrections.append(f"Clipped {component} from {value:.2f} to {bounds[1]}")

        # Check sum
        total = sum(comp.values())
        target = self.constraints.sum_wt_pct

        if abs(total - target) > self.constraints.sum_tolerance * target:
            errors.append(f"Composition sum ({total:.2f}%) != {target}%")

            if auto_fix:
                # Renormalize
                if total > 0:
                    factor = target / total
                    for key in comp:
                        comp[key] *= factor
                    corrections.append(f"Renormalized from {total:.2f}% to {target}%")

                    # Re-check bounds after normalization
                    for component, value in comp.items():
                        bounds = _get_bounds(self.constraints.bounds, component)
                        if value < bounds[0]:
                            comp[component] = bounds[0]
                            corrections.append(f"Post-norm: clipped {component} to {bounds[0]}")
                        elif value > bounds[1]:
                            comp[component] = bounds[1]
                            corrections.append(f"Post-norm: clipped {component} to {bounds[1]}")

        # Check additive total (hybrid: SSOT rules + unclassified key detection)
        additive_total = _compute_additive_total(comp, warnings)
        additive_max = self.constraints.bounds["additive_total"][1]
        if additive_total > additive_max:
            warnings.append(
                f"Total additive ({additive_total:.2f}%) exceeds "
                f"recommended maximum ({additive_max}%)"
            )

        # Determine final validity
        corrected_comp = comp if corrections else None

        # If auto-fix was applied, re-validate the corrected composition
        if corrections:
            final_total = sum(comp.values())
            all_in_bounds = all(
                _get_bounds(self.constraints.bounds, k)[0]
                <= v
                <= _get_bounds(self.constraints.bounds, k)[1]
                for k, v in comp.items()
            )
            sum_ok = abs(final_total - target) <= self.constraints.sum_tolerance * target
            valid = sum_ok and all_in_bounds
        else:
            valid = len(errors) == 0

        return ValidationResult(
            valid=valid,
            errors=errors,
            warnings=warnings,
            original_composition=composition,
            corrected_composition=corrected_comp,
            corrections_applied=corrections,
        )

    def generate_random_composition(
        self,
        include_additive: bool = False,
        additive_name: str = "additive",
        seed: int | None = None,
    ) -> dict[str, float]:
        """
        Generate a random valid composition.

        Args:
            include_additive: Whether to include additive
            additive_name: Name for additive component
            seed: Random seed

        Returns:
            Valid composition dictionary
        """
        rng = np.random.default_rng(seed)

        bounds = self.constraints.bounds

        # Generate random values within bounds (성분 순회는 SSOT tuple 순서 —
        # seed 결정성 보장. 전역 np.random.seed 뮤테이션 금지: 동시 요청 간섭)
        comp = {}
        for component in _SARA_COMPONENTS:
            b = _get_bounds(bounds, component)
            comp[component] = rng.uniform(b[0], b[1])

        if include_additive:
            b = bounds["additive_total"]
            comp[additive_name] = rng.uniform(b[0], b[1])

        # Redistribute toward the target sum proportionally to each
        # component's slack within bounds, satisfying BOTH per-component
        # bounds and the sum constraint. (Plain normalization could push a
        # component out of bounds; clipping it back would break the sum.)
        target = self.constraints.sum_wt_pct
        delta = target - sum(comp.values())
        if abs(delta) > 1e-12:
            comp_bounds = {k: _get_bounds(bounds, k) for k in comp}
            if delta > 0:
                slack = {k: comp_bounds[k][1] - v for k, v in comp.items()}
            else:
                slack = {k: v - comp_bounds[k][0] for k, v in comp.items()}
            total_slack = sum(slack.values())
            if total_slack > 0 and abs(delta) <= total_slack:
                for key in comp:
                    comp[key] += delta * slack[key] / total_slack
            else:
                # Target unreachable within bounds — fall back to plain
                # normalization; validate() below surfaces the violation.
                total = sum(comp.values())
                if total > 0:
                    factor = target / total
                    for key in comp:
                        comp[key] *= factor

        # Validate and correct if needed
        result = self.validate(comp)
        if result.corrected_composition:
            return result.corrected_composition
        return comp

    def get_search_space(self) -> dict[str, tuple[float, float]]:
        """
        Get the search space for optimization.

        Returns:
            Dictionary of component bounds
        """
        bounds = self.constraints.bounds
        space = {}

        for component in _SARA_COMPONENTS:
            space[component] = _get_bounds(bounds, component)

        space["additive"] = bounds["additive_total"]

        return space


class ValidityDomainClassifier:
    """
    Classifies compositions into validity domains based on force field limitations.
    """

    def __init__(self, constraints: CompositionConstraints | None = None):
        """Initialize classifier (임계값은 composition policy SSOT에서)."""
        c = constraints or DEFAULT_COMPOSITION_CONSTRAINTS
        self.thresholds = {
            "asphaltene_high": c.validity_asphaltene_high_wt,
            "additive_high": c.validity_additive_high_wt,
            "temperature_low": c.validity_temperature_low_k,
        }

    def classify(
        self,
        composition: dict[str, float],
        temperature_k: float = 298.0,
    ) -> list[str]:
        """
        Classify composition into validity domains.

        Args:
            composition: Component weight percentages
            temperature_k: Temperature in Kelvin

        Returns:
            List of validity domain tags
        """
        tags: list[str] = [ValidityDomainTag.BULK_GAFF2_OK]

        # Check asphaltene content
        asphaltene = composition.get("asphaltene", 0)
        if asphaltene >= self.thresholds["asphaltene_high"]:
            tags.append(ValidityDomainTag.HIGH_ASPHALTENE_SENSITIVE)

        # Check temperature
        if temperature_k < self.thresholds["temperature_low"]:
            tags.append(ValidityDomainTag.LOW_TEMPERATURE_CAUTION)

        # Check additive content (hybrid: SSOT rules + unclassified key detection)
        _warnings: list[str] = []
        additive_total = _compute_additive_total(composition, _warnings)
        if additive_total > self.thresholds["additive_high"]:
            tags.append(ValidityDomainTag.HIGH_ADDITIVE_UNCERTAIN)

        return tags
