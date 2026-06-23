"""Tests for the cross-process build-concurrency throttle."""

import contextlib
import time

from builder.build_throttle import _resolve_limit, build_slot


def test_resolve_limit_reads_policy():
    """None resolves to the budget policy SSOT (>=0)."""
    from contracts.policies.budget import DEFAULT_JOB_BUDGETING_POLICY

    assert _resolve_limit(None) == int(DEFAULT_JOB_BUDGETING_POLICY.max_concurrent_builds)
    assert _resolve_limit(5) == 5
    assert _resolve_limit(0) == 0


def test_disabled_throttle_is_passthrough():
    """limit<=0 disables throttling (acquired=True, no blocking)."""
    with build_slot(0) as ok:
        assert ok is True


def test_single_slot_acquire_release():
    """A slot can be acquired and is released on context exit (re-acquirable)."""
    with build_slot(1) as ok:
        assert ok is True
    # After release, immediately re-acquirable.
    with build_slot(1) as ok2:
        assert ok2 is True


def test_concurrent_slots_up_to_limit():
    """Up to `limit` slots can be held at once (distinct slot files)."""
    with build_slot(2) as a, build_slot(2) as b:
        assert a is True
        assert b is True


def test_over_limit_fails_open_after_timeout():
    """When all slots are held, the next acquire times out and proceeds (fail-open).

    flock file descriptions are independent even within one process, so holding
    both slots of a limit=2 throttle forces the third acquire to wait then
    fail-open (yield False) — a throttle must never deadlock the build pipeline.
    """
    with contextlib.ExitStack() as stack:
        stack.enter_context(build_slot(2))
        stack.enter_context(build_slot(2))
        start = time.monotonic()
        with build_slot(2, timeout_seconds=1.0, poll_seconds=0.1) as third:
            elapsed = time.monotonic() - start
            # Could not get a real slot → fail-open (False), after ~timeout.
            assert third is False
            assert elapsed >= 0.9
