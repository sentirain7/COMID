"""v00.99.94 — POST /artifacts/admin/dump-stacks diagnostics endpoint.

The endpoint writes the API process's full thread tracebacks to a
timestamped file under ``logs/`` and returns the file path plus a
list of direct-child PIDs so the operator can fan out with
``py-spy dump --pid <pid>`` against worker subprocesses.

This test locks the contract:

* Writes a file whose contents contain faulthandler's traceback
  header ``Thread 0x...`` (or at least ``# Stack dump captured at``
  + the faulthandler output).
* Returns a JSON body with the expected keys
  (``status``, ``path``, ``captured_at``, ``thread_count``,
  ``child_pids``).
* Admin gate is absent (v00.99.45+), so no auth is required.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


@pytest.fixture
def app_with_router():
    from features.molecules.router import router

    app = FastAPI()
    app.include_router(router)
    return app


def test_dump_stacks_writes_file_and_returns_metadata(app_with_router, tmp_path, monkeypatch):
    """Happy path: endpoint creates a stackdump file and returns its
    path, timestamp, thread count, and child PIDs."""
    # Redirect logs/ to tmp so the test doesn't pollute the repo.
    monkeypatch.chdir(tmp_path)

    client = TestClient(app_with_router)
    resp = client.post("/artifacts/admin/dump-stacks")

    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Response shape.
    for key in ("status", "path", "captured_at", "thread_count", "child_pids"):
        assert key in body, f"missing key {key!r} in response: {body}"
    assert body["status"] == "ok"
    assert body["thread_count"] >= 1
    assert isinstance(body["child_pids"], list)

    # File exists and has traceback content.
    dump_file = Path(body["path"])
    assert dump_file.exists(), f"dump file not written: {dump_file}"
    content = dump_file.read_text()
    assert "Stack dump captured at" in content
    # faulthandler.dump_traceback emits 'Thread 0x' headers for each
    # live thread (in Python 3.12 the exact format is
    # "Thread 0x{handle:x} (most recent call first):").
    assert "Thread 0x" in content or "Current thread" in content


def test_dump_stacks_returns_500_on_write_error(app_with_router, monkeypatch):
    """If the dump file cannot be written (e.g. permission issue),
    surface it as 500 with a clear detail payload."""

    def _raise(*args, **kwargs):
        raise OSError("simulated disk full")

    monkeypatch.setattr("builtins.open", _raise)

    client = TestClient(app_with_router)
    resp = client.post("/artifacts/admin/dump-stacks")

    assert resp.status_code == 500
    detail = resp.json().get("detail")
    assert isinstance(detail, dict)
    assert "Failed to write stack dump file" in detail.get("message", "")
    assert "simulated disk full" in detail.get("error", "")
