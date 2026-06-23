"""
GPU detection and statistics utilities.

v01.05.01 simplification: the Prometheus stack (metrics registry,
middleware, queue/system collectors) was removed. Only nvidia-smi based
GPU detection/statistics remain — these are used by the orchestrator's
GPU service and the dashboard GPU panel.
"""

from .gpu_collector import (
    GPUCollector,
    GPUStats,
    create_gpu_collector,
    detect_eligible_compute_gpus,
    detect_mig_instances,
    detect_system_gpus,
    enumerate_compute_devices,
    gpu_uuid_for,
    resolve_sharing_mode,
    total_compute_slots,
)

__all__ = [
    "GPUCollector",
    "GPUStats",
    "detect_system_gpus",
    "detect_eligible_compute_gpus",
    "enumerate_compute_devices",
    "detect_mig_instances",
    "resolve_sharing_mode",
    "total_compute_slots",
    "gpu_uuid_for",
    "create_gpu_collector",
]
