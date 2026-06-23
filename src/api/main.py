"""Compatibility entrypoint for FastAPI app bootstrap."""

from api.application import app, run_server
from features.batch_job_binder_cell.service import (
    create_batch_job_binder_cell,
    validate_batch_job_binder_cell,
)

__all__ = ["app", "run_server", "validate_batch_job_binder_cell", "create_batch_job_binder_cell"]


if __name__ == "__main__":
    run_server()
