"""
Replicate policy — SSOT for seed replicate requirements.

Defines minimum replicate counts, confidence intervals, and
tier-specific requirements for statistically valid MD results.

Reference: Allen & Tildesley (2017) — independent seed replicates (n>=3)
with 95% CI reporting are required for statistical significance.
"""

from pydantic import BaseModel, Field


class ReplicatePolicy(BaseModel):
    """Policy for seed replicate requirements.

    Args:
        min_seeds: Minimum number of independent seeds for statistical validity
        ci_level: Confidence interval level (0.95 = 95% CI)
        required_for_tiers: Tiers that require full replicate compliance
        recommended_for_tiers: Tiers where replicates are recommended but not enforced
        default_seeds: Default seed list when none is specified
        significance_alpha: Alpha level for hypothesis testing (Welch's t-test)
    """

    min_seeds: int = Field(3, ge=1, description="Minimum independent seeds")
    ci_level: float = Field(0.95, gt=0.0, lt=1.0, description="Confidence interval level")
    required_for_tiers: list[str] = Field(
        default_factory=lambda: ["confirm", "viscosity"],
        description="Tiers requiring full replicate compliance",
    )
    recommended_for_tiers: list[str] = Field(
        default_factory=lambda: ["screening"],
        description="Tiers where replicates are recommended",
    )
    default_seeds: list[int] = Field(
        default_factory=lambda: [1, 2, 3],
        description="Default seed list for replicate runs",
    )
    significance_alpha: float = Field(
        0.05, gt=0.0, lt=1.0, description="Significance level for hypothesis testing"
    )
    report_standard_error: bool = Field(
        default=True,
        description=(
            "Recommended: report ensemble mean and standard error (SEM = std/sqrt(n)) "
            "when aggregating replicate measurements. Enabled by default so aggregate "
            "results carry mean + standard error out of the box."
        ),
    )

    def is_required(self, tier: str) -> bool:
        """Check if replicates are required for a given tier.

        Args:
            tier: Run tier name

        Returns:
            True if replicates are mandatory for this tier
        """
        return tier in self.required_for_tiers

    def is_recommended(self, tier: str) -> bool:
        """Check if replicates are recommended for a given tier.

        Args:
            tier: Run tier name

        Returns:
            True if replicates are recommended (but not enforced)
        """
        return tier in self.recommended_for_tiers

    def get_seeds(self, user_seeds: list[int] | None = None) -> list[int]:
        """Get seed list, falling back to defaults.

        Args:
            user_seeds: User-provided seed list (None = use defaults)

        Returns:
            List of seeds to use
        """
        if user_seeds is not None and len(user_seeds) > 0:
            return user_seeds
        return list(self.default_seeds)

    def validate_replicate_count(self, n_replicates: int, tier: str) -> bool:
        """Check if replicate count meets tier requirements.

        Args:
            n_replicates: Number of replicates available
            tier: Run tier name

        Returns:
            True if count is sufficient for the tier
        """
        if self.is_required(tier):
            return n_replicates >= self.min_seeds
        return True


DEFAULT_REPLICATE_POLICY = ReplicatePolicy()
