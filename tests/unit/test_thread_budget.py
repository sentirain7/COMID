"""Co-location-aware thread budgeting (v01.05.56 C).

In GPU mode the per-job OpenMP thread count is the atom-based value (8/12/16)
CAPPED by the per-job CPU budget = cpu_count // (gpu_count * slots_per_gpu), so
N co-located jobs don't oversubscribe host cores. slots_per_gpu defaults to 1,
keeping single-job behavior byte-identical.
"""

from unittest.mock import patch

from orchestrator.lammps_runner import calculate_threads_per_job


def test_single_job_mode_is_unchanged():
    """slots_per_gpu=1 with a large core count → atom-based value unchanged."""
    with patch("orchestrator.lammps_runner.os.cpu_count", return_value=256):
        # 6 GPUs, 1 job each → budget = 256//6 = 42 ≥ atom-based, so no cap.
        assert (
            calculate_threads_per_job(
                6, accel_mode="kokkos_gpu", target_atoms=100_000, slots_per_gpu=1
            )
            == 8
        )
        assert (
            calculate_threads_per_job(
                6, accel_mode="kokkos_gpu", target_atoms=200_000, slots_per_gpu=1
            )
            == 16
        )


def test_colocation_caps_threads_to_core_budget():
    """slots_per_gpu=6 caps threads so sum across co-located jobs ≤ cores."""
    with patch("orchestrator.lammps_runner.os.cpu_count", return_value=256):
        # 6 GPUs × 6 slots = 36 concurrent jobs; budget = 256//36 = 7.
        # atom-based would be 8/12/16 but all capped to 7.
        for atoms in (100_000, 150_000, 200_000):
            assert (
                calculate_threads_per_job(
                    6, accel_mode="kokkos_gpu", target_atoms=atoms, slots_per_gpu=6
                )
                == 7
            )


def test_budget_never_below_min_threads():
    """Tiny core count still yields at least min_threads."""
    with patch("orchestrator.lammps_runner.os.cpu_count", return_value=8):
        # 6 GPUs × 6 slots = 36 jobs; 8//36 = 0 → floored to min_threads.
        assert (
            calculate_threads_per_job(
                6, accel_mode="kokkos_gpu", target_atoms=100_000, slots_per_gpu=6,
                min_threads=2,
            )
            == 2
        )


def test_default_slots_per_gpu_is_one():
    """Omitting slots_per_gpu preserves legacy (single-job) behavior."""
    with patch("orchestrator.lammps_runner.os.cpu_count", return_value=256):
        assert (
            calculate_threads_per_job(6, accel_mode="kokkos_gpu", target_atoms=100_000)
            == 8
        )
