#!/usr/bin/env python3
"""Backfill ``viscosity`` for experiments whose viscosity run COMPLETED but were
marked failed by the post-run write_restart bug (fixed in v01.06.24).

Problem this solves
-------------------
The Muller-Plathe viscosity stage ran its full NEMD steps and wrote a complete
``f_viscosity_N`` thermo series + ``vprofile_*.dat``, but the job then aborted at
``write_restart`` ("ERROR: Could not find thermo fix ID viscosity_N") because the
thermo_style still referenced the just-unfixed viscosity fix. The job was marked
``failed`` and the metrics pipeline never ran — yet the viscosity is FULLY
computable from the existing on-disk data with **no re-simulation**.

What it does
------------
For each experiment that has complete viscosity output on disk but lacks a
``viscosity`` metric, it:
  1. parses ``log.lammps`` thermo (LogParser) and finds ``f_viscosity_N``,
  2. reconstructs the viscosity-run time axis (last N Step entries x dt),
  3. extracts the cross-sectional box area Lx*Ly from the log,
  4. parses the ``vprofile_*.dat`` velocity profile,
  5. computes viscosity with the production ``ViscosityCalculator`` (the SAME
     code path normal metric computation uses),
  6. persists it via ``MetricRepository.save()`` (``metrics`` table, experiment_id
     resolved, registry validated) — so dashboards show it identically.

Safety
------
Dry-run by default (compute + report, NO writes). Pass ``--commit`` to persist.
Additive/post-processing only: never touches experiments, running jobs, or other
metrics. Viscosity rows are upserted (idempotent — re-running is safe). A loose
physical-sanity gate flags non-physical values (never persisted).

Usage
-----
    python scripts/backfill_viscosity.py                  # dry-run, all eligible
    python scripts/backfill_viscosity.py --commit         # compute + persist
    python scripts/backfill_viscosity.py --exp-id A1_X1_NA_SBS_3_7_293K_xxxx --commit
    python scripts/backfill_viscosity.py --status failed --commit
"""

from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

import numpy as np

# Make ``src`` importable when run from the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

VISCOSITY_METRIC = "viscosity"
EXPERIMENT_DB_DIR = _REPO_ROOT / "database"
_DT_FS = 1.0  # viscosity-tier runs use a 1.0 fs timestep


def _eligible(session, *, exp_id: str | None, statuses: list[str], limit: int | None) -> list:
    """Experiments (in given statuses, non single-molecule) that lack a viscosity metric."""
    from database.models import ExperimentModel, MetricModel

    q = session.query(ExperimentModel)
    if exp_id:
        q = q.filter(ExperimentModel.exp_id == exp_id)
    else:
        q = q.filter(ExperimentModel.status.in_(statuses))
        q = q.filter(~ExperimentModel.exp_id.like("SM_%"))
    rows = q.order_by(ExperimentModel.id.asc()).all()

    out = []
    for exp in rows:
        has_visc = (
            session.query(MetricModel.id)
            .filter(
                MetricModel.experiment_id == exp.id,
                MetricModel.metric_name == VISCOSITY_METRIC,
            )
            .first()
        )
        if has_visc and not exp_id:
            continue  # already has viscosity (explicit --exp-id reprocesses/upserts)
        out.append(exp)
        if limit and len(out) >= limit:
            break
    return out


def _best_viscosity_log(exp_id: str):
    """Find the attempt dir whose log has the most complete f_viscosity series.

    Returns (log_path, thermo_data) or (None, None). A run may have several
    attempt dirs; pick the one whose completed viscosity run has the longest
    f_viscosity_* column.
    """
    from metrics.viscosity import ViscosityCalculator
    from parsers.log_parser import LogParser

    logs = sorted(
        glob.glob(str(EXPERIMENT_DB_DIR / exp_id / "attempt_*" / "seed_*" / "log.lammps"))
    )
    best_log = None
    best_td = None
    best_n = 0
    for lg in logs:
        try:
            td = LogParser().parse(Path(lg)).thermo_data
        except Exception:  # noqa: BLE001 - skip unreadable logs
            continue
        if not td:
            continue
        f_col = ViscosityCalculator.find_f_viscosity_column(td)
        if f_col and len(td[f_col]) > best_n:
            best_log, best_td, best_n = Path(lg), td, len(td[f_col])
    return best_log, best_td


