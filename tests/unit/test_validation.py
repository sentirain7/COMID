"""
Unit tests for ReaxFF Validation Module.
"""

import pytest

from validation import (
    ComparisonResult,
    OutlierCandidate,
    ReaxFFSelector,
    ReaxFFValidator,
    SelectionCriteria,
    ValidationJob,
    ValidationStatus,
)
from validation.reaxff_selector import SelectionReason
from validation.reaxff_validator import ComparisonVerdict


class TestSelectionCriteria:
    """Tests for SelectionCriteria."""

    def test_default_values(self):
        """Test default criteria values."""
        criteria = SelectionCriteria()

        assert criteria.density_zscore_threshold == 2.0
        assert criteria.ced_zscore_threshold == 2.0
        assert criteria.max_selections_per_batch == 5
        assert criteria.minimum_bulk_ff_runs == 50
        assert "energy_drift" in criteria.stability_flags

    def test_custom_values(self):
        """Test custom criteria values."""
        criteria = SelectionCriteria(
            density_zscore_threshold=3.0,
            max_selections_per_batch=10,
        )

        assert criteria.density_zscore_threshold == 3.0
        assert criteria.max_selections_per_batch == 10


class TestReaxFFSelector:
    """Tests for ReaxFFSelector."""

    @pytest.fixture
    def sample_experiments(self):
        """Generate sample experiment data."""
        # Create 60 experiments with realistic metrics
        experiments = []
        for i in range(60):
            exp = {
                "exp_id": f"exp_{i:03d}",
                "run_tier": "screening",
                "composition": {
                    "asphaltene": 0.20,
                    "resin": 0.30,
                    "aromatic": 0.35,
                    "saturate": 0.15,
                },
                "metrics": {
                    "density": 1.0 + (i % 10) * 0.01,  # 1.0 to 1.09
                    "ced": 280 + (i % 20) * 2,  # 280 to 318
                },
            }
            experiments.append(exp)

        return experiments

    @pytest.fixture
    def experiments_with_outliers(self, sample_experiments):
        """Add outliers to sample experiments."""
        experiments = sample_experiments.copy()

        # Add high density outlier
        experiments.append(
            {
                "exp_id": "exp_outlier_1",
                "run_tier": "screening",
                "composition": {},
                "metrics": {"density": 1.5, "ced": 300},  # Very high density
            }
        )

        # Add low CED outlier
        experiments.append(
            {
                "exp_id": "exp_outlier_2",
                "run_tier": "screening",
                "composition": {},
                "metrics": {"density": 1.05, "ced": 200},  # Very low CED
            }
        )

        # Add stability flag outlier
        experiments.append(
            {
                "exp_id": "exp_outlier_3",
                "run_tier": "screening",
                "composition": {},
                "metrics": {"density": 1.05, "ced": 300},
                "stability_flag": "energy_drift",
            }
        )

        return experiments

    def test_init_default(self):
        """Test default initialization."""
        selector = ReaxFFSelector()

        assert selector.criteria.density_zscore_threshold == 2.0

    def test_init_custom_criteria(self):
        """Test custom criteria initialization."""
        criteria = SelectionCriteria(density_zscore_threshold=3.0)
        selector = ReaxFFSelector(criteria=criteria)

        assert selector.criteria.density_zscore_threshold == 3.0

    def test_insufficient_data(self):
        """Test handling of insufficient data."""
        selector = ReaxFFSelector()

        # Only 10 experiments (below 50 minimum)
        experiments = [{"exp_id": f"exp_{i}"} for i in range(10)]
        result = selector.select_candidates(experiments)

        assert len(result.candidates) == 0
        assert result.statistics.get("error") == "insufficient_data"

    def test_no_outliers(self, sample_experiments):
        """Test when no outliers are present."""
        selector = ReaxFFSelector()

        result = selector.select_candidates(sample_experiments)

        # All values are within normal range, so few or no selections
        assert result.total_evaluated == len(sample_experiments)

    def test_detect_density_outlier(self, experiments_with_outliers):
        """Test detection of density outliers."""
        selector = ReaxFFSelector()

        result = selector.select_candidates(experiments_with_outliers)

        # Should detect the high density outlier
        outlier_ids = [c.exp_id for c in result.candidates]
        assert "exp_outlier_1" in outlier_ids

    def test_detect_ced_outlier(self, experiments_with_outliers):
        """Test detection of CED outliers."""
        selector = ReaxFFSelector()

        result = selector.select_candidates(experiments_with_outliers)

        # Should detect the low CED outlier
        outlier_ids = [c.exp_id for c in result.candidates]
        assert "exp_outlier_2" in outlier_ids

    def test_detect_stability_flag(self, experiments_with_outliers):
        """Test detection of stability flag outliers."""
        selector = ReaxFFSelector()

        result = selector.select_candidates(experiments_with_outliers)

        # Should detect the stability flag outlier
        outlier_ids = [c.exp_id for c in result.candidates]
        assert "exp_outlier_3" in outlier_ids

    def test_selection_cap(self, experiments_with_outliers):
        """Test selection cap is applied."""
        criteria = SelectionCriteria(max_selections_per_batch=2)
        selector = ReaxFFSelector(criteria=criteria)

        result = selector.select_candidates(experiments_with_outliers)

        assert len(result.candidates) <= 2
        assert result.selection_cap_reached or len(result.candidates) <= 2

    def test_priority_scoring(self, experiments_with_outliers):
        """Test priority scoring of candidates."""
        selector = ReaxFFSelector()

        result = selector.select_candidates(experiments_with_outliers)

        # Candidates should be sorted by priority
        if len(result.candidates) >= 2:
            for i in range(len(result.candidates) - 1):
                assert (
                    result.candidates[i].priority_score >= result.candidates[i + 1].priority_score
                )

    def test_statistics(self, sample_experiments):
        """Test statistics calculation."""
        selector = ReaxFFSelector()

        selector.select_candidates(sample_experiments)
        stats = selector.get_statistics()

        assert "n_samples" in stats
        assert "density" in stats
        assert stats["density"]["mean"] > 0
        assert stats["density"]["std"] > 0

    def test_manual_selection(self, sample_experiments):
        """Test manual selection."""
        selector = ReaxFFSelector()

        candidates = selector.select_manual(
            ["exp_000", "exp_001"],
            sample_experiments,
        )

        assert len(candidates) == 2
        assert candidates[0].exp_id == "exp_000"
        assert SelectionReason.MANUAL in candidates[0].selection_reasons


