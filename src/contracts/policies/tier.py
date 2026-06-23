"""
Tier policy - SSOT for run tier definitions and transitions.

All sessions must use this policy for tier-related decisions.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class RunTier(StrEnum):
    """Run tier enumeration."""

    SCREENING = "screening"
    CONFIRM = "confirm"
    VISCOSITY = "viscosity"
    VALIDATION = "validation"


class SamplingConfig(BaseModel):
    """Sampling configuration for dump intervals.

    Controls how frequently trajectory frames are dumped during simulation.
    The dump interval is calculated as: clamp(total_steps // target_frames, min, max)
    """

    enabled: bool = Field(True, description="Enable adaptive dump interval")
    production_target_frames: int = Field(
        50, description="Target frames for production (NPT/viscosity)"
    )
    equilibration_target_frames: int = Field(
        30, description="Target frames for equilibration (NVT)"
    )
    min_interval_steps: int = Field(10_000, description="Minimum dump interval (steps)")
    max_interval_steps: int = Field(100_000, description="Maximum dump interval (steps)")


class TierConfig(BaseModel):
    """Configuration for a single tier."""

    target_atoms: int = Field(..., description="Target atom count")
    atom_tolerance: float = Field(0.10, description="Atom count tolerance")
    nvt_ps: float = Field(..., description="NVT duration (ps)")
    npt_ps: float = Field(..., description="NPT duration (ps)")
    minimize_steps: int = Field(1000, description="Minimization steps")
    dt_fs: float = Field(1.0, description="Timestep (fs)")
    dt_min_fs: float = Field(0.25, description="Minimum timestep on failure")
    viscosity_ns: float | None = Field(None, description="Viscosity duration (ns)")
    trigger_condition: str | None = Field(None, description="Condition for tier upgrade")
    ff_type: str = Field("bulk_ff_gaff2", description="Force field type")
    cap_per_batch: int | None = Field(None, description="Cap per batch (for validation)")
    sampling: SamplingConfig | None = Field(
        None, description="Sampling strategy for dump intervals"
    )


class ConvergenceCriteria(BaseModel):
    """Convergence criteria for simulations."""

    density_window_ps: float = Field(200.0, description="Window for density convergence")
    density_threshold_pct: float = Field(0.5, description="Density variation threshold")
    energy_window_ps: float = Field(100.0, description="Window for energy convergence")
    energy_threshold_pct: float = Field(1.0, description="Energy variation threshold")

    # --- NPT convergence-based early stop (opt-in, off by default) ---
    # When enabled, the NPT production step emits a LAMMPS ``fix halt`` that
    # terminates the run once the trailing-window density coefficient of
    # variation (std/mean) drops below ``early_stop_density_cv``, but only
    # after a floor of ``early_stop_min_fraction`` of the nominal nsteps has
    # elapsed. Default OFF preserves the fixed-duration behaviour exactly;
    # activation is a deliberate per-deployment decision pending property-
    # accuracy validation. (RadonPy/PolyJarvis-style equilibration short-cut.)
    enable_early_stop: bool = Field(
        False, description="Enable NPT convergence-based early stop (opt-in)"
    )
    early_stop_density_cv: float = Field(
        0.002, description="Trailing-window density CV (std/mean) halt threshold"
    )
    early_stop_min_fraction: float = Field(
        0.5, description="Min fraction of nominal nsteps before halt may trigger"
    )


class TierPolicy(BaseModel):
    """
    Tier policy - SSOT for tier definitions and transitions.

    This defines all run tiers and their parameters.
    """

    tiers: dict[str, TierConfig] = Field(
        default={
            "screening": TierConfig(
                target_atoms=100000,
                atom_tolerance=0.10,
                nvt_ps=300.0,
                npt_ps=1000.0,
                minimize_steps=1000,
                dt_fs=1.0,
                dt_min_fs=0.25,
                sampling=SamplingConfig(
                    production_target_frames=50,
                    equilibration_target_frames=30,
                ),
            ),
            "confirm": TierConfig(
                target_atoms=200000,
                atom_tolerance=0.10,
                nvt_ps=300.0,
                npt_ps=3000.0,
                minimize_steps=5000,
                dt_fs=1.0,
                dt_min_fs=0.25,
                trigger_condition="candidate_for_recommendation OR density_zscore > 2.0",
                sampling=SamplingConfig(
                    production_target_frames=100,
                    equilibration_target_frames=30,
                ),
            ),
            "viscosity": TierConfig(
                target_atoms=150000,
                atom_tolerance=0.10,
                nvt_ps=300.0,
                npt_ps=3000.0,
                minimize_steps=5000,
                dt_fs=1.0,
                dt_min_fs=0.25,
                viscosity_ns=5.0,
                trigger_condition="candidate_selected_for_recommendation",
                sampling=SamplingConfig(
                    production_target_frames=200,
                    equilibration_target_frames=30,
                ),
            ),
            "validation": TierConfig(
                target_atoms=100000,
                atom_tolerance=0.10,
                nvt_ps=300.0,
                npt_ps=1000.0,
                minimize_steps=1000,
                dt_fs=0.5,
                dt_min_fs=0.1,
                ff_type="reaxff",
                trigger_condition="abs(zscore) > 2.0 OR stability_flag",
                cap_per_batch=5,
                sampling=SamplingConfig(
                    production_target_frames=50,
                    equilibration_target_frames=30,
                ),
            ),
        },
        description="Tier configurations",
    )

    convergence_criteria: ConvergenceCriteria = Field(
        default_factory=ConvergenceCriteria, description="Convergence criteria for all tiers"
    )

    def get_tier_config(self, tier: str | RunTier) -> TierConfig:
        """
        Get configuration for a tier.

        Args:
            tier: Tier name or enum

        Returns:
            TierConfig for the tier
        """
        tier_name = tier.value if isinstance(tier, RunTier) else tier
        if tier_name not in self.tiers:
            raise ValueError(f"Unknown tier: {tier_name}")
        return self.tiers[tier_name]

    def get_target_atoms(self, tier: str | RunTier) -> int:
        """Get target atom count for tier."""
        return self.get_tier_config(tier).target_atoms

    def get_npt_duration(self, tier: str | RunTier) -> float:
        """Get NPT duration for tier in ps."""
        return self.get_tier_config(tier).npt_ps

    def get_dt(self, tier: str | RunTier) -> float:
        """Get timestep for tier in fs."""
        return self.get_tier_config(tier).dt_fs

    def get_dt_min(self, tier: str | RunTier) -> float:
        """Get minimum timestep for tier in fs."""
        return self.get_tier_config(tier).dt_min_fs

    def should_upgrade_tier(
        self, current_tier: str, metrics: dict[str, float], flags: dict[str, bool]
    ) -> str | None:
        """
        Check if tier should be upgraded based on conditions.

        Args:
            current_tier: Current tier name
            metrics: Calculated metrics
            flags: Boolean flags (candidate_selected, etc.)

        Returns:
            Next tier name if upgrade needed, None otherwise
        """
        # screening -> confirm
        if current_tier == "screening":
            if flags.get("candidate_for_recommendation", False):
                return "confirm"
            if abs(metrics.get("density_zscore", 0)) > 2.0:
                return "confirm"

        # confirm -> viscosity
        if current_tier == "confirm":
            if flags.get("candidate_selected_for_recommendation", False):
                return "viscosity"

        # Any tier -> validation (for outliers)
        if current_tier in ["screening", "confirm"]:
            if abs(metrics.get("density_zscore", 0)) > 2.0:
                if flags.get("stability_flag", False):
                    return "validation"
            if abs(metrics.get("ced_zscore", 0)) > 2.0:
                return "validation"

        return None

    def is_viscosity_enabled(self, tier: str | RunTier) -> bool:
        """Check if viscosity calculation is enabled for tier."""
        config = self.get_tier_config(tier)
        return config.viscosity_ns is not None


# Default instance for convenience
DEFAULT_TIER_POLICY = TierPolicy()
DEFAULT_SCREENING_TARGET_ATOMS: int = DEFAULT_TIER_POLICY.get_target_atoms("screening")
