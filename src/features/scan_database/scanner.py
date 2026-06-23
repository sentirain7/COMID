"""Filesystem scanner for experiment directories.

Discovers experiment folders under ``database/``, parses ``in.lammps`` headers,
and determines protocol compatibility with the current version.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from common.hashing import compute_file_hash
from common.logging import get_logger
from contracts.policies.forcefield import get_ff_version

logger = get_logger("features.scan_database.scanner")

# ---------------------------------------------------------------------------
# Header regex patterns for in.lammps
# ---------------------------------------------------------------------------
_RE_TIER = re.compile(r"^#\s*Tier:\s*(.+)", re.IGNORECASE)
_RE_FF = re.compile(r"^#\s*Force\s+Field:\s*(.+)", re.IGNORECASE)
_RE_STUDY = re.compile(r"^#\s*Study\s+Type:\s*(.+)", re.IGNORECASE)
_RE_TEMP = re.compile(r"^#\s*Temperature:\s*([\d.]+)", re.IGNORECASE)
_RE_PRESS = re.compile(r"^#\s*Pressure:\s*([\d.]+)", re.IGNORECASE)
_RE_HASH = re.compile(r"^#\s*Protocol\s+hash:\s*(\S+)", re.IGNORECASE)
_RE_STEP = re.compile(r"^#\s*Step\s+(\d+)\s*:\s*(.+?)\s*$", re.IGNORECASE)

# SM exp_id patterns for additive_mol_id extraction
# Legacy first to avoid greedy capture of "X1_NA_" prefix by current regex
_RE_SM_LEGACY = re.compile(r"^SM_X1_NA_(.+)_(\d+)K_([0-9a-fA-F]{6})$")
_RE_SM_CURRENT = re.compile(r"^SM_(.+)_(\d+)K_([0-9a-fA-F]{6})$")
# No-temp legacy: SM_{mol_id}_{hash6} (temperature from in.lammps header)
_RE_SM_NO_TEMP = re.compile(r"^SM_(.+)_([0-9a-fA-F]{6})$")

# Completion marker in log.lammps
_WALL_TIME_PATTERN = re.compile(r"Total wall time", re.IGNORECASE)

# Compatibility levels (ordered by importability priority)
COMPAT_PRIORITY: dict[str, int] = {
    "compatible": 0,
    "compatible_incomplete": 1,
    "protocol_mismatch": 2,
    "hash_unverifiable": 3,
    "no_metadata": 4,
    "empty": 5,
}


@dataclass
class AttemptInfo:
    """Metadata extracted from a single attempt directory."""

    attempt_dir: Path
    seed: int | None = None

    # Extracted from in.lammps header
    has_in_lammps: bool = False
    has_log_lammps: bool = False
    has_data_lammps: bool = False
    tier: str | None = None
    ff_type: str | None = None
    study_type: str | None = None
    temperature_k: float | None = None
    pressure_atm: float | None = None
    protocol_hash_found: str | None = None

    # Computed
    protocol_hash_current: str | None = None
    compatibility: str = "empty"
    compatibility_reason: str = ""
    lammps_completed: bool = False
    total_atoms: int | None = None
    box_dims: list[float] | None = None
    final_step: int = 0
    mtime: float = 0.0
    dump_file_path: str | None = None
    additive_mol_id: str | None = None


@dataclass
class ScannedExperiment:
    """Result of scanning a single experiment directory."""

    exp_id: str
    directory: str
    has_in_lammps: bool = False
    has_log_lammps: bool = False
    has_data_lammps: bool = False
    tier: str | None = None
    ff_type: str | None = None
    temperature_k: float | None = None
    total_atoms: int | None = None
    protocol_hash_found: str | None = None
    protocol_hash_current: str | None = None
    compatibility: str = "empty"
    compatibility_reason: str = ""
    lammps_completed: bool = False
    already_in_db: bool = False
    seed: int | None = None
    box_dims: list[float] | None = None
    # Internal: paths for import
    data_file_path: str | None = None
    input_file_path: str | None = None
    log_file_path: str | None = None
    dump_file_path: str | None = None
    topology_hash: str | None = None
    study_type: str | None = None
    pressure_atm: float | None = None
    attempt_dir: str | None = None
    additive_mol_id: str | None = None


def _extract_sm_mol_id(exp_id: str) -> str | None:
    """Extract mol_id from SM experiment ID.

    Supports three formats (matched in this order):

    1. Legacy: ``SM_X1_NA_{mol_id}_{temp}K_{hash6}``
    2. Current: ``SM_{mol_id}_{temp}K_{hash6}``
    3. No-temp legacy: ``SM_{mol_id}_{hash6}``

    Legacy (1) is matched first to prevent greedy capture of ``X1_NA_``.
    No-temp (3) is last because ``_([0-9a-fA-F]{6})$`` is very broad —
    the temp-aware patterns must be tried first.
    """
    m = _RE_SM_LEGACY.match(exp_id)
    if m:
        return m.group(1)
    m = _RE_SM_CURRENT.match(exp_id)
    if m:
        return m.group(1)
    m = _RE_SM_NO_TEMP.match(exp_id)
    if m:
        return m.group(1)
    return None


def _get_database_dir() -> Path:
    """Resolve the ``database/`` directory relative to project root."""
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    db_dir = project_root / "database"
    if not db_dir.is_dir():
        raise FileNotFoundError(f"database/ directory not found at {db_dir}")
    return db_dir


def _parse_in_lammps_header(in_lammps_path: Path) -> dict:
    """Parse metadata from in.lammps header comments.

    Args:
        in_lammps_path: Path to in.lammps file.

    Returns:
        Dict with keys: tier, ff_type, study_type, temperature_k,
        pressure_atm, protocol_hash.
    """
    result: dict = {}
    try:
        with open(in_lammps_path) as f:
            for line in f:
                line = line.strip()
                if not line.startswith("#"):
                    # Stop at first non-comment, non-empty line
                    if line:
                        break
                    continue

                if m := _RE_TIER.match(line):
                    result["tier"] = m.group(1).strip()
                elif m := _RE_FF.match(line):
                    result["ff_type"] = m.group(1).strip()
                elif m := _RE_STUDY.match(line):
                    result["study_type"] = m.group(1).strip()
                elif m := _RE_TEMP.match(line):
                    result["temperature_k"] = float(m.group(1))
                elif m := _RE_PRESS.match(line):
                    result["pressure_atm"] = float(m.group(1))
                elif m := _RE_HASH.match(line):
                    result["protocol_hash"] = m.group(1).strip()
    except Exception as exc:
        logger.warning(f"Failed to parse in.lammps header at {in_lammps_path}: {exc}")

    return result


def _parse_in_lammps_step_names(in_lammps_path: Path) -> list[str]:
    """Parse protocol step names from ``# Step N: <name>`` comments."""
    step_names: list[str] = []
    expected_index = 1

    try:
        with open(in_lammps_path) as f:
            for raw_line in f:
                line = raw_line.strip()
                if m := _RE_STEP.match(line):
                    step_index = int(m.group(1))
                    if step_index != expected_index:
                        logger.warning(
                            "Non-sequential step markers in %s: expected Step %s, found Step %s",
                            in_lammps_path,
                            expected_index,
                            step_index,
                        )
                        return []
                    step_names.append(m.group(2).strip())
                    expected_index += 1
    except Exception as exc:
        logger.warning(f"Failed to parse in.lammps steps at {in_lammps_path}: {exc}")

    return step_names


