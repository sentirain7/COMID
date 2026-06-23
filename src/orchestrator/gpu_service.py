"""
GPU Service - Single Source of Truth for GPU allocation.

This module provides centralized GPU management for MD simulations.
DB is the primary storage for allocations (multi-process safety),
in-memory cache is used for stats/status queries.

v00.68.04: Initial implementation (no existing code modified)

Usage:
    service = get_gpu_service()
    service.initialize(selected_gpus=[0, 1])  # Optional: explicit GPU list

    gpu_id = service.allocate(task_id="abc123")
    ...
    service.release(gpu_id, task_id="abc123")
"""

import os
import tempfile
import threading
import time
from datetime import datetime

try:
    import fcntl
except Exception:  # pragma: no cover - non-POSIX fallback
    fcntl = None

from common.logging import get_logger
from orchestrator.gpu_types import GPUInfo, GPUStatus

logger = get_logger("orchestrator.gpu_service")


class GPUService:
    """
    GPU allocation Single Source of Truth.

    Uses DB as primary storage for allocations (ensures multi-process safety
    across Celery workers). In-memory cache provides fast status queries
    and stores real-time stats from nvidia-smi.

    Key design decisions:
    - DB-based allocation with `with_for_update()` for atomic updates
    - Same logic as tasks.py `_allocate_gpu()` for compatibility
    - Thread-safe via `threading.Lock` for in-memory cache
    - Lazy initialization via `get_gpu_service()` singleton

    Usage:
        service = get_gpu_service()
        service.initialize(selected_gpus=[0, 1])

        # Allocate GPU for a Celery task
        gpu_id = service.allocate(task_id="abc123")
        if gpu_id is None:
            # No GPU available
            ...

        # Release GPU when done
        service.release(gpu_id, task_id="abc123")

        # Get current status
        status = service.get_status()
    """

    def __init__(self):
        """Initialize GPUService (call initialize() to activate)."""
        self._lock = threading.Lock()
        self._cache: dict[int, GPUInfo] = {}
        self._selected_gpus: list[int] = []
        self._initialized = False
        self._rr_cursor = 0
        self._alloc_lock_path = os.path.join(tempfile.gettempdir(), "asphalt_gpu_allocation.lock")
        # {gpu_id: {eligible, slots, kind, uuid}} cache (from the device
        # registry). Lazily built once so allocate() never shells out to
        # nvidia-smi inside the lock.
        self._device_cache: dict[int, dict] | None = None

    def _slots_per_gpu(self) -> int:
        """Max concurrent jobs per GPU (policy SSOT; >=1).

        N>1 enables GPU co-location (MPS) — small systems under-use the H200
        (latency-bound), so multiple jobs share one GPU. The atomic global lock
        + single transaction in allocate*() serialize slot counting so the
        "no over-allocation" invariant holds for N>1 exactly as for N=1.
        """
        try:
            from contracts.policies.budget import DEFAULT_JOB_BUDGETING_POLICY

            return max(1, int(DEFAULT_JOB_BUDGETING_POLICY.max_concurrent_jobs_per_gpu))
        except Exception:  # noqa: BLE001 - fail safe to single-job behavior
            return 1

    def _device_info(self) -> dict[int, dict]:
        """``{gpu_id: {eligible, slots, kind, uuid}}`` from the device registry
        (cached, lock-free).

        Built once from ``enumerate_compute_devices`` (mode-aware: MPS whole
        GPUs, MIG instances, etc.); topology/mode changes require a restart (or
        ``reset_gpu_service``). Empty in non-GPU/test envs -> callers fall back to
        policy defaults (byte-identical to prior behavior).
        """
        if self._device_cache is None:
            try:
                from monitoring.gpu_collector import enumerate_compute_devices

                self._device_cache = {
                    int(d["gpu_id"]): {
                        "eligible": bool(d.get("eligible", True)),
                        "slots": int(d.get("slots", self._slots_per_gpu())),
                        "kind": d.get("kind", "whole_gpu"),
                        "uuid": d.get("uuid"),
                    }
                    for d in enumerate_compute_devices()
                }
            except Exception:  # noqa: BLE001 - fail open
                self._device_cache = {}
        return self._device_cache

    def _slot_caps(self) -> dict[int, int]:
        """Per-GPU slot cap ``{gpu_id: cap}`` for the selected devices.

        Sourced from the registry's per-device ``slots`` (mode-aware): MPS
        eligible GPU -> policy N, MIG instance -> 1. Devices with no registry info
        default to the policy count (test/non-GPU env -> byte-identical).

        **Sub-threshold (ineligible) GPUs get cap 0 — hard-excluded from
        allocation.** A display/consumer GPU below the ``min_gpu_memory_gb`` floor
        (e.g. an RTX 3050) stays visible/enumerable in the registry, but
        ``_available_with_slots`` can never return it (``0 < 0`` is False). This is
        the authoritative 32GB eligibility gate at the allocation chokepoint —
        BOTH ``allocate()`` and ``allocate_gpu()`` route through here — so an MD
        job never lands on an unusable GPU even if its id slips into
        ``selected_gpus`` via the GPU-selection UI or a settings churn.
        """
        base = self._slots_per_gpu()
        info = self._device_info()
        caps: dict[int, int] = {}
        for gid in self._selected_gpus:
            d = info.get(gid)
            if d is None:
                caps[gid] = base
            elif not d.get("eligible", True):
                caps[gid] = 0  # sub-threshold device -> never allocatable
            else:
                caps[gid] = int(d["slots"])
        return caps

    @staticmethod
    def _available_with_slots(
        selected: list[int],
        allocated_gpu_ids: list[int | None],
        slots: int | dict[int, int],
    ) -> list[int]:
        """GPUs whose current allocation count is below the per-GPU slot limit.

        ``slots`` may be a uniform int OR a ``{gpu_id: cap}`` map (per-device cap).
        """
        from collections import Counter

        counts = Counter(g for g in allocated_gpu_ids if g is not None)

        def _cap(g: int) -> int:
            return slots.get(g, 1) if isinstance(slots, dict) else slots

        return [g for g in selected if counts.get(g, 0) < _cap(g)]

    @staticmethod
    def _detect_overallocation(
        allocated_gpu_ids: list[int | None], slots: int | dict[int, int]
    ) -> dict[int, int]:
        """Return ``{gpu_id: count}`` for any GPU allocated beyond its slot cap.

        Reconciliation backstop (mandatory after the DB unique index
        ``uq_experiments_active_gpu_alloc`` is dropped for slots>1): that index
        used to make a 2nd-job-per-GPU commit fail at the DB layer. With it gone,
        only the fcntl-locked allocator enforces the per-GPU cap, so a logic
        regression or an out-of-lock direct write to ``gpu_id_allocated`` would
        silently double-book a GPU. Calling this inside the allocation critical
        section surfaces such a violation loudly instead of failing silently.

        ``slots`` may be a uniform int OR a ``{gpu_id: cap}`` map.
        """
        from collections import Counter

        counts = Counter(g for g in allocated_gpu_ids if g is not None)

        def _cap(g: int) -> int:
            return slots.get(int(g), 1) if isinstance(slots, dict) else slots

        return {int(g): int(n) for g, n in counts.items() if n > _cap(g)}

    def initialize(self, selected_gpus: list[int] | None = None) -> None:
        """
        Initialize the GPU service.

        Should be called once at API/worker startup. Safe to call multiple times
        (subsequent calls are no-ops).

        Args:
            selected_gpus: List of GPU IDs to manage. If None, loads from
                          settings.json or auto-detects via nvidia-smi.
        """
        with self._lock:
            if self._initialized:
                logger.debug("GPUService already initialized, skipping")
                return

            # 1. Determine selected GPUs
            if selected_gpus is not None:
                self._selected_gpus = list(selected_gpus)
            else:
                self._selected_gpus = self._load_selected_gpus()
            self._rr_cursor = 0

            if not self._selected_gpus:
                logger.warning("GPUService initialized with no GPUs (CPU-only mode)")
                self._initialized = True
                return

            # 2. Initialize cache for each GPU
            for gpu_id in self._selected_gpus:
                self._cache[gpu_id] = GPUInfo(
                    gpu_id=gpu_id,
                    name=f"GPU-{gpu_id}",
                    last_updated=datetime.now(),
                )

            # 3. Restore allocation state from DB
            restored = self._restore_from_db()

            self._initialized = True
            logger.info(
                f"GPUService initialized: gpus={self._selected_gpus}, "
                f"restored={restored} allocations from DB"
            )

    def _load_selected_gpus(self) -> list[int]:
        """
        Load GPU list from settings.json or auto-detect.

        Priority:
        1. settings.json "selected_gpus" field
        2. nvidia-smi auto-detection
        3. Empty list (CPU-only mode)

        Returns:
            List of GPU IDs
        """
        from config.dashboard_settings import get_selected_gpus

        # MIG mode: the device universe is MIG instances (sequential ids), so a
        # whole-GPU selection stored in settings.json (raw indices) is stale.
        # Use ALL eligible MIG instances — participation is chosen at MIG-setup
        # time (which GPUs were partitioned), not via the whole-GPU checkbox.
        try:
            from monitoring.gpu_collector import (
                enumerate_compute_devices,
                resolve_sharing_mode,
            )

            if resolve_sharing_mode() == "mig":
                devs = [
                    int(d["gpu_id"])
                    for d in enumerate_compute_devices()
                    if d.get("eligible", True)
                ]
                if devs:
                    logger.info(f"MIG mode: using all {len(devs)} eligible MIG instances")
                    return devs
        except Exception as e:  # noqa: BLE001
            logger.warning(f"MIG-mode selection failed, falling back to settings: {e}")

        gpus = get_selected_gpus()
        if gpus:
            logger.info(f"Loaded GPUs from settings.json: {gpus}")
            return gpus

        # Fallback to auto-detection — eligible compute GPUs only (excludes
        # sub-threshold display/consumer GPUs so MD jobs never land on them).
        try:
            from monitoring.gpu_collector import detect_eligible_compute_gpus

            detected = detect_eligible_compute_gpus()
            gpus = [g["gpu_id"] for g in detected]
            if gpus:
                logger.info(f"Auto-detected eligible GPUs: {gpus}")
                return gpus
        except Exception as e:
            logger.warning(f"GPU auto-detection failed: {e}")

        return []

    def _restore_from_db(self) -> int:
        """
        Restore GPU allocation state from DB into cache.

        Queries experiments with gpu_id_allocated set and updates cache
        to reflect current allocations.

        Returns:
            Number of allocations restored
        """
        restored = 0

        try:
            from database.connection import session_scope
            from database.models import ExperimentModel

            with session_scope() as session:
                # Find all experiments with GPU allocated
                running_exps = (
                    session.query(ExperimentModel)
                    .filter(ExperimentModel.gpu_id_allocated.isnot(None))
                    .all()
                )

                by_gpu: dict[int, list[dict]] = {}
                for exp in running_exps:
                    by_gpu.setdefault(exp.gpu_id_allocated, []).append(
                        {"task_id": exp.celery_task_id, "exp_id": exp.exp_id}
                    )
                now = datetime.now()
                for gpu_id, jobs in by_gpu.items():
                    if gpu_id in self._cache:
                        info = self._cache[gpu_id]
                        info.set_jobs(jobs)
                        info.status = GPUStatus.BUSY
                        info.allocated_at = now
                        info.last_updated = now
                        restored += len(jobs)
                        logger.debug(f"Restored GPU {gpu_id}: {len(jobs)} job(s)")

        except Exception as e:
            logger.error(f"Failed to restore GPU state from DB: {e}")

        return restored

    def _pick_available_gpu(
        self, available: list[int], counts: dict[int, int] | None = None
    ) -> int:
        """Pick one GPU from ``available``.

        When ``counts`` (gpu_id -> current job count) is given, prefer the
        LEAST-LOADED GPU so empty GPUs fill before any GPU takes a 2nd job —
        minimizing idle GPUs under co-location (v01.05.56 P1-1). Ties, and the
        no-counts fallback, use round-robin over ``selected_gpus`` order for
        deterministic behavior. ``counts`` must come from the same locked
        allocation snapshot so the choice is correct cross-process.
        """
        if len(available) == 1:
            return available[0]

        with self._lock:
            total = len(self._selected_gpus)
            if total <= 0:
                return available[0]

            start = self._rr_cursor % total
            # Candidates in round-robin order (preserves tie-break determinism).
            ordered = [
                ((start + offset) % total, self._selected_gpus[(start + offset) % total])
                for offset in range(total)
                if self._selected_gpus[(start + offset) % total] in available
            ]
            if not ordered:
                # Fallback: keep behavior predictable if selected/available diverge.
                return available[0]

            if counts is not None:
                # Stable min: ties keep the earliest round-robin position.
                idx, gpu_id = min(ordered, key=lambda t: counts.get(t[1], 0))
            else:
                idx, gpu_id = ordered[0]
            self._rr_cursor = (idx + 1) % total
            return gpu_id

    def _acquire_allocation_lock(self, timeout_seconds: int = 10) -> object:
        """Acquire cross-process lock for GPU allocation critical section.

        Uses a POSIX file lock to serialize allocation across workers/processes.
        Raises RuntimeError when lock cannot be obtained within timeout.
        """
        if fcntl is None:
            raise RuntimeError("GPU allocation lock requires POSIX fcntl support")

        handle = open(self._alloc_lock_path, "a+", encoding="utf-8")
        deadline = time.monotonic() + max(1, timeout_seconds)
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return handle
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    handle.close()
                    raise RuntimeError("GPU allocation lock is busy") from None
                time.sleep(0.05)
            except Exception:
                handle.close()
                raise

    def _release_allocation_lock(self, handle: object | None) -> None:
        """Release allocation lock handle."""
        if handle is None:
            return
        try:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            handle.close()
        except Exception:
            pass

    def allocate(self, task_id: str) -> int | None:
        """
        Allocate a GPU for a Celery task (DB-based, atomic).

        This method mirrors the logic from tasks.py `_allocate_gpu()`:
        1. Queries DB for all experiments with gpu_id_allocated set
        2. Finds first available GPU from selected_gpus
        3. Updates experiment.gpu_id_allocated in same transaction
        4. Updates in-memory cache

        Args:
            task_id: Celery task ID (used to find experiment record)

        Returns:
            Allocated GPU ID, or None if:
            - Service not initialized
            - No GPUs configured
            - No GPU available
            - Experiment record not found for task_id
        """
        if not self._initialized:
            logger.error(
                f"GPUService.allocate() called before initialize() for task {task_id}. "
                "Call get_gpu_service().initialize() at startup."
            )
            return None

        if not self._selected_gpus:
            logger.warning(f"No GPUs configured for task {task_id}")
            return None

        try:
            from database.connection import session_scope
            from database.models import ExperimentModel

            lock_handle = self._acquire_allocation_lock()
            try:
                with session_scope() as session:
                    # Atomic query: lock all experiments with GPU allocated
                    running_exps = (
                        session.query(ExperimentModel)
                        .filter(ExperimentModel.gpu_id_allocated.isnot(None))
                        .with_for_update()
                        .all()
                    )

                    # 슬롯 카운트(GPU별 ≤ cap) — eligible는 정책 N, 부적격(3050)은 1.
                    # N=1·전부 eligible이면 기존 1잡/GPU와 동일.
                    allocated_ids = [exp.gpu_id_allocated for exp in running_exps]
                    slot_caps = self._slot_caps()
                    over = self._detect_overallocation(allocated_ids, slot_caps)
                    if over:
                        logger.error(
                            "GPU over-allocation detected (reconciliation backstop): "
                            f"{over} exceed per-gpu slot caps={slot_caps}. Index dropped for "
                            "multi-job — investigate out-of-lock writers to gpu_id_allocated."
                        )
                    available = self._available_with_slots(
                        self._selected_gpus, allocated_ids, slot_caps
                    )

                    if not available:
                        logger.warning(
                            f"No GPU slot available for task {task_id} "
                            f"(selected={self._selected_gpus}, slot_caps={slot_caps})"
                        )
                        return None

                    counts: dict[int, int] = {}
                    for g in allocated_ids:
                        if g is not None:
                            counts[g] = counts.get(g, 0) + 1
                    gpu_id = self._pick_available_gpu(available, counts)

                    # Find and update experiment record
                    exp = (
                        session.query(ExperimentModel)
                        .filter(ExperimentModel.celery_task_id == task_id)
                        .first()
                    )

                    if not exp:
                        # Return None to avoid tracking inconsistency
                        # (GPU would be "allocated" but not tracked in DB/cache)
                        logger.error(
                            f"Experiment not found for task {task_id}, "
                            "cannot allocate GPU without experiment record"
                        )
                        return None

                    exp.gpu_id_allocated = gpu_id
                    session.commit()
                    logger.info(f"Allocated GPU {gpu_id} to task {task_id} (exp: {exp.exp_id})")

                    # Update cache (append job to slot list — best-effort, the
                    # authoritative active_jobs are rebuilt by _sync_from_db).
                    with self._lock:
                        if gpu_id in self._cache:
                            info = self._cache[gpu_id]
                            jobs = [j for j in info.active_jobs if j.get("task_id") != task_id]
                            jobs.append({"task_id": task_id, "exp_id": exp.exp_id})
                            info.set_jobs(jobs)
                            info.status = GPUStatus.BUSY
                            now = datetime.now()
                            info.allocated_at = info.allocated_at or now
                            info.last_updated = now

                    return gpu_id
            finally:
                self._release_allocation_lock(lock_handle)

        except Exception as e:
            logger.error(f"GPU allocation failed for task {task_id}: {e}")
            return None

    def release(
        self,
        gpu_id: int,
        task_id: str | None = None,
        exp_id: str | None = None,
    ) -> bool:
        """
        Release a GPU allocation.

        Updates DB to clear gpu_id_allocated, then updates cache.
        Uses a 2-level lookup priority:
          1. task_id + gpu_id (most specific)
          2. exp_id + gpu_id (fallback when task_id lookup fails)

        Args:
            gpu_id: GPU ID to release
            task_id: Celery task ID (optional, for verification)
            exp_id: Experiment ID (optional, for fallback lookup)

        Returns:
            True if release succeeded, False otherwise
        """
        try:
            from database.connection import session_scope
            from database.models import ExperimentModel

            with session_scope() as session:
                exp = None

                # Priority 1: task_id + gpu_id
                if task_id:
                    exp = (
                        session.query(ExperimentModel)
                        .filter(
                            ExperimentModel.celery_task_id == task_id,
                            ExperimentModel.gpu_id_allocated == gpu_id,
                        )
                        .first()
                    )

                # Priority 2: exp_id + gpu_id
                if exp is None and exp_id:
                    exp = (
                        session.query(ExperimentModel)
                        .filter(
                            ExperimentModel.exp_id == exp_id,
                            ExperimentModel.gpu_id_allocated == gpu_id,
                        )
                        .first()
                    )

                if exp is None:
                    logger.warning(
                        "GPU release skipped: no experiment matches gpu_id=%s with task_id=%s exp_id=%s",
                        gpu_id,
                        task_id,
                        exp_id,
                    )
                    return False

                released_exp_id = exp.exp_id
                released_task_id = exp.celery_task_id
                exp.gpu_id_allocated = None
                session.commit()
                logger.info(f"Released GPU {gpu_id} (task={task_id}, exp={exp.exp_id})")

            # Update cache: remove only this job's slot. GPU goes AVAILABLE only
            # when no slots remain (다른 동시잡이 남아 있으면 BUSY 유지).
            with self._lock:
                if gpu_id in self._cache:
                    info = self._cache[gpu_id]
                    jobs = [
                        j
                        for j in info.active_jobs
                        if j.get("task_id") not in (task_id, released_task_id)
                        and j.get("exp_id") not in (exp_id, released_exp_id)
                    ]
                    info.set_jobs(jobs)
                    if jobs:
                        info.status = GPUStatus.BUSY
                    else:
                        info.status = GPUStatus.AVAILABLE
                        info.allocated_at = None
                    info.last_updated = datetime.now()

            return True

        except Exception as e:
            logger.error(f"GPU release failed for GPU {gpu_id}: {e}")
            return False

    def get_status(self) -> dict:
        """
        Get current GPU status (cache + DB sync).

        Syncs with DB first to ensure accuracy, then returns status dict.

        Returns:
            Dict with structure:
            {
                "gpus": [
                    {
                        "gpu_id": int,
                        "status": str,
                        "current_task_id": str | None,
                        "current_exp_id": str | None,
                        "memory_used_gb": float,
                        "memory_total_gb": float,
                        "utilization_pct": float,
                        "allocated_at": str | None,  # ISO format
                    },
                    ...
                ],
                "total": int,
                "available": int,
                "busy": int,
            }
        """
        # Sync from DB to ensure cache is accurate
        self._sync_from_db()

        with self._lock:
            gpus = []
            for info in self._cache.values():
                gpus.append(
                    {
                        "gpu_id": info.gpu_id,
                        "status": info.status.value,
                        "current_task_id": info.current_task_id,
                        "current_exp_id": info.current_exp_id,
                        "memory_used_gb": info.memory_used_gb,
                        "memory_total_gb": info.memory_total_gb,
                        "utilization_pct": info.utilization_pct,
                        "allocated_at": (
                            info.allocated_at.isoformat() if info.allocated_at else None
                        ),
                    }
                )

            return {
                "gpus": gpus,
                "total": len(self._cache),
                "available": sum(
                    1 for g in self._cache.values() if g.status == GPUStatus.AVAILABLE
                ),
                "busy": sum(1 for g in self._cache.values() if g.status == GPUStatus.BUSY),
            }

    def _sync_from_db(self) -> None:
        """
        Sync cache with DB.

        Updates cache to match current DB allocation state.
        Called before get_status() and get_available_gpus().

        Note: OFFLINE GPUs (not in selected_gpus) retain their OFFLINE status
        even if they have no allocation in DB.
        """
        try:
            from database.connection import session_scope
            from database.models import ExperimentModel

            with session_scope() as session:
                running_exps = (
                    session.query(ExperimentModel)
                    .filter(ExperimentModel.gpu_id_allocated.isnot(None))
                    .all()
                )

                # Build map of gpu_id -> [jobs] (N슬롯: 한 GPU에 여러 실험 가능).
                allocated_map: dict[int, list[dict]] = {}
                for exp in running_exps:
                    allocated_map.setdefault(exp.gpu_id_allocated, []).append(
                        {"task_id": exp.celery_task_id, "exp_id": exp.exp_id}
                    )

                with self._lock:
                    for gpu_id, info in self._cache.items():
                        if gpu_id in allocated_map:
                            # GPU has active allocation(s)
                            info.set_jobs(allocated_map[gpu_id])
                            info.status = GPUStatus.BUSY
                            info.allocated_at = info.allocated_at or datetime.now()
                            info.last_updated = datetime.now()
                        elif self._selected_gpus and gpu_id not in self._selected_gpus:
                            # GPU is not in selected_gpus -> keep OFFLINE
                            info.set_jobs([])
                            info.status = GPUStatus.OFFLINE
                            info.allocated_at = None
                            info.last_updated = datetime.now()
                        else:
                            # GPU is available (in selected_gpus, no allocation)
                            info.set_jobs([])
                            info.status = GPUStatus.AVAILABLE
                            info.allocated_at = None
                            info.last_updated = datetime.now()

        except Exception as e:
            logger.warning(f"Failed to sync GPU state from DB: {e}")

    def update_stats(
        self,
        gpu_id: int,
        memory_used_gb: float = 0.0,
        memory_total_gb: float = 0.0,
        utilization_pct: float = 0.0,
        temperature_c: float = 0.0,
    ) -> None:
        """
        Update GPU real-time statistics (in-memory only).

        Called by monitoring/GPU collector to update stats from nvidia-smi.
        Does not affect allocation state.

        Args:
            gpu_id: GPU ID
            memory_used_gb: Memory used in GB
            memory_total_gb: Total memory in GB
            utilization_pct: GPU utilization percentage
            temperature_c: Temperature in Celsius
        """
        with self._lock:
            if gpu_id in self._cache:
                self._cache[gpu_id].memory_used_gb = memory_used_gb
                self._cache[gpu_id].memory_total_gb = memory_total_gb
                self._cache[gpu_id].utilization_pct = utilization_pct
                self._cache[gpu_id].temperature_c = temperature_c
                self._cache[gpu_id].last_updated = datetime.now()

    # -------------------------------------------------------------------------
    # GPUResourceTracker compatibility layer (Phase 1)
    # -------------------------------------------------------------------------

    def get_gpu(self, gpu_id: int) -> GPUInfo | None:
        """GPUResourceTracker-compatible: get GPU info by ID."""
        return self._cache.get(gpu_id)

    def get_all_gpus(self) -> list[GPUInfo]:
        """GPUResourceTracker-compatible: get all GPU info."""
        self._sync_from_db()
        with self._lock:
            return list(self._cache.values())

    def get_available_gpus(self) -> list[GPUInfo]:
        """GPUResourceTracker-compatible: get available GPUs."""
        self._sync_from_db()
        with self._lock:
            return [g for g in self._cache.values() if g.is_available]

    def allocate_gpu(
        self,
        job_id: str,
        gpu_id: int | None = None,
        exp_id: str | None = None,
    ) -> int | None:
        """
        GPUResourceTracker-compatible allocation method.

        Supports optional specific gpu_id and optional exp_id. Uses DB as SSOT.
        Requires an ExperimentModel record to exist in DB (by exp_id or job_id).
        """
        if gpu_id is None and exp_id is None:
            return self.allocate(task_id=job_id)

        if not self._initialized:
            logger.error(f"GPUService.allocate_gpu() called before initialize() for job {job_id}")
            return None

        if not self._selected_gpus:
            logger.warning(f"No GPUs configured for job {job_id}")
            return None

        try:
            from database.connection import session_scope
            from database.models import ExperimentModel

            lock_handle = self._acquire_allocation_lock()
            try:
                with session_scope() as session:
                    # Lock current allocations
                    running_exps = (
                        session.query(ExperimentModel)
                        .filter(ExperimentModel.gpu_id_allocated.isnot(None))
                        .with_for_update()
                        .all()
                    )
                    allocated_ids = [exp.gpu_id_allocated for exp in running_exps]
                    slot_caps = self._slot_caps()
                    over = self._detect_overallocation(allocated_ids, slot_caps)
                    if over:
                        logger.error(
                            "GPU over-allocation detected (reconciliation backstop): "
                            f"{over} exceed per-gpu slot caps={slot_caps}. Index dropped for "
                            "multi-job — investigate out-of-lock writers to gpu_id_allocated."
                        )
                    available = self._available_with_slots(
                        self._selected_gpus, allocated_ids, slot_caps
                    )

                    if gpu_id is not None:
                        # 명시 GPU도 슬롯 여유가 있어야 배정(count < cap).
                        if gpu_id not in self._selected_gpus or gpu_id not in available:
                            return None
                        chosen_gpu = gpu_id
                    else:
                        if not available:
                            return None
                        counts: dict[int, int] = {}
                        for g in allocated_ids:
                            if g is not None:
                                counts[g] = counts.get(g, 0) + 1
                        chosen_gpu = self._pick_available_gpu(available, counts)

                    # Resolve experiment record
                    exp = None
                    if exp_id is not None:
                        exp = (
                            session.query(ExperimentModel)
                            .filter(ExperimentModel.exp_id == exp_id)
                            .first()
                        )
                    if exp is None:
                        exp = (
                            session.query(ExperimentModel)
                            .filter(ExperimentModel.celery_task_id == job_id)
                            .first()
                        )

                    if not exp:
                        logger.error(
                            f"Experiment not found for job {job_id} (exp_id={exp_id}), "
                            "cannot allocate GPU"
                        )
                        return None

                    exp.gpu_id_allocated = chosen_gpu
                    session.commit()

                    # Update cache (append slot — best-effort, _sync_from_db 권위).
                    with self._lock:
                        info = self._cache.get(chosen_gpu)
                        if info:
                            now = datetime.now()
                            jobs = [j for j in info.active_jobs if j.get("task_id") != job_id]
                            jobs.append({"task_id": job_id, "exp_id": exp.exp_id})
                            info.set_jobs(jobs)
                            info.status = GPUStatus.BUSY
                            info.allocated_at = info.allocated_at or now
                            info.last_updated = now

                    return chosen_gpu
            finally:
                self._release_allocation_lock(lock_handle)

        except Exception as e:
            logger.error(f"GPU allocation failed for job {job_id}: {e}")
            return None

    def release_gpu(self, gpu_id: int, exp_id: str | None = None) -> bool:
        """GPUResourceTracker-compatible release."""
        return self.release(gpu_id, task_id=None, exp_id=exp_id)

    def update_gpu_stats(
        self,
        gpu_id: int,
        memory_used_gb: float,
        utilization_percent: float,
        temperature_c: float,
    ) -> None:
        """GPUResourceTracker-compatible stats update."""
        total_gb = self._cache[gpu_id].memory_total_gb if gpu_id in self._cache else 0.0
        self.update_stats(
            gpu_id=gpu_id,
            memory_used_gb=memory_used_gb,
            memory_total_gb=total_gb,
            utilization_pct=utilization_percent,
            temperature_c=temperature_c,
        )

    def get_utilization_summary(self) -> dict:
        """GPUResourceTracker-compatible utilization summary."""
        self._sync_from_db()
        with self._lock:
            available = sum(1 for g in self._cache.values() if g.is_available)
            busy = sum(1 for g in self._cache.values() if g.status == GPUStatus.BUSY)
            total_memory = sum(g.memory_total_gb for g in self._cache.values())
            used_memory = sum(g.memory_used_gb for g in self._cache.values())
            avg_util = sum(g.utilization_percent for g in self._cache.values()) / max(
                1, len(self._cache)
            )

            return {
                "total_gpus": len(self._cache),
                "available_gpus": available,
                "busy_gpus": busy,
                "total_memory_gb": total_memory,
                "used_memory_gb": used_memory,
                "average_utilization_percent": avg_util,
            }

    def restore_allocation(
        self,
        gpu_id: int,
        job_id: str | None = None,
        exp_id: str | None = None,
    ) -> bool:
        """
        GPUResourceTracker-compatible allocation restore.

        Updates in-memory cache only (DB already reflects allocation).
        """
        with self._lock:
            info = self._cache.get(gpu_id)
            if not info:
                return False

            if info.is_available:
                info.status = GPUStatus.BUSY
                info.current_job_id = job_id
                info.current_exp_id = exp_id
                now = datetime.now()
                info.allocated_at = now
                info.last_updated = now
                return True

            if info.status == GPUStatus.BUSY:
                same_job = job_id is not None and info.current_job_id == job_id
                same_exp = exp_id is not None and info.current_exp_id == exp_id
                if same_job or same_exp:
                    return True

            return False

    def clear_all_allocations(self) -> int:
        """GPUResourceTracker-compatible: clear all allocations."""
        cleared = 0

        try:
            from database.connection import session_scope
            from database.models import ExperimentModel

            with session_scope() as session:
                running_exps = (
                    session.query(ExperimentModel)
                    .filter(ExperimentModel.gpu_id_allocated.isnot(None))
                    .all()
                )
                for exp in running_exps:
                    exp.gpu_id_allocated = None
                session.commit()
        except Exception as e:
            logger.warning(f"Failed to clear GPU allocations in DB: {e}")

        with self._lock:
            for info in self._cache.values():
                if info.status == GPUStatus.BUSY:
                    info.status = GPUStatus.AVAILABLE
                    info.current_task_id = None
                    info.current_exp_id = None
                    info.allocated_at = None
                    info.last_updated = datetime.now()
                    cleared += 1

        if cleared > 0:
            logger.info(f"Cleared {cleared} GPU allocations")
        return cleared

    # -------------------------------------------------------------------------
    # OFFLINE GPU support methods (Phase 2)
    # -------------------------------------------------------------------------

    def register_detected_gpus(self, detected_gpus: list[dict]) -> None:
        """
        Register all detected GPUs into cache (including non-selected).

        Use this to ensure all system GPUs appear in API responses, with
        non-selected GPUs marked as OFFLINE.

        Args:
            detected_gpus: List of detected GPU info dicts with structure:
                [{"gpu_id": int, "name": str, "memory_gb": float}, ...]
        """
        now = datetime.now()
        with self._lock:
            for g in detected_gpus:
                gpu_id = g.get("gpu_id")
                if gpu_id is None:
                    continue

                info = self._cache.get(gpu_id)
                if info is None:
                    # Create new entry for non-selected GPU
                    info = GPUInfo(gpu_id=gpu_id)
                    self._cache[gpu_id] = info

                # Update name if provided
                name = g.get("name")
                if name:
                    info.name = name
                elif info.name == "Unknown":
                    info.name = f"GPU-{gpu_id}"

                # Update memory if provided and > 0
                memory_gb = g.get("memory_gb")
                if memory_gb is not None and memory_gb > 0:
                    info.memory_total_gb = memory_gb

                # Hardware identity + eligibility + per-device slots (from
                # enumerate_compute_devices).
                uuid = g.get("uuid")
                if uuid:
                    info.uuid = uuid
                if "eligible" in g:
                    info.eligible = bool(g["eligible"])
                kind = g.get("kind")
                if kind:
                    info.kind = kind
                if g.get("slots") is not None:
                    info.slots = int(g["slots"])

                info.last_updated = now

        logger.debug(
            f"Registered {len(detected_gpus)} detected GPUs, "
            f"cache now has {len(self._cache)} entries"
        )

    def apply_offline_for_unselected(self) -> None:
        """
        Mark GPUs not in selected_gpus as OFFLINE.

        Should be called after register_detected_gpus() to ensure non-selected
        GPUs have OFFLINE status for correct API responses.
        """
        if not self._selected_gpus:
            # No selected GPUs configured - don't mark anything offline
            return

        with self._lock:
            for gpu_id, info in self._cache.items():
                if gpu_id not in self._selected_gpus:
                    info.status = GPUStatus.OFFLINE
                    info.current_task_id = None
                    info.current_exp_id = None
                    info.allocated_at = None
                    info.last_updated = datetime.now()
                    logger.debug(f"GPU {gpu_id} marked as OFFLINE (not in selected_gpus)")

    def validate_selected_gpus(self, detected_ids: list[int]) -> list[int]:
        """
        Reconcile selected_gpus against the current GPU detection (non-destructive).

        Selected GPUs absent from the current detection are marked **OFFLINE**
        (so the scheduler never routes work to them) but are **NOT removed** from
        ``selected_gpus`` nor deleted from the cache. They auto-recover to
        AVAILABLE the moment they are detected again (re-registered by the next
        detection pass).

        Rationale (v01.06.12 latent fix): a transient nvidia-smi miss — e.g.
        during a host reboot or a GPU fall-off — can momentarily drop a healthy
        GPU from a single detection pass. The previous behavior *removed* it from
        ``selected_gpus`` permanently; once any settings save echoed that reduced
        set (e.g. the GPU-selection UI, which only shows tracker GPUs), a healthy
        GPU was silently lost until manually re-selected. That is exactly how
        ``selected_gpus`` became ``[3,0,1,4]`` (GPU2 dropped) after the 2026-06-17
        fall-off. Keeping it selected-but-OFFLINE removes the permanent-loss
        failure mode while still preventing allocation to a genuinely-absent id
        (it simply stays OFFLINE and is never picked by ``_available_with_slots``).

        Args:
            detected_ids: List of GPU IDs detected in the current pass.

        Returns:
            Selected GPU IDs absent from the current detection (marked OFFLINE;
            kept selected for auto-recovery).
        """
        if not self._selected_gpus:
            return []

        detected_set = set(detected_ids)
        undetected_ids = [g for g in self._selected_gpus if g not in detected_set]

        if undetected_ids:
            logger.warning(
                "Selected GPU(s) %s absent from current detection %s — marking OFFLINE "
                "but KEEPING them selected (transient nvidia-smi miss or removed HW). "
                "They auto-recover when detected again; not dropped from selected_gpus to "
                "avoid permanently losing a healthy GPU after a transient detection glitch.",
                undetected_ids,
                detected_ids,
            )
            with self._lock:
                for gpu_id in undetected_ids:
                    info = self._cache.get(gpu_id)
                    if info is not None:
                        info.status = GPUStatus.OFFLINE
                        info.current_task_id = None
                        info.current_exp_id = None
                        info.allocated_at = None

        return undetected_ids

    def refresh_inventory(self, eligible_devices: list[dict], *, auto_mode: bool) -> dict:
        """Real-time GPU pool reconciliation (periodic, no restart needed).

        Lets a repaired/added GPU become usable for computation as soon as it is
        detected again, and marks a removed GPU OFFLINE — WITHOUT disturbing any
        in-flight allocation. Designed for the operator workflow where a faulty
        GPU is repaired and re-added while the service keeps running.

        Behavior (all non-destructive to running work):
        - Registers every eligible device (metadata only; ``register_detected_gpus``
          never resets a BUSY GPU's status).
        - ``auto_mode`` (settings.json ``selected_gpus`` empty = follow live
          detection): newly-eligible GPU ids are APPENDED to the active selection
          (additive — a user's explicit selection is never auto-grown).
        - A previously-OFFLINE *selected* GPU that is detected again and is idle
          is recovered to AVAILABLE (so the scheduler picks it up).
        - A *selected* GPU absent from detection and idle is marked OFFLINE
          (kept selected → auto-recovers later). A GPU that still holds jobs is
          left untouched (let it finish / be reconciled by status sync).

        Args:
            eligible_devices: ``enumerate_compute_devices()`` entries with
                ``eligible=True`` ([{"gpu_id", "name", "memory_gb", "uuid", ...}]).
            auto_mode: True when selection follows live detection (settings empty).

        Returns:
            Summary dict: {"added", "recovered", "offlined", "eligible"}.
        """
        eligible_ids = [
            d["gpu_id"] for d in eligible_devices if d.get("gpu_id") is not None
        ]
        # Register OUTSIDE the lock — register_detected_gpus takes the same
        # non-reentrant lock and only updates metadata (never status).
        self.register_detected_gpus(eligible_devices)

        elig_set = set(eligible_ids)
        added: list[int] = []
        recovered: list[int] = []
        offlined: list[int] = []
        with self._lock:
            if auto_mode:
                for gid in eligible_ids:
                    if gid not in self._selected_gpus:
                        self._selected_gpus.append(gid)
                        added.append(gid)
            for gid in list(self._selected_gpus):
                info = self._cache.get(gid)
                if info is None:
                    continue
                if gid in elig_set:
                    # Re-detected: recover OFFLINE -> AVAILABLE only if idle.
                    if info.status == GPUStatus.OFFLINE and not info.active_jobs:
                        info.status = GPUStatus.AVAILABLE
                        info.last_updated = datetime.now()
                        recovered.append(gid)
                elif info.status != GPUStatus.OFFLINE and not info.active_jobs:
                    # Selected but absent from this detection and idle -> OFFLINE
                    # (non-destructive: stays selected, auto-recovers if it returns).
                    info.status = GPUStatus.OFFLINE
                    info.current_task_id = None
                    info.current_exp_id = None
                    info.allocated_at = None
                    offlined.append(gid)

        if added or recovered or offlined:
            logger.info(
                "GPU inventory refreshed: added=%s recovered=%s offlined=%s (eligible=%s)",
                added,
                recovered,
                offlined,
                eligible_ids,
            )
        return {
            "added": added,
            "recovered": recovered,
            "offlined": offlined,
            "eligible": eligible_ids,
        }

    @property
    def selected_gpus(self) -> list[int]:
        """Get list of selected GPU IDs."""
        return list(self._selected_gpus)

    @property
    def num_gpus(self) -> int:
        """GPUResourceTracker compatibility: number of GPUs in cache."""
        return len(self._cache)

    @property
    def is_initialized(self) -> bool:
        """Check if service is initialized."""
        return self._initialized


