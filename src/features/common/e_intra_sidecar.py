"""Per-molecule E_intra sidecar store (git-tracked, shareable across machines).

Each molecule gets one JSON file under ``data/forcefield_artifacts/e_intra/``
holding its E_intra values per (ff_name, ff_version, method, temperature).
The DB ``e_intra`` table is a runtime cache; these sidecars are the durable,
diffable, git-tracked source of truth.

Two directions:
  * **write-through** (``upsert_entry``): called from the SSOT store helper so
    that completing one (molecule, temperature) E_intra run automatically
    updates that molecule's sidecar — no manual export.  Per-file ``fcntl``
    lock + atomic ``os.replace`` make concurrent same-molecule writes safe.
  * **import** (``import_sidecars_to_db``): reads the sidecars (after ``git
    pull``) and upserts them into the local DB via ``EIntraRepository.set``,
    which resolves ``mol_id`` → local ``molecule_id``.  The frontend coverage
    matrix then reflects the imported temperatures.

Entries are sorted and carry no machine-specific fields (no ``source_exp_id``,
no timestamps) so diffs are minimal and merges across machines are clean.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from common.logging import get_logger
from common.pathing import get_project_root
from contracts.policies.e_intra_export import DEFAULT_E_INTRA_EXPORT_POLICY

logger = get_logger("features.common.e_intra_sidecar")

# Fields that uniquely identify an entry within a molecule's sidecar.
_ENTRY_KEY_FIELDS = ("ff_name", "ff_version", "method", "temperature_K")


def _sidecar_dir() -> Path:
    """Resolve the sidecar directory (workspace-isolation aware).

    Resolution order:
        1. ``ASPHALT_E_INTRA_SIDECAR_DIR`` env (tests / explicit redirect).
        2. ``ASPHALT_PROJECT_ROOT`` env + policy subdir (isolated workspaces).
        3. ``common.pathing.get_project_root()`` + policy subdir (default;
           same root the FF artifact loader uses, so sidecars sit beside the
           force-field artifacts).
    """
    override = os.environ.get("ASPHALT_E_INTRA_SIDECAR_DIR")
    if override:
        return Path(override)
    subdir = DEFAULT_E_INTRA_EXPORT_POLICY.sidecar_subdir
    root_env = os.environ.get("ASPHALT_PROJECT_ROOT")
    root = Path(root_env) if root_env else get_project_root()
    return root / subdir


def _safe_filename(mol_id: str) -> str:
    """Map a mol_id to a filesystem-safe sidecar filename.

    mol_ids are already filename-safe in practice (e.g. ``U-AS-Thio``); this
    only guards against stray separators so the sidecar never escapes its dir.
    """
    safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in mol_id)
    return f"{safe}{DEFAULT_E_INTRA_EXPORT_POLICY.filename_suffix}"


def sidecar_path(mol_id: str) -> Path:
    """Return the sidecar file path for ``mol_id`` (not guaranteed to exist)."""
    return _sidecar_dir() / _safe_filename(mol_id)


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    """Hold an exclusive ``fcntl`` lock on ``<path>.lock`` for the body.

    Serializes read-modify-write on a molecule's sidecar across processes
    (e.g. 12 same-molecule temperature jobs completing concurrently).  No-op
    fallback on platforms without ``fcntl`` (still atomic via ``os.replace``).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    try:
        import fcntl
    except ImportError:  # pragma: no cover - non-POSIX
        yield
        return
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write ``payload`` to ``path`` atomically (tmp file + ``os.replace``)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_sidecar(mol_id: str) -> dict[str, Any] | None:
    """Read a molecule's sidecar, or ``None`` if absent / unreadable."""
    path = sidecar_path(mol_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Unreadable E_intra sidecar %s: %s", path, exc)
        return None


def _sort_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort entries by the unique-key fields for deterministic, diff-clean output."""
    return sorted(
        entries,
        key=lambda e: (
            str(e.get("ff_name", "")),
            str(e.get("ff_version", "")),
            str(e.get("method", "")),
            float(e.get("temperature_K", 0.0)),
        ),
    )


def _entry_matches(entry: dict[str, Any], **key: Any) -> bool:
    """True iff ``entry`` matches all unique-key fields in ``key``."""
    for field in _ENTRY_KEY_FIELDS:
        a, b = entry.get(field), key.get(field)
        if field == "temperature_K":
            if abs(float(a) - float(b)) >= 0.1:
                return False
        elif str(a) != str(b):
            return False
    return True


def upsert_entry(
    *,
    mol_id: str,
    ff_name: str,
    ff_version: str,
    method: str,
    temperature_K: float,
    e_intra: float,
    n_samples: int | None = None,
    averaging_window_ps: float | None = None,
) -> Path | None:
    """Write-through one E_intra value into the molecule's sidecar (idempotent).

    Reads the existing sidecar, replaces (or inserts) the entry matching
    ``(ff_name, ff_version, method, temperature_K)``, and writes back
    atomically under a per-file lock.  Returns the sidecar path, or ``None``
    if the export policy is disabled.

    Best-effort: callers must guard against exceptions so a sidecar failure
    never breaks the authoritative DB write.
    """
    if not DEFAULT_E_INTRA_EXPORT_POLICY.enabled:
        return None

    path = sidecar_path(mol_id)
    new_entry = {
        "ff_name": ff_name,
        "ff_version": ff_version,
        "method": method,
        "temperature_K": float(temperature_K),
        "e_intra": float(e_intra),
        "n_samples": n_samples,
        "averaging_window_ps": averaging_window_ps,
    }
    with _locked(path):
        doc = read_sidecar(mol_id) or {
            "schema_version": DEFAULT_E_INTRA_EXPORT_POLICY.schema_version,
            "mol_id": mol_id,
            "entries": [],
        }
        entries = [
            e
            for e in doc.get("entries", [])
            if not _entry_matches(
                e,
                ff_name=ff_name,
                ff_version=ff_version,
                method=method,
                temperature_K=temperature_K,
            )
        ]
        entries.append(new_entry)
        doc["mol_id"] = mol_id
        doc["schema_version"] = DEFAULT_E_INTRA_EXPORT_POLICY.schema_version
        doc["entries"] = _sort_entries(entries)
        _atomic_write_json(path, doc)
    return path


def iter_sidecar_files() -> Iterator[Path]:
    """Yield every sidecar JSON file in the sidecar directory."""
    base = _sidecar_dir()
    if not base.exists():
        return
    suffix = DEFAULT_E_INTRA_EXPORT_POLICY.filename_suffix
    for p in sorted(base.glob(f"*{suffix}")):
        if p.name.endswith(".tmp") or p.name.endswith(".lock"):
            continue
        yield p


def import_sidecars_to_db(session: Any) -> dict[str, int]:
    """Upsert all sidecar entries into the DB ``e_intra`` table.

    Reads every sidecar and applies each entry through
    ``EIntraRepository.set`` (which resolves ``mol_id`` → local
    ``molecule_id``).  Idempotent on the 5-column unique key.  The caller
    is responsible for committing the session.

    Returns:
        Counts dict: ``{"files", "entries", "upserted", "skipped"}``.
    """
    from contracts.schemas import EIntraKey, EIntraValue
    from database.repositories.e_intra_repo import EIntraRepository

    repo = EIntraRepository(session)
    files = entries = upserted = skipped = 0
    for path in iter_sidecar_files():
        files += 1
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Skipping unreadable sidecar %s: %s", path, exc)
            continue
        mol_id = doc.get("mol_id")
        if not mol_id:
            continue
        for entry in doc.get("entries", []):
            entries += 1
            try:
                key = EIntraKey(
                    mol_id=mol_id,
                    ff_name=entry["ff_name"],
                    ff_version=entry["ff_version"],
                    temperature_K=float(entry["temperature_K"]),
                    method=entry["method"],
                )
                value = EIntraValue(
                    e_intra=float(entry["e_intra"]),
                    temperature_K=float(entry["temperature_K"]),
                    source_exp_id=None,
                    averaging_window_ps=entry.get("averaging_window_ps"),
                    n_samples=entry.get("n_samples"),
                )
                repo.set(key, value)
                upserted += 1
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning("Skipping malformed entry in %s: %s", path, exc)
                skipped += 1
    return {"files": files, "entries": entries, "upserted": upserted, "skipped": skipped}


def export_db_to_sidecars(session: Any) -> dict[str, int]:
    """Rebuild all sidecars from the DB ``e_intra`` table (backfill / repair).

    One-shot reconciliation for E_intra computed before write-through existed,
    or to repair drift.  Writes one entry per DB row, grouped by molecule.

    Returns:
        Counts dict: ``{"rows", "molecules", "sidecars"}``.
    """
    from database.models import EIntraModel

    rows = session.query(
        EIntraModel.mol_id,
        EIntraModel.ff_name,
        EIntraModel.ff_version,
        EIntraModel.method,
        EIntraModel.temperature_K,
        EIntraModel.e_intra,
        EIntraModel.n_samples,
        EIntraModel.averaging_window_ps,
    ).all()

    by_mol: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if not r.mol_id:
            continue
        by_mol.setdefault(r.mol_id, []).append(
            {
                "ff_name": r.ff_name,
                "ff_version": r.ff_version,
                "method": r.method,
                "temperature_K": float(r.temperature_K),
                "e_intra": float(r.e_intra),
                "n_samples": r.n_samples,
                "averaging_window_ps": r.averaging_window_ps,
            }
        )

    sidecars = 0
    for mol_id, entries in by_mol.items():
        path = sidecar_path(mol_id)
        with _locked(path):
            _atomic_write_json(
                path,
                {
                    "schema_version": DEFAULT_E_INTRA_EXPORT_POLICY.schema_version,
                    "mol_id": mol_id,
                    "entries": _sort_entries(entries),
                },
            )
        sidecars += 1
    return {"rows": len(rows), "molecules": len(by_mol), "sidecars": sidecars}
