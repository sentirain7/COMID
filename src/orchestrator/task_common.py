"""Shared helpers for Celery task modules."""

import re
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from common.pathing import get_project_root
from database.connection import session_scope

T = TypeVar("T")


def _sanitize_attempt_tag(tag: str) -> str:
    """Sanitize attempt tag for filesystem-safe path segments."""
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(tag)).strip("-")
    return normalized or "unknown"


def get_experiment_work_dir(exp_id: str, attempt_tag: str | None = None) -> Path:
    """
    Get permanent work directory for experiment.

    When attempt_tag is provided, writes are isolated under:
      database/{exp_id}/attempt_{attempt_tag}
    """
    base_dir = get_project_root() / "database" / exp_id
    if attempt_tag:
        work_dir = base_dir / f"attempt_{_sanitize_attempt_tag(attempt_tag)}"
    else:
        work_dir = base_dir
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def run_in_task_session(fn: Callable) -> T:
    """Run callable with a managed DB session and return its result."""
    with session_scope() as session:
        return fn(session)


def run_in_task_session_commit(fn: Callable) -> T:
    """Run callable with managed DB session and commit before returning."""
    with session_scope() as session:
        result = fn(session)
        session.commit()
        return result


class TaskResult:
    """Standardized task result format."""

    def __init__(
        self,
        success: bool,
        exp_id: str | None = None,
        error: str | None = None,
        metrics: dict | None = None,
        duration_seconds: float = 0.0,
    ):
        self.success = success
        self.exp_id = exp_id
        self.error = error
        self.metrics = metrics or {}
        self.duration_seconds = duration_seconds

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "success": self.success,
            "exp_id": self.exp_id,
            "error": self.error,
            "metrics": self.metrics,
            "duration_seconds": self.duration_seconds,
        }
