"""LAMMPS binary capability probing.

Detects LAMMPS build features (packages, KOKKOS backend, GPU hardware)
and determines the optimal acceleration mode for input script generation.

Probing runs lazily in each worker process on first call, with file-based
caching keyed by (executable_path, mtime) to avoid repeated subprocess calls.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from common.logging import get_logger
from contracts.schema_enums import AccelMode, KokkosBackend
from contracts.schemas import LammpsCaps

logger = get_logger("orchestrator.lammps_probe")

# ---------------------------------------------------------------------------
# Module-level singleton cache (per-process)
# ---------------------------------------------------------------------------
_cached_caps: LammpsCaps | None = None
_cached_key: tuple[str, float] | None = None  # (resolved_path, mtime) — binary identity

_CACHE_FILENAME = "lammps_caps_cache.json"


def _get_cache_path() -> Path:
    """Return path to the file-based capability cache."""
    from common.pathing import get_project_root

    return get_project_root() / _CACHE_FILENAME


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_lammps_caps(executable: str = "lmp", mpi_command: str = "mpirun") -> LammpsCaps:
    """Return cached LAMMPS capabilities, probing on first call.

    Lazy singleton: probes once per worker process, backed by a file cache
    keyed on ``(executable_path, mtime)`` so that recompiling the binary
    automatically invalidates the cache.

    Args:
        executable: LAMMPS executable name or path.

    Returns:
        LammpsCaps with detected capabilities and acceleration mode.
    """
    global _cached_caps, _cached_key  # noqa: PLW0603

    resolved = _resolve_executable(executable)
    if resolved is None:
        logger.warning(f"LAMMPS executable '{executable}' not found, using defaults")
        return _default_caps(executable)

    mtime = os.stat(resolved).st_mtime
    # Cache key is the BINARY identity (path, mtime) ONLY. A LAMMPS binary's
    # capabilities (installed packages, KOKKOS backend) are fixed at compile time
    # and only change when the binary is recompiled (mtime changes).
    #
    # GPU availability is deliberately NOT part of the key (v01.06.07 root-cause
    # fix). Under heavy job load nvidia-smi (10s) and ``lmp -h`` (15s) can BOTH
    # transiently time out and report "no GPU", which previously (a) flipped the
    # key so the good ``gpu=true`` file cache no longer matched, AND (b) made
    # Defense B's fallback lookup miss it too — so the worker silently downgraded
    # to mpi_only and ran LAMMPS without ``-k on``, failing with "Package kokkos
    # command without KOKKOS package enabled" (and the mirror "Must use 'newton
    # off' ..." when the degraded profile was baked at BUILD time). Keying on
    # binary identity keeps caps STABLE across the whole batch.
    key = (resolved, mtime)

    # In-process cache hit
    if _cached_caps is not None and _cached_key == key:
        return _cached_caps

    # File cache hit (binary-identity keyed). A good cache is trusted AS-IS so that
    # steady-state workers NEVER re-run lmp -h / nvidia-smi per job (the source of
    # the load-induced degradation). The start-up idle warm (start_all.sh
    # warm_lammps_caps) guarantees this good cache exists before load. Exception:
    # the cache says non-GPU but a CUDA GPU is now present (rare hardware/driver
    # upgrade) — only then re-probe. A transient nvidia-smi failure during steady
    # state reports detected=False -> no upgrade -> the good cache is kept.
    cached = _load_file_cache(key)
    if cached is not None and cached.installed_packages:
        if _is_gpu_upgrade_available(cached):
            logger.info(
                "LAMMPS caps cache is non-GPU but a CUDA GPU is now present; re-probing"
            )
        else:
            _cached_caps = cached
            _cached_key = key
            logger.info(f"LAMMPS caps loaded from file cache: accel_mode={cached.accel_mode}")
            return cached

    # Full probe (first call after (re)compile, or GPU-upgrade re-probe)
    caps = probe_lammps_caps(resolved, mpi_command=mpi_command)

    # Defense B (v01.06.06): an empty installed-packages list means ``lmp -h``
    # read NOTHING — i.e. the capability probe failed (almost always a timeout
    # when this runs under heavy job load). Its kokkos_backend/accel_mode are then
    # bogus (none / mpi_only). DO NOT persist or pin such a degraded result: it
    # would poison the SHARED file cache for every worker, making them run LAMMPS
    # without ``-k on`` and fail en masse with "Package kokkos command without
    # KOKKOS package enabled". Instead keep any existing good cache and let this
    # worker re-probe on its next task (when load has eased). Pairs with the
    # start-up idle warm (start_all.sh warm_lammps_caps) so a good cache exists
    # before load and is never overwritten by a timed-out probe.
    if not caps.installed_packages:
        logger.warning(
            "LAMMPS probe degraded (lmp -h read 0 packages — likely a timeout "
            "under load); not caching so a good cache is preserved and the probe "
            "retries next time. accel_mode=%s",
            caps.accel_mode,
        )
        existing = _load_file_cache(key)
        if existing is not None and existing.installed_packages:
            _cached_caps = existing
            _cached_key = key
            return existing
        # No good cache to fall back to: use the degraded caps for THIS call but
        # do not pin/persist, so the next call probes afresh.
        return caps

    _cached_caps = caps
    _cached_key = key
    _save_file_cache(key, caps)
    logger.info(
        f"LAMMPS probed: version={caps.version_string}, "
        f"packages={caps.installed_packages}, "
        f"kokkos={caps.kokkos_backend}, accel_mode={caps.accel_mode}"
    )
    return caps


def probe_lammps_caps(executable_path: str, mpi_command: str = "mpirun") -> LammpsCaps:
    """Probe LAMMPS binary capabilities via ``lmp -h`` and a short test input.

    Args:
        executable_path: Resolved absolute path to LAMMPS binary.
        mpi_command: MPI launcher command (from LAMMPS_MPI_COMMAND setting).

    Returns:
        LammpsCaps with all detected fields populated.
    """
    caps_data: dict[str, Any] = {
        "executable_path": executable_path,
        "probed_at": datetime.now(UTC),
        "cpu_cores": os.cpu_count() or 1,
    }

    # --- Phase 1: Parse lmp -h output ---
    help_text = _run_lammps_help(executable_path)
    if help_text:
        caps_data["version_string"] = _parse_version(help_text)
        caps_data["installed_packages"] = _parse_packages(help_text)
        caps_data["kokkos_backend"] = _parse_kokkos_backend(help_text)
        caps_data["kokkos_precision"] = _parse_kokkos_precision(help_text)
        caps_data["kokkos_fft"] = _parse_kokkos_fft(help_text)

    # --- Phase 2: GPU detection (nvidia-smi) ---
    gpu_info = _detect_gpus()
    caps_data["gpu_detected"] = gpu_info["detected"]
    caps_data["gpu_count"] = gpu_info["count"]
    caps_data["gpu_model"] = gpu_info["model"]

    # --- Phase 3: Probe input validation (if KOKKOS+GPU) ---
    has_kokkos = "KOKKOS" in caps_data.get("installed_packages", [])
    backend = caps_data.get("kokkos_backend", KokkosBackend.NONE)
    if has_kokkos and backend in (KokkosBackend.CUDA, KokkosBackend.HIP) and gpu_info["detected"]:
        if not _verify_kokkos_gpu(executable_path, mpi_command=mpi_command):
            logger.warning("KOKKOS GPU probe input failed, falling back to MPI_ONLY")
            caps_data["kokkos_backend"] = KokkosBackend.NONE

    # --- Phase 4: Determine acceleration mode ---
    caps = LammpsCaps(**caps_data)
    caps.accel_mode = determine_accel_mode(caps)
    return caps


def determine_accel_mode(caps: LammpsCaps) -> AccelMode:
    """Determine optimal acceleration mode from capabilities.

    Args:
        caps: Probed LAMMPS capabilities.

    Returns:
        AccelMode enum value.
    """
    has_kokkos = "KOKKOS" in caps.installed_packages

    if has_kokkos and caps.kokkos_backend in (KokkosBackend.CUDA, KokkosBackend.HIP):
        if caps.gpu_detected:
            return AccelMode.KOKKOS_GPU
        logger.warning("KOKKOS CUDA/HIP build but no GPU detected, falling back to MPI_ONLY")
        return AccelMode.MPI_ONLY

    if has_kokkos and caps.kokkos_backend == KokkosBackend.OPENMP:
        return AccelMode.KOKKOS_CPU

    if not has_kokkos and caps.gpu_detected:
        logger.warning(
            "GPU detected but KOKKOS not installed. "
            "GPU_PACKAGE mode is not supported — falling back to MPI_ONLY. "
            "Rebuild LAMMPS with KOKKOS for GPU acceleration."
        )
        return AccelMode.MPI_ONLY

    if caps.cpu_cores > 1:
        return AccelMode.MPI_ONLY

    return AccelMode.SERIAL


def get_optimization_profile(caps: LammpsCaps) -> dict[str, Any]:
    """Return optimization parameters for LAMMPS input script generation.

    All optimizations are accuracy-preserving (no cutoff/precision changes).

    Args:
        caps: Probed LAMMPS capabilities.

    Returns:
        Dict of optimization parameters keyed by setting name.
    """
    mode = caps.accel_mode

    # Common optimizations (all modes, accuracy-preserving)
    profile: dict[str, Any] = {
        # Neighbor list: relax check frequency (safe for slow-diffusing asphalt polymers)
        "neigh_delay": 10,
        "neigh_every": 5,
        "neigh_check": True,
        # NOTE: dump intervals are now computed adaptively in protocol_chain.py
        # based on tier sampling policy (SamplingConfig). The keys nvt_dump_interval
        # and npt_dump_interval have been removed (v00.97.00).
        # Remove velocity columns from NVT/NPT dumps (not needed for RDF/MSD)
        "dump_velocity": False,
        # Viscosity dumps keep velocity columns (needed for velocity profile)
        "viscosity_dump_velocity": True,
    }

    # Mode-specific KOKKOS settings
    if mode == AccelMode.KOKKOS_GPU:
        profile.update(
            {
                # LAMMPS 2025+: newton off required with KOKKOS neigh full option
                "newton": "off",
                # Full neighbor list + GPU-direct communication
                "package_kokkos": "package kokkos neigh full comm device",
            }
        )
    elif mode == AccelMode.KOKKOS_CPU:
        profile.update(
            {
                # CPU: newton on with half neighbor list (cache-efficient)
                "newton": "on",
                # Half neighbor list + host communication
                "package_kokkos": "package kokkos neigh half comm host",
            }
        )
    else:
        # MPI_ONLY / SERIAL: no KOKKOS commands
        profile.update(
            {
                "newton": "on",
                "package_kokkos": None,
            }
        )

    return profile


# ---------------------------------------------------------------------------
# Internal helpers: lmp -h parsing
# ---------------------------------------------------------------------------


def _resolve_executable(executable: str) -> str | None:
    """Resolve executable to absolute path."""
    resolved = shutil.which(executable)
    if resolved:
        return os.path.realpath(resolved)
    # Try as absolute path
    if os.path.isfile(executable) and os.access(executable, os.X_OK):
        return os.path.realpath(executable)
    return None


def _run_lammps_help(executable: str) -> str | None:
    """Run ``lmp -h`` and return stdout text.

    Timeout is generous (60s): a KOKKOS-CUDA binary initialises a CUDA/MPS context
    even for ``-h``, which under heavy concurrent job load can take far longer than
    the old 15s (observed: mass timeouts during a 300-job burst). A probe is now
    rare (only on a cold cache or binary recompile — see ``get_lammps_caps``), so a
    slow-but-correct probe is strictly better than a fast degraded one.
    """
    try:
        result = subprocess.run(
            [executable, "-h"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.stdout + result.stderr
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.warning(f"Failed to run '{executable} -h': {e}")
        return None


def _parse_version(help_text: str) -> str:
    """Extract LAMMPS version string."""
    for line in help_text.splitlines():
        if "Large-scale Atomic" in line or "LAMMPS" in line:
            match = re.search(r"(\d+\s+\w+\s+\d{4})", line)
            if match:
                return match.group(1)
    return "unknown"


def _parse_packages(help_text: str) -> list[str]:
    """Extract installed package list."""
    packages: list[str] = []
    in_packages = False
    for line in help_text.splitlines():
        if "Installed packages:" in line:
            in_packages = True
            continue
        if in_packages:
            stripped = line.strip()
            if not stripped:
                # Skip blank lines immediately after header, stop on second blank
                if packages:
                    break
                continue
            # Stop if we hit the next section header (e.g. "List of individual style")
            if stripped.startswith("List of") or stripped.startswith("*"):
                break
            packages.extend(stripped.split())
    return sorted(set(packages))


def _parse_kokkos_backend(help_text: str) -> KokkosBackend:
    """Detect KOKKOS backend from help output."""
    # Look for "KOKKOS package API: CUDA Serial" or similar
    for line in help_text.splitlines():
        if "KOKKOS package API" in line:
            lower = line.lower()
            if "cuda" in lower:
                return KokkosBackend.CUDA
            if "hip" in lower:
                return KokkosBackend.HIP
            if "openmp" in lower:
                return KokkosBackend.OPENMP
            if "serial" in lower:
                # "Serial" alone without CUDA/HIP/OpenMP means no accelerator
                return KokkosBackend.SERIAL
    return KokkosBackend.NONE


def _parse_kokkos_precision(help_text: str) -> str:
    """Extract KOKKOS precision setting."""
    for line in help_text.splitlines():
        if "KOKKOS package precision" in line:
            parts = line.split(":")
            if len(parts) >= 2:
                return parts[-1].strip().lower()
    return "unknown"


def _parse_kokkos_fft(help_text: str) -> str:
    """Extract KOKKOS FFT engine."""
    for line in help_text.splitlines():
        if "KOKKOS FFT library" in line:
            parts = line.split("=")
            if len(parts) >= 2:
                return parts[-1].strip()
    return "unknown"


# ---------------------------------------------------------------------------
# Internal helpers: GPU detection
# ---------------------------------------------------------------------------


def _is_gpu_upgrade_available(cached: LammpsCaps) -> bool:
    """True only for the rare UPGRADE case: the cached caps say non-GPU but the
    binary is CUDA/HIP-capable KOKKOS and a GPU is now present.

    This is the *only* condition under which a good (packages-present) file cache
    is discarded for a re-probe. Crucially it never DOWNGRADES: during steady-state
    load a transient nvidia-smi timeout returns detected=False, which yields False
    here, so the good KOKKOS_GPU cache is kept. (v01.06.07)
    """
    if cached.accel_mode == AccelMode.KOKKOS_GPU:
        return False
    if "KOKKOS" not in cached.installed_packages:
        return False
    if cached.kokkos_backend not in (KokkosBackend.CUDA, KokkosBackend.HIP):
        return False
    return _detect_gpus()["detected"]


def _detect_gpus() -> dict[str, Any]:
    """Detect NVIDIA GPUs via nvidia-smi."""
    result: dict[str, Any] = {"detected": False, "count": 0, "model": None}
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0:
            lines = [ln.strip() for ln in proc.stdout.strip().splitlines() if ln.strip()]
            result["count"] = len(lines)
            result["detected"] = len(lines) > 0
            if lines:
                result["model"] = lines[0].split(",")[0].strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return result


# ---------------------------------------------------------------------------
# Internal helpers: probe input validation
# ---------------------------------------------------------------------------


def _verify_kokkos_gpu(executable: str, mpi_command: str = "mpirun") -> bool:
    """Run a minimal LAMMPS input to verify KOKKOS GPU works.

    Creates a tiny simulation (no atoms) that exercises the KOKKOS GPU path.
    Returns True if the probe succeeds.
    """
    # NOTE: package kokkos must come BEFORE create_box (LAMMPS requirement)
    # LAMMPS 2025+: newton off is required with KOKKOS neigh full option
    probe_script = """\
