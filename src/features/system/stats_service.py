"""System statistics service."""

import asyncio

from common.logging import get_logger

logger = get_logger("features.system")


def _get_system_stats_sync() -> dict[str, float]:
    """Synchronous implementation of system stats collection."""
    import psutil

    return {
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "memory_percent": psutil.virtual_memory().percent,
        "disk_percent": psutil.disk_usage("/").percent,
    }


async def get_system_stats() -> dict[str, float]:
    """Get system resource usage (CPU, Memory, Disk)."""
    try:
        return await asyncio.to_thread(_get_system_stats_sync)
    except ImportError:
        return {
            "cpu_percent": 0.0,
            "memory_percent": 0.0,
            "disk_percent": 0.0,
        }
