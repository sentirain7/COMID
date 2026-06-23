"""Least-loaded GPU placement (v01.05.56 P1-1).

_pick_available_gpu prefers the GPU with the fewest active jobs so empty GPUs
fill before any GPU takes a 2nd job, minimizing idle GPUs under co-location.
Ties (and the no-counts fallback) use round-robin order for determinism.
"""

from orchestrator.gpu_service import GPUService


def _svc(gpus):
    s = GPUService()
    s.initialize(selected_gpus=list(gpus))
    return s


def test_empty_gpu_is_filled_before_a_second_job():
    s = _svc([0, 1, 2, 3, 4, 6])
    # GPUs 0..4 each have 1 job; GPU 6 is empty. slots>1 so all are "available".
    counts = {0: 1, 1: 1, 2: 1, 3: 1, 4: 1}
    available = [0, 1, 2, 3, 4, 6]
    assert s._pick_available_gpu(available, counts) == 6


def test_balances_load_across_gpus():
    s = _svc([0, 1, 2])
    # GPU 0 has 2, GPU 1 has 1, GPU 2 has 0 → pick GPU 2.
    assert s._pick_available_gpu([0, 1, 2], {0: 2, 1: 1, 2: 0}) == 2
    # GPU 2 now has 1; next least-loaded is GPU 1 (1) vs GPU 2 (1) — tie → RR.
    assert s._pick_available_gpu([0, 1, 2], {0: 2, 1: 1, 2: 1}) in (1, 2)


def test_tie_uses_round_robin_when_counts_equal():
    s = _svc([0, 1, 2])
    s._rr_cursor = 0
    # All equal load → round-robin advances through the list.
    first = s._pick_available_gpu([0, 1, 2], {0: 1, 1: 1, 2: 1})
    second = s._pick_available_gpu([0, 1, 2], {0: 1, 1: 1, 2: 1})
    assert first != second  # cursor advanced → different GPU


def test_no_counts_falls_back_to_round_robin():
    s = _svc([0, 1, 2])
    s._rr_cursor = 0
    # Without counts, behavior is the legacy round-robin (byte-identical path).
    assert s._pick_available_gpu([0, 1, 2]) == 0
    assert s._pick_available_gpu([0, 1, 2]) == 1