def _parse_log_status(log_path: Path) -> tuple[bool, int]:
    """Parse log.lammps for completion status and final step.

    Uses LogParser when available, falls back to tail-based detection.

    Args:
        log_path: Path to log.lammps file.

    Returns:
        Tuple of (completed, final_step).
    """
    if not log_path.exists():
        return False, 0

    try:
        from parsers.log_parser import LogParser

        result = LogParser().parse(log_path)
        return result.completed, result.final_step
    except Exception:
        # Fallback: simple tail check
        try:
            size = log_path.stat().st_size
            with open(log_path, "rb") as f:
                if size > 2048:
                    f.seek(size - 2048)
                tail = f.read().decode("utf-8", errors="replace")
            return bool(_WALL_TIME_PATTERN.search(tail)), 0
        except Exception:
            return False, 0


def _parse_atoms_from_data_file(data_path: Path) -> int | None:
    """Extract atom count from data.lammps header."""
    try:
        with open(data_path) as f:
            for line in f:
                line = line.strip()
                if "atoms" in line.lower():
                    parts = line.split()
                    if parts and parts[0].isdigit():
                        return int(parts[0])
    except Exception:
        pass
    return None


def _parse_box_from_data_file(data_path: Path) -> list[float] | None:
    """Extract box dimensions [lx, ly, lz] from data.lammps header."""
    try:
        bounds: dict[str, tuple[float, float]] = {}
        with open(data_path) as f:
            for line in f:
                line_stripped = line.strip()
                if "xlo xhi" in line_stripped:
                    parts = line_stripped.split()
                    bounds["x"] = (float(parts[0]), float(parts[1]))
                elif "ylo yhi" in line_stripped:
                    parts = line_stripped.split()
                    bounds["y"] = (float(parts[0]), float(parts[1]))
                elif "zlo zhi" in line_stripped:
                    parts = line_stripped.split()
                    bounds["z"] = (float(parts[0]), float(parts[1]))
                elif line_stripped.startswith("Atoms"):
                    break

        if len(bounds) == 3:
            return [
                bounds["x"][1] - bounds["x"][0],
                bounds["y"][1] - bounds["y"][0],
                bounds["z"][1] - bounds["z"][0],
            ]
    except Exception:
        pass
    return None


