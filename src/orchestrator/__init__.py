"""
Orchestrator module - Pipeline execution and job management.

This module contains the core pipeline implementation for running
MD simulations from specification to metrics.

Supports both in-memory job management and distributed Celery-based execution.
"""

try:
    from orchestrator.celery_job_manager import CeleryJob, CeleryJobManager, CeleryJobStatus
except ImportError:  # celery not installed
    CeleryJob = None  # type: ignore[assignment,misc]
    CeleryJobManager = None  # type: ignore[assignment,misc]
    CeleryJobStatus = None  # type: ignore[assignment,misc]

from orchestrator.benchmark import BenchmarkReport, BenchmarkRunner, MetricValidation
from orchestrator.gpu_service import (
    GPUInfo,
    GPUService,
    GPUStatus,
    get_gpu_service,
    reset_gpu_service,
)
from orchestrator.lammps_runner import LAMMPSConfig, LAMMPSRunner, MockLAMMPSRunner
from orchestrator.pipeline import Pipeline

__all__ = [
    # Pipeline
    "Pipeline",
    # LAMMPS Runner
    "LAMMPSRunner",
    "MockLAMMPSRunner",
    "LAMMPSConfig",
    # Celery Job Manager
    "CeleryJobManager",
    "CeleryJob",
    "CeleryJobStatus",
    # GPU Service (recommended)
    "GPUService",
    "GPUInfo",
    "GPUStatus",
    "get_gpu_service",
    "reset_gpu_service",
    # Benchmark
    "BenchmarkRunner",
    "BenchmarkReport",
    "MetricValidation",
]
