"""
GPU metrics collector for NVIDIA GPUs.

Uses nvidia-smi to collect GPU utilization and memory metrics.
Provides GPU detection for dynamic system configuration.
"""

import re
import subprocess
import threading
from dataclasses import dataclass
from typing import Any

from common.logging import get_logger

logger = get_logger("monitoring.gpu_collector")


def detect_system_gpus() -> list[dict[str, Any]]:
    """
    Detect system GPUs using nvidia-smi with lspci fallback.

    This function is used by ResourceManager, Celery, and Tasks to dynamically
    determine available GPUs instead of hardcoded defaults.

    Returns:
        List of detected GPUs with format:
        [{"gpu_id": int, "name": str, "memory_gb": float}, ...]

        Empty list if no NVIDIA GPUs are detected.
    """
    # 1. Try nvidia-smi first (most accurate)
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,uuid,name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0 and result.stdout.strip():
            gpus = []
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 4:
                    try:
                        gpus.append(
                            {
                                # raw nvidia-smi (PCI-order) index = the logical id
                                # used across the whole stack. enumerate_compute_devices
                                # keeps it as-is (no renumbering); physical routing is
                                # by UUID via gpu_uuid_for().
                                "gpu_id": int(parts[0]),
                                # hardware UUID — stable routing identity (immune to
                                # PCI order / CUDA_DEVICE_ORDER / MPS remapping).
                                "uuid": parts[1],
                                "name": parts[2],
                                "memory_gb": float(parts[3]) / 1024,  # MiB to GB
                            }
                        )
                    except (ValueError, IndexError):
                        continue
            if gpus:
                return gpus
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass

    # 2. Fallback to lspci (less detailed but works without nvidia-smi)
    return _detect_via_lspci()


def _mig_profile_memory_gb(profile: str) -> float:
    """Parse slice memory (GB) from a MIG profile name, e.g. '1g.18gb' -> 18.0."""
    m = re.search(r"\.(\d+)gb", profile or "")
    return float(m.group(1)) if m else 0.0