def _extract_seed_from_dirname(name: str) -> int | None:
    """Extract seed from directory name like 'seed_20260316'."""
    if name.startswith("seed_"):
        try:
            return int(name[5:])
        except ValueError:
            pass
    return None


def _compute_current_protocol_hash(
    tier: str,
    ff_type: str,
    study_type: str,
    temperature_k: float,
    pressure_atm: float,
    data_file_path: str,
    in_lammps_path: str | None = None,
) -> str | None:
    """Compute protocol hash for current version using ProtocolHasher.

    Args:
        tier: Run tier string.
        ff_type: Force field type string.
        study_type: Study type string.
        temperature_k: Temperature in Kelvin.
        pressure_atm: Pressure in atmospheres.
        data_file_path: Path to data.lammps (required by ProtocolRequest).

    Returns:
        Protocol hash string or None on failure.
    """
    try:
        from protocols.protocol_hash import ProtocolHasher

        hasher = ProtocolHasher()
        step_names: list[str] = []

        if in_lammps_path:
            step_names = _parse_in_lammps_step_names(Path(in_lammps_path))

        if not step_names:
            from contracts.schemas import FFType, ProtocolRequest, RunTier, StudyType
            from protocols.protocol_chain import ProtocolChainBuilder

            builder = ProtocolChainBuilder()
            chain = builder.build(
                ProtocolRequest(
                    run_tier=RunTier(tier),
                    ff_type=FFType(ff_type),
                    temperature_K=temperature_k,
                    pressure_atm=pressure_atm,
                    study_type=StudyType(study_type) if study_type else StudyType.BULK,
                    data_file_path=data_file_path,
                )
            )
            step_names = [step.name for step in chain.steps]

        return hasher.hash(
            tier=tier,
            force_field=ff_type,
            ff_version=get_ff_version(ff_type),
            topology_hash="",
            temperature_K=temperature_k,
            pressure_atm=pressure_atm,
            step_names=step_names,
        )
    except Exception as exc:
        logger.warning(f"Failed to compute current protocol hash: {exc}")
        return None


