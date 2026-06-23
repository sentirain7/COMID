#!/usr/bin/env python3
"""Export experiment RESULTS to git-tracked sidecars (backfill / repair).

Writes one JSON sidecar per completed experiment under ``data/result_sidecars/``
(metadata + scalar metrics + array-curve refs). Use this once to backfill
experiments completed before write-through existed; afterwards completion keeps
sidecars in sync automatically. The large LAMMPS raw outputs (``database/``) are
NOT exported — only the distilled, graph-driving result.

Then commit the sidecars + the small ``data/arrays/*.parquet`` curves and push;
another machine runs ``import_result_sidecars.py`` after pulling.

Usage:
    python scripts/export_result_sidecars.py                  # completed only
    python scripts/export_result_sidecars.py --statuses completed,failed
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def main() -> int:
    ap = argparse.ArgumentParser(description="Export experiment result sidecars.")
    ap.add_argument(
        "--statuses",
        default="completed",
        help="Comma-separated experiment statuses to export (default: completed).",
    )
    args = ap.parse_args()
    statuses = tuple(s.strip() for s in args.statuses.split(",") if s.strip())

    from database.connection import session_scope
    from features.common.result_sidecar import export_db_to_sidecars

    with session_scope() as session:
        counts = export_db_to_sidecars(session, statuses=statuses)
    print(
        f"[export_result_sidecars] statuses={statuses} "
        f"experiments={counts['experiments']} sidecars_written={counts['sidecars']}"
    )
    print(
        "[export_result_sidecars] now: git add data/result_sidecars data/arrays/**/*.parquet "
        "&& git commit && git push"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
