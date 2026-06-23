#!/usr/bin/env python3
"""Rebuild E_intra sidecars from the local DB (backfill / repair).

Normal computation already write-throughs each E_intra into its sidecar.  This
one-shot reconciliation regenerates all sidecars from the DB ``e_intra`` table
— use it to export values computed *before* write-through existed, or to repair
drift.  After running, ``git status`` shows the changed sidecars to commit.

Usage:
    python scripts/export_e_intra_sidecars.py            # rebuild (default)
    python scripts/export_e_intra_sidecars.py --dry-run  # report only
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from common.logging import get_logger  # noqa: E402
from database.connection import session_scope  # noqa: E402
from features.common.e_intra_sidecar import export_db_to_sidecars  # noqa: E402

logger = get_logger("scripts.export_e_intra_sidecars")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report DB row / molecule counts without writing sidecars.",
    )
    args = parser.parse_args()

    with session_scope() as session:
        if args.dry_run:
            from database.models import EIntraModel

            rows = session.query(EIntraModel.mol_id).all()
            mols = {r.mol_id for r in rows if r.mol_id}
            print(f"[dry-run] {len(rows)} e_intra row(s) across {len(mols)} molecule(s); no writes.")
            return 0
        result = export_db_to_sidecars(session)

    print(
        "Rebuilt E_intra sidecars: "
        f"{result['rows']} row(s) → {result['sidecars']} sidecar(s) "
        f"({result['molecules']} molecule(s))."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
