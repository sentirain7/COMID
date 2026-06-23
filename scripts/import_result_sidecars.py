#!/usr/bin/env python3
"""Apply experiment RESULT sidecars into the local DB (after ``git pull``).

Reads every sidecar under ``data/result_sidecars/`` and upserts it into this
machine's DB: the experiment row (by ``exp_id``), its molecule composition (by
``mol_id`` via the molecule library), and its metrics (via
``MetricRepository.upsert``, with array-curve paths re-localised to this
machine). The dashboard reads the DB, so after import the graphs reflect the
shared results — without ever shipping the binary SQLite DB or the large LAMMPS
raw outputs.

Typical flow on a second machine:
    git pull
    python scripts/import_result_sidecars.py

Idempotent — safe to re-run after every pull.

Usage:
    python scripts/import_result_sidecars.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def main() -> int:
    from database.connection import session_scope
    from features.common.result_sidecar import import_sidecars_to_db

    with session_scope() as session:
        counts = import_sidecars_to_db(session)
        session.commit()
    print(
        f"[import_result_sidecars] files={counts['files']} "
        f"experiments={counts['experiments']} metrics={counts['metrics']} "
        f"skipped={counts['skipped']}"
    )
    print("[import_result_sidecars] done — refresh the dashboard to see the graphs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
