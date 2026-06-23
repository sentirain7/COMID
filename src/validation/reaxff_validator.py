"""
ReaxFF Validator for Outlier Verification.

Runs ReaxFF simulations and compares results with bulk FF.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from common.logging import get_logger

from .reaxff_selector import OutlierCandidate

logger = get_logger("validation.reaxff_validator")


class ValidationStatus(Enum):
    """Status of a validation job."""

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ComparisonVerdict(Enum):
    """Verdict from comparing bulk FF and ReaxFF results."""

    CONSISTENT = "consistent"  # Results agree within tolerance
    DIVERGENT = "divergent"  # Significant difference
    REAXFF_UNSTABLE = "reaxff_unstable"  # ReaxFF run failed/unstable
    INCONCLUSIVE = "inconclusive"  # Cannot determine


@dataclass
class ValidationJob:
    """A ReaxFF validation job."""

    job_id: str
    candidate: OutlierCandidate
    status: ValidationStatus = ValidationStatus.PENDING

    # Job configuration
    dt_fs: float = 0.5  # ReaxFF default timestep
    npt_duration_ps: float = 500  # Shorter than bulk FF
    temperature_k: float = 298.0
    pressure_atm: float = 1.0

    # Tracking
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    # Results
    result: Optional["ValidationResult"] = None
    error_message: str | None = None


@dataclass
class ComparisonResult:
    """Result of comparing bulk FF and ReaxFF metrics."""

    metric_name: str
    bulk_ff_gaff2_value: float | None
    reaxff_value: float | None
    difference: float | None
    percent_difference: float | None
    within_tolerance: bool
    tolerance_percent: float


@dataclass
class ValidationResult:
    """Complete result of ReaxFF validation."""

    job_id: str
    exp_id: str
    validation_exp_id: str  # New experiment ID for ReaxFF run

    # Metrics
    reaxff_density: float | None = None
    reaxff_ced: float | None = None
    reaxff_energy: float | None = None

    # Stability
    is_stable: bool = True
    stability_issues: list[str] = field(default_factory=list)

    # Comparison
    comparisons: list[ComparisonResult] = field(default_factory=list)
    verdict: ComparisonVerdict = ComparisonVerdict.INCONCLUSIVE

    # Metadata
    completed_at: datetime = field(default_factory=datetime.now)
    runtime_hours: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "job_id": self.job_id,
            "exp_id": self.exp_id,
            "validation_exp_id": self.validation_exp_id,
            "reaxff_density": self.reaxff_density,
            "reaxff_ced": self.reaxff_ced,
            "is_stable": self.is_stable,
            "stability_issues": self.stability_issues,
            "comparisons": [
                {
                    "metric": c.metric_name,
                    "bulk_ff_gaff2": c.bulk_ff_gaff2_value,
                    "reaxff": c.reaxff_value,
                    "diff_percent": c.percent_difference,
                    "within_tolerance": c.within_tolerance,
                }
                for c in self.comparisons
            ],
            "verdict": self.verdict.value,
            "runtime_hours": self.runtime_hours,
        }


class ReaxFFValidator:
    """
    Validates bulk FF results using ReaxFF simulations.

    This class manages the validation workflow:
    1. Create ReaxFF jobs for selected candidates
    2. Submit and track jobs
    3. Compare results and determine verdict
    """

    # Default tolerances for comparison
    DEFAULT_TOLERANCES = {
        "density": 5.0,  # 5% difference allowed
        "ced": 10.0,  # 10% difference allowed
        "energy": 15.0,  # 15% difference allowed
    }

    def __init__(
        self,
        tolerances: dict[str, float] | None = None,
        job_submitter: Callable[[ValidationJob], str] | None = None,
    ):
        """
        Initialize validator.

        Args:
            tolerances: Metric tolerances (percent)
            job_submitter: Function to submit jobs (for testing)
        """
        self.tolerances = tolerances or self.DEFAULT_TOLERANCES.copy()
        self._job_submitter = job_submitter

        self._jobs: dict[str, ValidationJob] = {}
        self._results: dict[str, ValidationResult] = {}

    def create_validation_jobs(
        self,
        candidates: list[OutlierCandidate],
    ) -> list[ValidationJob]:
        """
        Create validation jobs for candidates.

        Args:
            candidates: List of candidates to validate

        Returns:
            List of ValidationJob
        """
        jobs = []

        for candidate in candidates:
            job_id = f"reaxff_{uuid.uuid4().hex[:12]}"

            job = ValidationJob(
                job_id=job_id,
                candidate=candidate,
                status=ValidationStatus.PENDING,
            )

            self._jobs[job_id] = job
            jobs.append(job)

            logger.info(f"Created validation job {job_id} for experiment {candidate.exp_id}")

        return jobs

    def submit_job(self, job: ValidationJob) -> bool:
        """
        Submit a validation job for execution.

        Args:
            job: ValidationJob to submit

        Returns:
            True if submitted successfully
        """
        if job.status != ValidationStatus.PENDING:
            logger.warning(f"Job {job.job_id} is not pending, cannot submit")
            return False

        try:
            if self._job_submitter:
                self._job_submitter(job)

            job.status = ValidationStatus.QUEUED
            job.started_at = datetime.now()

            logger.info(f"Submitted validation job {job.job_id}")
            return True

        except Exception as e:
            job.status = ValidationStatus.FAILED
            job.error_message = str(e)
            logger.error(f"Failed to submit job {job.job_id}: {e}")
            return False

    def submit_all(self, jobs: list[ValidationJob]) -> int:
        """
        Submit all jobs.

        Args:
            jobs: List of jobs to submit

        Returns:
            Number of successfully submitted jobs
        """
        submitted = 0
        for job in jobs:
            if self.submit_job(job):
                submitted += 1
        return submitted

    def complete_job(
        self,
        job_id: str,
        reaxff_metrics: dict[str, Any],
        bulk_ff_metrics: dict[str, Any],
        is_stable: bool = True,
        stability_issues: list[str] | None = None,
    ) -> ValidationResult:
        """
        Complete a validation job with results.

        Args:
            job_id: Job ID
            reaxff_metrics: Metrics from ReaxFF simulation
            bulk_ff_metrics: Original bulk FF metrics
            is_stable: Whether ReaxFF run was stable
            stability_issues: List of stability issues

        Returns:
            ValidationResult
        """
        job = self._jobs.get(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        job.completed_at = datetime.now()
        runtime_hours = 0.0
        if job.started_at:
            runtime_hours = (job.completed_at - job.started_at).total_seconds() / 3600

        # Generate validation experiment ID
        validation_exp_id = f"val_{job.candidate.exp_id}"

        # Compare metrics
        comparisons = self._compare_metrics(bulk_ff_metrics, reaxff_metrics)

        # Determine verdict
        verdict = self._determine_verdict(comparisons, is_stable)

        result = ValidationResult(
            job_id=job_id,
            exp_id=job.candidate.exp_id,
            validation_exp_id=validation_exp_id,
            reaxff_density=reaxff_metrics.get("density"),
            reaxff_ced=reaxff_metrics.get("ced"),
            reaxff_energy=reaxff_metrics.get("energy"),
            is_stable=is_stable,
            stability_issues=stability_issues or [],
            comparisons=comparisons,
            verdict=verdict,
            runtime_hours=runtime_hours,
        )

        job.result = result
        job.status = ValidationStatus.COMPLETED
        self._results[job_id] = result

        logger.info(f"Completed validation job {job_id} with verdict: {verdict.value}")

        return result

    def fail_job(self, job_id: str, error: str) -> None:
        """Mark a job as failed."""
        job = self._jobs.get(job_id)
        if job:
            job.status = ValidationStatus.FAILED
            job.error_message = error
            job.completed_at = datetime.now()
            logger.error(f"Validation job {job_id} failed: {error}")

    def _compare_metrics(
        self,
        bulk_ff_metrics: dict[str, Any],
        reaxff_metrics: dict[str, Any],
    ) -> list[ComparisonResult]:
        """Compare bulk FF and ReaxFF metrics."""
        comparisons = []

        for metric_name in ["density", "ced", "energy"]:
            bulk_value = bulk_ff_metrics.get(metric_name)
            reaxff_value = reaxff_metrics.get(metric_name)
            tolerance = self.tolerances.get(metric_name, 10.0)

            if bulk_value is not None and reaxff_value is not None:
                difference = reaxff_value - bulk_value
                if bulk_value != 0:
                    percent_diff = abs(difference / bulk_value) * 100
                else:
                    percent_diff = 0 if reaxff_value == 0 else 100

                within_tolerance = percent_diff <= tolerance
            else:
                difference = None
                percent_diff = None
                within_tolerance = True  # Cannot compare

            comparisons.append(
                ComparisonResult(
                    metric_name=metric_name,
                    bulk_ff_gaff2_value=bulk_value,
                    reaxff_value=reaxff_value,
                    difference=difference,
                    percent_difference=percent_diff,
                    within_tolerance=within_tolerance,
                    tolerance_percent=tolerance,
                )
            )

        return comparisons

    def _determine_verdict(
        self,
        comparisons: list[ComparisonResult],
        is_stable: bool,
    ) -> ComparisonVerdict:
        """Determine verdict from comparisons."""
        if not is_stable:
            return ComparisonVerdict.REAXFF_UNSTABLE

        # Check if we have valid comparisons
        valid_comparisons = [c for c in comparisons if c.percent_difference is not None]

        if not valid_comparisons:
            return ComparisonVerdict.INCONCLUSIVE

        # Check if all are within tolerance
        all_within = all(c.within_tolerance for c in valid_comparisons)

        if all_within:
            return ComparisonVerdict.CONSISTENT
        else:
            return ComparisonVerdict.DIVERGENT

    def get_job(self, job_id: str) -> ValidationJob | None:
        """Get job by ID."""
        return self._jobs.get(job_id)

    def get_result(self, job_id: str) -> ValidationResult | None:
        """Get result by job ID."""
        return self._results.get(job_id)

    def get_jobs_by_status(self, status: ValidationStatus) -> list[ValidationJob]:
        """Get jobs by status."""
        return [j for j in self._jobs.values() if j.status == status]

    def get_summary(self) -> dict[str, Any]:
        """Get summary of validation jobs."""
        jobs = list(self._jobs.values())
        results = list(self._results.values())

        verdict_counts = {}
        for r in results:
            v = r.verdict.value
            verdict_counts[v] = verdict_counts.get(v, 0) + 1

        return {
            "total_jobs": len(jobs),
            "pending": sum(1 for j in jobs if j.status == ValidationStatus.PENDING),
            "queued": sum(1 for j in jobs if j.status == ValidationStatus.QUEUED),
            "running": sum(1 for j in jobs if j.status == ValidationStatus.RUNNING),
            "completed": sum(1 for j in jobs if j.status == ValidationStatus.COMPLETED),
            "failed": sum(1 for j in jobs if j.status == ValidationStatus.FAILED),
            "verdicts": verdict_counts,
        }
