"""v00.99.95 — HealthChecker celery_workers latency threshold contract.

Context:
    v00.99.62 까지: ``ping_timeout = min(self.timeout, 0.5)`` → healthy
    ping latency ≈ 500 ms → below 1500 ms threshold → READY.
    v00.99.63: timeout 을 2.0 s 로 상향 (FF batch 중 false DOWN 오탐 방지)
    하면서 threshold 를 손대지 않아 healthy ping latency ≈ 2000 ms >
    1500 ms → 상시 LIMITED (false warn).
    v00.99.95: threshold 를 timeout 위쪽으로 올려 (2500 ms) 정상적인
    broadcast 대기 시간이 warn 을 유발하지 않도록 복원.

이 테스트는 설정이 다시 돌아가는 것을 막기 위한 contract lock 이다.
구체적으로:

* `_latency_warn_ms["celery_workers"]` 는 `timeout * 1000` 보다 엄격히
  커야 한다 (broadcast 가 timeout 을 꽉 채울 수 있으므로).
* timeout 과 threshold 의 관계가 깨지면 본 테스트가 실패한다.
* `_status_from_latency` 가 timeout 경계값에서 READY 를 반환하는지
  직접 확인.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


def test_celery_threshold_is_strictly_above_timeout():
    from orchestrator.health_checker import HealthChecker

    checker = HealthChecker()  # default timeout = 2.0 s
    timeout_ms = checker.timeout * 1000
    threshold = checker._latency_warn_ms["celery_workers"]
    assert threshold > timeout_ms, (
        f"celery_workers warn threshold ({threshold} ms) must be strictly "
        f"greater than the ping timeout ({timeout_ms} ms). Otherwise every "
        "healthy ping trips the LIMITED status because Celery's "
        "inspect.ping() broadcast waits the full timeout even when a "
        "single worker responded in milliseconds."
    )

    # And the gap must be at least small-buffer sized so benign
    # scheduling jitter above the timeout doesn't falsely warn either.
    assert (threshold - timeout_ms) >= 300, (
        f"threshold ({threshold} ms) should leave at least 300 ms cushion "
        f"above the timeout ({timeout_ms} ms) to absorb broadcast + network "
        f"overhead on a busy host"
    )


def test_status_from_latency_ready_at_typical_ping_latency():
    """A healthy celery ping sits around the timeout (~2000 ms at the
    current default). The status mapping must report READY for that
    value, not LIMITED."""
    from orchestrator.health_checker import HealthChecker, HealthStatus

    checker = HealthChecker()
    typical_healthy_latency = checker.timeout * 1000  # ~= 2000 ms
    status = checker._status_from_latency("celery_workers", typical_healthy_latency)
    assert status == HealthStatus.READY, (
        f"Healthy ping at {typical_healthy_latency} ms must map to READY; got {status}"
    )


def test_status_from_latency_limited_when_ping_blown_out():
    """If latency truly exceeds the warn ceiling — e.g. broker stall
    returning pong but slowly — the mapping should still degrade to
    LIMITED so the UI surfaces the degradation."""
    from orchestrator.health_checker import HealthChecker, HealthStatus

    checker = HealthChecker()
    threshold = checker._latency_warn_ms["celery_workers"]
    # Slightly above the threshold must be LIMITED.
    status = checker._status_from_latency("celery_workers", threshold + 100)
    assert status == HealthStatus.LIMITED
