"""Per-experiment RESULT sidecar store (git-tracked, shareable across machines).

Each completed experiment gets one JSON file under ``data/result_sidecars/``
holding the machine-independent scientific result: composition/conditions
metadata + scalar metrics + references to the small array-metric curves
(``data/arrays/*.parquet``, also git-tracked). The large LAMMPS raw outputs
(``database/`` dumps/restarts/logs/trajectories, ~GB) are NEVER shared.

The DB is a runtime cache; these sidecars + the array parquets are the durable,
diffable, git-tracked source of truth — so a ``git pull`` + import lights up the
frontend graphs on another machine WITHOUT shipping the binary SQLite DB.

Two directions (mirrors ``e_intra_sidecar``):
  * **write-through** (``write_experiment_sidecar``): called once per completed
    experiment so its sidecar stays in sync automatically — no manual export.
  * **import** (``import_sidecars_to_db``): after ``git pull``, upserts every
    sidecar into the local DB (experiment row by ``exp_id``, molecules by
    ``mol_id``, metrics via ``MetricRepository.upsert`` with array paths
    re-localised). The dashboard reads the DB, so import is what shows the graphs.

Per-file ``fcntl`` lock + atomic ``os.replace`` make concurrent writes safe.
Payloads carry no machine-specific fields (no int PKs, paths, timestamps, GPU
or scheduler state) so diffs are minimal and cross-machine merges are clean.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from common.logging import get_logger
from common.pathing import get_project_root
from contracts.policies.result_export import (
    DEFAULT_RESULT_EXPORT_POLICY,
    SHARED_EXPERIMENT_FIELDS,
)

logger = get_logger("features.common.result_sidecar")

_SAFE = re.compile(r"[^A-Za-z0-9._=-]")

# Single-molecule (E_intra) experiments are NOT shared as result sidecars — their
# DB result (E_intra) is already shared via the per-molecule E_intra sidecars
# (``e_intra_sidecar``). Result sidecars carry binder-cell / layered metrics.
_SINGLE_MOLECULE_PREFIX = "SM_"


def _is_shareable_experiment(exp_id: str | None) -> bool:
    return bool(exp_id) and not str(exp_id).startswith(_SINGLE_MOLECULE_PREFIX)


def _project_root() -> Path:
    root_env = os.environ.get("ASPHALT_PROJECT_ROOT")
    return Path(root_env) if root_env else get_project_root()


def _sidecar_dir() -> Path:
    """Sidecar directory (workspace-isolation aware, mirrors e_intra)."""
    override = os.environ.get("ASPHALT_RESULT_SIDECAR_DIR")
    if override:
        return Path(override)
    return _project_root() / DEFAULT_RESULT_EXPORT_POLICY.sidecar_subdir


def _safe_filename(exp_id: str) -> str:
    return _SAFE.sub("_", exp_id) + DEFAULT_RESULT_EXPORT_POLICY.filename_suffix


def sidecar_path(exp_id: str) -> Path:
    return _sidecar_dir() / _safe_filename(exp_id)


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    import fcntl

    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with open(lock_path, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    os.replace(tmp, path)


def read_sidecar(exp_id: str) -> dict[str, Any] | None:
    path = sidecar_path(exp_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _rel_array_path(abs_path: str | None) -> str | None:
    """Project-relative form of an absolute array_file_path (machine-independent)."""
    if not abs_path:
        return None
    try:
        return str(Path(abs_path).resolve().relative_to(_project_root().resolve()))
    except (ValueError, OSError):
        return None


def _experiment_payload(session: Any, exp: Any) -> dict[str, Any]:
    from database.models import ExperimentMoleculeModel, MetricModel, MoleculeModel

    experiment = {f: getattr(exp, f, None) for f in SHARED_EXPERIMENT_FIELDS}

    mols: list[dict[str, Any]] = []
    rows = (
        session.query(
            MoleculeModel.mol_id,
            ExperimentMoleculeModel.count,
            ExperimentMoleculeModel.weight_fraction,
        )
        .join(MoleculeModel, MoleculeModel.id == ExperimentMoleculeModel.molecule_id)
        .filter(ExperimentMoleculeModel.experiment_id == exp.id)
        .all()
    )
    for mol_id, count, wf in rows:
        if mol_id:
            mols.append({"mol_id": mol_id, "count": count, "weight_fraction": wf})
    mols.sort(key=lambda m: str(m["mol_id"]))

    metrics: list[dict[str, Any]] = []
    for m in session.query(MetricModel).filter(MetricModel.experiment_id == exp.id).all():
        metrics.append(
            {
                "metric_name": m.metric_name,
                "value": m.value,
                "unit": m.unit,
                "namespace": m.namespace,
                "uncertainty": m.uncertainty,
                "layer_index": m.layer_index,
                "interface_index": m.interface_index,
                "array_rel_path": _rel_array_path(m.array_file_path),
                "array_shape": m.array_shape,
            }
        )
    metrics.sort(
        key=lambda x: (
            str(x["metric_name"]),
            x.get("layer_index") if x.get("layer_index") is not None else -1,
            x.get("interface_index") if x.get("interface_index") is not None else -1,
        )
    )

    return {
        "schema_version": DEFAULT_RESULT_EXPORT_POLICY.schema_version,
        "exp_id": exp.exp_id,
        "experiment": experiment,
        "molecules": mols,
        "metrics": metrics,
    }


def write_experiment_sidecar(session: Any, exp_id: str) -> bool:
    """Write-through: persist one experiment's result sidecar from the DB.

    Best-effort: returns ``False`` (never raises) when disabled, the experiment
    is missing, or any I/O fails — so it can never break completion handling.
    """
    if not DEFAULT_RESULT_EXPORT_POLICY.enabled:
        return False
    if not _is_shareable_experiment(exp_id):
        return False
    try:
        from database.models import ExperimentModel

        exp = session.query(ExperimentModel).filter(ExperimentModel.exp_id == exp_id).first()
        if exp is None:
            return False
        payload = _experiment_payload(session, exp)
        path = sidecar_path(exp_id)
        with _locked(path):
            _atomic_write_json(path, payload)
        return True
    except Exception as exc:  # noqa: BLE001 - write-through must never break completion
        logger.warning("Result sidecar write-through failed for %s: %s", exp_id, exc)
        return False


def iter_sidecar_files() -> Iterator[Path]:
    base = _sidecar_dir()
    if not base.exists():
        return
    suffix = DEFAULT_RESULT_EXPORT_POLICY.filename_suffix
    for p in sorted(base.glob(f"*{suffix}")):
        if p.name.endswith(".tmp") or p.name.endswith(".lock"):
            continue
        yield p


def import_sidecars_to_db(session: Any) -> dict[str, int]:
    """Upsert all result sidecars into the local DB (after ``git pull``).

    Experiment rows are keyed by ``exp_id`` (created if absent), molecules
    resolved by ``mol_id`` via the molecule library, metrics upserted via
    ``MetricRepository`` with array paths re-localised to this machine. Caller
    commits the session.

    Returns:
        ``{"files", "experiments", "metrics", "skipped"}``.
    """
    from database.models import ExperimentModel, ExperimentMoleculeModel, MoleculeModel
    from database.repositories.metric_repo import MetricRepository

    repo = MetricRepository(session)
    root = _project_root()
    files = experiments = metrics = skipped = 0

    for path in iter_sidecar_files():
        files += 1
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Skipping unreadable result sidecar %s: %s", path, exc)
            continue
        eid = doc.get("exp_id")
        if not eid:
            continue
        try:
            expd = doc.get("experiment") or {}
            exp = session.query(ExperimentModel).filter(ExperimentModel.exp_id == eid).first()
            if exp is None:
                exp = ExperimentModel(exp_id=eid)
                session.add(exp)
            for field in SHARED_EXPERIMENT_FIELDS:
                if field != "exp_id" and field in expd:
                    setattr(exp, field, expd[field])
            session.flush()  # assign exp.id

            # molecules — replace the set for this experiment
            session.query(ExperimentMoleculeModel).filter(
                ExperimentMoleculeModel.experiment_id == exp.id
            ).delete()
            for mrow in doc.get("molecules", []):
                mol = (
                    session.query(MoleculeModel)
                    .filter(MoleculeModel.mol_id == mrow.get("mol_id"))
                    .first()
                )
                if mol is None:
                    continue  # molecule library not loaded yet — skip linkage
                session.add(
                    ExperimentMoleculeModel(
                        experiment_id=exp.id,
                        molecule_id=mol.id,
                        count=mrow.get("count"),
                        weight_fraction=mrow.get("weight_fraction"),
                    )
                )

            # metrics — upsert (resolves experiment_id by exp_id, validates registry)
            for mrow in doc.get("metrics", []):
                rel = mrow.get("array_rel_path")
                local = str(root / rel) if rel else None
                try:
                    repo.upsert(
                        exp_id=eid,
                        metric_name=mrow["metric_name"],
                        value=mrow.get("value"),
                        unit=mrow["unit"],
                        namespace=mrow["namespace"],
                        uncertainty=mrow.get("uncertainty"),
                        array_file_path=local,
                        array_shape=mrow.get("array_shape"),
                        layer_index=mrow.get("layer_index"),
                        interface_index=mrow.get("interface_index"),
                    )
                    metrics += 1
                except Exception as exc:  # noqa: BLE001 - skip one bad metric
                    logger.warning("Skipping metric %s for %s: %s", mrow.get("metric_name"), eid, exc)
                    skipped += 1
            experiments += 1
        except Exception as exc:  # noqa: BLE001 - skip one bad experiment
            logger.warning("Skipping result sidecar %s: %s", eid, exc)
            skipped += 1

    return {"files": files, "experiments": experiments, "metrics": metrics, "skipped": skipped}


def export_db_to_sidecars(session: Any, *, statuses: tuple[str, ...] = ("completed",)) -> dict[str, int]:
    """Rebuild result sidecars from the DB (backfill / repair).

    One-shot reconciliation for experiments completed before write-through
    existed. Writes one sidecar per experiment in ``statuses`` (default:
    completed only — failed/cancelled runs are not shared).

    Returns:
        ``{"experiments", "sidecars"}``.
    """
    from database.models import ExperimentModel

    q = session.query(ExperimentModel).filter(ExperimentModel.exp_id.isnot(None))
    if statuses:
        q = q.filter(ExperimentModel.status.in_(list(statuses)))
    # Exclude single-molecule E_intra runs (shared via e_intra sidecars instead).
    q = q.filter(~ExperimentModel.exp_id.like(f"{_SINGLE_MOLECULE_PREFIX}%"))
    written = 0
    total = 0
    for exp in q.all():
        total += 1
        payload = _experiment_payload(session, exp)
        # Only share experiments that actually carry metrics (else nothing to graph).
        if not payload["metrics"]:
            continue
        path = sidecar_path(exp.exp_id)
        with _locked(path):
            _atomic_write_json(path, payload)
        written += 1
    return {"experiments": total, "sidecars": written}
