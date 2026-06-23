"""
Failure policy - SSOT for failure classification and retry strategies.

All sessions must use this policy for error handling decisions.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class FailureCategory(StrEnum):
    """Failure classification categories."""

    OVERLAP_INSTABILITY = "overlap_instability"
    PRESSURE_BLOWUP = "pressure_blowup"
    ENERGY_DRIFT = "energy_drift"
    QEQ_DIVERGENCE = "qeq_divergence"
    PACKING_OVERLAP_SUSPECTED = "packing_overlap_suspected"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


class RetryAction(StrEnum):
    """Retry action types."""

    CHANGE_SEED = "change_seed"
    REDUCE_DT = "reduce_dt"
    CHANGE_SEED_AND_REBUILD = "change_seed_and_rebuild"
    REDUCE_DT_OR_FAIL = "reduce_dt_or_fail"
    NONE = "none"


class RetryStrategy(BaseModel):
    """Configuration for a retry strategy."""

    action: RetryAction = Field(..., description="Action to take")
    dt_factor: float = Field(0.5, description="Factor to reduce dt")
    description: str = Field("", description="Human-readable description")


class FailureCategoryConfig(BaseModel):
    """Configuration for handling a failure category."""

    category: FailureCategory
    description: str
    retry_strategy: RetryAction
    indicators: list[str] = Field(default_factory=list, description="Log indicators")


class RetryPolicy(BaseModel):
    """Retry policy configuration."""

    max_retries: int = Field(2, description="Maximum retry attempts")
    strategies: list[RetryStrategy] = Field(
        default=[
            RetryStrategy(
                action=RetryAction.CHANGE_SEED, description="Try with different random seed"
            ),
            RetryStrategy(
                action=RetryAction.REDUCE_DT, dt_factor=0.5, description="Reduce timestep by 50%"
            ),
        ],
        description="Ordered list of retry strategies",
    )


class FailurePolicy(BaseModel):
    """
    Failure policy - SSOT for failure handling.

    This defines how to classify and handle simulation failures.
    """

    # Bulk FF failure policy
    bulk_ff_max_retries: int = Field(2, description="Max retries for bulk FF")
    bulk_ff_dt_min_fs: float = Field(0.25, description="Minimum dt for bulk FF")

    # ReaxFF failure policy
    reaxff_max_retries: int = Field(1, description="Max retries for ReaxFF")
    reaxff_dt_min_fs: float = Field(0.1, description="Minimum dt for ReaxFF")

    # GPU availability retry policy (for GPU_NOT_AVAILABLE errors)
    gpu_not_available_max_retries: int = Field(
        1440, description="Max retries when GPU not available (1440 × 30s = 12h)"
    )
    gpu_not_available_retry_delay_seconds: int = Field(
        30, description="Delay between GPU availability retries (seconds)"
    )

    # Failure category configurations
    failure_categories: dict[str, FailureCategoryConfig] = Field(
        default={
            "overlap_instability": FailureCategoryConfig(
                category=FailureCategory.OVERLAP_INSTABILITY,
                description="Initial structure overlap causing instability",
                retry_strategy=RetryAction.CHANGE_SEED,
                indicators=["SHAKE", "bond atoms", "missing", "Lost atoms"],
            ),
            "pressure_blowup": FailureCategoryConfig(
                category=FailureCategory.PRESSURE_BLOWUP,
                description="Pressure divergence",
                retry_strategy=RetryAction.REDUCE_DT,
                indicators=["Pressure", "diverge", "NaN", "Inf"],
            ),
            "energy_drift": FailureCategoryConfig(
                category=FailureCategory.ENERGY_DRIFT,
                description="Energy drift beyond acceptable range",
                retry_strategy=RetryAction.REDUCE_DT,
                indicators=["Energy", "drift", "conservation"],
            ),
            "qeq_divergence": FailureCategoryConfig(
                category=FailureCategory.QEQ_DIVERGENCE,
                description="ReaxFF QEq charge equilibration failed",
                retry_strategy=RetryAction.REDUCE_DT_OR_FAIL,
                indicators=["QEq", "charge", "equilibration", "not converge"],
            ),
            "packing_overlap_suspected": FailureCategoryConfig(
                category=FailureCategory.PACKING_OVERLAP_SUSPECTED,
                description="Packmol packing issues suspected",
                retry_strategy=RetryAction.CHANGE_SEED_AND_REBUILD,
                indicators=["overlap", "minimize", "max force"],
            ),
        },
        description="Failure category configurations",
    )

    # Success criteria
    energy_convergence_window_ps: float = Field(100.0, description="Window for energy check")
    energy_convergence_threshold_pct: float = Field(1.0, description="Energy variation threshold")
    density_convergence_window_ps: float = Field(200.0, description="Window for density check")
    density_convergence_threshold_pct: float = Field(0.5, description="Density variation threshold")

    # Physical bounds
    density_min: float = Field(0.2, description="Minimum valid density (g/cm3)")
    density_max: float = Field(1.3, description="Maximum valid density (g/cm3)")

    # Asphalt normal range (for quality assessment, not failure detection)
    asphalt_density_min: float = Field(0.8, description="Asphalt normal range lower bound (g/cm3)")
    asphalt_density_max: float = Field(1.3, description="Asphalt normal range upper bound (g/cm3)")

    # Physical validity range (broader than failure bounds, for sanity check)
    physical_density_min: float = Field(0.5, description="Physical validity lower bound (g/cm3)")
    physical_density_max: float = Field(2.0, description="Physical validity upper bound (g/cm3)")

    def classify_failure(
        self, log_content: str, exit_code: int, error_message: str | None = None
    ) -> FailureCategory:
        """
        Classify a failure based on log content and error.

        Args:
            log_content: LAMMPS log file content
            exit_code: LAMMPS exit code
            error_message: Optional error message

        Returns:
            Classified failure category
        """
        combined_text = f"{log_content} {error_message or ''}"

        for _cat_name, config in self.failure_categories.items():
            for indicator in config.indicators:
                if indicator.lower() in combined_text.lower():
                    return config.category

        return FailureCategory.UNKNOWN

    def get_retry_action(
        self, failure_category: FailureCategory, ff_type: str = "bulk_ff_gaff2"
    ) -> RetryAction:
        """
        Get retry action for a failure category.

        Args:
            failure_category: Classified failure
            ff_type: Force field type

        Returns:
            Recommended retry action
        """
        cat_name = failure_category.value
        if cat_name in self.failure_categories:
            return self.failure_categories[cat_name].retry_strategy
        return RetryAction.NONE

    def get_max_retries(self, ff_type: str = "bulk_ff_gaff2") -> int:
        """Get maximum retries for force field type."""
        if ff_type == "reaxff":
            return self.reaxff_max_retries
        return self.bulk_ff_max_retries

    def get_dt_min(self, ff_type: str = "bulk_ff_gaff2") -> float:
        """Get minimum timestep for force field type."""
        if ff_type == "reaxff":
            return self.reaxff_dt_min_fs
        return self.bulk_ff_dt_min_fs

    def calculate_new_dt(
        self, current_dt: float, ff_type: str = "bulk_ff_gaff2", factor: float = 0.5
    ) -> float | None:
        """
        Calculate new timestep after failure.

        Args:
            current_dt: Current timestep (fs)
            ff_type: Force field type
            factor: Reduction factor

        Returns:
            New timestep, or None if below minimum
        """
        new_dt = current_dt * factor
        dt_min = self.get_dt_min(ff_type)

        if new_dt < dt_min:
            return None
        return new_dt

    def check_density_valid(self, density: float) -> tuple[bool, str | None]:
        """
        Check if density is within valid range.

        Args:
            density: Density value (g/cm3)

        Returns:
            Tuple of (is_valid, error_message)
        """
        if density < self.density_min:
            return False, f"Density {density:.4f} below minimum {self.density_min}"
        if density > self.density_max:
            return False, f"Density {density:.4f} above maximum {self.density_max}"
        return True, None


# Default instance for convenience
DEFAULT_FAILURE_POLICY = FailurePolicy()