units real
atom_style full
boundary p p p
newton off
package kokkos neigh full comm device
region box block 0 10 0 10 0 10
create_box 1 box
neighbor 2.0 bin
print "PROBE_OK"
"""
    try:
        with tempfile.TemporaryDirectory(prefix="lammps_probe_") as tmpdir:
            input_file = Path(tmpdir) / "probe.lmp"
            input_file.write_text(probe_script)

            probe_cmd = [executable, "-k", "on", "g", "1", "-sf", "kk", "-in", str(input_file)]
            if mpi_command:
                probe_cmd = [mpi_command, "-np", "1"] + probe_cmd
            # Route the probe by UUID (logical GPU 0) for the same reason as the
            # runner: a raw index breaks under MPS remapping. See memory
            # `gpu-uuid-routing-principle`. Falls back to "0" without nvidia-smi.
            from monitoring.gpu_collector import gpu_uuid_for

            result = subprocess.run(
                probe_cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=tmpdir,
                env={**os.environ, "CUDA_VISIBLE_DEVICES": gpu_uuid_for(0)},
            )
            return "PROBE_OK" in result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.warning(f"KOKKOS GPU probe failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Internal helpers: file cache
# ---------------------------------------------------------------------------


def _load_file_cache(key: tuple[str, float]) -> LammpsCaps | None:
    """Try to load cached caps from file if the binary-identity key matches.

    Key is (path, mtime) only — see ``get_lammps_caps``. The legacy
    ``_cache_key_gpu`` field (if present in an older cache file) is ignored, so a
    cache written by a previous version still loads.
    """
    cache_path = _get_cache_path()
    if not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text())
        cached_key = (
            data.get("_cache_key_path", ""),
            data.get("_cache_key_mtime", 0.0),
        )
        if cached_key != key:
            return None
        # Remove cache metadata before constructing LammpsCaps
        caps_data = {k: v for k, v in data.items() if not k.startswith("_cache_key")}
        return LammpsCaps(**caps_data)
    except Exception as e:
        logger.debug(f"File cache load failed: {e}")
        return None


def _save_file_cache(key: tuple[str, float], caps: LammpsCaps) -> None:
    """Save caps to file cache atomically."""
    cache_path = _get_cache_path()
    data = caps.model_dump(mode="json")
    data["_cache_key_path"] = key[0]
    data["_cache_key_mtime"] = key[1]
    # gpu_detected is recorded for diagnostics only — it is NOT part of the cache
    # key (a transient nvidia-smi timeout must not invalidate a good cache).
    data["_cache_key_gpu"] = caps.gpu_detected

    try:
        # Atomic write: write to temp file then rename
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=cache_path.parent, suffix=".tmp", prefix=".lammps_caps_"
        )
        try:
            with os.fdopen(tmp_fd, "w") as f:
                json.dump(data, f, indent=2, default=str)
            os.replace(tmp_path, cache_path)
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception as e:
        logger.debug(f"File cache save failed: {e}")


def _default_caps(executable: str) -> LammpsCaps:
    """Return conservative default caps when probing fails."""
    return LammpsCaps(
        executable_path=executable,
        version_string="unknown",
        accel_mode=AccelMode.SERIAL,
        cpu_cores=os.cpu_count() or 1,
        probed_at=datetime.now(UTC),
    )
