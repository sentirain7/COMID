"""Crystal batch generation progress tracking (P2).

Separate from artifact_service._batch_progress to avoid conflicts.
In-memory store — state is lost on restart.

Codex feedback incorporated:
- acquire_batch_slot/release_batch_slot for concurrent execution guard
- init_batch_progress_queued for router-level init (202 returned before worker starts)
- start_batch_progress to transition from queued → running
- idempotent update_item_progress (previous status checked before incrementing)
- mark_batch_failed for worker exception handling
"""

import threading
from typing import Any

_progress_store: dict[str, dict] = {}
_progress_lock = threading.Lock()

# Global slot to prevent concurrent batch execution
_batch_slot_owner: str | None = None


def acquire_batch_slot(batch_id: str) -> bool:
    """Acquire the global batch slot for exclusive execution.

    Returns True if acquired, False if another batch is running.
    Used by router to prevent double-click issues.
    """
    global _batch_slot_owner
    with _progress_lock:
        if _batch_slot_owner is not None:
            return False
        _batch_slot_owner = batch_id
        return True


def release_batch_slot(batch_id: str) -> None:
    """Release the global batch slot.

    Called by worker when batch completes or fails.
    """
    global _batch_slot_owner
    with _progress_lock:
        if _batch_slot_owner == batch_id:
            _batch_slot_owner = None


def get_running_batch_id() -> str | None:
    """Get the currently running batch ID, if any."""
    with _progress_lock:
        return _batch_slot_owner


def init_batch_progress_queued(batch_id: str, items: list[str]) -> None:
    """Initialize progress as 'queued' (router-level, before worker starts).

    This ensures polling immediately after 202 sees queued status instead of not_found.
    """
    with _progress_lock:
        _progress_store[batch_id] = {
            "status": "queued",
            "batch_id": batch_id,
            "total": len(items),
            "completed": 0,
            "failed": 0,
            "skipped": 0,
            "percent": 0,
            "items": {item: {"status": "pending", "result": None} for item in items},
            "metadata": {},  # Will be set by start_batch_progress
        }


def start_batch_progress(
    batch_id: str,
    items: list[str] | None = None,
    metadata: dict | None = None,
) -> None:
    """Transition batch from 'queued' to 'running' (worker-level).

    Called at the start of background worker.
    Optionally updates items if they were not known at router time.
    Optionally sets metadata (material, surface, etc.) for response reconstruction.

    Args:
        batch_id: The batch identifier.
        items: Optional list of item labels. If provided, updates total and items.
        metadata: Optional dict with batch-level info (material, surface) for response reconstruction.
    """
    with _progress_lock:
        if batch_id in _progress_store:
            _progress_store[batch_id]["status"] = "running"
            if items is not None:
                _progress_store[batch_id]["total"] = len(items)
                _progress_store[batch_id]["items"] = {
                    item: {"status": "pending", "result": None} for item in items
                }
            if metadata is not None:
                _progress_store[batch_id]["metadata"] = metadata


def init_batch_progress(batch_id: str, items: list[str]) -> None:
    """Initialize progress tracking for a new batch.

    DEPRECATED: Use init_batch_progress_queued in router, then start_batch_progress in worker.
    Kept for backward compatibility with existing tests.
    """
    with _progress_lock:
        _progress_store[batch_id] = {
            "status": "running",
            "batch_id": batch_id,
            "total": len(items),
            "completed": 0,
            "failed": 0,
            "skipped": 0,
            "percent": 0,
            "items": {item: {"status": "pending", "result": None} for item in items},
        }


def update_item_progress(
    batch_id: str,
    item: str,
    status: str,
    result: Any = None,
) -> None:
    """Update progress for a single item (fully idempotent).

    Codex fix: Handle terminal -> terminal state changes correctly.
    Decrement previous terminal counter, then increment new terminal counter.
    """
    with _progress_lock:
        if batch_id not in _progress_store:
            return
        prog = _progress_store[batch_id]

        if item not in prog["items"]:
            return

        # Get previous status for idempotent counter update
        prev_status = prog["items"][item]["status"]
        terminal_states = {"completed", "failed", "skipped"}

        # If previous was terminal, decrement that counter first
        if prev_status in terminal_states:
            if prev_status == "completed":
                prog["completed"] = max(0, prog["completed"] - 1)
            elif prev_status == "failed":
                prog["failed"] = max(0, prog["failed"] - 1)
            elif prev_status == "skipped":
                prog["skipped"] = max(0, prog["skipped"] - 1)

        # Increment new terminal counter
        if status in terminal_states:
            if status == "completed":
                prog["completed"] += 1
            elif status == "failed":
                prog["failed"] += 1
            elif status == "skipped":
                prog["skipped"] += 1

        # Update item status
        prog["items"][item] = {"status": status, "result": result}

        # Update percent
        done = prog["completed"] + prog["failed"] + prog["skipped"]
        prog["percent"] = int(done / prog["total"] * 100) if prog["total"] > 0 else 0


def finalize_batch_progress(batch_id: str) -> None:
    """Mark batch as completed and release slot."""
    with _progress_lock:
        if batch_id not in _progress_store:
            return
        prog = _progress_store[batch_id]
        prog["percent"] = 100
        if prog["failed"] > 0:
            prog["status"] = "completed_with_errors"
        else:
            prog["status"] = "completed"

    # Release slot outside lock to avoid deadlock
    release_batch_slot(batch_id)


def mark_batch_failed(batch_id: str, error: str) -> None:
    """Mark batch as failed due to worker exception.

    Codex fix: Ensures failed status is recorded even if exception occurs
    before items are processed.
    """
    with _progress_lock:
        if batch_id not in _progress_store:
            # Create minimal progress entry if not exists
            _progress_store[batch_id] = {
                "status": "failed",
                "batch_id": batch_id,
                "total": 0,
                "completed": 0,
                "failed": 0,
                "skipped": 0,
                "percent": 0,
                "items": {},
                "error": error,
            }
        else:
            prog = _progress_store[batch_id]
            prog["status"] = "failed"
            prog["error"] = error

    # Release slot outside lock
    release_batch_slot(batch_id)


def get_batch_progress(batch_id: str) -> dict:
    """Get current progress for a batch."""
    with _progress_lock:
        if batch_id not in _progress_store:
            return {"status": "not_found", "batch_id": batch_id}
        return dict(_progress_store[batch_id])


def cleanup_batch_progress(batch_id: str) -> None:
    """Remove batch from progress store (optional cleanup)."""
    with _progress_lock:
        _progress_store.pop(batch_id, None)


def is_batch_running(batch_id: str) -> bool:
    """Check if a batch is currently running."""
    with _progress_lock:
        prog = _progress_store.get(batch_id)
        return prog is not None and prog["status"] in ("queued", "running")
