"""System feature service facade.

Backwards-compatible import surface for:
- get_system_stats
- get_settings
- update_settings
- get_gpu_stats
"""

from .gpu_stats_service import get_gpu_stats
from .settings_service import get_settings, update_settings
from .stats_service import get_system_stats


async def get_lammps_caps() -> dict:
    """Get detailed LAMMPS capability information."""
    try:
        from config.settings import get_settings as _get_settings
        from orchestrator.lammps_probe import get_lammps_caps as _probe_caps
        from orchestrator.lammps_probe import get_optimization_profile

        caps = _probe_caps(_get_settings().lammps.executable)
        result = caps.model_dump(mode="json")
        result["optimization_profile"] = get_optimization_profile(caps)
        return result
    except Exception as e:
        return {"error": str(e), "accel_mode": "unknown"}


__all__ = [
    "get_system_stats",
    "get_settings",
    "update_settings",
    "get_gpu_stats",
    "get_lammps_caps",
]