def _compute_viscosity(log_path: Path, thermo_data: dict):
    """Compute a ViscosityResult from on-disk log + vprofile (production code path)."""
    from metrics.viscosity import ViscosityCalculator

    calc = ViscosityCalculator()
    f_col = ViscosityCalculator.find_f_viscosity_column(thermo_data)
    if not f_col:
        return None, "no f_viscosity column"
    f_values = thermo_data[f_col]
    if len(f_values) < 3:
        return None, f"too few f_viscosity samples ({len(f_values)})"

    # Reconstruct the viscosity-run time axis: f_viscosity appears only in the
    # (last) viscosity run, so take the last N Step entries.
    n_visc = len(f_values)
    step_col = thermo_data.get("Step", [])
    steps_visc = step_col[-n_visc:] if len(step_col) >= n_visc else list(range(n_visc))
    time_fs = np.array(steps_visc, dtype=np.float64) * _DT_FS

    # Cross-sectional box area Lx*Ly.
    box_area = None
    try:
        box_area = ViscosityCalculator.extract_box_area_from_log(log_path.read_text())
    except OSError:
        pass
    if box_area is None:
        vol = thermo_data.get("Volume", thermo_data.get("Vol", []))
        if vol:
            box_area = ViscosityCalculator.estimate_box_area_from_volume(
                float(np.mean(vol[-n_visc:]))
            )
    if not box_area or box_area <= 0:
        return None, "could not determine box area"

    # Velocity profile.
    profile = None
    vprofiles = sorted(log_path.parent.glob("vprofile_*.dat"))
    if vprofiles:
        profile = calc.parse_velocity_profile(vprofiles[-1])

    result = calc.compute_from_rnemd(
        f_viscosity_values=f_values,
        time_fs=time_fs,
        box_area_A2=box_area,
        velocity_profile=profile,
    )
    return result, None


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill viscosity from completed RNEMD data.")
    ap.add_argument("--commit", action="store_true", help="Persist to DB (default: dry-run).")
    ap.add_argument("--exp-id", default=None, help="Single experiment exp_id (else all eligible).")
    ap.add_argument(
        "--status",
        default="failed,completed,timeout",
        help="Comma-separated statuses to scan (default: failed,completed,timeout).",
    )
    ap.add_argument("--limit", type=int, default=None, help="Max experiments to process.")
    # Loose physical-sanity gate: asphalt-binder viscosity spans many orders of
    # magnitude with temperature, so only obvious garbage (<=0 or absurd) is gated.
    ap.add_argument(
        "--min-visc", type=float, default=1e-3, help="Min viscosity to persist (mPa.s)."
    )
    ap.add_argument("--max-visc", type=float, default=1e9, help="Max viscosity to persist (mPa.s).")
    # QUALITY gate — the Muller-Plathe velocity gradient must be a clean line for
    # the viscosity to be trustworthy. A low grad_R2 means the imposed flow never
    # established a linear profile (e.g. glassy low-T asphalt, or the unbiased
    # thermostat issue), so eta is noise. Such fits are FLAGGED, never persisted.
    ap.add_argument(
        "--min-grad-r2",
        type=float,
        default=0.9,
        help="Min velocity-gradient fit R^2 to persist (default 0.9). Set 0 to disable.",
    )
    args = ap.parse_args()

    from database.connection import session_scope
    from database.repositories.metric_repo import MetricRepository
    from metrics.viscosity import ViscosityCalculator

    statuses = [s.strip() for s in args.status.split(",") if s.strip()]
    mode = "COMMIT" if args.commit else "DRY-RUN"
    print(f"[backfill_viscosity] mode={mode} statuses={statuses}\n")

    computed = persisted = skipped_no_data = skipped_no_visc = flagged = 0
    with session_scope() as session:
        repo = MetricRepository(session)
        calc = ViscosityCalculator()
        rows = _eligible(session, exp_id=args.exp_id, statuses=statuses, limit=args.limit)
        print(f"[backfill_viscosity] eligible (no viscosity metric): {len(rows)}\n")

        for exp in rows:
            eid = exp.exp_id
            log_path, thermo = _best_viscosity_log(eid)
            if not thermo:
                skipped_no_data += 1
                print(f"  SKIP  {eid[:38]:38s} (no completed viscosity data on disk)")
                continue

            result, err = _compute_viscosity(log_path, thermo)
            if result is None or result.viscosity_mPas is None:
                skipped_no_visc += 1
                reason = err or (result.error if result else "unknown")
                print(f"  SKIP  {eid[:38]:38s} ({reason})")
                continue

            v = result.viscosity_mPas
            gr2 = result.gradient_fit_r_squared
            if not (args.min_visc <= v <= args.max_visc):
                flagged += 1
                print(
                    f"  FLAG  {eid[:38]:38s} = {v:.4g} mPa.s "
                    f"(outside [{args.min_visc:g},{args.max_visc:g}] — NOT persisted)"
                )
                continue
            if gr2 is None or gr2 < args.min_grad_r2:
                flagged += 1
                print(
                    f"  FLAG  {eid[:38]:38s} = {v:.4g} mPa.s "
                    f"(grad_R2={gr2 if gr2 is not None else float('nan'):.3f} "
                    f"< {args.min_grad_r2:g} — noisy velocity gradient, NOT persisted)"
                )
                continue

            computed += 1
            fr2 = result.flux_fit_r_squared
            gr2 = result.gradient_fit_r_squared
            print(
                f"  VISC  {eid[:38]:38s} = {v:9.3f} mPa.s "
                f"(flux_R2={fr2:.3f} grad_R2={gr2 if gr2 is not None else float('nan'):.3f} "
                f"n={result.n_thermo_samples})"
            )
            if args.commit:
                metric = calc.create_scalar_metric(result)
                if metric is None:
                    skipped_no_visc += 1
                    continue
                metric.exp_id = eid  # resolve experiment_id on save (same as normal path)
                repo.save(metric)
                persisted += 1

    print(
        f"\n[backfill_viscosity] done: computed(sane)={computed} persisted={persisted} "
        f"flagged={flagged} skipped(no data)={skipped_no_data} skipped(no viscosity)={skipped_no_visc}"
    )
    if not args.commit and computed:
        print(
            "[backfill_viscosity] DRY-RUN — re-run with --commit to persist to the metrics table."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
