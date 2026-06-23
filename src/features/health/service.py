"""Health and monitoring service."""

import asyncio

from api.schemas import DetailedHealthResponse
from contracts import __version__


def root() -> dict[str, str]:
    """Root endpoint payload."""
    return {"message": "Asphalt Binder MD/ML Agent API", "version": __version__}


async def health_check() -> DetailedHealthResponse:
    """Health check with infrastructure status."""
    from orchestrator.health_checker import HealthChecker

    checker = HealthChecker(timeout_seconds=2.0)
    health = await asyncio.to_thread(checker.check_all)
    db_status = (
        "connected" if health["components"]["database"]["status"] != "down" else "disconnected"
    )

    # LAMMPS capability check — only use in-process cache to avoid
    # triggering a full probe (lmp -h + GPU probe = up to 45s) from
    # the health endpoint.  If no worker has probed yet, report "not_checked".
    try:
        from orchestrator.lammps_probe import _cached_caps

        if _cached_caps is not None:
            lammps_status = f"available ({_cached_caps.accel_mode})"
        else:
            lammps_status = "not_checked"
    except Exception:
        lammps_status = "not_checked"

    return DetailedHealthResponse(
        status=health["overall"],
        severity=health["severity"],
        version=__version__,
        database=db_status,
        lammps=lammps_status,
        components=health["components"],
        can_submit_jobs=health["can_submit_jobs"],
        llm_status=_get_llm_status(),
    )


def _get_llm_status() -> str:
    """Determine LLM provider operational status.

    Returns:
        ``"ok"`` if a real provider is configured and available,
        ``"mock"`` if using the deterministic mock provider, or
        ``"degraded"`` if a real provider is configured but unreachable.
    """
    try:
        from config.settings import get_settings

        provider = (get_settings().llm.provider or "mock").lower()
        if provider == "mock":
            return "mock"

        # Attempt a lightweight client creation to verify credentials exist.
        from llm.client_factory import create_llm_client

        create_llm_client(provider=provider)
        return "ok"
    except Exception:
        return "degraded"
