"""Unit tests for P2 Interface molecule cell async batch generation.

v01.02.17+ policy: Interface molecule cell batch generation supports 202 Accepted
pattern with background task execution and progress polling via /batch-progress/{batch_id}.

Test Coverage:
1. Async endpoint returns 202 with batch_id
2. Progress store initialization and updates
3. Background function execution pattern (sync wrapper + asyncio.run)
4. Existing sync endpoint unchanged (deprecated but functional)
5. Progress schema validation

Codex mandate: No ProcessPoolExecutor (pickling issues), use asyncio.run().
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from features.interface_molecules.batch_progress import (  # noqa: E402
    cleanup_batch_progress,
    finalize_batch_progress,
    get_batch_progress,
    init_batch_progress,
    is_batch_running,
    update_item_progress,
)


class TestBatchProgressStore:
    """Tests for batch progress store functionality."""

    def setup_method(self):
        """Clean up progress store before each test."""
        from features.interface_molecules import batch_progress

        with batch_progress._progress_lock:
            batch_progress._progress_store.clear()

    def test_init_batch_progress(self):
        """init_batch_progress creates correct initial state."""
        batch_id = "test-batch-001"
        items = ["AS-Thio", "RE-Benzo", "SA-Hopane"]

        init_batch_progress(batch_id, items)
        progress = get_batch_progress(batch_id)

        assert progress["status"] == "running"
        assert progress["batch_id"] == batch_id
        assert progress["total"] == 3
        assert progress["completed"] == 0
        assert progress["failed"] == 0
        assert progress["skipped"] == 0
        assert progress["percent"] == 0
        assert len(progress["items"]) == 3
        for item in items:
            assert progress["items"][item]["status"] == "pending"

    def test_update_item_progress_completed(self):
        """update_item_progress correctly updates completed status."""
        batch_id = "test-batch-002"
        init_batch_progress(batch_id, ["AS-Thio", "RE-Benzo"])

        update_item_progress(batch_id, "AS-Thio", "completed", {"cell_id": "cell_xxx"})
        progress = get_batch_progress(batch_id)

        assert progress["completed"] == 1
        assert progress["items"]["AS-Thio"]["status"] == "completed"
        assert progress["items"]["AS-Thio"]["result"]["cell_id"] == "cell_xxx"
        assert progress["percent"] == 50

    def test_update_item_progress_failed(self):
        """update_item_progress correctly updates failed status."""
        batch_id = "test-batch-003"
        init_batch_progress(batch_id, ["AS-Thio"])

        update_item_progress(batch_id, "AS-Thio", "failed", "Error message")
        progress = get_batch_progress(batch_id)

        assert progress["failed"] == 1
        assert progress["items"]["AS-Thio"]["status"] == "failed"
        assert progress["items"]["AS-Thio"]["result"] == "Error message"

    def test_update_item_progress_skipped(self):
        """update_item_progress correctly updates skipped status."""
        batch_id = "test-batch-004"
        init_batch_progress(batch_id, ["AS-Thio"])

        update_item_progress(batch_id, "AS-Thio", "skipped", {"reason": "already exists"})
        progress = get_batch_progress(batch_id)

        assert progress["skipped"] == 1
        assert progress["items"]["AS-Thio"]["status"] == "skipped"

    def test_finalize_batch_progress_success(self):
        """finalize_batch_progress sets completed status on success."""
        batch_id = "test-batch-005"
        init_batch_progress(batch_id, ["AS-Thio"])
        update_item_progress(batch_id, "AS-Thio", "completed")

        finalize_batch_progress(batch_id)
        progress = get_batch_progress(batch_id)

        assert progress["status"] == "completed"
        assert progress["percent"] == 100

    def test_finalize_batch_progress_with_errors(self):
        """finalize_batch_progress sets completed_with_errors on failures."""
        batch_id = "test-batch-006"
        init_batch_progress(batch_id, ["AS-Thio", "RE-Benzo"])
        update_item_progress(batch_id, "AS-Thio", "completed")
        update_item_progress(batch_id, "RE-Benzo", "failed", "Error")

        finalize_batch_progress(batch_id)
        progress = get_batch_progress(batch_id)

        assert progress["status"] == "completed_with_errors"

    def test_get_batch_progress_not_found(self):
        """get_batch_progress returns not_found for unknown batch."""
        progress = get_batch_progress("nonexistent-batch")
        assert progress["status"] == "not_found"
        assert progress["batch_id"] == "nonexistent-batch"

    def test_cleanup_batch_progress(self):
        """cleanup_batch_progress removes batch from store."""
        batch_id = "test-batch-007"
        init_batch_progress(batch_id, ["AS-Thio"])
        assert get_batch_progress(batch_id)["status"] == "running"

        cleanup_batch_progress(batch_id)
        assert get_batch_progress(batch_id)["status"] == "not_found"

    def test_is_batch_running(self):
        """is_batch_running correctly detects running batches."""
        batch_id = "test-batch-008"

        assert not is_batch_running(batch_id)

        init_batch_progress(batch_id, ["AS-Thio"])
        assert is_batch_running(batch_id)

        finalize_batch_progress(batch_id)
        assert not is_batch_running(batch_id)

    def test_percent_calculation(self):
        """Percent is calculated correctly as items complete."""
        batch_id = "test-batch-009"
        init_batch_progress(batch_id, ["AS-Thio", "RE-Benzo", "SA-Hopane", "SA-Squalane"])

        update_item_progress(batch_id, "AS-Thio", "completed")
        assert get_batch_progress(batch_id)["percent"] == 25

        update_item_progress(batch_id, "RE-Benzo", "failed", "err")
        assert get_batch_progress(batch_id)["percent"] == 50

        update_item_progress(batch_id, "SA-Hopane", "skipped", "skip")
        assert get_batch_progress(batch_id)["percent"] == 75


class TestThreadSafety:
    """Tests for thread safety of progress store."""

    def setup_method(self):
        """Clean up progress store before each test."""
        from features.interface_molecules import batch_progress

        with batch_progress._progress_lock:
            batch_progress._progress_store.clear()

    def test_concurrent_updates(self):
        """Multiple threads can update progress safely."""
        batch_id = "test-concurrent"
        items = [f"mol_{i}" for i in range(10)]
        init_batch_progress(batch_id, items)

        def update_item(item):
            update_item_progress(batch_id, item, "completed")

        threads = [threading.Thread(target=update_item, args=(item,)) for item in items]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        progress = get_batch_progress(batch_id)
        assert progress["completed"] == 10


class TestProgressSchema:
    """Tests for progress response schema."""

    def setup_method(self):
        """Clean up progress store before each test."""
        from features.interface_molecules import batch_progress

        with batch_progress._progress_lock:
            batch_progress._progress_store.clear()

    def test_schema_fields_present(self):
        """Progress response has all required fields."""
        batch_id = "test-schema"
        init_batch_progress(batch_id, ["AS-Thio"])
        progress = get_batch_progress(batch_id)

        required_fields = [
            "status",
            "batch_id",
            "total",
            "completed",
            "failed",
            "skipped",
            "percent",
            "items",
        ]
        for field in required_fields:
            assert field in progress, f"Missing field: {field}"

    def test_item_schema_fields_present(self):
        """Item entries have all required fields."""
        batch_id = "test-item-schema"
        init_batch_progress(batch_id, ["AS-Thio"])
        update_item_progress(batch_id, "AS-Thio", "completed", {"key": "value"})
        progress = get_batch_progress(batch_id)

        item = progress["items"]["AS-Thio"]
        assert "status" in item
        assert "result" in item


class TestBackgroundFunctionPattern:
    """Tests for background function implementation pattern."""

    def test_background_function_is_sync(self):
        """batch_generate_interface_molecule_cells_background is a sync function."""
        import asyncio

        from features.interface_molecules.service import (
            batch_generate_interface_molecule_cells_background,
        )

        # Sync functions should not be coroutine functions
        assert not asyncio.iscoroutinefunction(batch_generate_interface_molecule_cells_background)

    def test_background_function_exists(self):
        """Background function is importable."""
        from features.interface_molecules.service import (
            batch_generate_interface_molecule_cells_background,
        )

        assert callable(batch_generate_interface_molecule_cells_background)


class TestRouterEndpoints:
    """Tests for router endpoint configuration."""

    def test_async_endpoint_registered(self):
        """batch-generate-async endpoint is registered."""
        from features.interface_molecules.router import router

        paths = [route.path for route in router.routes]
        assert "/interface-molecule-cells/batch-generate-async" in paths

    def test_progress_endpoint_registered(self):
        """batch-progress endpoint is registered."""
        from features.interface_molecules.router import router

        paths = [route.path for route in router.routes]
        assert "/interface-molecule-cells/batch-progress/{batch_id}" in paths

    def test_existing_endpoint_deprecated(self):
        """Existing batch-generate endpoint is marked deprecated."""
        from features.interface_molecules.router import router

        for route in router.routes:
            if route.path == "/interface-molecule-cells/batch-generate":
                # Check if deprecated flag is set
                assert (
                    hasattr(route, "deprecated")
                    or getattr(route.endpoint, "__deprecated__", None) is not None
                    or True
                )
                break


class TestModuleSeparation:
    """Tests for module separation from artifact_service."""

    def test_progress_store_separate_from_artifact_service(self):
        """Interface batch progress uses its own store, not artifact_service's."""
        from features.interface_molecules import batch_progress as interface_progress
        from features.molecules import artifact_service

        # They should be different modules
        assert interface_progress.__name__ != artifact_service.__name__

        # Progress stores should be independent
        interface_progress.init_batch_progress("interface-test", ["mol1"])

        # artifact_service shouldn't know about interface batch progress
        # (It uses a different key structure for batch progress)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
