#!/usr/bin/env python3
"""Backfill metrics for experiments that completed NPT (density / CED / bulk
modulus / RDF / MSD) but were marked FAILED at the viscosity write_restart bug
(v24), so the metrics pipeline never ran and NOTHING was saved to the DB.

These runs have complete on-disk outputs (log.lammps with all NPT/equilibration
stages + dump trajectories) — only the metric-extraction step was skipped. This
reconstructs a LAMMPSRunResult from the existing files and runs the PRODUCTION
``MetricCalculator`` (same code the live pipeline uses), then persists the
NPT-derived metrics. Viscosity is EXCLUDED (unreliable for these pre-v25 runs;
recompute it after a re-run with the v25 temp_profile fix).

Safety: dry-run by default (compute + report, NO writes). Pass --commit to
persist. Only metrics NOT already present for an experiment are added (idempotent;
never overwrites existing rows). DB experiments are never modified.

Usage:
    python scripts/backfill_failed_metrics.py                       # dry-run, failed %SBS%
    python scripts/backfill_failed_metrics.py --commit
    python scripts/backfill_failed_metrics.py --exp-id A1_X1_LA_SBS_3_7_293K_62feb8
    python scripts/backfill_failed_metrics.py --like %SBS% --status failed --commit
"""

from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# Viscosity is the failed/unreliable stage for these pre-v25 runs — never backfill it.
EXCLUDE_METRICS = {"viscosity"}
DB_DIR = _REPO / "database"


def _run_dir(exp_id: str) -> Path | None:
    """Attempt/seed dir whose log.lammps is largest (= the completed multi-stage run)."""
    logs = glob.glob(str(DB_DIR / exp_id / "attempt_*" / "seed_*" / "log.lammps"))
    if not logs:
        return None
    return Path(max(logs, key=lambda p: Path(p).stat().st_size)).parent


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill NPT-derived metrics for failed-at-viscosity runs.")
    ap.add_argument("--commit", action="store_true", help="Persist to DB (default: dry-run).")
    ap.add_argument("--exp-id", default=None, help="Single experiment exp_id.")
    ap.add_argument("--like", default="%SBS%", help="exp_id LIKE filter (default %%SBS%%).")
    ap.add_argument("--status", default="failed", help="Comma statuses to scan (default failed).")
    ap.add_argument("--limit", type=int, default=None, help="Max experiments.")
    args = ap.parse_args()

    from contracts.schemas import LAMMPSRunResult
    from database.connection import session_scope
    from database.models import ExperimentModel, MetricModel
    from database.repositories.metric_repo import MetricRepository
    from orchestrator.task_runners import make_metrics_calculator

    statuses = [s.strip() for s in args.status.split(",") if s.strip()]
    mode = "COMMIT" if args.commit else "DRY-RUN"
    print(f"[backfill_failed_metrics] mode={mode} status={statuses} like={args.like}\n")

    total_added = scanned = skipped = errored = 0
    with session_scope() as session:
        calc = make_metrics_calculator(session)
        repo = MetricRepository(session)

        q = session.query(ExperimentModel)
        if args.exp_id:
            q = q.filter(ExperimentModel.exp_id == args.exp_id)
        else:
            q = q.filter(
                ExperimentModel.status.in_(statuses),
                ExperimentModel.exp_id.like(args.like),
            )
        exps = q.order_by(ExperimentModel.exp_id).all()
        if args.limit:
            exps = exps[: args.limit]
        print(f"  candidates: {len(exps)}\n")

        for exp in exps:
            scanned += 1
            rdir = _run_dir(exp.exp_id)
            if rdir is None:
                skipped += 1
                print(f"  SKIP  {exp.exp_id} (no log.lammps on disk)")
                continue
            dumps = sorted(str(p) for p in rdir.glob("dump_*.lammpstrj"))
            rr = LAMMPSRunResult(
                success=True,
                log_file=str(rdir / "log.lammps"),
                dump_files=dumps,
                wall_time_seconds=0.0,
                exit_code=0,
                exp_id=exp.exp_id,
            )
            try:
                metrics = calc.calculate(rr)
            except Exception as exc:  # noqa: BLE001 - report and continue
                errored += 1
                print(f"  ERR   {exp.exp_id}: {exc}")
                continue

            keep = [m for m in metrics if m.metric_name not in EXCLUDE_METRICS and m.value is not None]
            existing = {
                r[0]
                for r in session.query(MetricModel.metric_name)
                .filter(MetricModel.experiment_id == exp.id)
                .all()
            }
            new = [m for m in keep if m.metric_name not in existing]

            shown = ", ".join(f"{m.metric_name}={m.value:.4g}" for m in keep)
            print(f"  {exp.exp_id}: [{shown}]  -> new={len(new)} (existing={len(existing)})")

            if args.commit and new:
                for m in new:
                    m.exp_id = exp.exp_id
                    repo.save(m)
                total_added += len(new)

    print(
        f"\n[backfill_failed_metrics] done: scanned={scanned} metrics_added={total_added} "
        f"skipped(no data)={skipped} errored={errored}"
    )
    if not args.commit:
        print("[backfill_failed_metrics] DRY-RUN — re-run with --commit to persist.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