class TestOutlierCandidate:
    """Tests for OutlierCandidate."""

    def test_create(self):
        """Test creating a candidate."""
        candidate = OutlierCandidate(
            exp_id="exp_001",
            run_tier="screening",
            composition={"asphaltene": 0.2},
            density=1.05,
            density_zscore=2.5,
        )

        assert candidate.exp_id == "exp_001"
        assert candidate.density == 1.05
        assert candidate.density_zscore == 2.5


class TestValidationJob:
    """Tests for ValidationJob."""

    def test_create(self):
        """Test creating a job."""
        candidate = OutlierCandidate(
            exp_id="exp_001",
            run_tier="screening",
            composition={},
        )

        job = ValidationJob(
            job_id="reaxff_001",
            candidate=candidate,
        )

        assert job.job_id == "reaxff_001"
        assert job.status == ValidationStatus.PENDING
        assert job.dt_fs == 0.5


class TestReaxFFValidator:
    """Tests for ReaxFFValidator."""

    @pytest.fixture
    def sample_candidates(self):
        """Create sample candidates."""
        return [
            OutlierCandidate(
                exp_id="exp_001",
                run_tier="screening",
                composition={"asphaltene": 0.2},
                density=1.5,
                density_zscore=3.0,
            ),
            OutlierCandidate(
                exp_id="exp_002",
                run_tier="screening",
                composition={"asphaltene": 0.25},
                ced=200,
                ced_zscore=-3.0,
            ),
        ]

    def test_init_default(self):
        """Test default initialization."""
        validator = ReaxFFValidator()

        assert validator.tolerances["density"] == 5.0
        assert validator.tolerances["ced"] == 10.0

    def test_init_custom_tolerances(self):
        """Test custom tolerances."""
        validator = ReaxFFValidator(tolerances={"density": 10.0})

        assert validator.tolerances["density"] == 10.0

    def test_create_validation_jobs(self, sample_candidates):
        """Test creating validation jobs."""
        validator = ReaxFFValidator()

        jobs = validator.create_validation_jobs(sample_candidates)

        assert len(jobs) == 2
        assert all(j.status == ValidationStatus.PENDING for j in jobs)
        assert jobs[0].candidate.exp_id == "exp_001"

    def test_submit_job(self, sample_candidates):
        """Test submitting a job."""
        validator = ReaxFFValidator()
        jobs = validator.create_validation_jobs(sample_candidates)

        result = validator.submit_job(jobs[0])

        assert result is True
        assert jobs[0].status == ValidationStatus.QUEUED
        assert jobs[0].started_at is not None

    def test_submit_already_running(self, sample_candidates):
        """Test submitting already running job."""
        validator = ReaxFFValidator()
        jobs = validator.create_validation_jobs(sample_candidates)

        validator.submit_job(jobs[0])
        result = validator.submit_job(jobs[0])  # Submit again

        assert result is False

    def test_submit_all(self, sample_candidates):
        """Test submitting all jobs."""
        validator = ReaxFFValidator()
        jobs = validator.create_validation_jobs(sample_candidates)

        count = validator.submit_all(jobs)

        assert count == 2

    def test_complete_job_consistent(self, sample_candidates):
        """Test completing job with consistent results."""
        validator = ReaxFFValidator()
        jobs = validator.create_validation_jobs(sample_candidates)
        validator.submit_job(jobs[0])

        result = validator.complete_job(
            jobs[0].job_id,
            reaxff_metrics={"density": 1.52, "ced": 305},  # Within 5% of bulk
            bulk_ff_metrics={"density": 1.50, "ced": 300},
        )

        assert result.verdict == ComparisonVerdict.CONSISTENT
        assert result.is_stable
        assert jobs[0].status == ValidationStatus.COMPLETED

    def test_complete_job_divergent(self, sample_candidates):
        """Test completing job with divergent results."""
        validator = ReaxFFValidator()
        jobs = validator.create_validation_jobs(sample_candidates)
        validator.submit_job(jobs[0])

        result = validator.complete_job(
            jobs[0].job_id,
            reaxff_metrics={"density": 1.2, "ced": 350},  # Very different
            bulk_ff_metrics={"density": 1.5, "ced": 300},
        )

        assert result.verdict == ComparisonVerdict.DIVERGENT

    def test_complete_job_unstable(self, sample_candidates):
        """Test completing job with unstable ReaxFF."""
        validator = ReaxFFValidator()
        jobs = validator.create_validation_jobs(sample_candidates)
        validator.submit_job(jobs[0])

        result = validator.complete_job(
            jobs[0].job_id,
            reaxff_metrics={"density": 1.0, "ced": 200},
            bulk_ff_metrics={"density": 1.5, "ced": 300},
            is_stable=False,
            stability_issues=["energy_drift"],
        )

        assert result.verdict == ComparisonVerdict.REAXFF_UNSTABLE
        assert not result.is_stable

    def test_fail_job(self, sample_candidates):
        """Test failing a job."""
        validator = ReaxFFValidator()
        jobs = validator.create_validation_jobs(sample_candidates)
        validator.submit_job(jobs[0])

        validator.fail_job(jobs[0].job_id, "Simulation crashed")

        assert jobs[0].status == ValidationStatus.FAILED
        assert jobs[0].error_message == "Simulation crashed"

    def test_get_job(self, sample_candidates):
        """Test getting a job."""
        validator = ReaxFFValidator()
        jobs = validator.create_validation_jobs(sample_candidates)

        retrieved = validator.get_job(jobs[0].job_id)

        assert retrieved is not None
        assert retrieved.job_id == jobs[0].job_id

    def test_get_jobs_by_status(self, sample_candidates):
        """Test getting jobs by status."""
        validator = ReaxFFValidator()
        jobs = validator.create_validation_jobs(sample_candidates)
        validator.submit_job(jobs[0])

        pending = validator.get_jobs_by_status(ValidationStatus.PENDING)
        queued = validator.get_jobs_by_status(ValidationStatus.QUEUED)

        assert len(pending) == 1
        assert len(queued) == 1

    def test_get_summary(self, sample_candidates):
        """Test getting summary."""
        validator = ReaxFFValidator()
        jobs = validator.create_validation_jobs(sample_candidates)
        validator.submit_job(jobs[0])

        summary = validator.get_summary()

        assert summary["total_jobs"] == 2
        assert summary["pending"] == 1
        assert summary["queued"] == 1

    def test_result_to_dict(self, sample_candidates):
        """Test ValidationResult.to_dict()."""
        validator = ReaxFFValidator()
        jobs = validator.create_validation_jobs(sample_candidates)
        validator.submit_job(jobs[0])

        result = validator.complete_job(
            jobs[0].job_id,
            reaxff_metrics={"density": 1.52},
            bulk_ff_metrics={"density": 1.50},
        )

        d = result.to_dict()

        assert "job_id" in d
        assert "verdict" in d
        assert "comparisons" in d


