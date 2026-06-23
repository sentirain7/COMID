"""GAFF2 artifact generation service.

Wraps the antechamber+parmchk2+tleap+parmed pipeline for generating
curated GAFF2 force field artifacts from MOL files.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import multiprocessing as mp
import os
import signal
import subprocess
import tempfile
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from common.logging import get_logger

from .admin_status import AdminStatusStore, recommended_action_for_failure
from .exceptions import ArtifactFailureCode, ArtifactGenerationError

logger = get_logger("molecules.artifact_service")


def _kill_process_group(
    proc: subprocess.Popen,  # type: ignore[type-arg]
    stage_name: str,
    mol_id: str,
) -> None:
    """Kill entire process group: SIGTERM → 5s grace → SIGKILL (guaranteed).

    Unlike proc.wait() which only waits for the direct child, this sends
    signals to the entire process group (including grandchildren like sqm)
    and always escalates to SIGKILL to ensure no orphan remains.
    """
    pgid: int | None = None
    try:
        pgid = os.getpgid(proc.pid)
    except (ProcessLookupError, OSError):
        pass

    if pgid is not None:
        # Step 1: SIGTERM to entire group
        try:
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass

        # Step 2: Grace period — wait for voluntary exit
        time.sleep(5)

        # Step 3: SIGKILL to entire group (guaranteed cleanup)
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass  # Already dead — fine

    # Step 4: Reap direct child to avoid zombie
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    except (ProcessLookupError, OSError):
        pass

    logger.info(
        "Process group cleanup completed for %s/%s (pgid=%s)",
        stage_name,
        mol_id,
        pgid,
    )


def _pdeathsig_preexec() -> None:
    """Linux preexec_fn: set PR_SET_PDEATHSIG=SIGKILL on the child.

    v00.99.92: `start_new_session=True` isolates antechamber/sqm into
    a new process group so timeout-driven ``os.killpg()`` can reliably
    reap the whole subtree. But the same isolation prevents the child
    from receiving SIGHUP when its parent (uvicorn worker) dies
    ungracefully — e.g. server restart, `uvicorn --reload`, OS OOM,
    external SIGKILL. In those cases antechamber gets reparented to
    init (PID 1 / WSL /init) and keeps running for hours as a pure
    CPU leak.

    `prctl(PR_SET_PDEATHSIG, SIGKILL)` instructs the kernel to send
    SIGKILL to *this* process the moment its parent thread exits,
    regardless of the session / process-group isolation. It runs
    between ``fork()`` and ``execve()`` in the child, so the flag is
    in place before the real antechamber/sqm binary even starts.

    No-op on non-Linux platforms (prctl is Linux-only) — silently
    skip so the same code remains portable for macOS dev machines.
    """
    try:
        import ctypes
        import ctypes.util
        import signal

        libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        PR_SET_PDEATHSIG = 1
        # prctl(PR_SET_PDEATHSIG, SIGKILL, 0, 0, 0)
        libc.prctl(PR_SET_PDEATHSIG, signal.SIGKILL, 0, 0, 0)
    except Exception:
        # Non-Linux, libc not found, or prctl missing — silently continue.
        # The timeout-driven killpg path still protects us on the happy
        # path; PR_SET_PDEATHSIG is an additional safety net for the
        # "parent dies ungracefully" scenario.
        pass


def _run_subprocess_with_group_kill(
    cmd: list[str],
    *,
    cwd: str,
    timeout: int,
    stage_name: str,
    mol_id: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run subprocess in a new session, kill entire process group on timeout.

    Prevents grandchild processes (e.g. sqm spawned by antechamber) from
    surviving as CPU-hogging orphans after timeout.

    v00.99.92: also installs ``PR_SET_PDEATHSIG=SIGKILL`` via
    ``preexec_fn`` so the child is killed by the kernel when its parent
    (uvicorn worker / batch runner) dies ungracefully. This closes the
    orphan-reparent-to-init gap that survived even after the timeout
    handler, since an ungraceful parent death never reaches the Python
    timeout code path.

    Args:
        cmd: Command and arguments.
        cwd: Working directory.
        timeout: Maximum execution time in seconds.
        stage_name: Human-readable stage name for error messages.
        mol_id: Molecule ID for error messages.

    Returns:
        CompletedProcess with returncode, stdout, stderr.

    Raises:
        RuntimeError: If the subprocess times out.
    """
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        preexec_fn=_pdeathsig_preexec,
        env=env,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_group(proc, stage_name, mol_id)
        raise RuntimeError(f"{stage_name} timed out after {timeout}s for {mol_id}") from None
    except BaseException:
        # Any error (including SystemExit, KeyboardInterrupt) — clean up
        _kill_process_group(proc, stage_name, mol_id)
        raise

    return subprocess.CompletedProcess(
        args=cmd,
        returncode=proc.returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _analyze_sqm_output(workdir: Path) -> dict[str, object]:
    """Analyze sqm.out for convergence status and progress.

    Parses xmin optimization iterations from sqm.out to detect
    stalled/diverging patterns beyond simple stderr matching.

    Returns:
        Dict with converged, iterations, final_energy, final_gradient,
        progress_pct, failure_hint.
    """
    sqm_out = workdir / "sqm.out"
    if not sqm_out.exists():
        return {
            "converged": False,
            "iterations": 0,
            "failure_hint": "no_output",
            "final_energy": 0.0,
            "final_gradient": 999.0,
            "progress_pct": 0.0,
        }

    try:
        text = sqm_out.read_text(errors="replace")
    except Exception:
        return {
            "converged": False,
            "iterations": 0,
            "failure_hint": "read_error",
            "final_energy": 0.0,
            "final_gradient": 999.0,
            "progress_pct": 0.0,
        }

    iterations = 0
    energies: list[float] = []
    gradients: list[float] = []

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("xmin"):
            parts = stripped.split()
            if len(parts) >= 5:
                try:
                    iterations = int(parts[1])
                    energies.append(float(parts[2]))
                    gradients.append(float(parts[4]))
                except (ValueError, IndexError):
                    continue

    if not energies:
        return {
            "converged": False,
            "iterations": 0,
            "failure_hint": "no_iterations",
            "final_energy": 0.0,
            "final_gradient": 999.0,
            "progress_pct": 0.0,
        }

    converged = gradients[-1] < 0.01 if gradients else False

    failure_hint = ""
    if len(energies) >= 10:
        recent = energies[-5:]
        if max(recent) - min(recent) < 0.001:
            failure_hint = "stalled"
        elif energies[-1] > energies[-5]:
            failure_hint = "diverging"

    return {
        "converged": converged,
        "iterations": iterations,
        "final_energy": energies[-1],
        "final_gradient": gradients[-1] if gradients else 999.0,
        "progress_pct": min(100.0, iterations / 5.0),
        "failure_hint": failure_hint,
    }


_FILE_RELATIVE_PROJECT_ROOT = Path(__file__).resolve().parents[3]
STRICT_ORGANIC_ARTIFACT_CHARGE_TOLERANCE = 1e-4

# Import-time snapshots. PROJECT_ROOT / ARTIFACT_DIR are kept as real module
# attributes (so ``monkeypatch.setattr`` works cleanly without polluting the
# module on teardown). The path-resolving helpers below treat a value that
# still equals its snapshot as "not overridden" and apply env-based resolution
# (ASPHALT_PROJECT_ROOT) on top — giving workspace isolation — while an
# attribute that differs from the snapshot is honoured as a test override.
PROJECT_ROOT = _FILE_RELATIVE_PROJECT_ROOT
ARTIFACT_DIR = PROJECT_ROOT / "data" / "forcefield_artifacts" / "organic_gaff2"
_SNAPSHOT_PROJECT_ROOT = PROJECT_ROOT
_SNAPSHOT_ARTIFACT_DIR = ARTIFACT_DIR


def _project_root() -> Path:
    """Resolve the project root for artifact/catalog data (env-aware).

    Resolution order:
    1. ``monkeypatch.setattr(..., "PROJECT_ROOT", x)`` override (differs
       from the import-time snapshot).
    2. ``ASPHALT_PROJECT_ROOT`` env var (workspace-isolated runs).
    3. Source-relative root — NOT ``common.pathing.get_project_root()``
       which defaults to ``cwd`` — because ``data/forcefield_artifacts``
       and ``data/molecules`` ship with the source tree.
    """
    import os

    cur = globals().get("PROJECT_ROOT", _SNAPSHOT_PROJECT_ROOT)
    if cur != _SNAPSHOT_PROJECT_ROOT:
        return cur
    env = os.environ.get("ASPHALT_PROJECT_ROOT")
    return Path(env) if env else cur


def _artifact_dir() -> Path:
    """Resolve the organic GAFF2 artifact directory (env-aware).

    A ``monkeypatch.setattr(..., "ARTIFACT_DIR", x)`` override takes
    precedence; otherwise the directory is derived from the env-aware
    project root.
    """
    cur = globals().get("ARTIFACT_DIR", _SNAPSHOT_ARTIFACT_DIR)
    if cur != _SNAPSHOT_ARTIFACT_DIR:
        return cur
    return _project_root() / "data" / "forcefield_artifacts" / "organic_gaff2"


# ─────────────────────────────────────────────────────────────────────────────
# Common helpers for artifact path resolution (fail-closed policy v00.99.29)
# ─────────────────────────────────────────────────────────────────────────────


def resolve_artifact_source_id(mol_id: str, ff_assignment: dict | None) -> str:
    """Resolve the effective source_id for artifact lookup.

    Handles:
    - None ff_assignment → use mol_id
    - Empty source_id → use mol_id
    - "_variant_" sentinel → use mol_id (runtime resolution)
    - Explicit source_id → use as-is

    Args:
        mol_id: The molecule identifier.
        ff_assignment: The molecule's ff_assignment dict from YAML.

    Returns:
        The resolved source_id for artifact lookup.
    """
    if ff_assignment is None:
        return mol_id

    source_id = ff_assignment.get("source_id") or mol_id
    if source_id == "_variant_":
        return mol_id

    return source_id


def artifact_filename_for(source_id: str) -> str:
    """Return the canonical artifact filename for a source_id.

    Handles trailing .json if someone accidentally passes it.

    Args:
        source_id: The source_id (mol_id or explicit override).

    Returns:
        Filename like "Toluene.json".
    """
    # Strip .json if already present (defensive)
    if source_id.endswith(".json"):
        source_id = source_id[:-5]
    return f"{source_id}.json"


def get_artifact_path(mol_id: str, ff_assignment: dict | None = None) -> Path:
    """Get the full path to an artifact file.

    This is the SSOT for artifact path resolution. All code that needs
    to locate an artifact should use this function.

    Args:
        mol_id: The molecule identifier.
        ff_assignment: The molecule's ff_assignment dict from YAML.

    Returns:
        Full path to the artifact JSON file.
    """
    source_id = resolve_artifact_source_id(mol_id, ff_assignment)
    filename = artifact_filename_for(source_id)
    return _artifact_dir() / filename


# ─────────────────────────────────────────────────────────────────────────────
# ArtifactTarget — unified resolver (v00.99.41)
#
# Single source of truth for path/consumer/passthrough resolution. All public
# artifact operations (generate, delete, batch, status) go through this
# resolver so filename/dedup semantics stay consistent.
# ─────────────────────────────────────────────────────────────────────────────


_ADMIN_STATUS_SUBDIR = ".admin_status"


@dataclass(frozen=True)
class ArtifactTarget:
    """Canonical resolution of a molecule's artifact location and sharing.

    Attributes:
        mol_id: Requested mol_id (consumer identity).
        source_id: Resolved artifact source_id (dedup key, filename stem).
        ff_assignment: Full ff_assignment dict from YAML (or {}).
        structure_file: Resolved absolute path to MOL/MOL2 structure, or None
            if the catalog entry does not supply one.
        smiles: Canonical SMILES (empty string if unknown).
        formal_charge: Net formal charge from YAML (default 0).
        parameterization_mode: e.g. "organic_gaff2", "organic_gaff2_passthrough",
            "inorganic_profile", or "" when unset.
        is_passthrough: True iff ``parameterization_mode == "organic_gaff2_passthrough"``.
        consumer_ids: All mol_ids in the catalog that resolve to the same
            source_id, sorted alphabetically. Length ≥1 (self inclusive).
        artifact_path: Canonical ``{source_id}.json`` path.
        admin_sidecar_path: Paired ``.admin_status/{source_id}.json`` path.
    """

    mol_id: str
    source_id: str
    ff_assignment: dict = field(default_factory=dict)
    structure_file: Path | None = None
    smiles: str = ""
    formal_charge: int = 0
    parameterization_mode: str = ""
    is_passthrough: bool = False
    consumer_ids: list[str] = field(default_factory=list)
    artifact_path: Path = field(default_factory=lambda: _artifact_dir())
    admin_sidecar_path: Path = field(default_factory=lambda: _artifact_dir() / _ADMIN_STATUS_SUBDIR)

    @property
    def has_shared_source_id(self) -> bool:
        """True when more than one mol_id resolves to this source_id."""
        return len(self.consumer_ids) > 1


# In-process consumer index cache (populated lazily; invalidated by refresh).
_consumer_index_cache: dict[str, list[str]] | None = None
_consumer_ff_cache: dict[str, dict] | None = None
_consumer_mol_cache: dict[str, dict] | None = None
_available_aging_cache: dict[str, list[str]] | None = None  # base_id → available_aging
_consumer_index_lock = threading.Lock()


def _build_consumer_index() -> tuple[
    dict[str, list[str]], dict[str, dict], dict[str, dict], dict[str, list[str]]
]:
    """Scan all molecule YAMLs and build the source_id → [mol_id] index.

    Returns:
        Tuple of (consumer_index, ff_assignment_by_mol_id, metadata_by_mol_id, available_aging_by_base_id).
        ``metadata`` carries structure_file, formal_charge, smiles for later
        ArtifactTarget assembly so we do not re-parse YAML on every resolve.
        ``available_aging_by_base_id`` maps base_id → list of supported aging states.
    """
    import yaml

    consumers: dict[str, list[str]] = defaultdict(list)
    ff_map: dict[str, dict] = {}
    meta_map: dict[str, dict] = {}
    available_aging_map: dict[str, list[str]] = {}  # base_id → available_aging

    def _record(
        mol_id: str,
        ff: dict,
        structure_file: str | None,
        smiles: str,
        formal_charge: int | float,
        parameterization_mode: str = "",
    ) -> None:
        source_id = resolve_artifact_source_id(mol_id, ff)
        if mol_id not in consumers[source_id]:
            consumers[source_id].append(mol_id)
        ff_map[mol_id] = dict(ff or {})
        meta_map[mol_id] = {
            "structure_file": str(structure_file) if structure_file else None,
            "smiles": smiles or "",
            "formal_charge": int(formal_charge or 0),
            "parameterization_mode": parameterization_mode or "",
        }

    def _entry_param_mode(entry: dict) -> str:
        param = entry.get("parameterization") or {}
        if isinstance(param, dict):
            return str(param.get("mode") or "")
        return ""

    # single_moles.yaml
    sm = _project_root() / "data/molecules/single_moles.yaml"
    if sm.exists():
        with open(sm) as f:
            data = yaml.safe_load(f) or {}
        for e in data.get("molecules", []):
            ff = e.get("ff_assignment", {}) or {}
            mol_id = e.get("base_id", "")
            sf = e.get("structure_file", "")
            resolved_sf = str(_project_root() / "data/molecules" / sf) if sf else None
            _record(
                mol_id=mol_id,
                ff=ff,
                structure_file=resolved_sf,
                smiles=ff.get("canonical_smiles", ""),
                formal_charge=ff.get("formal_charge", 0),
                parameterization_mode=_entry_param_mode(e),
            )

    # asphalt_binder.yaml (aging variants + temp_code consumers)
    ab = _project_root() / "data/molecules/asphalt_binder.yaml"
    if ab.exists():
        with open(ab) as f:
            data = yaml.safe_load(f) or {}
        # v00.99.63: read temperature_codes so we can register
        # temp_code-suffixed mol_ids (e.g. "U-RE-Thio-0293") as consumers
        # of the same source artifact ("U-RE-Thio.json"). This eliminates
        # the frontend regex-strip heuristic (v00.99.61) and makes
        # admin_generate_selected's consumer_ids-based matching exact.
        ab_temp_codes = list((data.get("temperature_codes") or {}).keys())
        for e in data.get("molecules", []):
            ff = e.get("ff_assignment", {}) or {}
            base = e.get("base_id", "")
            # Cache available_aging for P1.5 aging UI (base_id → available_aging list)
            mol_available_aging = e.get("available_aging", ["non_aging"])
            available_aging_map[base] = list(mol_available_aging)
            for aging in mol_available_aging:
                pfx = {"non_aging": "U", "short_aging": "S", "long_aging": "L"}.get(aging, "U")
                vid = f"{pfx}-{base}"
                dmap = {
                    "non_aging": "non_aging_moles",
                    "short_aging": "short_aging_moles",
                    "long_aging": "long_aging_moles",
                }
                mp = (
                    _project_root()
                    / "data/molecules/asphalt_binder"
                    / dmap.get(aging, "non_aging_moles")
                    / f"{vid}.mol"
                )
                _record(
                    mol_id=vid,
                    ff=ff,
                    structure_file=str(mp),
                    smiles=ff.get("canonical_smiles", ""),
                    formal_charge=ff.get("formal_charge", 0),
                    parameterization_mode=_entry_param_mode(e),
                )
                # Register temp_code variants as consumers of the same source.
                # The variant's ff_map entry carries an explicit source_id so
                # resolve_artifact_target("U-RE-Thio-0293") resolves to
                # source_id="U-RE-Thio" and artifact_path="U-RE-Thio.json".
                source_id = resolve_artifact_source_id(vid, ff)
                for tc in ab_temp_codes:
                    tc_vid = f"{vid}-{tc}"
                    if tc_vid not in consumers[source_id]:
                        consumers[source_id].append(tc_vid)
                    if tc_vid not in ff_map:
                        tc_ff = dict(ff or {})
                        tc_ff["source_id"] = source_id
                        ff_map[tc_vid] = tc_ff
                    if tc_vid not in meta_map:
                        meta_map[tc_vid] = {
                            "structure_file": str(mp),
                            "smiles": ff.get("canonical_smiles", ""),
                            "formal_charge": int(ff.get("formal_charge", 0)),
                            "parameterization_mode": _entry_param_mode(e),
                        }

    # additives.yaml
    ad = _project_root() / "data/molecules/additives.yaml"
    if ad.exists():
        with open(ad) as f:
            data = yaml.safe_load(f) or {}
        for k, e in data.get("additives", {}).items():
            if not isinstance(e, dict):
                continue
            ff = e.get("ff_assignment", {}) or {}
            sf = e.get("structure_file", f"additives/{k}.mol")
            _record(
                mol_id=k,
                ff=ff,
                structure_file=str(_project_root() / "data/molecules" / sf),
                smiles=ff.get("canonical_smiles", ""),
                formal_charge=ff.get("formal_charge", 0),
                parameterization_mode=_entry_param_mode(e),
            )

    for sid in consumers:
        consumers[sid].sort()
    return dict(consumers), ff_map, meta_map, available_aging_map


def _load_consumer_index(
    refresh: bool = False,
) -> tuple[dict[str, list[str]], dict[str, dict], dict[str, dict]]:
    """Return cached consumer index, scanning YAML lazily on first call.

    Thread-safe; callers may pass ``refresh=True`` to invalidate after YAML edits.
    """
    global _consumer_index_cache, _consumer_ff_cache, _consumer_mol_cache, _available_aging_cache
    with _consumer_index_lock:
        if refresh or _consumer_index_cache is None:
            (
                _consumer_index_cache,
                _consumer_ff_cache,
                _consumer_mol_cache,
                _available_aging_cache,
            ) = _build_consumer_index()
        assert _consumer_index_cache is not None
        assert _consumer_ff_cache is not None
        assert _consumer_mol_cache is not None
        return _consumer_index_cache, _consumer_ff_cache, _consumer_mol_cache


def refresh_consumer_index() -> None:
    """Invalidate the cached YAML → consumer index."""
    _load_consumer_index(refresh=True)


def get_available_aging(base_id: str) -> list[str]:
    """Get the available aging states for a base molecule ID.

    Uses cached YAML data from the consumer index. This is the SSOT for
    determining which aging variants (non_aging, short_aging, long_aging)
    are supported for a given asphalt molecule.

    Args:
        base_id: Base molecule ID (e.g., "SA-Squalane", "AS-Thio").

    Returns:
        List of supported aging states (e.g., ["non_aging"] for saturates,
        ["non_aging", "short_aging", "long_aging"] for asphaltenes).
        Defaults to ["non_aging"] if base_id not found.
    """
    # Ensure index is loaded (triggers lazy load if needed)
    _load_consumer_index()
    if _available_aging_cache is None:
        return ["non_aging"]
    return _available_aging_cache.get(base_id, ["non_aging"])


def resolve_artifact_target(
    mol_id: str,
    ff_assignment: dict | None = None,
    *,
    structure_file: str | Path | None = None,
    smiles: str | None = None,
    formal_charge: int | None = None,
) -> ArtifactTarget:
    """Resolve a mol_id to its canonical :class:`ArtifactTarget`.

    When ``ff_assignment`` is omitted, looks it up from the cached YAML index.
    Explicit overrides (``structure_file``, ``smiles``, ``formal_charge``) take
    precedence over the cached metadata so callers can inject runtime values.

    Args:
        mol_id: Consumer molecule identifier.
        ff_assignment: Optional ff_assignment dict. If None, loaded from YAML.
        structure_file: Optional override for the MOL/MOL2 path.
        smiles: Optional SMILES override.
        formal_charge: Optional formal charge override.

    Returns:
        Fully populated :class:`ArtifactTarget`.
    """
    consumers, ff_map, meta_map = _load_consumer_index()

    effective_ff = dict(ff_assignment) if ff_assignment else dict(ff_map.get(mol_id, {}))
    source_id = resolve_artifact_source_id(mol_id, effective_ff)

    meta = meta_map.get(mol_id, {})
    resolved_sf = structure_file if structure_file is not None else meta.get("structure_file")
    sf_path: Path | None = Path(resolved_sf) if resolved_sf else None

    resolved_smiles = (
        smiles
        if smiles is not None
        else effective_ff.get("canonical_smiles", meta.get("smiles", ""))
    )
    resolved_charge = (
        formal_charge
        if formal_charge is not None
        else int(effective_ff.get("formal_charge", meta.get("formal_charge", 0)))
    )

    # parameterization.mode lives at the entry top level (sibling of
    # ff_assignment in YAML). Allow callers to also pass it through
    # ff_assignment.parameterization for forward-compat with synthesised
    # assignments coming from non-YAML sources.
    explicit_param = effective_ff.get("parameterization") if ff_assignment else None
    if isinstance(explicit_param, dict) and explicit_param.get("mode"):
        mode = str(explicit_param["mode"])
    else:
        mode = str(meta.get("parameterization_mode") or "")

    consumer_ids = list(consumers.get(source_id, [mol_id]))
    if mol_id not in consumer_ids:
        consumer_ids.append(mol_id)
        consumer_ids.sort()

    artifact_path = _artifact_dir() / artifact_filename_for(source_id)
    admin_sidecar_path = _artifact_dir() / _ADMIN_STATUS_SUBDIR / artifact_filename_for(source_id)

    return ArtifactTarget(
        mol_id=mol_id,
        source_id=source_id,
        ff_assignment=effective_ff,
        structure_file=sf_path,
        smiles=resolved_smiles,
        formal_charge=resolved_charge,
        parameterization_mode=mode,
        is_passthrough=(mode == "organic_gaff2_passthrough"),
        consumer_ids=consumer_ids,
        artifact_path=artifact_path,
        admin_sidecar_path=admin_sidecar_path,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Source-level generation lock (v00.99.42)
#
# Lifted out of artifact_runtime.ensure_organic_artifact so that admin/public
# generate endpoints, batch workers, and runtime auto-generation all share
# the same fcntl LOCK_EX scope keyed on ``source_id``. This guarantees that
# the artifact JSON write and the admin sidecar write happen as one atomic
# block — readers (admin status, runtime fast-path) never observe one half
# of the pair without the other.
# ─────────────────────────────────────────────────────────────────────────────


_STALE_LOCK_THRESHOLD_SECONDS = 21600  # 6h — matches artifact_runtime


def _generation_lock_path(source_id: str, artifact_dir: Path | None = None) -> Path:
    target_dir = Path(artifact_dir) if artifact_dir is not None else _artifact_dir()
    return target_dir / f".{source_id}.generating.lock"


def cleanup_stale_generation_locks(artifact_dir: Path | None = None) -> int:
    """Remove ``.generating.lock`` files older than the stale threshold.

    Idempotent and safe to call from any process. Mirrors the helper that
    used to live in ``artifact_runtime`` so admin tooling can also call it.

    Returns:
        Number of stale lock files removed.
    """
    target_dir = Path(artifact_dir) if artifact_dir is not None else _artifact_dir()
    if not target_dir.exists():
        return 0
    now = time.time()
    removed = 0
    for lock_file in target_dir.glob(".*.generating.lock"):
        try:
            age = now - lock_file.stat().st_mtime
            if age > _STALE_LOCK_THRESHOLD_SECONDS:
                lock_file.unlink(missing_ok=True)
                removed += 1
        except OSError:
            pass
    if removed:
        logger.info("Cleaned up %d stale lock file(s) in %s", removed, target_dir)
    return removed


@contextlib.contextmanager
def source_generation_lock(source_id: str, *, artifact_dir: Path | None = None) -> Iterator[Path]:
    """Acquire an ``fcntl.LOCK_EX`` keyed on ``source_id``.

    Used as the single serialization primitive for any code path that
    writes ``{source_id}.json`` (artifact) and/or
    ``.admin_status/{source_id}.json`` (sidecar). Wrapping both writes
    inside the same ``with`` block keeps them in sync from the reader's
    perspective.

    Yields the underlying lock file path so callers can log it, but
    nothing else.

    Critical correctness note (v00.99.42 reinforcement): the marker file
    is intentionally **left in place** on normal exit. ``fcntl`` is an
    inode-level lock; if we ``unlink()`` while another writer is blocked
    on this fd, a third writer who arrives next opens a *new* inode and
    the two would acquire concurrent exclusive locks on different inodes
    — silent loss of mutual exclusion. The dedicated
    :func:`cleanup_stale_generation_locks` helper is the only mechanism
    that may remove these marker files, and it does so only when the
    file is older than the stale threshold (no concurrent writer
    contention possible at that age).
    """
    target_dir = Path(artifact_dir) if artifact_dir is not None else _artifact_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    cleanup_stale_generation_locks(target_dir)
    lock_path = _generation_lock_path(source_id, target_dir)
    with open(lock_path, "w") as lock_f:
        fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
        try:
            yield lock_path
        finally:
            try:
                fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
    # NB: do NOT unlink lock_path here — see docstring above.


# ─────────────────────────────────────────────────────────────────────────────
# Admin helpers (v00.99.42)
#
# `validate_admin_generation_request` and `diagnose_artifact_target` are the
# single-source-of-truth for admin-side gating + preflight. The HTTP router
# and the offline CLI both call only these functions so the policy cannot
# drift between surfaces.
# ─────────────────────────────────────────────────────────────────────────────


class AdminGenerationError(RuntimeError):
    """Structured admin-validation failure carrying an HTTP status hint."""

    def __init__(self, *, status_code: int, message: str, detail: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.detail = detail or {}


def validate_admin_generation_request(
    target: ArtifactTarget,
    profile: str,
    store: AdminStatusStore | None = None,
) -> None:
    """Apply the admin generate gating policy.

    Raises :class:`AdminGenerationError` with the same status_code that the
    router exposes (400 / 405 / 409) so HTTP and CLI surface identical
    semantics. ``store`` is required only when ``profile == "sqm_robust"``
    so the policy can read the most recent failure_code.
    """
    if profile not in SUPPORTED_GENERATION_PROFILES:
        raise AdminGenerationError(
            status_code=400,
            message=(
                f"profile must be one of {list(SUPPORTED_GENERATION_PROFILES)}; got {profile!r}."
            ),
        )
    if target.is_passthrough:
        raise AdminGenerationError(
            status_code=405,
            message=(
                f"{target.mol_id} is a passthrough entry "
                "(parameterization.mode=organic_gaff2_passthrough); the admin "
                "surface cannot generate it because no AM1-BCC executor exists."
            ),
        )
    if profile == "sqm_robust":
        sidecar = store.get(target.source_id) if store is not None else None
        last_code = sidecar.failure_code if sidecar else None
        if last_code not in {"sqm_timeout", "sqm_nonconverged"}:
            raise AdminGenerationError(
                status_code=409,
                message=(
                    "sqm_robust may only be retried after a baseline "
                    "sqm_timeout or sqm_nonconverged failure. Latest "
                    f"failure_code={last_code!r}."
                ),
                detail={"latest_failure_code": last_code},
            )


def diagnose_artifact_target(target: ArtifactTarget) -> dict:
    """Run the RDKit preflight for an :class:`ArtifactTarget`.

    Single SSOT for both ``POST /artifacts/admin/diagnose/{mol_id}`` and
    ``scripts/generate_gaff2_artifact.py --diagnose-only`` so the two
    surfaces produce identical reports. Returns the JSON-friendly dict
    documented in :func:`features.molecules.preflight.run_rdkit_preflight`.
    """
    from .preflight import run_rdkit_preflight

    return run_rdkit_preflight(
        mol_id=target.mol_id,
        structure_file=target.structure_file,
        smiles=target.smiles,
        formal_charge=target.formal_charge,
        is_passthrough=target.is_passthrough,
    )


# Batch generation progress (thread-safe). v00.99.43: extended with
# batch_kind / generation_profile / started_at metadata so the admin FF
# Parameters page can tell whether a running batch is its own.
_batch_progress: dict = {
    "running": False,
    "cancelled": False,
    "total": 0,
    "completed": 0,
    "failed": 0,
    "skipped": 0,
    "retried": 0,  # v00.99.55: count of mols that auto-retried baseline→sqm_robust
    # v00.99.57: bucket breakdown so the UI can render a stacked progress bar
    # without ambiguity. `retried_succeeded` <= `retried`; the difference is
    # "retried but still failed" (already accounted for in `failed`).
    "retried_succeeded": 0,
    # Number of mols currently executing (submit - complete). Chunked
    # ProcessPoolExecutor so this caps at `max_workers` at any instant.
    "in_progress": 0,
    # v00.99.93: in_progress_baseline / in_progress_robust removed. The
    # v00.99.90 Manager.dict phase_map IPC introduced a hang path where
    # `run_parallel_batch` could not complete its `with` block teardown,
    # leaving `running=True` latched indefinitely. Front-end already
    # falls back to single `Running N` label when these fields are
    # absent (AdminBatchProgress.jsx: hasPhaseSplit guard).
    "last_completed_mol_id": "",  # v00.99.55: renamed from current_mol_id — with ProcessPoolExecutor
    # workers run in parallel so this is the *most recently completed* mol, not in-flight.
    "current_mol_id": "",  # kept for backwards compat — mirrors last_completed_mol_id
    "last_retry_reason": "",  # v00.99.55: short human-readable last retry hint
    "percent": 0.0,
    "max_workers": 0,
    "batch_kind": "",  # "" | "public" | "admin"
    "generation_profile": "",  # "" | "baseline" | "sqm_robust"
    "started_at": None,  # unix epoch float | None
}
_batch_lock = threading.Lock()


def get_batch_progress() -> dict:
    """Get current batch generation progress.

    Includes stale-batch auto-detection: if running=True but no workers
    are in-flight and all molecules reached a terminal state, the batch
    slot is force-released. This prevents a permanently stuck running
    flag after abnormal process termination (timeout kill, etc.).
    """
    with _batch_lock:
        if _batch_progress["running"]:
            total = _batch_progress.get("total", 0)
            in_progress = _batch_progress.get("in_progress", 0)
            done = (
                (_batch_progress.get("completed", 0) or 0)
                + (_batch_progress.get("failed", 0) or 0)
                + (_batch_progress.get("skipped", 0) or 0)
            )
            if total > 0 and in_progress == 0 and done >= total:
                logger.warning(
                    "Stale batch detected (running=True, in_progress=0, "
                    "done=%d >= total=%d). Auto-releasing batch slot.",
                    done,
                    total,
                )
                _batch_progress["running"] = False
                _batch_progress["cancelled"] = False
                _batch_progress["batch_kind"] = ""
                _batch_progress["generation_profile"] = ""
                _batch_progress["started_at"] = None
                _batch_progress["current_mol_id"] = ""
                _batch_progress["in_progress"] = 0
                _batch_progress["retried_succeeded"] = 0
        return dict(_batch_progress)


def acquire_batch_slot(
    batch_kind: str,
    generation_profile: str = "baseline",
) -> bool:
    """Atomic test-and-set guard preventing concurrent batches.

    v00.99.43: ``_batch_progress`` is a module-level singleton shared
    between public ``/artifacts/generate-all`` and admin
    ``/artifacts/admin/generate-all``. Without this guard two callers
    that both observe ``running=False`` could each start a worker pool
    that races on the same source_ids. The guard runs inside
    ``_batch_lock`` so the read-modify-write is atomic.

    Args:
        batch_kind: ``"public"`` or ``"admin"``. Stored in the progress
            payload so frontends can identify their own batch.
        generation_profile: ``"baseline"`` or ``"sqm_robust"``. Persisted
            so the admin page can warn when a sqm_robust batch is in
            flight.

    Returns:
        True when the slot was acquired (caller is now the writer);
        False when another batch is already running and the caller must
        back off (HTTP routers should map False to 409).
    """
    if batch_kind not in {"public", "admin", "typing_prepare"}:
        raise ValueError(f"batch_kind must be public|admin|typing_prepare, got {batch_kind!r}")
    with _batch_lock:
        if _batch_progress["running"]:
            return False
        # v00.99.43 codex audit: reset counters atomically with the
        # running flip so the first /batch-progress poll after acquire
        # never returns stale numbers from the previous batch.
        _batch_progress.update(
            {
                "running": True,
                "cancelled": False,
                "total": 0,
                "completed": 0,
                "failed": 0,
                "skipped": 0,
                "retried": 0,
                "retried_succeeded": 0,
                "in_progress": 0,
                "percent": 0.0,
                "current_mol_id": "",
                "last_completed_mol_id": "",
                "last_retry_reason": "",
                "max_workers": 0,
                "batch_kind": batch_kind,
                "generation_profile": generation_profile,
                "started_at": time.time(),
            }
        )
        return True


def release_batch_slot() -> None:
    """Release the batch slot, clearing metadata so the next acquire
    starts from a clean state. Idempotent."""
    with _batch_lock:
        _batch_progress["running"] = False
        _batch_progress["cancelled"] = False
        _batch_progress["batch_kind"] = ""
        _batch_progress["generation_profile"] = ""
        _batch_progress["started_at"] = None
        _batch_progress["current_mol_id"] = ""
        # v00.99.57: drop bucketed counters so the next batch acquire doesn't
        # inherit stale in_progress / retried_succeeded from a previous run.
        _batch_progress["in_progress"] = 0
        _batch_progress["retried_succeeded"] = 0

    # v00.99.91: opportunistic stale-lock sweep at batch end. Runs outside
    # the `_batch_lock` so a slow filesystem never blocks the slot reset.
    # Exceptions are swallowed — cleanup is best-effort maintenance and
    # must not prevent a caller from releasing the slot.
    try:
        cleanup_stale_generation_locks()
    except Exception:
        logger.exception("release_batch_slot: stale-lock cleanup failed")


def cancel_batch() -> bool:
    """Request cancellation of the running batch.

    Sets a cancel flag that the batch runner checks between molecules.
    The currently generating molecule will finish (artifact stays valid),
    but no new molecules will be started.

    Returns:
        True if a batch was running, False if nothing to cancel.
    """
    with _batch_lock:
        if not _batch_progress["running"]:
            return False
        _batch_progress["cancelled"] = True
        logger.info("Batch cancellation requested")
        return True


def force_cleanup_batch() -> dict:
    """Force-cleanup stuck batch: locks + batch state.

    Use this when the batch process terminated abnormally and left
    orphan lock files or a stuck ``running=True`` state. This function:

    1. Deletes ALL ``.*.generating.lock`` files regardless of age.
    2. Releases the batch slot (resets ``_batch_progress``).

    Returns:
        Dict with ``locks_removed``, ``affected_source_ids``, ``batch_reset``.

    Note:
        This is a destructive operation. If a generation process is
        actually running, force cleanup may cause race conditions.
        The UI should confirm with the operator before calling.
    """
    locks_removed = 0
    affected_source_ids: list[str] = []

    # Step 1: Delete ALL .generating.lock files (regardless of age)
    if _artifact_dir().exists():
        for lock_file in _artifact_dir().glob(".*.generating.lock"):
            try:
                # .{source_id}.generating.lock → extract source_id
                name = lock_file.name
                # Remove "." prefix and ".generating.lock" suffix
                source_id = name[1:-16]
                affected_source_ids.append(source_id)
                lock_file.unlink(missing_ok=True)
                locks_removed += 1
                logger.info("Force-removed lock: %s", source_id)
            except OSError as e:
                logger.warning("Failed to remove lock %s: %s", lock_file, e)

    # Step 2: Reset batch_progress state
    release_batch_slot()

    logger.info("Force cleanup: locks_removed=%d", locks_removed)

    return {
        "locks_removed": locks_removed,
        "affected_source_ids": affected_source_ids,
        "batch_reset": True,
    }


def _is_batch_cancelled() -> bool:
    """Check if cancellation has been requested."""
    with _batch_lock:
        return _batch_progress.get("cancelled", False)


def _update_batch_progress(**kwargs: object) -> None:
    """Update batch progress (internal use by batch runner)."""
    with _batch_lock:
        _batch_progress.update(kwargs)
        total = _batch_progress["total"]
        done = (
            _batch_progress["completed"]
            + _batch_progress["failed"]
            + _batch_progress.get("skipped", 0)
        )
        _batch_progress["percent"] = round(done / total * 100, 1) if total > 0 else 0.0


def delete_artifact(
    mol_id: str,
    ff_family: str = "organic_gaff2",
    *,
    ff_assignment: dict | None = None,
    force: bool = False,
) -> bool:
    """Delete a GAFF2 artifact JSON by canonical source_id.

    Resolves the target through :func:`resolve_artifact_target`, refuses to
    delete when the resolved ``source_id`` is shared by more than one consumer
    (unless ``force=True``), and defensively unlinks any legacy
    ``{mol_id}.json`` sibling left over from the pre-v00.99.41 filename scheme.

    Args:
        mol_id: Requested consumer identifier.
        ff_family: Force field family key (reserved; only ``"organic_gaff2"``
            is currently supported).
        ff_assignment: Optional explicit ff_assignment dict. If omitted, the
            value is loaded from the cached catalog index.
        force: When True, proceed even if the source_id has multiple consumers.

    Returns:
        True when at least one file was removed (canonical or legacy),
        False when nothing existed to delete.

    Raises:
        ValueError: Malformed ``mol_id`` that could escape the artifact dir.
        PermissionError: Resolved path traverses outside ``ARTIFACT_DIR``.
        RuntimeError: Shared-source deletion attempted without ``force``.
    """
    import re

    # Whitelist mol_id format: alphanumeric, hyphens, underscores, spaces only
    if not re.fullmatch(r"[A-Za-z0-9_ \-]+", mol_id):
        raise ValueError(f"Invalid mol_id format: {mol_id!r}")

    target = resolve_artifact_target(mol_id, ff_assignment)

    if target.has_shared_source_id and not force:
        raise RuntimeError(
            "Refusing to delete artifact with shared source_id "
            f"{target.source_id!r} (consumers={target.consumer_ids}). "
            "Pass force=True to override.",
        )

    legacy_path = _artifact_dir() / artifact_filename_for(mol_id)
    artifact_removed = False

    for candidate in (target.artifact_path, legacy_path):
        try:
            resolved = candidate.resolve()
            resolved.relative_to(_artifact_dir().resolve())
        except ValueError:
            raise PermissionError(
                f"Path traversal blocked for mol_id={mol_id!r}",
            ) from None
        if resolved.exists():
            resolved.unlink()
            artifact_removed = True

    if artifact_removed:
        try:
            from forcefield.organic_curated_artifact import clear_artifact_cache

            clear_artifact_cache()
        except ImportError:
            pass

    # v01.02.05: always delete sidecar if it exists, even when no artifact JSON
    # was present. This allows resetting failed artifacts to pending state.
    sidecar_removed = False
    try:
        sidecar_removed = _admin_status_store().delete(target.source_id)
    except Exception:
        logger.exception("admin sidecar delete failed for %s", target.source_id)

    removed = artifact_removed or sidecar_removed
    if removed:
        logger.info(
            "Deleted artifact: mol_id=%s source_id=%s (artifact=%s, sidecar=%s)",
            mol_id,
            target.source_id,
            artifact_removed,
            sidecar_removed,
        )
    return removed


def check_ambertools_available() -> bool:
    """Check if antechamber, parmchk2, tleap are on PATH."""
    for cmd in ("antechamber", "parmchk2", "tleap"):
        if subprocess.run(["which", cmd], capture_output=True).returncode != 0:
            return False
    try:
        import parmed  # noqa: F401

        return True
    except ImportError:
        return False


def _normalize_artifact_atom_charges(
    atoms: list[dict],
    formal_charge: int | float = 0,
    *,
    tolerance: float = STRICT_ORGANIC_ARTIFACT_CHARGE_TOLERANCE,
) -> tuple[list[dict], float]:
    """Normalize charges so the artifact sum matches formal_charge.

    AmberTools AM1-BCC output can leave a small residual charge after rounding.
    Curated artifacts are treated as strict runtime inputs, so we collapse the
    residual onto the most charged heavy atom to make the artifact deterministic
    and runtime-neutral.
    """
    normalized = [dict(atom) for atom in atoms]
    if not normalized:
        return normalized, float(formal_charge)

    total_charge = sum(float(atom.get("charge", 0.0)) for atom in normalized)
    target_charge = float(formal_charge)
    delta = target_charge - total_charge
    if abs(delta) <= tolerance:
        return normalized, total_charge

    heavy_atoms = [atom for atom in normalized if str(atom.get("element", "")).upper() != "H"]
    candidate_atoms = heavy_atoms or normalized
    target_atom = max(
        candidate_atoms,
        key=lambda atom: (abs(float(atom.get("charge", 0.0))), -int(atom.get("index", 0))),
    )
    target_atom["charge"] = round(float(target_atom.get("charge", 0.0)) + delta, 6)

    normalized_total = sum(float(atom.get("charge", 0.0)) for atom in normalized)
    residual = target_charge - normalized_total
    if abs(residual) > tolerance:
        target_atom["charge"] = round(float(target_atom["charge"]) + residual, 6)
        normalized_total = sum(float(atom.get("charge", 0.0)) for atom in normalized)

    if abs(target_charge - normalized_total) > tolerance:
        raise RuntimeError(
            f"Failed to normalize artifact charge sum: target={target_charge:+.6f} "
            f"actual={normalized_total:+.6f}"
        )

    return normalized, normalized_total


def _artifact_charge_mismatch(
    artifact: dict,
    *,
    tolerance: float = STRICT_ORGANIC_ARTIFACT_CHARGE_TOLERANCE,
) -> tuple[bool, float, float]:
    """Return whether an artifact charge sum deviates from formal charge."""
    atoms = artifact.get("atoms", [])
    actual = sum(float(atom.get("charge", 0.0)) for atom in atoms)
    expected = float(artifact.get("formal_charge", 0.0))
    return abs(actual - expected) > tolerance, expected, actual


GenerationProfile = str  # Literal["baseline", "sqm_robust", "fragment_fallback"]
SUPPORTED_GENERATION_PROFILES: tuple[str, ...] = ("baseline", "sqm_robust", "fragment_fallback")


def _assert_fragment_fallback_eligible(mol_path: Path, mol_id: str, formal_charge: int) -> None:
    """Gate the fragment_fallback profile to neutral C/H/O/N/S molecules.

    Mirrors the governance domain of the fragment-reference charge table
    (``forcefield.fragment_fallback._REFERENCE_CHARGES``): only neutral CHONS
    molecules qualify. Non-CHONS / charged / radical species fail closed — they
    are handled by the ionic route or rejected at preflight, never here.

    Raises:
        ArtifactGenerationError: if the molecule is unparseable, non-CHONS, or
            carries a net charge other than ``formal_charge``.
    """
    from rdkit import Chem

    from forcefield.fragment_fallback import _ALLOWED_ELEMENTS

    mol = Chem.MolFromMolFile(str(mol_path), removeHs=False)
    if mol is None:
        raise ArtifactGenerationError(
            stage="fragment_fallback",
            failure_code=ArtifactFailureCode.MANUAL_REVIEW_REQUIRED,
            message=f"RDKit could not parse {mol_path.name} for {mol_id} (fragment_fallback gate).",
        )
    elements = {a.GetSymbol() for a in mol.GetAtoms()}
    if not elements.issubset(_ALLOWED_ELEMENTS):
        raise ArtifactGenerationError(
            stage="fragment_fallback",
            failure_code=ArtifactFailureCode.MANUAL_REVIEW_REQUIRED,
            message=(
                f"Fragment fallback supports only neutral C/H/O/N/S; "
                f"{mol_id} contains {sorted(elements - _ALLOWED_ELEMENTS)}."
            ),
        )
    if Chem.GetFormalCharge(mol) != formal_charge:
        raise ArtifactGenerationError(
            stage="fragment_fallback",
            failure_code=ArtifactFailureCode.MANUAL_REVIEW_REQUIRED,
            message=(
                f"Fragment fallback requires neutral molecules matching nc={formal_charge}; "
                f"{mol_id} has formal charge {Chem.GetFormalCharge(mol)}."
            ),
        )


def _apply_fragment_reference_charges(atoms: list[dict], formal_charge: int = 0) -> list[dict]:
    """Replace per-atom charges with fragment-reference AM1-BCC values (in place).

    The ``-c gas`` typing step assigns Gasteiger charges, which the FF
    governance explicitly rejects (the GAFF2 LJ parameters are validated against
    AM1-BCC charges — swapping the charge *model* breaks the non-bonded
    LJ<->Coulomb balance). So for the fragment_fallback profile we overwrite the
    charges with the project's fragment-environment AM1-BCC reference values,
    keyed by GAFF2 atom type, keeping the AM1-BCC charge model. Atom typing,
    bonded terms and LJ stay exactly as the canonical antechamber->parmchk2->
    tleap->parmed pipeline produced them.

    The residual to the formal charge is spread UNIFORMLY across all atoms
    (``fragment_fallback._normalize_charges``), exactly as the legacy RDKit
    fragment path did — NOT collapsed onto a single atom like the AM1-BCC
    normaliser (whose residuals are tiny), which would put an unphysical bulk
    charge on one atom when the reference sum is far from neutral.
    """
    from forcefield.fragment_fallback import _REFERENCE_CHARGES, _normalize_charges

    raw = [_REFERENCE_CHARGES.get(str(a.get("ff_type", "")), 0.0) for a in atoms]
    normalized = _normalize_charges(raw, formal_charge)
    for a, q in zip(atoms, normalized, strict=False):
        a["charge"] = round(q, 6)
    return atoms


def generate_gaff2_artifact(
    mol_path: Path,
    mol_id: str,
    smiles: str = "",
    formal_charge: int = 0,
    *,
    progress_callback: Callable[[str, str], None] | None = None,
    ff_assignment: dict | None = None,
    generation_profile: GenerationProfile = "baseline",
) -> dict:
    """Generate GAFF2 artifact JSON from MOL file.

    Pipeline: antechamber -> parmchk2 -> tleap -> parmed -> JSON.

    The output filename is resolved via :func:`resolve_artifact_target` so
    consumer entries sharing an explicit ``source_id`` write to the same
    canonical artifact (and shared-source conflicts are rejected before we
    touch AmberTools).

    Args:
        mol_path: Path to MDL MOL or MOL2 file.
        mol_id: Molecule identifier (consumer-side).
        smiles: Canonical SMILES string.
        formal_charge: Net formal charge.
        progress_callback: Optional ``(code, label)`` callback invoked
            immediately before each of the four subprocess stages
            (``artifact_antechamber``, ``artifact_parmchk2``,
            ``artifact_tleap``, ``artifact_parmed``). Exceptions raised by
            the callback are swallowed to keep builds best-effort.
        ff_assignment: Optional ff_assignment dict. If omitted, it is
            resolved from the catalog index.

    Returns:
        Artifact dict (schema_version=2, ff_family=organic_gaff2).

    Raises:
        ArtifactGenerationError: If any pipeline step fails or a passthrough
            / shared source_id conflict is detected before AmberTools is
            invoked. ``stage`` and ``failure_code`` identify the phase and
            machine-actionable cause; ``stderr_excerpt`` carries the
            truncated subprocess stderr.
        FileNotFoundError: If ``mol_path`` doesn't exist.
    """
    import shutil

    import parmed

    def _emit(code: str, label: str) -> None:
        if progress_callback is None:
            return
        try:
            progress_callback(code, label)
        except Exception as exc:
            logger.debug("artifact progress callback failed: %s", exc)

    if generation_profile not in SUPPORTED_GENERATION_PROFILES:
        raise ValueError(
            f"generation_profile={generation_profile!r} not in {SUPPORTED_GENERATION_PROFILES}"
        )

    if not mol_path.exists():
        raise FileNotFoundError(f"MOL file not found: {mol_path}")

    target = resolve_artifact_target(
        mol_id,
        ff_assignment,
        structure_file=mol_path,
        smiles=smiles,
        formal_charge=formal_charge,
    )
    if target.is_passthrough:
        raise ArtifactGenerationError(
            stage="preflight",
            failure_code=ArtifactFailureCode.PASSTHROUGH_UNSUPPORTED,
            message=(
                f"Refusing GAFF2 generation for passthrough entry "
                f"mol_id={mol_id!r} (parameterization.mode="
                "organic_gaff2_passthrough). Passthrough entries have no "
                "AM1-BCC executor; the admin FF Parameters page is the "
                "correct surface."
            ),
        )
    if target.has_shared_source_id:
        logger.warning(
            "Shared source_id %s detected (consumers=%s); artifact will be "
            "written once under the canonical filename.",
            target.source_id,
            target.consumer_ids,
        )

    # Fragment-fallback profile: the AM1 SCF won't converge for this structure
    # (baseline + sqm_robust both exhausted). We still derive the FULL canonical
    # GAFF2 set — atom typing + bonds/angles/dihedrals/impropers + LJ — from the
    # antechamber->parmchk2->tleap->parmed pipeline below, because those are
    # SCF-independent gaff2.dat lookups (the typing step runs with ``-c gas`` so
    # no SCF is attempted). Only the CHARGES fall back to fragment-reference
    # AM1-BCC values (applied after parmed), so the charge MODEL stays AM1-BCC —
    # no Gasteiger/EEM — and the GAFF2 LJ<->Coulomb balance + Lorentz-Berthelot
    # mixing are preserved. Eligibility is gated to neutral CHONS (governance:
    # research_only via generator=fragment_fallback_gaff2).
    if generation_profile == "fragment_fallback":
        _assert_fragment_fallback_eligible(mol_path, mol_id, formal_charge)

    # The antechamber pipeline below raises ArtifactGenerationError on failure;
    # the caller (artifact_runtime) decides whether to escalate the profile.
    try:
        with tempfile.TemporaryDirectory(prefix=f"gaff2_{mol_id[:20]}_") as tmpdir:
            wd = Path(tmpdir)

            # Copy input to workdir (portable, no absolute paths)
            fi = "mdl" if mol_path.suffix.lower() == ".mol" else "mol2"
            local_input = wd / f"input{mol_path.suffix}"
            shutil.copy2(mol_path, local_input)

            # Step 1: antechamber (GAFF2 typing + charges). fragment_fallback uses
            # ``-c gas`` (no SCF) for typing only; its charges are overwritten with
            # fragment-reference AM1-BCC values after parmed.
            _is_fragment = generation_profile == "fragment_fallback"
            _emit(
                "artifact_antechamber",
                (
                    "GAFF2 원자타이핑 (antechamber, SCF 우회)"
                    if _is_fragment
                    else "부분전하 계산 (antechamber AM1-BCC)"
                ),
            )
            mol2_out = wd / "typed.mol2"
            antechamber_cmd: list[str] = [
                "antechamber",
                "-i",
                local_input.name,
                "-fi",
                fi,
                "-o",
                str(mol2_out),
                "-fo",
                "mol2",
                "-c",
                "gas" if _is_fragment else "bcc",
                "-at",
                "gaff2",
                "-pf",
                "y",
                "-nc",
                str(formal_charge),
            ]
            if generation_profile == "sqm_robust":
                # sqm_robust profile (admin-only) injects convergence-aid
                # options inspired by Walker & Crowley (J Chem Theory Comput
                # 2007). antechamber forwards everything after ``-ek`` to sqm.
                antechamber_cmd.extend(
                    [
                        "-ek",
                        (
                            "vshift=0.1, scfconv=1.0d-9, itrmax=500, maxcyc=2000, "
                            "ndiis_attempts=200, ndiis_matrices=6, tight_p_conv=0, "
                            "pseudo_diag=1, grms_tol=0.0005"
                        ),
                    ]
                )
            _antechamber_env = {**os.environ, "OMP_NUM_THREADS": "1"}
            # Timeouts are policy SSOT (efficiency layer, v01.06.20): baseline
            # ~600s, sqm_robust ~1800s. A non-convergent structure grinds to the
            # cap regardless; molecules that converge do so well inside it. The
            # fragment_fallback profile reuses the baseline cap (its ``-c gas``
            # typing is fast and SCF-free).
            from contracts.policies.ff_generation import DEFAULT_FF_GENERATION_POLICY as _FFGEN

            _antechamber_timeout = (
                _FFGEN.sqm_robust_timeout_s
                if generation_profile == "sqm_robust"
                else _FFGEN.baseline_timeout_s
            )
            try:
                r = _run_subprocess_with_group_kill(
                    antechamber_cmd,
                    cwd=str(wd),
                    timeout=_antechamber_timeout,
                    stage_name="antechamber",
                    mol_id=mol_id,
                    env=_antechamber_env,
                )
            except RuntimeError as timeout_err:
                sqm_analysis = _analyze_sqm_output(wd)
                raise ArtifactGenerationError(
                    stage="antechamber",
                    failure_code=ArtifactFailureCode.SQM_TIMEOUT,
                    message=(
                        f"antechamber timed out for {mol_id} "
                        f"({sqm_analysis['iterations']} iters, "
                        f"hint={sqm_analysis['failure_hint']})"
                    ),
                    stderr_excerpt=str(timeout_err)[:2048],
                ) from timeout_err
            if r.returncode != 0 or not mol2_out.exists():
                sqm_analysis = _analyze_sqm_output(wd)
                stderr_blob = r.stderr or ""
                if sqm_analysis["failure_hint"] in ("stalled", "diverging"):
                    failure = ArtifactFailureCode.SQM_NONCONVERGED
                elif "timed out" in stderr_blob.lower():
                    failure = ArtifactFailureCode.SQM_TIMEOUT
                elif (
                    "not converged" in stderr_blob.lower()
                    or "convergence failure" in stderr_blob.lower()
                    or "scf failed" in stderr_blob.lower()
                ):
                    failure = ArtifactFailureCode.SQM_NONCONVERGED
                else:
                    failure = ArtifactFailureCode.ANTECHAMBER_FAILED
                raise ArtifactGenerationError(
                    stage="antechamber",
                    failure_code=failure,
                    message=(
                        f"antechamber failed for {mol_id} "
                        f"(sqm: {sqm_analysis['iterations']} iters, "
                        f"hint={sqm_analysis['failure_hint']}): {stderr_blob[:200]}"
                    ),
                    stderr_excerpt=stderr_blob[:2048],
                )

            # Step 2: parmchk2 (fill missing parameters)
            _emit("artifact_parmchk2", "본딩 파라미터 보완 (parmchk2)")
            frcmod = wd / "missing.frcmod"
            r2 = _run_subprocess_with_group_kill(
                [
                    "parmchk2",
                    "-i",
                    str(mol2_out),
                    "-f",
                    "mol2",
                    "-o",
                    str(frcmod),
                    "-s",
                    "gaff2",
                ],
                cwd=str(wd),
                timeout=120,
                stage_name="parmchk2",
                mol_id=mol_id,
            )
            if r2.returncode != 0:
                raise ArtifactGenerationError(
                    stage="parmchk2",
                    failure_code=ArtifactFailureCode.PARMCHK2_FAILED,
                    message=f"parmchk2 failed for {mol_id}: {(r2.stderr or '')[:300]}",
                    stderr_excerpt=r2.stderr or "",
                )
            if not frcmod.exists():
                raise ArtifactGenerationError(
                    stage="parmchk2",
                    failure_code=ArtifactFailureCode.PARMCHK2_FAILED,
                    message=f"parmchk2 did not produce frcmod for {mol_id}",
                    stderr_excerpt=r2.stderr or "",
                )

            # Step 3: tleap (build AMBER topology)
            _emit("artifact_tleap", "토폴로지 구축 (tleap)")
            prmtop = wd / "sys.prmtop"
            inpcrd = wd / "sys.inpcrd"
            (wd / "leap.in").write_text(
                "source leaprc.gaff2\n"
                "MOL = loadmol2 typed.mol2\n"
                "loadamberparams missing.frcmod\n"
                "saveamberparm MOL sys.prmtop sys.inpcrd\n"
                "quit\n"
            )
            r3 = _run_subprocess_with_group_kill(
                ["tleap", "-f", str(wd / "leap.in")],
                cwd=str(wd),
                timeout=120,
                stage_name="tleap",
                mol_id=mol_id,
            )
            if r3.returncode != 0:
                raise ArtifactGenerationError(
                    stage="tleap",
                    failure_code=ArtifactFailureCode.TLEAP_FAILED,
                    message=(
                        f"tleap non-zero exit ({r3.returncode}) for {mol_id}: {(r3.stderr or '')[:300]}"
                    ),
                    stderr_excerpt=r3.stderr or "",
                )
            if not prmtop.exists():
                raise ArtifactGenerationError(
                    stage="tleap",
                    failure_code=ArtifactFailureCode.TLEAP_FAILED,
                    message=f"tleap failed for {mol_id}: prmtop not produced",
                    stderr_excerpt=r3.stderr or "",
                )

            # Step 4: parmed (extract COMPLETE parameters from prmtop)
            _emit("artifact_parmed", "LJ/bonded 파라미터 추출 (parmed)")
            parm = parmed.load_file(str(prmtop), str(inpcrd))

            atoms = []
            for a in parm.atoms:
                atom_dict: dict[str, object] = {
                    "index": a.idx + 1,
                    "element": a.element_name.strip(),
                    "ff_type": a.type,
                    "charge": round(a.charge, 6),
                }
                # Extract GAFF2 LJ parameters (epsilon/sigma) from parmed
                eps = a.epsilon
                sig = a.sigma
                if not eps or not sig:
                    # Fallback to atom_type if per-atom values are missing
                    if hasattr(a, "atom_type") and a.atom_type is not None:
                        eps = a.atom_type.epsilon or 0.0
                        sig = a.atom_type.sigma or 0.0
                if eps and sig:
                    atom_dict["epsilon"] = round(eps, 6)
                    atom_dict["sigma"] = round(sig, 6)
                atoms.append(atom_dict)

            # Bond types
            bseen: set[str] = set()
            bond_types = []
            for b in parm.bonds:
                k = "-".join(sorted([b.atom1.type, b.atom2.type]))
                if k not in bseen:
                    bseen.add(k)
                    bond_types.append(
                        {
                            "key": f"{b.atom1.type}-{b.atom2.type}",
                            "k": round(b.type.k, 1),
                            "r0": round(b.type.req, 4),
                        }
                    )

            # Angle types
            aseen: set[str] = set()
            angle_types = []
            for a in parm.angles:
                k = f"{a.atom1.type}-{a.atom2.type}-{a.atom3.type}"
                rk = f"{a.atom3.type}-{a.atom2.type}-{a.atom1.type}"
                if k not in aseen and rk not in aseen:
                    aseen.add(k)
                    angle_types.append(
                        {
                            "key": k,
                            "k": round(a.type.k, 2),
                            "theta0": round(a.type.theteq, 2),
                        }
                    )

            # Dihedral types
            dih_terms: dict[str, list[tuple[float, float, float]]] = defaultdict(list)
            for d in parm.dihedrals:
                k = f"{d.atom1.type}-{d.atom2.type}-{d.atom3.type}-{d.atom4.type}"
                rk = f"{d.atom4.type}-{d.atom3.type}-{d.atom2.type}-{d.atom1.type}"
                canon = min(k, rk)
                d_sign = -1.0 if abs(d.type.phase - 180.0) < 1e-6 else 1.0
                term = (round(d.type.phi_k, 4), d_sign, float(int(d.type.per)))
                if term not in dih_terms[canon]:
                    dih_terms[canon].append(term)
            dihedral_types = []
            for k, terms in dih_terms.items():
                coeffs: list[float] = []
                for kk, d, n in terms:
                    coeffs.extend([kk, d, n])
                dihedral_types.append({"key": k, "style": "fourier", "coeffs": coeffs})

            # Improper types + instances
            iseen: set[str] = set()
            improper_types = []
            improper_instances: list[dict[str, int]] = []
            for imp in parm.impropers:
                k = f"{imp.atom1.type}-{imp.atom2.type}-{imp.atom3.type}-{imp.atom4.type}"
                if k not in iseen:
                    iseen.add(k)
                    d_sign = -1.0 if abs(imp.type.psi_eq - 180.0) < 1e-6 else 1.0
                    improper_types.append(
                        {
                            "key": k,
                            "style": "cvff",
                            "coeffs": [
                                round(imp.type.psi_k, 4),
                                d_sign,
                                float(int(imp.type.per)),
                            ],
                        }
                    )
                # Store every improper instance (atom indices, 1-based)
                improper_instances.append(
                    {
                        "atom1": imp.atom1.idx + 1,
                        "atom2": imp.atom2.idx + 1,
                        "atom3": imp.atom3.idx + 1,
                        "atom4": imp.atom4.idx + 1,
                    }
                )

        # fragment_fallback: discard the ``-c gas`` Gasteiger charges and apply
        # fragment-reference AM1-BCC charges (governance: AM1-BCC model only).
        if generation_profile == "fragment_fallback":
            atoms = _apply_fragment_reference_charges(atoms, formal_charge)

        atoms, normalized_total_charge = _normalize_artifact_atom_charges(atoms, formal_charge)
        charge_sum = round(normalized_total_charge, 6)

        artifact = {
            "schema_version": 2,
            "ff_family": "organic_gaff2",
            "charge_model": "am1_bcc",
            "mol_id": mol_id,
            "generator": (
                "fragment_fallback_gaff2"
                if generation_profile == "fragment_fallback"
                else "antechamber_am1bcc"
            ),
            "generator_version": "ambertools_parmed",
            "generation_profile": generation_profile,
            "provenance": f"Generated from {mol_path.name}",
            "canonical_smiles": smiles,
            "formal_charge": formal_charge,
            "topology_hash": "",
            "charge_sum": charge_sum,
            "atoms": atoms,
            "bond_types": bond_types,
            "angle_types": angle_types,
            "dihedral_types": dihedral_types,
            "improper_types": improper_types,
            "improper_instances": improper_instances,
        }

        # Save to canonical artifact path (source_id-based filename)
        _artifact_dir().mkdir(parents=True, exist_ok=True)
        out_path = target.artifact_path
        with open(out_path, "w") as f:
            json.dump(artifact, f, indent=2)

        logger.info(
            "Generated GAFF2 artifact: mol_id=%s source_id=%s "
            "(atoms=%d bonds=%d angles=%d dihedrals=%d impropers=%d Sq=%+.4f)",
            mol_id,
            target.source_id,
            len(atoms),
            len(bond_types),
            len(angle_types),
            len(dihedral_types),
            len(improper_types),
            charge_sum,
        )

        return artifact
    except ArtifactGenerationError:
        # Let the exception propagate so the caller can attempt sqm_robust
        raise


def _describe_organic_row(
    mol_id: str, ff: dict, *, catalog: str, atom_count: int, mol_path: str
) -> dict:
    """Build a pending-molecules row for an ``organic_curated_artifact`` entry.

    Uses :func:`resolve_artifact_target` so the artifact filename, source_id,
    and consumer list stay consistent with the rest of the service. The full
    ``ff_assignment`` is carried through so workers running in
    ``ProcessPoolExecutor`` subprocesses don't need to re-parse YAML.
    """
    target = resolve_artifact_target(mol_id, ff)
    art = target.artifact_path
    is_complete = _is_artifact_complete(art) if art.exists() else False
    validation = None
    if is_complete and art.exists():
        try:
            with open(art) as fh:
                art_data = json.load(fh)
            validation = validate_artifact(art_data)
        except Exception:
            validation = None
    return {
        "mol_id": mol_id,
        "source_id": target.source_id,
        "consumer_ids": list(target.consumer_ids),
        "atom_count": atom_count,
        "catalog": catalog,
        "mol_path": mol_path,
        "smiles": target.smiles,
        "formal_charge": target.formal_charge,
        "has_artifact": art.exists(),
        "is_complete": is_complete,
        "validation": validation,
        "artifact_type": "organic",
        "parameterization_mode": target.parameterization_mode,
        "is_passthrough": target.is_passthrough,
        "ff_assignment": dict(target.ff_assignment),
    }


def get_pending_molecules() -> list[dict]:
    """Get list of molecules with pending (missing) artifacts.

    Includes both organic (GAFF2) and ionic (JC/TIP3P) molecules, distinguished
    by the ``artifact_type`` field ("organic" or "ionic"). Organic rows surface
    ``source_id`` and ``consumer_ids`` additively so shared-source overrides are
    observable.
    """
    import yaml

    from features.molecules.ionic_artifact_service import (
        IONIC_ARTIFACT_DIR,
        validate_ionic_artifact,
    )

    pending: list[dict] = []

    # single_moles
    sm = _project_root() / "data/molecules/single_moles.yaml"
    if sm.exists():
        with open(sm) as f:
            data = yaml.safe_load(f)
        for e in data.get("molecules", []):
            ff = e.get("ff_assignment", {})
            route = ff.get("route", "")
            mol_id = e["base_id"]

            if route == "organic_curated_artifact":
                sf = e.get("structure_file", "")
                pending.append(
                    _describe_organic_row(
                        mol_id=mol_id,
                        ff=ff,
                        catalog="single_moles",
                        atom_count=e.get("atom_count", 0),
                        mol_path=(str(_project_root() / "data/molecules" / sf) if sf else ""),
                    )
                )
            elif route == "ionic_profile":
                ionic_art = IONIC_ARTIFACT_DIR / f"{mol_id}.json"
                is_complete = _is_ionic_artifact_complete(ionic_art)
                validation = None
                if is_complete and ionic_art.exists():
                    try:
                        with open(ionic_art) as fh:
                            art_data = json.load(fh)
                        validation = validate_ionic_artifact(art_data)
                    except Exception:
                        validation = None
                pending.append(
                    {
                        "mol_id": mol_id,
                        "source_id": mol_id,
                        "consumer_ids": [mol_id],
                        "atom_count": e.get("atom_count", 0),
                        "catalog": "single_moles",
                        "mol_path": "",
                        "smiles": "",
                        "formal_charge": 0,
                        "has_artifact": ionic_art.exists(),
                        "is_complete": is_complete,
                        "validation": validation,
                        "artifact_type": "ionic",
                        "parameterization_mode": (ff.get("parameterization", {}) or {}).get(
                            "mode", ""
                        ),
                        "is_passthrough": False,
                    }
                )

    # asphalt_binder
    ab = _project_root() / "data/molecules/asphalt_binder.yaml"
    if ab.exists():
        with open(ab) as f:
            data = yaml.safe_load(f)
        for e in data.get("molecules", []):
            ff = e.get("ff_assignment", {})
            if ff.get("route") != "organic_curated_artifact":
                continue
            for aging in e.get("available_aging", ["non_aging"]):
                pfx = {
                    "non_aging": "U",
                    "short_aging": "S",
                    "long_aging": "L",
                }.get(aging, "U")
                vid = f"{pfx}-{e['base_id']}"
                dmap = {
                    "non_aging": "non_aging_moles",
                    "short_aging": "short_aging_moles",
                    "long_aging": "long_aging_moles",
                }
                mp = (
                    _project_root()
                    / "data/molecules/asphalt_binder"
                    / dmap.get(aging, "non_aging_moles")
                    / f"{vid}.mol"
                )
                pending.append(
                    _describe_organic_row(
                        mol_id=vid,
                        ff=ff,
                        catalog="asphalt_binder",
                        atom_count=e.get("atom_count", 0),
                        mol_path=str(mp),
                    )
                )

    # additives
    ad = _project_root() / "data/molecules/additives.yaml"
    if ad.exists():
        with open(ad) as f:
            data = yaml.safe_load(f)
        for k, e in data.get("additives", {}).items():
            if not isinstance(e, dict):
                continue
            ff = e.get("ff_assignment", {})
            if ff.get("route") != "organic_curated_artifact":
                continue
            sf = e.get("structure_file", f"additives/{k}.mol")
            pending.append(
                _describe_organic_row(
                    mol_id=k,
                    ff=ff,
                    catalog="additives",
                    atom_count=e.get("atom_count", 0),
                    mol_path=str(_project_root() / "data/molecules" / sf),
                )
            )

    pending.sort(key=lambda x: x["atom_count"])
    return pending


def _is_artifact_complete(art_path: Path) -> bool:
    """Quick check if artifact has bonded data, charge neutrality, and LJ params."""
    try:
        with open(art_path) as f:
            data = json.load(f)
        has_core_terms = bool(data.get("bond_types")) and bool(data.get("atoms"))
        if not has_core_terms:
            return False
        mismatch, _expected, _actual = _artifact_charge_mismatch(data)
        if mismatch:
            return False
        # Check that ALL atoms have LJ params (GAFF2 epsilon/sigma)
        atoms = data.get("atoms", [])
        has_lj = all(a.get("epsilon") is not None and a.get("sigma") is not None for a in atoms)
        if not has_lj:
            return False
        return True
    except Exception:
        return False


def _is_ionic_artifact_complete(art_path: Path) -> bool:
    """Quick check if ionic artifact has atom data with LJ params.

    Ionic artifacts have no bonded terms — completeness requires atoms with
    charge and LJ sigma/epsilon.
    """
    try:
        with open(art_path) as f:
            data = json.load(f)
        atoms = data.get("atoms", [])
        if not atoms:
            return False
        return all(a.get("sigma") is not None and a.get("epsilon") is not None for a in atoms)
    except Exception:
        return False


def validate_artifact(artifact: dict) -> dict:
    """Validate artifact completeness — no missing parameters.

    Args:
        artifact: Artifact JSON dict (schema v2).

    Returns:
        Dict with keys: valid (bool), checks (per-field status), warnings (list[str]).
    """
    checks: dict[str, dict] = {}
    warnings: list[str] = []

    atoms = artifact.get("atoms", [])
    empty_ff = sum(1 for a in atoms if not a.get("ff_type"))
    empty_charge = sum(1 for a in atoms if a.get("charge") is None)
    checks["atoms"] = {
        "count": len(atoms),
        "status": "ok" if atoms and not empty_ff else "missing",
    }
    if empty_ff:
        warnings.append(f"{empty_ff} atoms without ff_type")
    if empty_charge:
        warnings.append(f"{empty_charge} atoms without charge")

    bonds = artifact.get("bond_types", [])
    checks["bond_types"] = {
        "count": len(bonds),
        "status": "ok" if bonds or len(atoms) <= 1 else "missing",
    }

    angles = artifact.get("angle_types", [])
    checks["angle_types"] = {
        "count": len(angles),
        "status": "ok" if angles or len(atoms) <= 2 else "missing",
    }

    dihedrals = artifact.get("dihedral_types", [])
    dih_status = "ok" if dihedrals or len(atoms) <= 3 else "warning"
    checks["dihedral_types"] = {"count": len(dihedrals), "status": dih_status}
    if not dihedrals and len(atoms) > 3:
        warnings.append("No dihedral types (may be acceptable for rigid molecules)")

    impropers = artifact.get("improper_types", [])
    checks["improper_types"] = {"count": len(impropers), "status": "ok"}

    mismatch, expected_charge, actual_charge = _artifact_charge_mismatch(artifact)
    checks["charge_neutrality"] = {
        "value": round(actual_charge, 6),
        "expected": expected_charge,
        "status": "warning" if mismatch else "ok",
    }
    if mismatch:
        warnings.append(
            f"Charge sum {actual_charge:+.6f} deviates from formal charge {expected_charge:+.6f}"
        )

    # LJ params completeness
    missing_lj = sum(1 for a in atoms if a.get("epsilon") is None or a.get("sigma") is None)
    checks["lj_params"] = {
        "count": len(atoms) - missing_lj,
        "total": len(atoms),
        "status": "ok" if missing_lj == 0 else "missing",
    }
    if missing_lj:
        warnings.append(f"{missing_lj} atoms without LJ params (epsilon/sigma)")

    valid = all(c["status"] != "missing" for c in checks.values()) and not mismatch
    return {"valid": valid, "checks": checks, "warnings": warnings}


# ---------------------------------------------------------------------------
# Parallel batch generation
# ---------------------------------------------------------------------------


def _admin_status_store() -> AdminStatusStore:
    """Lazy accessor so test code can monkeypatch ``ARTIFACT_DIR``."""
    return AdminStatusStore(_artifact_dir())


def _generate_one_worker(mol_info: dict) -> dict:
    """Worker function for parallel batch -- runs in subprocess.

    Must be module-level (not nested) so ProcessPoolExecutor can pickle it.
    Each subprocess gets its own tempdir via generate_gaff2_artifact, and
    every outcome (success or :class:`ArtifactGenerationError`) is recorded
    to the family-specific admin sidecar so the operator surface survives a
    process restart.

    v00.99.93: the phase_map parameter introduced in v00.99.90 was removed
    after a batch-lifecycle hang was traced to the associated Manager.dict
    IPC path. Real-time baseline / robust in-flight counters are deferred
    until they can be reintroduced via a spawn+initializer pattern.

    Args:
        mol_info: Dict with mol_id, source_id (optional), mol_path, smiles,
            formal_charge, consumer_ids (optional), and ff_assignment
            (optional) keys.

    Returns:
        Result dict with mol_id, source_id, status, and either artifact
        summary or error payload (``failure_code``, ``stage``).
    """
    from pathlib import Path

    mol_id = mol_info["mol_id"]
    mol_path = Path(mol_info["mol_path"])
    ff_assignment = mol_info.get("ff_assignment")
    source_id = mol_info.get("source_id") or mol_id
    consumer_ids = list(mol_info.get("consumer_ids") or [mol_id])
    profile = str(mol_info.get("generation_profile") or "baseline")
    result_base: dict[str, object] = {
        "mol_id": mol_id,
        "source_id": source_id,
        "generation_profile": profile,
    }
    store = _admin_status_store()

    # v00.99.42 reinforcement: defense-in-depth — if the caller queued a
    # non-baseline profile, re-validate the admin policy here so that a
    # future caller invoking ``run_parallel_batch`` directly cannot
    # bypass the CLI/API gate. baseline keeps the public/runtime path
    # unchanged (no re-validation cost).
    if profile != "baseline":
        try:
            target = resolve_artifact_target(
                mol_id, ff_assignment if isinstance(ff_assignment, dict) else None
            )
        except Exception:
            target = None  # fall through; outer handler still records
        if target is not None:
            try:
                validate_admin_generation_request(target, profile, store)
            except AdminGenerationError as exc:
                err = ArtifactGenerationError(
                    stage="preflight",
                    failure_code=ArtifactFailureCode.MANUAL_REVIEW_REQUIRED,
                    message=f"admin_policy_blocked: {exc.message}",
                )
                try:
                    store.record_failure(
                        source_id,
                        err,
                        consumer_ids=consumer_ids,
                        generation_profile=profile,
                        recommended_action=recommended_action_for_failure(err.failure_code.value),
                    )
                except Exception:
                    logger.exception("admin sidecar record_failure failed for %s", source_id)
                return {
                    **result_base,
                    "status": "error",
                    "error": err.message,
                    "failure_code": err.failure_code.value,
                    "stage": err.stage,
                }

    if not mol_path.exists():
        err = ArtifactGenerationError(
            stage="preflight",
            failure_code=ArtifactFailureCode.INPUT_INVALID,
            message="MOL file missing",
        )
        try:
            store.record_failure(
                source_id,
                err,
                consumer_ids=consumer_ids,
                generation_profile=profile,
                recommended_action=recommended_action_for_failure(err.failure_code.value),
            )
        except Exception:
            logger.exception("admin sidecar record_failure failed for %s", source_id)
        return {
            **result_base,
            "status": "error",
            "error": err.message,
            "failure_code": err.failure_code.value,
            "stage": err.stage,
        }

    # Lock keeps the artifact JSON write and the sidecar write atomic from
    # any reader's perspective (admin status, runtime fast-path). Both
    # success AND failure record_* calls happen inside the same critical
    # section so a reader never observes one without the other.
    #
    # v00.99.55: baseline→sqm_robust auto-retry in the admin batch path,
    # matching the runtime (ensure_organic_artifact) behavior. When a
    # baseline attempt fails with `exc.retryable=True`, we retry once
    # with sqm_robust inside the same source-lock. The retry outcome is
    # reported back via `effective_profile` / `retried` / `retry_reason`
    # so the batch runner can surface it on `_batch_progress`.
    try:
        with source_generation_lock(source_id):
            effective_profile = profile
            retried = False
            retry_reason: str | None = None
            primary_exc: ArtifactGenerationError | None = None
            try:
                artifact = generate_gaff2_artifact(
                    mol_path=mol_path,
                    mol_id=mol_id,
                    smiles=mol_info.get("smiles", ""),
                    formal_charge=mol_info.get("formal_charge", 0),
                    ff_assignment=ff_assignment,
                    generation_profile=profile,
                )
            except ArtifactGenerationError as e:
                primary_exc = e
                # sqm_robust retry only when the queued profile was
                # baseline AND the failure class is retryable. Non-baseline
                # profiles already tried the heavier recipe — escalating
                # again would loop.
                if profile == "baseline" and e.retryable:
                    try:
                        store.record_failure(
                            source_id,
                            e,
                            consumer_ids=consumer_ids,
                            generation_profile="baseline",
                            recommended_action=recommended_action_for_failure(e.failure_code.value),
                        )
                    except Exception:
                        logger.exception(
                            "admin sidecar record_failure (pre-retry) failed for %s",
                            source_id,
                        )
                    logger.warning(
                        "Admin batch: baseline failed for %s [%s/%s] — auto-retrying with sqm_robust",
                        source_id,
                        e.stage,
                        e.failure_code.value,
                    )
                    try:
                        artifact = generate_gaff2_artifact(
                            mol_path=mol_path,
                            mol_id=mol_id,
                            smiles=mol_info.get("smiles", ""),
                            formal_charge=mol_info.get("formal_charge", 0),
                            ff_assignment=ff_assignment,
                            generation_profile="sqm_robust",
                        )
                        effective_profile = "sqm_robust"
                        retried = True
                        retry_reason = f"baseline [{e.failure_code.value}] → sqm_robust"
                    except ArtifactGenerationError as retry_exc:
                        # v01.05.01: fragment fallback removed — sqm_robust failure is final
                        try:
                            store.record_failure(
                                source_id,
                                retry_exc,
                                consumer_ids=consumer_ids,
                                generation_profile="sqm_robust",
                                recommended_action=recommended_action_for_failure(
                                    retry_exc.failure_code.value
                                ),
                            )
                        except Exception:
                            logger.exception(
                                "admin sidecar record_failure (post-retry) failed for %s",
                                source_id,
                            )
                        return {
                            **result_base,
                            "status": "error",
                            "error": (
                                f"baseline [{e.failure_code.value}] → "
                                f"sqm_robust [{retry_exc.failure_code.value}]: "
                                f"{retry_exc.message[:200]}"
                            ),
                            "failure_code": retry_exc.failure_code.value,
                            "stage": retry_exc.stage,
                            "retried": True,
                            "effective_profile": "sqm_robust",
                        }
                else:
                    # v01.05.01: fragment fallback removed — fail closed on
                    # non-retryable baseline failure
                    try:
                        store.record_failure(
                            source_id,
                            e,
                            consumer_ids=consumer_ids,
                            generation_profile=profile,
                            recommended_action=recommended_action_for_failure(e.failure_code.value),
                        )
                    except Exception:
                        logger.exception("admin sidecar record_failure failed for %s", source_id)
                        return {
                            **result_base,
                            "status": "error",
                            "error": e.message[:300],
                            "failure_code": e.failure_code.value,
                            "stage": e.stage,
                            "retried": False,
                            "effective_profile": profile,
                        }

            v = validate_artifact(artifact)
            try:
                store.record_success(
                    source_id,
                    consumer_ids=consumer_ids,
                    generation_profile=effective_profile,
                    generator=artifact.get("generator", "antechamber_am1bcc"),
                )
            except Exception:
                logger.exception("admin sidecar record_success failed for %s", source_id)
        return {
            **result_base,
            "status": "completed",
            "atoms": len(artifact["atoms"]),
            "bond_types": len(artifact["bond_types"]),
            "angle_types": len(artifact["angle_types"]),
            "dihedral_types": len(artifact["dihedral_types"]),
            "improper_types": len(artifact["improper_types"]),
            "charge_sum": artifact.get("charge_sum", 0),
            "valid": v["valid"],
            "retried": retried,
            "retry_reason": retry_reason,
            "effective_profile": effective_profile,
            "primary_failure_code": (primary_exc.failure_code.value if primary_exc else None),
            # v01.02.07: generator for RDKit-GAFF2 tracking
            "generator": artifact.get("generator", "antechamber_am1bcc"),
        }
    except Exception as e:  # last-resort: never let worker crash silently
        err = ArtifactGenerationError(
            stage="unknown",
            failure_code=ArtifactFailureCode.ANTECHAMBER_FAILED,
            message=str(e)[:300],
        )
        try:
            store.record_failure(
                source_id,
                err,
                consumer_ids=consumer_ids,
                generation_profile=profile,
                recommended_action=recommended_action_for_failure(err.failure_code.value),
            )
        except Exception:
            logger.exception("admin sidecar record_failure failed for %s", source_id)
        return {**result_base, "status": "error", "error": str(e)[:300]}


def dedupe_by_source_id(pending: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return (unique, conflicts).

    Groups pending rows by ``source_id`` and keeps the canonical entry (the
    first row whose ``mol_id`` equals ``source_id``; otherwise the first row).
    Rows sharing a ``source_id`` with a different ``mol_path`` / structure
    file are returned as conflicts so the caller can flag them as
    ``SHARED_SOURCE_ID_CONFLICT`` instead of silently overwriting.

    Args:
        pending: Output of :func:`get_pending_molecules` (organic entries).

    Returns:
        Tuple ``(unique, conflicts)`` where ``unique`` contains one row per
        source_id and ``conflicts`` lists the duplicate rows that were
        skipped. ``conflicts`` rows gain a ``conflict_with`` key pointing to
        the canonical mol_id.
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in pending:
        sid = row.get("source_id") or row.get("mol_id", "")
        groups[sid].append(row)

    unique: list[dict] = []
    conflicts: list[dict] = []
    for sid, rows in groups.items():
        if len(rows) == 1:
            unique.append(rows[0])
            continue
        canonical = next(
            (r for r in rows if r.get("mol_id") == sid),
            rows[0],
        )
        unique.append(canonical)
        for other in rows:
            if other is canonical:
                continue
            if other.get("mol_path") != canonical.get("mol_path"):
                conflicts.append({**other, "conflict_with": canonical["mol_id"]})
    return unique, conflicts


def _low_priority_initializer() -> None:
    """Set lower CPU scheduling priority for batch workers.

    Reduces OS scheduler priority so Preview API threads get preference.
    Fails silently on Windows or when lacking CAP_SYS_NICE.

    v00.99.67: Added for Preview API priority guarantee.
    v01.02.16: Added default logging handler setup for spawn context workers.
    """
    try:
        import os

        os.nice(10)
    except (OSError, PermissionError, AttributeError):
        # Windows: AttributeError (no os.nice)
        # Linux without CAP_SYS_NICE: PermissionError/OSError
        pass

    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        root.addHandler(handler)


def run_parallel_batch(
    pending: list[dict],
    max_workers: int | None = None,
    timeout_per_mol: int = 10800,  # 3시간 - antechamber sqm_robust(2시간)보다 충분히 길게
    *,
    batch_kind: str = "public",
    generation_profile: str = "baseline",
    slot_already_acquired: bool = False,
) -> dict:
    """Run batch artifact generation in parallel across CPU cores.

    Uses ProcessPoolExecutor because sqm (AM1-BCC engine) is single-threaded
    and CPU-bound, so multiple molecules can run on separate cores simultaneously.

    v00.99.43: enforces the global batch slot guard. The router that
    schedules the BackgroundTask normally calls :func:`acquire_batch_slot`
    first (so the 409 response can be returned synchronously) and passes
    ``slot_already_acquired=True``. Direct callers (CLI, tests) leave the
    flag default and the slot is acquired here.

    Args:
        pending: List of molecule dicts from get_pending_molecules().
        max_workers: Max parallel processes. None = auto (cpu_count - 4, min 2, cap 24).
        timeout_per_mol: Timeout per molecule in seconds (default 15min).
        batch_kind: ``"public"`` or ``"admin"``; recorded on the global
            progress payload.
        generation_profile: ``"baseline"`` or ``"sqm_robust"`` recorded
            on the progress payload.
        slot_already_acquired: When True, skip the internal
            :func:`acquire_batch_slot` call (the HTTP layer already did
            it). The slot is still released on completion.

    Returns:
        Summary dict with success/failed counts and per-molecule details.

    Raises:
        RuntimeError: When ``slot_already_acquired=False`` and another
            batch is already running.
    """
    import os
    from concurrent.futures import ProcessPoolExecutor, as_completed

    # v00.99.93: batch lifecycle entry log — placed before any heavy
    # lifting so a future hang can be triaged against log presence.
    logger.info(
        "run_parallel_batch entered: batch_kind=%s profile=%s pending=%d",
        batch_kind,
        generation_profile,
        len(pending),
    )

    # v00.99.64: dynamic CPU allocation with per-chunk reassessment
    # v00.99.67: reduced fraction to reserve CPU headroom for Preview API
    cpu = os.cpu_count() or 4
    MAX_CPU_FRACTION = 0.70  # 0.80 → 0.70 for Preview API responsiveness
    MIN_BATCH_WORKERS = 2  # Guarantee minimum parallelism on low-core systems
    ceiling = max(MIN_BATCH_WORKERS, int(cpu * MAX_CPU_FRACTION))

    def _get_available_workers() -> int:
        """Get currently available workers based on system load."""
        try:
            load_avg = os.getloadavg()[0]
            busy_cores = int(load_avg)
            return max(1, ceiling - busy_cores)
        except (OSError, AttributeError):
            return max(2, ceiling)

    if max_workers is None:
        max_workers = _get_available_workers()
        logger.info(
            "Batch generation: cpu=%d, ceiling=%d (%.0f%%), initial_workers=%d, "
            "nice=+10 (v00.99.67 Preview API priority)",
            cpu,
            ceiling,
            MAX_CPU_FRACTION * 100,
            max_workers,
        )

    if not slot_already_acquired:
        if not acquire_batch_slot(batch_kind, generation_profile):
            raise RuntimeError(
                "another batch is already running; refusing to start a "
                "concurrent run_parallel_batch invocation"
            )

    # Deduplicate by source_id so shared overrides (e.g. CNT + Graphene
    # → carbon_sp2_passthrough_v1) are not generated twice. Conflicting
    # structure files are surfaced in the ``details`` as explicit failures.
    try:
        unique, conflicts = dedupe_by_source_id(pending)
    except Exception:
        # Defensive: if dedupe blows up, still release the slot so a
        # concurrent admin/public request can recover. Log the error
        # before releasing so the operator has a trail.
        logger.exception(
            "dedupe_by_source_id raised inside run_parallel_batch; "
            "releasing batch slot before propagating"
        )
        release_batch_slot()
        raise
    logger.info(
        "Parallel batch: %d rows -> %d unique source_ids (%d conflicts), %d workers",
        len(pending),
        len(unique),
        len(conflicts),
        max_workers,
    )

    # Slot was acquired before entry; here we just stamp counters.
    # batch_kind/generation_profile/started_at were set by acquire_batch_slot.
    # v00.99.57: seed bucketed counters so the first polling tick reports a
    # consistent snapshot even when conflicts pre-filled `failed`.
    _update_batch_progress(
        total=len(unique),
        completed=0,
        failed=len(conflicts),
        skipped=0,
        retried=0,
        retried_succeeded=0,
        in_progress=0,
        current_mol_id="starting...",
        last_completed_mol_id="",
        last_retry_reason="",
        percent=0.0,
        max_workers=max_workers,
    )

    results: dict = {
        "total": len(unique),
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "retried": 0,
        "retried_succeeded": 0,
        "cancelled": False,
        "details": [],
        "max_workers": max_workers,
    }

    conflict_store = _admin_status_store()
    for row in conflicts:
        sid = row.get("source_id") or row["mol_id"]
        err = ArtifactGenerationError(
            stage="preflight",
            failure_code=ArtifactFailureCode.SHARED_SOURCE_ID_CONFLICT,
            message=(
                f"shared source_id {sid!r}: {row['mol_id']} and "
                f"{row.get('conflict_with')} disagree on structure_file"
            ),
        )
        try:
            conflict_store.record_failure(
                sid,
                err,
                consumer_ids=row.get("consumer_ids") or [row["mol_id"]],
                recommended_action=recommended_action_for_failure(err.failure_code.value),
            )
        except Exception:
            logger.exception("admin sidecar record_failure failed for conflict %s", sid)
        results["details"].append(
            {
                "mol_id": row["mol_id"],
                "source_id": row.get("source_id"),
                "status": "error",
                "error": "shared_source_id_conflict",
                "failure_code": ArtifactFailureCode.SHARED_SOURCE_ID_CONFLICT.value,
                "conflict_with": row.get("conflict_with"),
            }
        )
        results["failed"] += 1

    # v00.99.64: Dynamic CPU allocation with continuous work submission.
    # Instead of fixed chunks that wait for all tasks to complete, we maintain
    # a sliding window of in-flight tasks, refilling as workers become free.
    # This eliminates CPU idle time between chunks.

    try:
        # v00.99.93: Manager.dict IPC removed. The v00.99.90 phase_map
        # was traced to a batch-lifecycle hang where the ``with Manager()``
        # + ``ProcessPoolExecutor`` teardown never completed, leaving
        # ``_batch_progress["running"]`` latched indefinitely. Reverting
        # to the plain executor pattern eliminates the IPC path entirely.
        # v01.02.16: Use an explicit multiprocessing context so uvicorn
        # pre-fork workers do not fork again by default. Operators can set
        # ASPHALT_ARTIFACT_POOL_START_METHOD=fork to roll back to legacy
        # behavior without a code change.
        start_method = os.getenv("ASPHALT_ARTIFACT_POOL_START_METHOD", "spawn")
        ctx = mp.get_context(start_method)
        logger.info(
            "creating ProcessPoolExecutor: max_workers=%d, start_method=%s",
            max_workers,
            start_method,
        )
        with ProcessPoolExecutor(
            max_workers=max_workers,
            initializer=_low_priority_initializer,
            mp_context=ctx,
        ) as executor:
            pending_mols = list(unique)  # Work queue
            future_to_mol: dict = {}  # Active futures
            next_idx = 0  # Next molecule to submit

            def _submit_next_batch() -> int:
                """Submit molecules up to available worker capacity. Returns count submitted."""
                nonlocal next_idx
                # v00.99.64: reassess available workers before each submission burst
                current_available = _get_available_workers()
                current_in_flight = len(future_to_mol)
                slots_free = max(0, current_available - current_in_flight)
                remaining = len(pending_mols) - next_idx

                to_submit = min(slots_free, remaining)
                if to_submit > 0 and current_available != max_workers:
                    logger.debug(
                        "Dynamic CPU: available=%d, in_flight=%d, submitting=%d",
                        current_available,
                        current_in_flight,
                        to_submit,
                    )

                for _ in range(to_submit):
                    if _is_batch_cancelled():
                        break
                    mol = pending_mols[next_idx]
                    future = executor.submit(_generate_one_worker, mol)
                    future_to_mol[future] = mol
                    next_idx += 1

                return to_submit

            # Initial submission burst
            _submit_next_batch()
            _update_batch_progress(in_progress=len(future_to_mol))

            # v00.99.73: cancel-before-start — if the cancel flag was set
            # before run_parallel_batch was called, _submit_next_batch
            # submitted nothing and the while loop never runs. Record the
            # remaining work as skipped/cancelled so the caller receives a
            # coherent result instead of a silent "zero-everything" payload.
            if not future_to_mol and next_idx < len(pending_mols) and _is_batch_cancelled():
                results["skipped"] = len(pending_mols) - next_idx
                results["cancelled"] = True
                _update_batch_progress(
                    skipped=results["skipped"],
                    in_progress=0,
                )

            while future_to_mol:
                # Check cancel flag
                if _is_batch_cancelled() and next_idx < len(pending_mols):
                    skipped = len(pending_mols) - next_idx
                    results["skipped"] += skipped
                    results["cancelled"] = True
                    _update_batch_progress(skipped=results["skipped"])
                    logger.info(f"Batch cancelled — skipping {skipped} remaining molecules")
                    # Let in-flight tasks complete but don't submit new ones

                # Wait for at least one task to complete.
                # v00.99.73: catch TimeoutError from as_completed(). Previously
                # the exception propagated out, aborting the batch mid-flight
                # with no coherent result state. Subprocess layer already owns
                # per-command timeouts (antechamber=600s / sqm cascade), so a
                # batch-level as_completed timeout means a worker is stuck
                # longer than expected — we mark in-flight mols as timeout
                # and break cleanly.
                done_futures = []
                try:
                    batch_iter = as_completed(future_to_mol, timeout=timeout_per_mol)
                    for future in batch_iter:
                        mol = future_to_mol[future]
                        try:
                            result = future.result(timeout=1)
                        except Exception as e:
                            result = {
                                "mol_id": mol["mol_id"],
                                "status": "error",
                                "error": f"Timeout/crash: {e!s:.200s}",
                            }

                        results["details"].append(result)
                        done_futures.append(future)

                        # v00.99.55: count auto-retries
                        if result.get("retried"):
                            results["retried"] = results.get("retried", 0) + 1
                            if result["status"] == "completed":
                                results["retried_succeeded"] = (
                                    results.get("retried_succeeded", 0) + 1
                                )

                        _retry_reason = result.get("retry_reason") or ""

                        if result["status"] == "completed":
                            results["success"] += 1
                        else:
                            results["failed"] += 1

                        logger.info(
                            f"[{results['success'] + results['failed']}/{len(unique)}] "
                            f"{result['mol_id']}: {result['status']}"
                        )

                        # Remove completed future and submit new work immediately
                        del future_to_mol[future]

                        # v00.99.64: immediately fill freed slot if not cancelled
                        if not results["cancelled"]:
                            _submit_next_batch()

                        # Update progress after each completion
                        common_kwargs = {
                            "retried": results.get("retried", 0),
                            "retried_succeeded": results.get("retried_succeeded", 0),
                            "in_progress": len(future_to_mol),
                            "current_mol_id": result["mol_id"],
                            "last_completed_mol_id": result["mol_id"],
                            "last_retry_reason": _retry_reason,
                        }
                        _update_batch_progress(
                            completed=results["success"],
                            failed=results["failed"],
                            **common_kwargs,
                        )

                        # Process one at a time to enable immediate refill
                        break
                except TimeoutError:
                    stuck = list(future_to_mol.items())
                    stuck_ids = [mol["mol_id"] for _, mol in stuck]
                    logger.warning(
                        "Batch timeout: no worker completed within %ds. "
                        "In-flight molecules marked as timeout: %s",
                        timeout_per_mol,
                        stuck_ids,
                    )
                    for future, mol in stuck:
                        future.cancel()  # no-op for already-running futures
                        results["details"].append(
                            {
                                "mol_id": mol["mol_id"],
                                "status": "error",
                                "error": (
                                    f"Batch timeout after {timeout_per_mol}s "
                                    "— subprocess still running; per-stage "
                                    "timeouts will clean it up."
                                ),
                            }
                        )
                        results["failed"] += 1
                        del future_to_mol[future]
                    # Refuse to submit further molecules — something is
                    # systemically slow; let the operator restart the batch.
                    results["cancelled"] = True
                    _update_batch_progress(
                        failed=results["failed"],
                        skipped=results["skipped"],
                        in_progress=0,
                    )
                    break
    finally:
        # Always release the singleton slot so the next caller (admin or
        # public) can acquire it, even if the worker pool itself raised.
        release_batch_slot()

    status = "cancelled" if results["cancelled"] else "complete"
    logger.info(
        f"Batch {status}: {results['success']} success, "
        f"{results['failed']} failed, {results['skipped']} skipped"
    )
    return results
