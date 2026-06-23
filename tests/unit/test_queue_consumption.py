"""Queue-consumption invariant (v01.05.56 P2-3).

Every Celery queue that a task is ROUTED to (celery_app.py task_routes) must be
CONSUMED by some worker (start_all.sh --queues lists). A routed-but-unconsumed
queue silently drops tasks into Redis forever — exactly the latent gap that
left `analysis.cpu` (e_inter CPU rerun) dead. This guards against future drift
when queues or worker pools change.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Routed queues that are intentionally NOT consumed (dead code / vestigial).
# (v01.06.14) `batch_job_binder_cell` is now folded into the cpu@ pool, closing
# the prior latent gap — nothing is intentionally unconsumed anymore.
KNOWN_UNCONSUMED: set[str] = set()


def _routed_queues() -> set[str]:
    text = (ROOT / "src/orchestrator/celery_app.py").read_text(encoding="utf-8")
    return set(re.findall(r'"queue":\s*"([^"]+)"', text))


def _consumed_queues() -> set[str]:
    text = (ROOT / "start_all.sh").read_text(encoding="utf-8")
    consumed: set[str] = set()
    for group in re.findall(r"--queues=([^\s\\]+)", text):
        consumed.update(q for q in group.split(",") if q)
    return consumed


def _pools() -> list[set[str]]:
    """Each worker pool's consumed-queue set (one per ``--queues=`` group)."""
    text = (ROOT / "start_all.sh").read_text(encoding="utf-8")
    return [
        {q for q in group.split(",") if q}
        for group in re.findall(r"--queues=([^\s\\]+)", text)
    ]


def _route_for_task(task_suffix: str) -> str | None:
    """Resolve the routed queue for a task by its name suffix (celery_app.py)."""
    text = (ROOT / "src/orchestrator/celery_app.py").read_text(encoding="utf-8")
    m = re.search(
        rf'"orchestrator\.tasks\.{re.escape(task_suffix)}":\s*\{{[^}}]*?"queue":\s*"([^"]+)"',
        text,
        re.DOTALL,
    )
    return m.group(1) if m else None


def test_every_routed_queue_is_consumed():
    routed = _routed_queues()
    consumed = _consumed_queues()
    assert routed, "no routed queues found — parser/source drift"
    assert consumed, "no consumed queues found — parser/source drift"
    missing = routed - consumed - KNOWN_UNCONSUMED
    assert not missing, (
        f"Routed queues with no worker consumer (tasks would be silently dropped): "
        f"{sorted(missing)}. Add them to a worker --queues list in start_all.sh, "
        f"or to KNOWN_UNCONSUMED if intentionally dead."
    )


def test_analysis_cpu_is_consumed():
    # Regression: analysis.cpu (e_inter CPU rerun) was routed but unconsumed.
    assert "analysis.cpu" in _consumed_queues()


def test_gpu_and_build_queues_split_across_pools():
    consumed = _consumed_queues()
    # The GPU-execution queue and the build queues are both consumed (by the
    # gpu@ and build@ pools respectively).
    assert "simulation.gpu" in consumed
    assert "simulation" in consumed


# --- Control-plane isolation invariant (v01.06.14) ---
# The structural fix: lightweight orchestration/beat tasks live on the `control`
# queue consumed by a dedicated pool, so they are NEVER blocked behind a saturated
# GPU worker pool. These tests pin that separation against future drift.


def test_control_queue_is_consumed():
    assert "control" in _consumed_queues(), "control queue has no worker consumer"


def test_scheduler_routes_to_control():
    # The dispatch-critical scheduler MUST be on the control queue.
    assert _route_for_task("schedule_ready_experiments") == "control"


def test_control_plane_isolated_from_gpu_pool():
    """The pool consuming the long-blocking GPU queue must NOT also consume the
    control queue — otherwise control-plane starvation (the v01.06.14 incident)
    can recur when all GPU workers are busy with ~20-min LAMMPS runs."""
    pools = _pools()
    gpu_pools = [p for p in pools if "simulation.gpu" in p]
    assert gpu_pools, "no pool consumes simulation.gpu — parser/source drift"
    for p in gpu_pools:
        assert "control" not in p, (
            f"GPU pool also consumes control queue {sorted(p)} — control plane "
            "would starve under GPU saturation. Keep control on a dedicated pool."
        )
        # The GPU pool must not consume CPU post-processing either (keeps the
        # 1-worker = 1-GPU-slot invariant that prevents ready-job slot churn).
        assert "metrics" not in p and "analysis.cpu" not in p, (
            f"GPU pool consumes CPU post-processing queues {sorted(p)} — this "
            "breaks the 1-worker=1-GPU-slot invariant."
        )


def test_critical_control_tasks_route_to_control():
    # All dispatch/recovery loop tasks must be isolated on the control queue.
    for task in (
        "schedule_ready_experiments",
        "sync_job_status",
        "recover_orphan_ready_allocations",
        "reconcile_dependency_chains",
        "refresh_gpu_inventory",
    ):
        assert _route_for_task(task) == "control", f"{task} not routed to control"