def _find_work_dirs(exp_dir: Path) -> list[tuple[Path, int | None]]:
    """Find all work directories (seed dirs) within an experiment.

    Supports two layouts:
      - New: ``attempt_{uuid}/seed_{seed}/``
      - Old: ``seed_{seed}/``

    Returns:
        List of (work_dir, seed) tuples.
    """
    results: list[tuple[Path, int | None]] = []

    for child in sorted(exp_dir.iterdir()):
        if not child.is_dir():
            continue

        if child.name.startswith("attempt_"):
            # New format: attempt_{uuid}/seed_{seed}/
            for sub in sorted(child.iterdir()):
                if sub.is_dir() and sub.name.startswith("seed_"):
                    seed = _extract_seed_from_dirname(sub.name)
                    results.append((sub, seed))
        elif child.name.startswith("seed_"):
            # Old format: seed_{seed}/
            seed = _extract_seed_from_dirname(child.name)
            results.append((child, seed))

    return results


def _evaluate_attempt(work_dir: Path, seed: int | None) -> AttemptInfo:
    """Evaluate a single attempt directory for compatibility."""
    info = AttemptInfo(attempt_dir=work_dir, seed=seed)

    in_lammps = work_dir / "in.lammps"
    log_lammps = work_dir / "log.lammps"
    data_lammps = work_dir / "data.lammps"

    info.has_in_lammps = in_lammps.exists()
    info.has_log_lammps = log_lammps.exists()
    info.has_data_lammps = data_lammps.exists()
    info.mtime = work_dir.stat().st_mtime

    # Empty directory check
    file_count = sum(1 for _ in work_dir.iterdir())
    if file_count == 0:
        info.compatibility = "empty"
        info.compatibility_reason = "Empty directory"
        return info

    # No in.lammps
    if not info.has_in_lammps:
        info.compatibility = "no_metadata"
        info.compatibility_reason = "No in.lammps file found"
        return info

    # Parse header
    header = _parse_in_lammps_header(in_lammps)
    info.tier = header.get("tier")
    info.ff_type = header.get("ff_type")
    info.study_type = header.get("study_type")
    info.temperature_k = header.get("temperature_k")
    info.pressure_atm = header.get("pressure_atm")
    info.protocol_hash_found = header.get("protocol_hash")

    # Parse data file
    if info.has_data_lammps:
        info.total_atoms = _parse_atoms_from_data_file(data_lammps)
        info.box_dims = _parse_box_from_data_file(data_lammps)

    # Discover dump files — same patterns as lammps_runner._find_dump_files()
    dump_patterns = ["*.dump", "dump.*", "*.lammpstrj"]
    seen: set[str] = set()
    dump_files: list[str] = []
    for pattern in dump_patterns:
        for f in work_dir.glob(pattern):
            s = str(f)
            if s not in seen:
                seen.add(s)
                dump_files.append(s)
    if dump_files:
        info.dump_file_path = sorted(dump_files)[0]

    # Parse log for completion status and final_step
    info.lammps_completed, info.final_step = _parse_log_status(log_lammps)

    # No hash in header → unverifiable
    if not info.protocol_hash_found:
        info.compatibility = "hash_unverifiable"
        info.compatibility_reason = "No protocol hash in in.lammps header"
        return info

    # Need tier and ff_type to compute current hash
    if not info.tier or not info.ff_type:
        info.compatibility = "hash_unverifiable"
        info.compatibility_reason = "Missing tier or ff_type in header"
        return info

    # Compute current protocol hash
    data_path = str(data_lammps) if data_lammps.exists() else str(in_lammps)
    current_hash = _compute_current_protocol_hash(
        tier=info.tier,
        ff_type=info.ff_type,
        study_type=info.study_type or "bulk",
        temperature_k=info.temperature_k or 298.0,
        pressure_atm=info.pressure_atm or 1.0,
        data_file_path=data_path,
        in_lammps_path=str(in_lammps),
    )
    info.protocol_hash_current = current_hash

    if current_hash is None:
        info.compatibility = "hash_unverifiable"
        info.compatibility_reason = "Failed to compute current protocol hash"
        return info

    # Compare hashes
    if info.protocol_hash_found == current_hash:
        if info.lammps_completed:
            info.compatibility = "compatible"
            info.compatibility_reason = "Protocol hash matches, LAMMPS completed"
        else:
            info.compatibility = "compatible_incomplete"
            info.compatibility_reason = "Protocol hash matches, LAMMPS not completed"
    else:
        info.compatibility = "protocol_mismatch"
        info.compatibility_reason = (
            f"Protocol hash mismatch: found={info.protocol_hash_found}, current={current_hash}"
        )

    return info