# =============================================================================
# Singleton
# =============================================================================

_gpu_service: GPUService | None = None
_gpu_service_lock = threading.Lock()


def get_gpu_service() -> GPUService:
    """
    Get GPUService singleton (thread-safe).

    Creates instance on first call. Call initialize() after getting
    the service to activate it.

    Returns:
        GPUService singleton instance
    """
    global _gpu_service
    if _gpu_service is None:
        with _gpu_service_lock:
            # Double-checked locking
            if _gpu_service is None:
                _gpu_service = GPUService()
    return _gpu_service


def reset_gpu_service() -> None:
    """
    Reset GPUService singleton (for testing only).

    Clears the global singleton so next get_gpu_service() creates fresh instance.
    """
    import os

    global _gpu_service
    with _gpu_service_lock:
        _gpu_service = None

    # Test isolation: clear lingering GPU allocations from the local test DB.
    # This runs only under pytest to avoid mutating runtime state.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        try:
            from database.connection import session_scope
            from database.models import ExperimentModel

            with session_scope() as session:
                running_exps = (
                    session.query(ExperimentModel)
                    .filter(ExperimentModel.gpu_id_allocated.isnot(None))
                    .all()
                )
                for exp in running_exps:
                    exp.gpu_id_allocated = None
                session.commit()
        except Exception:
            # Best-effort cleanup only.
            pass
