"""Benchmark API routes."""

from fastapi import APIRouter

from api.schemas import BenchmarkExpIdsResponse, BenchmarkReportResponse

from . import service as benchmark_service

router = APIRouter(tags=["Benchmark"])


@router.get("/benchmark/expected-ids", response_model=BenchmarkExpIdsResponse)
async def benchmark_expected_ids(seed: int | None = None, seeds: str | None = None):
    """Return expected experiment IDs for benchmark batch jobs."""
    return await benchmark_service.benchmark_expected_ids(seed=seed, seeds=seeds)


@router.get("/benchmark/validate", response_model=BenchmarkReportResponse)
async def benchmark_validate(seed: int | None = None, seeds: str | None = None):
    """Validate completed benchmark experiments against references."""
    return await benchmark_service.benchmark_validate(seed=seed, seeds=seeds)
