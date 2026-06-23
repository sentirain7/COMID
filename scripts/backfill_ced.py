#!/usr/bin/env python3
"""Backfill CED (cohesive_energy_density) for completed binder experiments.

Problem this solves
-------------------
CED is computed at metric time as ``CED = -(PE_bulk - sum(n_i * E_intra_i)) / V``.
When a binder system completed BEFORE the single-molecule E_intra reference
values existed, the CED metric was silently skipped (E_intra missing). The
binder's bulk energy/volume and molecule counts were still persisted, and the
E_intra values are now available — so CED is recoverable from EXISTING data with
**no re-simulation**.

What it does
------------
For each completed binder experiment that lacks a ``cohesive_energy_density``
metric, it:
  1. reads ``mol_counts`` from ``experiment_molecules`` (joined to ``molecules``),
  2. parses the binder's ``log.lammps`` thermo (PotEng + Volume) from disk,
  3. looks up E_intra per molecule at the binder temperature via the SAME
     DB-backed adapter production uses (``make_metrics_calculator``),
  4. computes CED with the production ``CEDCalculator.calculate_from_thermo``,
  5. persists it via ``MetricRepository.save()`` — the EXACT same path normal
     computation uses (``metrics`` table, experiment_id resolved, registry
     validated, committed) — so the dashboard/analysis screens show it
     identically to a normally-computed CED.

Safety
------
Dry-run by default (compute + report, NO writes). Pass ``--commit`` to persist.
Additive/post-processing only: never touches existing metrics, experiments, or
running jobs. CED rows are upserted (idempotent — re-running is safe).

Usage
-----
    python scripts/backfill_ced.py                      # dry-run, all eligible
    python scripts/backfill_ced.py --commit             # compute + persist
    python scripts/backfill_ced.py --exp-id K1_X1_SA_293K_xxxx --commit
    python scripts/backfill_ced.py --limit 10
    python scripts/backfill_ced.py --coverage-mode allow_tolerance --commit
"""

from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

# Make ``src`` importable when run from the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

CED_METRIC = "cohesive_energy_density"
EXPERIMENT_DB_DIR = _REPO_ROOT / "database"  # per-experiment work dirs live here


def _eligible_binders(session, *, exp_id: str | None, limit: int | None) -> list:
    """Completed binder experiments (non single-molecule, non-layered) that lack CED."""
    from database.models import ExperimentModel, MetricModel

    q = session.query(ExperimentModel).filter(ExperimentModel.status == "completed")
    if exp_id:
        q = q.filter(ExperimentModel.exp_id == exp_id)
    else:
        # exclude single-molecule E_intra runs and layered interface runs
        q = q.filter(~ExperimentModel.exp_id.like("SM_%"))
    rows = q.order_by(ExperimentModel.temperature_K.asc(), ExperimentModel.id.asc()).all()

    out = []
    for exp in rows:
        has_ced = (
            session.query(MetricModel.id)
            .filter(
                MetricModel.experiment_id == exp.id,
                MetricModel.metric_name == CED_METRIC,
            )
            .first()
        )
        if has_ced and not exp_id:
            continue  # already has CED (explicit --exp-id reprocesses/upserts)
        out.append(exp)
        if limit and len(out) >= limit:
            break
    return out


def _mol_counts(session, experiment_id: int) -> dict[str, int]:
    """``{string mol_id: count}`` for a binder — keys match ``e_intra.mol_id``."""
    from database.models import ExperimentMoleculeModel, MoleculeModel

    rows = (
        session.query(MoleculeModel.mol_id, ExperimentMoleculeModel.count)
        .join(MoleculeModel, MoleculeModel.id == ExperimentMoleculeModel.molecule_id)
        .filter(ExperimentMoleculeModel.experiment_id == experiment_id)
        .all()
    )
    return {mol_id: int(count) for mol_id, count in rows if mol_id}


