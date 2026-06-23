"""Dashboard and UI settings policy."""

from dataclasses import dataclass

from contracts.schema_enums import EIntraMethod


@dataclass(frozen=True)
class DashboardPolicy:
    """Dashboard configuration defaults (SSOT).

    These values define the default settings for the dashboard UI.
    They can be overridden at runtime via the /settings API endpoint.
    """

    # GPU Configuration
    gpu_enabled: bool = True

    # Job Configuration
    max_concurrent_jobs: int = 4
    default_tier: str = "screening"
    default_e_intra_method: str = EIntraMethod.SINGLE_MOLECULE_VACUUM.value
    auto_retry_on_failure: bool = True

    # Refresh Intervals (milliseconds)
    refresh_interval_queue_ms: int = 3000
    refresh_interval_gpu_ms: int = 3000
    refresh_interval_system_ms: int = 5000

    # Data Age Classification (seconds)
    current_session_threshold_s: int = 3600  # 1 hour
    today_threshold_s: int = 86400  # 24 hours


DEFAULT_DASHBOARD_POLICY = DashboardPolicy()
