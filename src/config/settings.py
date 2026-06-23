"""
Application settings - Environment configuration.

Provides centralized configuration management with support for
environment variables and defaults.
"""

import os
from pathlib import Path

# Load .env file from project root
from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

from config.llm_settings import LLMSettings
from config.tool_settings import ToolSettings
from contracts import __version__

_project_root = Path(__file__).parent.parent.parent
_env_file = _project_root / ".env"
if _env_file.exists():
    load_dotenv(_env_file)


class CelerySettings(BaseSettings):
    """Celery-specific settings."""

    broker_url: str = Field(
        default="redis://localhost:6379/0", description="Celery broker URL (Redis)"
    )
    result_backend: str = Field(
        default="redis://localhost:6379/1", description="Celery result backend URL"
    )
    task_serializer: str = Field(default="json")
    result_serializer: str = Field(default="json")
    accept_content: list[str] = Field(default=["json"])
    timezone: str = Field(default="UTC")
    enable_utc: bool = Field(default=True)

    # Task settings
    task_track_started: bool = Field(default=True)
    task_time_limit: int = Field(default=86400, description="Hard time limit for tasks (24 hours)")
    task_soft_time_limit: int = Field(
        default=82800, description="Soft time limit for tasks (23 hours)"
    )
    worker_prefetch_multiplier: int = Field(
        default=1, description="Prefetch multiplier (1 for long tasks)"
    )
    worker_concurrency: int = Field(default=4, description="Number of concurrent workers")

    # Queue configuration
    task_default_queue: str = Field(default="default")
    task_queues_names: list[str] = Field(default=["default", "simulation", "metrics", "priority"])

    class Config:
        env_prefix = "CELERY_"


class RedisSettings(BaseSettings):
    """Redis-specific settings."""

    host: str = Field(default="localhost")
    port: int = Field(default=6379)
    db: int = Field(default=0)
    password: str | None = Field(default=None)

    @property
    def url(self) -> str:
        """Build Redis URL."""
        if self.password:
            return f"redis://:{self.password}@{self.host}:{self.port}/{self.db}"
        return f"redis://{self.host}:{self.port}/{self.db}"

    class Config:
        env_prefix = "REDIS_"


class DatabaseSettings(BaseSettings):
    """Database-specific settings.

    URL resolution priority:
        1. Explicit ``DATABASE_URL`` environment variable
        2. SQLite fallback via ``database.connection.get_default_url()``

    Set ``DATABASE_URL=postgresql://user:pass@host/db`` to use PostgreSQL.
    """

    url: str | None = Field(default=None, description="Database URL (None = SQLite fallback)")
    pool_size: int = Field(default=5)
    max_overflow: int = Field(default=10)

    class Config:
        env_prefix = "DATABASE_"


class LAMMPSSettings(BaseSettings):
    """LAMMPS execution settings."""

    executable: str = Field(default="lmp", description="LAMMPS executable path")
    mpi_command: str = Field(default="mpirun", description="MPI command")
    gpu_package: str = Field(default="kokkos", description="GPU package (kokkos or gpu)")
    default_num_gpus: int = Field(default=1)
    default_num_procs: int = Field(default=1)

    class Config:
        env_prefix = "LAMMPS_"


class TypingChargeSettings(BaseSettings):
    """Atom typing and partial charge assignment settings."""

    enabled: bool = Field(default=True)
    charge_model_primary: str = Field(default="am1_bcc")
    charge_model_fallback: str = Field(default="am1_bcc")
    strict_param_coverage: bool = Field(default=False)
    total_charge_tolerance: float = Field(
        default=0.2, gt=0.0, description="Allowed abs(sum(partial)-formal) in e"
    )

    class Config:
        env_prefix = "TYPING_CHARGE_"


class Settings(BaseSettings):
    """Main application settings."""

    # Application info
    app_name: str = Field(default="asphalt-binder-agent")
    app_version: str = Field(default=__version__)
    debug: bool = Field(default=False)
    auto_resubmit_pending_on_startup: bool = Field(
        default=False,
        description="Auto-resubmit pending experiments on API startup",
    )

    # Paths
    base_dir: str = Field(
        default_factory=lambda: os.getcwd(), description="Base directory for data"
    )
    data_dir: str = Field(default="data")
    output_dir: str = Field(default="output")
    log_dir: str = Field(default="logs")

    # Sub-settings
    celery: CelerySettings = Field(default_factory=CelerySettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    lammps: LAMMPSSettings = Field(default_factory=LAMMPSSettings)
    typing_charge: TypingChargeSettings = Field(default_factory=TypingChargeSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    tools: ToolSettings = Field(default_factory=ToolSettings)

    class Config:
        env_prefix = "APP_"
        env_nested_delimiter = "__"


# Global settings instance
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get or create settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Reset settings (for testing)."""
    global _settings
    _settings = None