def _best_thermo(exp_id: str):
    """Parse the binder's production log.lammps; return the richest valid thermo.

    A binder may have multiple attempt dirs (failed retries + the successful run).
    Pick the log whose thermo has PotEng + Volume with the most data points (the
    completed multi-stage production run), so CED windows real NPT-production data.
    """
    from parsers.log_parser import LogParser

    logs = sorted(glob.glob(str(EXPERIMENT_DB_DIR / exp_id / "attempt_*" / "seed_*" / "log.lammps")))
    best = None
    best_n = 0
    for lg in logs:
        try:
            td = LogParser().parse(Path(lg)).thermo_data
        except Exception:  # noqa: BLE001 - skip unreadable logs
            continue
        if not td:
            continue
        pe = next((c for c in ("PotEng", "PE", "E_pot") if c in td and td[c]), None)
        vol = next((c for c in ("Volume", "Vol", "V") if c in td and td[c]), None)
        if pe and vol and len(td[pe]) > best_n:
            best, best_n = td, len(td[pe])
    return best


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill CED for completed binders.")
    ap.add_argument("--commit", action="store_true", help="Persist to DB (default: dry-run).")
    ap.add_argument("--exp-id", default=None, help="Single experiment exp_id (else all eligible).")
    ap.add_argument("--limit", type=int, default=None, help="Max experiments to process.")
    ap.add_argument(
        "--coverage-mode",
        default="exact_required",
        choices=["exact_required", "allow_tolerance", "allow_missing_pe_over_v"],
        help="CED E_intra coverage mode (default: exact_required = production default).",
    )
    # Physical sanity gate. Asphalt-binder CED is well-bounded (existing computed
    # values span ~298-392 MJ/m3). Out-of-range results indicate a data problem
    # (e.g. missing additive molecular weight, a non-equilibrated run) and are
    # FLAGGED for review, never persisted — so the DB only gets trustworthy CED.
    ap.add_argument("--min-ced", type=float, default=150.0, help="Min physical CED to persist (MJ/m3).")
    ap.add_argument("--max-ced", type=float, default=700.0, help="Max physical CED to persist (MJ/m3).")
    args = ap.parse_args()

    from contracts.policies.forcefield import get_ff_version
    from database.connection import session_scope
    from database.repositories.metric_repo import MetricRepository
    from orchestrator.task_runners import make_metrics_calculator

    ff_name = "GAFF2"
    ff_version = get_ff_version("bulk_ff_gaff2")
    e_intra_method = "single_molecule_vacuum"

    mode = "COMMIT" if args.commit else "DRY-RUN"
    print(f"[backfill_ced] mode={mode} coverage={args.coverage_mode} ff={ff_name}/{ff_version}\n")

    computed = persisted = skipped_no_thermo = skipped_no_ced = flagged_outlier = 0
    with session_scope() as session:
        calc = make_metrics_calculator(session, ced_coverage_mode=args.coverage_mode)
        repo = MetricRepository(session)
        binders = _eligible_binders(session, exp_id=args.exp_id, limit=args.limit)
        print(f"[backfill_ced] eligible binders (completed, no CED): {len(binders)}\n")

        for exp in binders:
            eid = exp.exp_id
            tK = float(exp.temperature_K or 298.0)
            mol_counts = _mol_counts(session, exp.id)
            thermo = _best_thermo(eid)
            if not thermo or not mol_counts:
                skipped_no_thermo += 1
                print(f"  SKIP  {eid[:34]:34s} (no thermo / no mol_counts)")
                continue

            ced = calc.ced_calc.calculate_from_thermo(
                thermo_data=thermo,
                mol_counts=mol_counts,
                ff_name=ff_name,
                ff_version=ff_version,
                window_ps=calc.window_ps,
                dt_fs=calc.dt_fs,
                thermo_interval=calc.thermo_interval,
                use_window_ps=True,
                temperature_K=tK,
                e_intra_method=e_intra_method,
            )
            if ced is None:
                skipped_no_ced += 1
                print(f"  SKIP  {eid[:34]:34s} T={tK:.0f}  (E_intra coverage insufficient)")
                continue

            ced.exp_id = eid  # resolve experiment_id on save (same as normal path)
            # Physical sanity gate — never persist a non-physical CED.
            if ced.value is None or not (args.min_ced <= ced.value <= args.max_ced):
                flagged_outlier += 1
                print(
                    f"  FLAG  {eid[:34]:34s} T={tK:.0f}  = {ced.value} {ced.unit}  "
                    f"(outside [{args.min_ced:.0f},{args.max_ced:.0f}] — NOT persisted; "
                    f"likely missing additive MW / bad equilibration)"
                )
                continue
            computed += 1
            print(f"  CED   {eid[:34]:34s} T={tK:.0f}  = {ced.value:8.1f} {ced.unit}")
            if args.commit:
                repo.save(ced)  # upsert into metrics table + commit (identical to normal)
                persisted += 1

    print(
        f"\n[backfill_ced] done: computed(sane)={computed} persisted={persisted} "
        f"flagged(out-of-range)={flagged_outlier} "
        f"skipped(no thermo)={skipped_no_thermo} skipped(no E_intra)={skipped_no_ced}"
    )
    if not args.commit and computed:
        print("[backfill_ced] DRY-RUN — re-run with --commit to persist to the metrics table.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
