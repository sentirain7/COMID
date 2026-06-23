"""Benchmark application service for API layer."""

from api.schemas import BenchmarkExpIdsResponse, BenchmarkReportResponse, BenchmarkValidationItem
from features.common import run_in_session


async def benchmark_expected_ids(
    seed: int | None = None,
    seeds: str | None = None,
) -> BenchmarkExpIdsResponse:
    """Return expected experiment IDs for benchmark batch jobs."""
    from orchestrator.benchmark import BenchmarkRunner

    seed_list = [int(s.strip()) for s in seeds.split(",")] if seeds else None
    ids = BenchmarkRunner.expected_exp_ids(seed=seed, seeds=seed_list)
    return BenchmarkExpIdsResponse(n_ids=len(ids), exp_ids=ids)


async def benchmark_validate(
    seed: int | None = None,
    seeds: str | None = None,
) -> BenchmarkReportResponse:
    """Validate completed benchmark experiments against references."""
    from database.repositories.experiment_repo import ExperimentRepository
    from database.repositories.metric_repo import MetricRepository
    from orchestrator.benchmark import BenchmarkRunner

    seed_list = [int(s.strip()) for s in seeds.split(",")] if seeds else None

    def _validate(session):
        exp_repo = ExperimentRepository(session)
        metric_repo = MetricRepository(session)
        runner = BenchmarkRunner(experiment_repo=exp_repo, metric_repo=metric_repo)
        return runner.validate_results(seed=seed, seeds=seed_list)

    report = run_in_session(_validate)

    summary = report.summary()
    return BenchmarkReportResponse(
        total_checks=summary["total_checks"],
        passed=summary["passed"],
        failed=summary["failed"],
        missing_data=summary["missing_data"],
        pass_rate=summary["pass_rate"],
        all_gates_passed=summary["all_gates_passed"],
        per_binder=report.per_binder_summary(),
        per_metric=report.per_metric_summary(),
        validations=[
            BenchmarkValidationItem(
                exp_id=v.exp_id,
                binder_type=v.binder_type,
                temperature_k=v.temperature_k,
                metric_name=v.metric_name,
                simulated_value=v.simulated_value,
                reference_value=v.reference_value,
                relative_error=v.relative_error,
                tolerance=v.tolerance,
                passed=v.passed,
            )
            for v in report.validations
        ],
    )