def detect_mig_instances() -> dict[str, list[dict[str, Any]]]:
    """Return ``{parent_gpu_uuid: [{profile, uuid, memory_gb}, ...]}`` for MIG
    instances, parsed from ``nvidia-smi -L``.

    Empty when MIG is disabled, no instances exist, or nvidia-smi is unavailable
    — callers then treat every GPU as a single whole device (no MIG). MIG
    instance UUIDs (``MIG-...``) are the routing identity, like whole-GPU UUIDs.
    """
    try:
        result = subprocess.run(
            ["nvidia-smi", "-L"], capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0 or not result.stdout.strip():
            return {}
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        return {}

    gpu_re = re.compile(r"^GPU\s+\d+:.*\(UUID:\s*(GPU-[^)\s]+)\)")
    mig_re = re.compile(r"^\s+MIG\s+(\S+)\s+Device\s+\d+:\s*\(UUID:\s*(MIG-[^)\s]+)\)")
    instances: dict[str, list[dict[str, Any]]] = {}
    current_parent: str | None = None
    for line in result.stdout.splitlines():
        gm = gpu_re.match(line)
        if gm:
            current_parent = gm.group(1)
            continue
        mm = mig_re.match(line)
        if mm and current_parent:
            profile, uuid = mm.group(1), mm.group(2)
            instances.setdefault(current_parent, []).append(
                {
                    "profile": profile,
                    "uuid": uuid,
                    "memory_gb": _mig_profile_memory_gb(profile),
                }
            )
    return instances


def _mig_enabled_gpu_uuids() -> set[str]:
    """UUIDs of GPUs whose MIG mode is currently 'Enabled' (from nvidia-smi).

    A GPU with MIG mode Enabled but NO instances created yet (mid-setup) cannot
    run any CUDA job — neither whole-GPU nor MIG. enumerate uses this to mark
    such GPUs ineligible so jobs are never routed to an unusable device.
    """
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=uuid,mig.mode.current",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return set()
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        return set()
    enabled: set[str] = set()
    for line in result.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2 and parts[1].lower() == "enabled":
            enabled.add(parts[0])
    return enabled


def resolve_sharing_mode(mode: str | None = None) -> str:
    """Resolve the effective GPU sharing mode: ``'mig' | 'mps' | 'none'``.

    ``None`` reads the budget policy (default ``'mig'``). ``'auto'`` -> ``'mig'``
    when any MIG instance is present, else ``'none'`` — it NEVER falls back to
    MPS (deprecated). ``'mig'`` with no MIG instances behaves as whole-GPU 1-job
    (enumeration handles it), so MPS is only ever used when explicitly set.
    """
    if mode is None:
        try:
            from contracts.policies.budget import DEFAULT_JOB_BUDGETING_POLICY

            mode = str(DEFAULT_JOB_BUDGETING_POLICY.gpu_sharing_mode or "mig")
        except Exception:  # noqa: BLE001
            mode = "mig"
    mode = (mode or "mig").lower()
    if mode == "auto":
        return "mig" if detect_mig_instances() else "none"
    return mode if mode in ("mig", "mps", "none") else "mig"


def _mps_slots_per_gpu() -> int:
    """Per-GPU MPS co-location slot count from the budget policy SSOT (>=1)."""
    try:
        from contracts.policies.budget import DEFAULT_JOB_BUDGETING_POLICY

        return max(1, int(DEFAULT_JOB_BUDGETING_POLICY.max_concurrent_jobs_per_gpu))
    except Exception:  # noqa: BLE001
        return 1


def enumerate_compute_devices(
    min_memory_gb: float | None = None,
    mode: str | None = None,
) -> list[dict[str, Any]]:
    """SSOT device registry — every allocatable compute device with a stable
    logical id, routing UUID, ``eligible`` tag, ``kind`` and per-device ``slots``.

    The device *universe* depends on the effective sharing mode
    (``resolve_sharing_mode``):

    - ``mps`` / ``none``: one device per whole GPU. ``gpu_id`` = raw nvidia-smi
      index (so settings.json selection stays valid). ``slots`` = policy N (mps)
      or 1 (none). A sub-threshold GPU (e.g. RTX 3050) is kept with
      ``eligible=False`` and ``slots=1`` (shown/selectable, no co-location OOM).
    - ``mig``: one device per MIG INSTANCE (``slots=1``, fully isolated) plus any
      non-MIG GPU as a whole device. ``gpu_id`` is sequential 0..M-1 (MIG
      instances have no raw index); routing is by ``MIG-``/``GPU-`` UUID.

    Routing is ALWAYS by ``uuid`` (``gpu_uuid_for``); the integer ``gpu_id`` is an
    internal handle only — never written to CUDA_VISIBLE_DEVICES directly.

    Args:
        min_memory_gb: Whole-GPU eligibility floor (GB). None -> budget SSOT.
        mode: Sharing mode override. None -> resolve from policy ('auto').

    Returns:
        Device dicts: ``{gpu_id, uuid, name, memory_gb, eligible, kind,
        parent_uuid, slots}``.
    """
    detected = detect_system_gpus()
    if not detected:
        return detected

    if min_memory_gb is None:
        try:
            from contracts.policies.budget import DEFAULT_JOB_BUDGETING_POLICY

            min_memory_gb = float(DEFAULT_JOB_BUDGETING_POLICY.min_gpu_memory_gb)
        except Exception:  # noqa: BLE001 - fail open: treat all as eligible
            min_memory_gb = 0.0

    eff_mode = resolve_sharing_mode(mode)
    whole_slots = _mps_slots_per_gpu() if eff_mode == "mps" else 1
    mig_map = detect_mig_instances() if eff_mode == "mig" else {}
    # A GPU with MIG mode enabled but no instances created cannot run ANY job
    # (neither whole-GPU nor MIG) regardless of sharing mode — mark it ineligible
    # in every mode so a partially-set-up or being-torn-down GPU never gets jobs.
    mig_enabled_uuids = _mig_enabled_gpu_uuids()
    sequential = eff_mode == "mig"

    devices: list[dict[str, Any]] = []
    next_logical = 0
    for g in detected:
        parent_uuid = g.get("uuid")
        insts = mig_map.get(parent_uuid) if parent_uuid else None
        if insts:
            # MIG-enabled GPU -> each instance is an isolated 1-slot device.
            for inst in insts:
                devices.append(
                    {
                        "gpu_id": next_logical,
                        "uuid": inst["uuid"],
                        "name": f"{g.get('name', 'GPU')} MIG {inst['profile']}",
                        "memory_gb": inst["memory_gb"],
                        "eligible": True,  # deliberately created compute slice
                        "kind": "mig_instance",
                        "parent_uuid": parent_uuid,
                        "slots": 1,
                    }
                )
                next_logical += 1
            continue

        # Whole GPU (no MIG instances, or a non-MIG card like the RTX 3050).
        mem = float(g.get("memory_gb", 0.0) or 0.0)
        whole_eligible = mem <= 0.0 or mem >= min_memory_gb
        # MIG mode enabled but no instances created yet -> unusable (mid-setup).
        configuring = parent_uuid in mig_enabled_uuids
        if configuring:
            whole_eligible = False
        lid = next_logical if sequential else int(g["gpu_id"])
        if sequential:
            next_logical += 1
        devices.append(
            {
                **g,
                "gpu_id": lid,
                "name": f"{g.get('name', 'GPU')} (MIG configuring)"
                if configuring
                else g.get("name", "GPU"),
                "eligible": bool(whole_eligible),
                "kind": "whole_gpu",
                "parent_uuid": None,
                "slots": whole_slots if whole_eligible else 1,
            }
        )
    return devices


def total_compute_slots() -> int:
    """Total job slots across all ELIGIBLE devices (sizes the GPU worker pool).

    mps: sum of per-GPU N (e.g. 6 GPUs x 6 = 36). mig: number of MIG instances
    (1 slot each). none: number of GPUs. Used by Celery concurrency / start_all.
    """
    try:
        return sum(
            int(d.get("slots", 1))
            for d in enumerate_compute_devices()
            if d.get("eligible", True)
        )
    except Exception:  # noqa: BLE001
        return 0


def detect_eligible_compute_gpus(
    min_memory_gb: float | None = None,
) -> list[dict[str, Any]]:
    """Eligible subset (memory >= floor) of ``enumerate_compute_devices``.

    Keeps the raw nvidia-smi ``gpu_id`` (no renumbering) so the id space is
    consistent with the full device registry and with settings.json. Used by the
    *allocation* selection fallback only — explicit ``selected_gpus`` in
    settings.json always takes precedence and is not filtered.

    Safety: GPUs with unknown memory (0.0, e.g. lspci fallback) are KEPT, and if
    the floor would remove ALL detected GPUs the unfiltered list is returned to
    avoid stranding the system in CPU-only mode.

    Returns:
        List of eligible device dicts (same shape as ``enumerate_compute_devices``).
    """
    devices = enumerate_compute_devices(min_memory_gb)
    if not devices:
        return devices
    eligible = [d for d in devices if d.get("eligible", True)]
    # Never strand the system: if the floor excluded everything, keep all.
    return eligible if eligible else devices


# ---------------------------------------------------------------------------
# Logical-id <-> UUID routing map (SSOT for GPU device routing)
# ---------------------------------------------------------------------------
# CUDA_VISIBLE_DEVICES must be set to a *UUID*, never a raw integer index:
# under CUDA MPS a non-contiguous visible set is renumbered to logical 0..N-1,
# so routing a physical index (e.g. "6") yields cudaErrorNoDevice. UUIDs are
# hardware-pinned and immune to MPS/PCI/CUDA_DEVICE_ORDER remapping. See memory
# `gpu-uuid-routing-principle`.
_GPU_UUID_MAP: dict[int, str] | None = None


def get_gpu_uuid_map(*, refresh: bool = False) -> dict[int, str]:
    """Return ``{logical_gpu_id: "GPU-<uuid>"}`` for ALL detected devices.

    Built from ``enumerate_compute_devices`` (the full universe, including
    sub-threshold GPUs like an RTX 3050) so EVERY real device — eligible or not —
    has a UUID and routes correctly. Building from the eligible subset only (the
    old behavior) left selected-but-ineligible or split-off indices without a map
    entry, forcing ``gpu_uuid_for`` to fall back to the raw integer index (the
    cudaErrorNoDevice bug under MPS).

    Caching is **fail-safe** (v01.06.15): an EMPTY result is never cached, so a
    transient ``nvidia-smi`` failure (timeout/partial output under heavy load,
    esp. at worker fork time) cannot poison the cache and force permanent
    raw-integer routing. Pass ``refresh=True`` to force a rebuild (used by
    ``gpu_uuid_for`` on a cache miss to self-heal a stale/incomplete map).
    """
    global _GPU_UUID_MAP
    if _GPU_UUID_MAP is None or refresh:
        mapping: dict[int, str] = {}
        for g in enumerate_compute_devices():
            uuid = g.get("uuid")
            if uuid:
                mapping[int(g["gpu_id"])] = uuid
        # Only cache a non-empty map. Caching {} (transient nvidia-smi miss)
        # is exactly what pinned a fork worker to raw-int routing for its
        # whole life — see memory `gpu-uuid-routing-principle`.
        if mapping:
            _GPU_UUID_MAP = mapping
        else:
            return {}
    return _GPU_UUID_MAP


def gpu_uuid_for(gpu_id: int) -> str:
    """Resolve a logical ``gpu_id`` to its ``CUDA_VISIBLE_DEVICES`` routing token.

    Returns a stable ``GPU-<uuid>`` string (hardware-pinned). Routing MUST be by
    UUID — a raw integer index is unreliable under MPS/MIG (cudaErrorNoDevice or
    wrong device). So a cache miss for a ``gpu_id`` the scheduler is actively
    routing to (the cached map was built incomplete during a transient
    ``nvidia-smi`` glitch) triggers a one-shot rebuild before any fallback.

    Only when the device is genuinely absent after a fresh enumeration (e.g. no
    ``nvidia-smi`` in CI/test) does it fall back to ``str(gpu_id)`` — and that
    fallback is logged loudly so a real misroute is never silent.

    Args:
        gpu_id: Logical GPU id (0..N-1) as tracked by GPUService/DB.

    Returns:
        ``"GPU-<uuid>"`` for routing, or ``str(gpu_id)`` last-resort fallback.
    """
    gid = int(gpu_id)
    uuid = get_gpu_uuid_map().get(gid)
    if uuid is None:
        # Stale/incomplete cache for a GPU we are routing to -> rebuild once.
        uuid = get_gpu_uuid_map(refresh=True).get(gid)
    if uuid:
        return uuid
    logger.warning(
        "gpu_uuid_for(%s): no UUID even after refresh — falling back to raw "
        "integer index. Raw CUDA_VISIBLE_DEVICES is unreliable under MPS/MIG; "
        "if a GPU is present this indicates an nvidia-smi/enumeration problem.",
        gid,
    )
    return str(gid)


def clear_gpu_uuid_map_cache() -> None:
    """Invalidate the cached logical-id -> UUID map (e.g. after topology change)."""
    global _GPU_UUID_MAP
    _GPU_UUID_MAP = None


def _detect_via_lspci() -> list[dict[str, Any]]:
    """
    Detect NVIDIA GPUs via lspci (fallback method).

    Returns:
        List of detected GPUs (minimal info, no memory details)
    """
    try:
        result = subprocess.run(
            ["lspci"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            return []

        gpus = []
        gpu_id = 0
        for line in result.stdout.split("\n"):
            # Look for NVIDIA VGA/3D controllers
            if "NVIDIA" in line and ("VGA" in line or "3D" in line):
                # Extract GPU name from lspci output
                # Example: "01:00.0 VGA compatible controller: NVIDIA Corporation GA102 [GeForce RTX 3090]"
                name_match = re.search(r"NVIDIA Corporation (.+)$", line)
                name = name_match.group(1) if name_match else f"NVIDIA GPU {gpu_id}"

                gpus.append(
                    {
                        "gpu_id": gpu_id,
                        "name": name.strip(),
                        "memory_gb": 0.0,  # Unknown via lspci
                    }
                )
                gpu_id += 1

        return gpus

    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        return []


@dataclass
class GPUStats:
    """GPU statistics."""

    gpu_id: str
    name: str
    utilization_percent: float
    memory_used_bytes: int
    memory_total_bytes: int
    temperature_celsius: float
    power_draw_watts: float


class GPUCollector:
    """
    Collector for NVIDIA GPU metrics.

    Polls nvidia-smi for GPU statistics.
    """

    def __init__(self, interval_seconds: float = 15.0):
        """
        Initialize GPU collector.

        Args:
            interval_seconds: Polling interval
        """
        self.interval = interval_seconds
        self._running = False
        self._thread: threading.Thread | None = None
        self._nvidia_smi_available = self._check_nvidia_smi()

    def _check_nvidia_smi(self) -> bool:
        """Check if nvidia-smi is available."""
        try:
            result = subprocess.run(
                ["nvidia-smi", "--version"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def is_available(self) -> bool:
        """Check if GPU collection is available."""
        return self._nvidia_smi_available

    def collect_once(self) -> list[GPUStats]:
        """
        Collect GPU stats once.

        Returns:
            List of GPUStats for each GPU
        """
        if not self._nvidia_smi_available:
            return []

        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=uuid,index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                return []

            # Map physical UUID -> logical id so live stats use the SAME
            # contiguous 0..N-1 numbering as allocation/DB/UI, and exclude
            # ineligible GPUs (e.g. a display RTX 3050). Empty map (no nvidia-smi
            # eligibility / test env) -> fall back to raw nvidia-smi index so
            # behavior is unchanged where UUID routing is not in play.
            uuid_to_logical = {u: lid for lid, u in get_gpu_uuid_map().items()}

            stats = []
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue

                parts = [p.strip() for p in line.split(",")]
                if len(parts) < 8:
                    continue

                uuid = parts[0]
                if uuid_to_logical:
                    logical = uuid_to_logical.get(uuid)
                    if logical is None:
                        continue  # not an eligible compute GPU (e.g. display card)
                    gpu_id = str(logical)
                else:
                    gpu_id = parts[1]  # fallback: raw nvidia-smi index

                try:
                    gpu_stats = GPUStats(
                        gpu_id=gpu_id,
                        name=parts[2],
                        utilization_percent=float(parts[3]) if parts[3] != "[N/A]" else 0.0,
                        memory_used_bytes=int(float(parts[4])) * 1024 * 1024,  # MiB to bytes
                        memory_total_bytes=int(float(parts[5])) * 1024 * 1024,
                        temperature_celsius=float(parts[6]) if parts[6] != "[N/A]" else 0.0,
                        power_draw_watts=float(parts[7]) if parts[7] != "[N/A]" else 0.0,
                    )
                    stats.append(gpu_stats)
                except (ValueError, IndexError):
                    continue

            stats.sort(key=lambda s: int(s.gpu_id) if str(s.gpu_id).isdigit() else 0)
            return stats

        except subprocess.TimeoutExpired:
            return []
        except Exception:
            return []


class MockGPUCollector:
    """Mock GPU collector for testing without NVIDIA GPUs."""

    def __init__(self, num_gpus: int = 2):
        """
        Initialize mock collector.

        Args:
            num_gpus: Number of mock GPUs
        """
        self.num_gpus = num_gpus

    def is_available(self) -> bool:
        """Always available for testing."""
        return True

    def collect_once(self) -> list[GPUStats]:
        """Generate mock GPU stats."""
        import random

        stats = []
        for i in range(self.num_gpus):
            stats.append(
                GPUStats(
                    gpu_id=str(i),
                    name=f"Mock GPU {i}",
                    utilization_percent=random.uniform(20, 80),
                    memory_used_bytes=random.randint(4, 20) * 1024 * 1024 * 1024,
                    memory_total_bytes=24 * 1024 * 1024 * 1024,  # 24 GB
                    temperature_celsius=random.uniform(40, 70),
                    power_draw_watts=random.uniform(100, 300),
                )
            )

        return stats


def create_gpu_collector(mock: bool = False) -> GPUCollector:
    """
    Create a GPU collector.

    Args:
        mock: Use mock collector for testing

    Returns:
        GPU collector instance
    """
    if mock:
        return MockGPUCollector()
    return GPUCollector()