class TestComparisonResult:
    """Tests for ComparisonResult."""

    def test_create(self):
        """Test creating comparison result."""
        comp = ComparisonResult(
            metric_name="density",
            bulk_ff_gaff2_value=1.0,
            reaxff_value=1.05,
            difference=0.05,
            percent_difference=5.0,
            within_tolerance=True,
            tolerance_percent=10.0,
        )

        assert comp.metric_name == "density"
        assert comp.within_tolerance


class TestIntegration:
    """Integration tests for validation module."""

    def test_full_workflow(self):
        """Test complete validation workflow."""
        # Create experiments
        experiments = []
        for i in range(60):
            experiments.append(
                {
                    "exp_id": f"exp_{i:03d}",
                    "run_tier": "screening",
                    "composition": {},
                    "metrics": {"density": 1.0 + i * 0.001, "ced": 300 + i * 0.5},
                }
            )

        # Add outlier
        experiments.append(
            {
                "exp_id": "exp_outlier",
                "run_tier": "screening",
                "composition": {},
                "metrics": {"density": 1.5, "ced": 400},
            }
        )

        # Select candidates
        selector = ReaxFFSelector()
        selection = selector.select_candidates(experiments)

        assert selection.total_selected > 0
        assert "exp_outlier" in [c.exp_id for c in selection.candidates]

        # Create validation jobs
        validator = ReaxFFValidator()
        jobs = validator.create_validation_jobs(selection.candidates)

        # Submit and complete
        for job in jobs:
            validator.submit_job(job)

            # Simulate completion
            validator.complete_job(
                job.job_id,
                reaxff_metrics={"density": 1.48, "ced": 395},  # Slightly different
                bulk_ff_metrics=job.candidate.__dict__,
            )

        # Check summary
        summary = validator.get_summary()
        assert summary["completed"] == len(jobs)