def scan_experiment_directories(
    database_dir: Path | None = None,
) -> list[ScannedExperiment]:
    """Scan the database/ directory and evaluate all experiments.

    Args:
        database_dir: Override database directory path.

    Returns:
        List of ScannedExperiment results.
    """
    db_dir = database_dir or _get_database_dir()
    results: list[ScannedExperiment] = []

    for entry in sorted(db_dir.iterdir()):
        if not entry.is_dir():
            continue
        # Skip amorphous_cells
        if entry.name == "amorphous_cells":
            continue

        exp_id = entry.name
        work_dirs = _find_work_dirs(entry)

        if not work_dirs:
            # Empty experiment directory
            results.append(
                ScannedExperiment(
                    exp_id=exp_id,
                    directory=str(entry),
                    compatibility="empty",
                    compatibility_reason="No attempt/seed directories found",
                )
            )
            continue

        # Evaluate all attempts
        attempts: list[AttemptInfo] = []
        for work_dir, seed in work_dirs:
            attempt = _evaluate_attempt(work_dir, seed)
            attempts.append(attempt)

        # Select best attempt by importability priority
        attempts.sort(
            key=lambda a: (
                COMPAT_PRIORITY.get(a.compatibility, 99),
                -a.final_step,
                -a.mtime,
            )
        )
        best = attempts[0]

        # Build topology hash from data.lammps
        data_path = best.attempt_dir / "data.lammps"
        topology_hash = None
        if data_path.exists():
            try:
                topology_hash = compute_file_hash(data_path)[:16]
            except Exception:
                pass

        # Extract additive_mol_id for single-molecule experiments from exp_id
        additive_mol_id = None
        if best.study_type == "single_molecule_vacuum":
            additive_mol_id = _extract_sm_mol_id(exp_id)

        results.append(
            ScannedExperiment(
                exp_id=exp_id,
                directory=str(entry),
                has_in_lammps=best.has_in_lammps,
                has_log_lammps=best.has_log_lammps,
                has_data_lammps=best.has_data_lammps,
                tier=best.tier,
                ff_type=best.ff_type,
                temperature_k=best.temperature_k,
                total_atoms=best.total_atoms,
                protocol_hash_found=best.protocol_hash_found,
                protocol_hash_current=best.protocol_hash_current,
                compatibility=best.compatibility,
                compatibility_reason=best.compatibility_reason,
                lammps_completed=best.lammps_completed,
                seed=best.seed,
                box_dims=best.box_dims,
                data_file_path=str(data_path) if data_path.exists() else None,
                input_file_path=(
                    str(best.attempt_dir / "in.lammps") if best.has_in_lammps else None
                ),
                log_file_path=(
                    str(best.attempt_dir / "log.lammps") if best.has_log_lammps else None
                ),
                dump_file_path=best.dump_file_path,
                topology_hash=topology_hash,
                study_type=best.study_type,
                pressure_atm=best.pressure_atm,
                attempt_dir=str(best.attempt_dir),
                additive_mol_id=additive_mol_id,
            )
        )

    return results
