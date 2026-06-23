"""Cross-process build-concurrency throttle for structure packing.

Structure builds (Packmol) need no GPU but are CPU/RAM intensive. Because the
build phase shares the Celery worker pool with GPU jobs (``gpu_count x slots``),
a large batch can launch dozens of Packmol subprocesses at once and exhaust
CPU/RAM — the wall-clock pathology recorded in v01.05.39. This module bounds the
number of *concurrent* builds to a policy SSOT (``max_concurrent_builds``) using
a POSIX file-lock counting semaphore that works across Celery prefork worker
processes (an in-process semaphore would not).

Design: N slot files in the temp dir; acquiring a slot means winning a
non-blocking ``flock`` on any one of them. When all N are held, the caller waits
and retries until a slot frees or a generous timeout elapses, at which point it
proceeds anyway (fail-open) — a throttle must never deadlock the build pipeline.
``limit <= 0`` disables throttling entirely (byte-identical legacy behavior).
"""

import contextlib
import os
import tempfile
import time
from collections.abc import Iterator

try:
    import fcntl
except Exception:  # pragma: no cover - non-POSIX fallback
    fcntl = None

from common.logging import get_logger

logger = get_logger("builder.build_throttle")

_SLOT_PREFIX = "asphalt_build_slot_"


def _resolve_limit(limit: int | None) -> int:
    """Resolve the concurrent-build limit from the budget policy SSOT."""
    if limit is not None:
        return limit
    try:
        from contracts.policies.budget import DEFAULT_JOB_BUDGETING_POLICY

        return int(DEFAULT_JOB_BUDGETING_POLICY.max_concurrent_builds)
    except Exception:  # noqa: BLE001 - fail open to unlimited
        return 0


@contextlib.contextmanager
def build_slot(
    limit: int | None = None,
    *,
    timeout_seconds: float = 1800.0,
    poll_seconds: float = 0.5,
) -> Iterator[bool]:
    """Acquire one of ``limit`` cross-process build slots for the duration.

    Args:
        limit: Max concurrent builds. None → budget policy SSOT. <=0 → no throttle.
        timeout_seconds: Max wait for a free slot before proceeding anyway.
        poll_seconds: Retry interval while all slots are busy.

    Yields:
        True if a slot was acquired (or throttling disabled), False if the wait
        timed out and the build proceeds un-throttled (fail-open).
    """
    resolved = _resolve_limit(limit)
    if resolved <= 0 or fcntl is None:
        # Throttling disabled or unavailable — passthrough.
        yield True
        return

    tmp = tempfile.gettempdir()
    deadline = time.monotonic() + max(1.0, timeout_seconds)
    # Offset the probe order by PID so workers don't all stampede slot 0.
    start = os.getpid() % resolved
    handle = None
    acquired_idx = -1

    while handle is None:
        for offset in range(resolved):
            idx = (start + offset) % resolved
            path = os.path.join(tmp, f"{_SLOT_PREFIX}{idx}.lock")
            try:
                fh = open(path, "a+", encoding="utf-8")
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                handle = fh
                acquired_idx = idx
                break
            except BlockingIOError:
                fh.close()
                continue
            except Exception:  # noqa: BLE001 - any FS error → fail open
                with contextlib.suppress(Exception):
                    fh.close()
                logger.warning("Build throttle FS error — proceeding un-throttled")
                yield False
                return

        if handle is not None:
            break

        if time.monotonic() >= deadline:
            logger.warning(
                "Build throttle: no free slot within %.0fs (limit=%d) — proceeding un-throttled",
                timeout_seconds,
                resolved,
            )
            yield False
            return
        time.sleep(poll_seconds)

    logger.debug("Acquired build slot %d/%d", acquired_idx, resolved)
    try:
        yield True
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except Exception:  # noqa: BLE001
            pass
        with contextlib.suppress(Exception):
            handle.close()
