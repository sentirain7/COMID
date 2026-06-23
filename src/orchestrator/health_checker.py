"""Infrastructure health checker.

Provides health checks for Redis, Celery workers, and database.
Used by API to validate infrastructure before job submission.
"""

import time
from dataclasses import dataclass
from enum import StrEnum

from common.logging import get_logger

logger = get_logger("orchestrator.health_checker")


class HealthStatus(StrEnum):
    """Service state enumeration for health checks."""

    READY = "ready"
    LIMITED = "limited"
    DOWN = "down"


@dataclass
class ComponentHealth:
    """Health status for a single component."""

    name: str
    status: HealthStatus
    message: str
    latency_ms: float | None = None


class HealthChecker:
    """Check health of Redis, Celery workers, and database.

    Args:
        timeout_seconds: Timeout for health checks (default 2.0 for UI responsiveness)
    """

    def __init__(self, timeout_seconds: float = 2.0):
        self.timeout = timeout_seconds
        self._latency_warn_ms = {
            "redis": 100.0,
            "database": 150.0,
            # v00.99.95: 1500 → 2500 ms. v00.99.63 raised the Celery ping
            # timeout from 0.5 s to 2.0 s (to avoid false "down" during FF
            # batches) but left this threshold at 1500 ms, so every healthy
            # ping (which always waits the full timeout because
            # inspect.ping() issues broadcast without `limit`) reported as
            # LIMITED. Keep the threshold strictly above the timeout so
            # only broker / worker stalls — not the inherent broadcast
            # collection window — trip the warn state.
            "celery_workers": 2500.0,
        }

    def _status_from_latency(self, component: str, latency_ms: float) -> HealthStatus:
        """Map latency to ready/limited state."""
        warn_threshold = self._latency_warn_ms.get(component, 200.0)
        return HealthStatus.READY if latency_ms <= warn_threshold else HealthStatus.LIMITED

    def check_redis(self) -> ComponentHealth:
        """Check Redis broker connectivity.

        Returns:
            ComponentHealth with Redis status
        """
        start = time.time()
        try:
            import redis

            from config.settings import get_settings

            settings = get_settings()
            # Parse broker URL (redis://host:port/db)
            client = redis.from_url(settings.celery.broker_url, socket_timeout=self.timeout)
            client.ping()
            latency = (time.time() - start) * 1000
            return ComponentHealth(
                name="redis",
                status=self._status_from_latency("redis", latency),
                message="Connected",
                latency_ms=latency,
            )
        except Exception as e:
            logger.warning(f"Redis health check failed: {e}")
            return ComponentHealth(name="redis", status=HealthStatus.DOWN, message=str(e))

    def check_celery_workers(self) -> ComponentHealth:
        """Check if Celery workers are responding.

        Returns:
            ComponentHealth with Celery worker status
        """
        start = time.time()
        try:
            from orchestrator.celery_app import celery_app

            # ping is a faster liveness check than active(), which can wait
            # near timeout even when workers are healthy.
            ping_timeout = self.timeout
            inspect = celery_app.control.inspect(timeout=ping_timeout)
            pong = inspect.ping()

            latency = (time.time() - start) * 1000

            if pong is None:
                return ComponentHealth(
                    name="celery_workers",
                    status=HealthStatus.DOWN,
                    message="No workers responding",
                    latency_ms=latency,
                )

            worker_count = len(pong)

            if worker_count == 0:
                return ComponentHealth(
                    name="celery_workers",
                    status=HealthStatus.DOWN,
                    message="No active workers",
                    latency_ms=latency,
                )

            return ComponentHealth(
                name="celery_workers",
                status=self._status_from_latency("celery_workers", latency),
                message=f"{worker_count} worker(s) active",
                latency_ms=latency,
            )
        except Exception as e:
            logger.warning(f"Celery worker health check failed: {e}")
            return ComponentHealth(name="celery_workers", status=HealthStatus.DOWN, message=str(e))

    def check_database(self) -> ComponentHealth:
        """Check database connectivity.

        Returns:
            ComponentHealth with database status
        """
        start = time.time()
        try:
            from sqlalchemy import text

            from database.connection import get_engine

            engine = get_engine()
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))

            latency = (time.time() - start) * 1000
            return ComponentHealth(
                name="database",
                status=self._status_from_latency("database", latency),
                message="Connected",
                latency_ms=latency,
            )
        except Exception as e:
            logger.warning(f"Database health check failed: {e}")
            return ComponentHealth(name="database", status=HealthStatus.DOWN, message=str(e))

    def check_all(self) -> dict:
        """Check all components and return summary.

        Returns:
            Dict with overall status, components, and can_submit_jobs flag
        """
        redis_health = self.check_redis()
        celery_health = self.check_celery_workers()
        db_health = self.check_database()

        components = {
            "redis": {
                "status": redis_health.status.value,
                "message": redis_health.message,
                "latency_ms": redis_health.latency_ms,
            },
            "celery_workers": {
                "status": celery_health.status.value,
                "message": celery_health.message,
                "latency_ms": celery_health.latency_ms,
            },
            "database": {
                "status": db_health.status.value,
                "message": db_health.message,
                "latency_ms": db_health.latency_ms,
            },
        }

        # Determine overall state and severity.
        statuses = [redis_health.status, celery_health.status, db_health.status]
        if any(s == HealthStatus.DOWN for s in statuses):
            overall = HealthStatus.DOWN.value
            severity = "critical"
        elif any(s == HealthStatus.LIMITED for s in statuses):
            overall = HealthStatus.LIMITED.value
            severity = "warn"
        else:
            overall = HealthStatus.READY.value
            severity = "ok"

        # Job submission requires Redis + Celery not down.
        can_submit = (
            redis_health.status != HealthStatus.DOWN and celery_health.status != HealthStatus.DOWN
        )

        return {
            "overall": overall,
            "severity": severity,
            "components": components,
            "can_submit_jobs": can_submit,
        }
