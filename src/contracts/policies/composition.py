"""
Composition constraints policy - SSOT for all composition validation.

All sessions must use this policy for composition validation and normalization.
"""

from pydantic import BaseModel, Field


class CompositionConstraints(BaseModel):
    """
    Composition constraints - all sessions must follow this policy.

    This is the Single Source of Truth for composition validation rules.
    """

    # wt% sum rules
    sum_wt_pct: float = Field(100.0, description="Required sum of wt%")
    sum_tolerance: float = Field(0.01, description="Tolerance for sum (±)")

    # Component bounds
    bounds: dict[str, tuple[float, float]] = Field(
        default={
            "asphaltene": (5.0, 30.0),
            "resin": (10.0, 50.0),
            "aromatic": (10.0, 60.0),
            "saturate": (5.0, 40.0),
            "additive_total": (0.0, 10.0),
        },
        description="Min/max bounds for each component",
    )

    # Auto-normalization settings
    auto_normalize: bool = Field(True, description="Enable auto-normalization")
    normalize_method: str = Field(
        "proportional", description="Normalization method: proportional or clip_and_redistribute"
    )

    # Validity domain thresholds (SSOT — get_validity_tags와
    # recommendation.ValidityDomainClassifier가 공유)
    validity_asphaltene_high_wt: float = Field(
        25.0, description="asphaltene >= 이 값(wt%) → high_asphaltene_sensitive"
    )
    validity_additive_high_wt: float = Field(
        10.0, description="additive 합계 > 이 값(wt%) → high_additive_uncertain"
    )
    validity_temperature_low_k: float = Field(
        273.0, description="T < 이 값(K) → low_temperature_caution"
    )

    # Composition error threshold
    composition_error_threshold_l1: float = Field(
        1.0, description="L1 error threshold in wt% units"
    )
    rebuild_if_exceeded: bool = Field(
        True, description="Trigger rebuild if error exceeds threshold"
    )

    def validate_composition(
        self, composition: dict[str, float], strict: bool = False
    ) -> tuple[bool, str | None]:
        """
        Validate composition against constraints.

        Args:
            composition: Component wt% values
            strict: If True, fail on any violation; if False, return warnings

        Returns:
            Tuple of (is_valid, error_message)
        """
        errors = []

        # Check for negative values
        for component, value in composition.items():
            if value < 0:
                errors.append(f"{component} has negative value: {value}")

        # Check sum
        total = sum(composition.values())
        if abs(total - self.sum_wt_pct) > self.sum_tolerance:
            errors.append(f"Sum {total:.4f} != {self.sum_wt_pct} (tolerance: {self.sum_tolerance})")

        # Check bounds for known components
        for component, value in composition.items():
            # Handle additive components
            if component.startswith("additive_") or component not in self.bounds:
                continue

            min_val, max_val = self.bounds.get(component, (0.0, 100.0))
            if value < min_val or value > max_val:
                errors.append(f"{component}: {value} not in [{min_val}, {max_val}]")

        # Check additive total
        additive_total = sum(
            v for k, v in composition.items() if k.startswith("additive_") or k == "additive"
        )
        if additive_total > 0:
            min_add, max_add = self.bounds.get("additive_total", (0.0, 10.0))
            if additive_total > max_add:
                errors.append(f"additive_total: {additive_total} > {max_add}")

        if errors:
            return False, "; ".join(errors)
        return True, None

    def normalize(
        self, composition: dict[str, float], method: str | None = None
    ) -> dict[str, float]:
        """
        Normalize composition to sum to 100%.

        Args:
            composition: Component wt% values
            method: Override normalization method

        Returns:
            Normalized composition
        """
        method = method or self.normalize_method
        total = sum(composition.values())

        if abs(total - self.sum_wt_pct) <= self.sum_tolerance:
            return composition.copy()

        if method == "proportional":
            factor = self.sum_wt_pct / total
            return {k: v * factor for k, v in composition.items()}

        elif method == "clip_and_redistribute":
            # First clip to bounds, then redistribute remainder
            clipped = {}
            remainder = 0.0

            for component, value in composition.items():
                if component in self.bounds:
                    min_val, max_val = self.bounds[component]
                    if value < min_val:
                        clipped[component] = min_val
                        remainder += min_val - value
                    elif value > max_val:
                        clipped[component] = max_val
                        remainder += value - max_val
                    else:
                        clipped[component] = value
                else:
                    clipped[component] = value

            # Redistribute remainder proportionally to non-clipped components
            if remainder != 0:
                adjustable = [
                    k
                    for k, v in clipped.items()
                    if k in self.bounds and self.bounds[k][0] < v < self.bounds[k][1]
                ]
                if adjustable:
                    adj_total = sum(clipped[k] for k in adjustable)
                    for k in adjustable:
                        clipped[k] -= remainder * (clipped[k] / adj_total)

            # Final proportional normalization
            total = sum(clipped.values())
            factor = self.sum_wt_pct / total
            return {k: v * factor for k, v in clipped.items()}

        return composition.copy()

    def get_validity_tags(self, composition: dict[str, float]) -> list[str]:
        """
        Get validity domain tags based on composition.

        Args:
            composition: Component wt% values

        Returns:
            List of validity domain tags
        """
        tags = ["bulk_gaff2_ok"]

        # Check high asphaltene
        asphaltene_wt = composition.get("asphaltene", 0.0)
        if asphaltene_wt >= self.validity_asphaltene_high_wt:
            tags.append("high_asphaltene_sensitive")

        # Check high additive
        additive_total = sum(
            v for k, v in composition.items() if k.startswith("additive_") or k == "additive"
        )
        if additive_total > self.validity_additive_high_wt:
            tags.append("high_additive_uncertain")

        return tags


# Default instance for convenience
DEFAULT_COMPOSITION_CONSTRAINTS = CompositionConstraints()
