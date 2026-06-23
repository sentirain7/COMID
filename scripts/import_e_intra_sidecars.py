#!/usr/bin/env python3
"""Import git-tracked E_intra sidecars into the local DB.

After ``git pull`` brings the per-molecule sidecars (``data/forcefield_artifacts/
e_intra/*.json``) to disk, this applies their values into the local ``e_intra``
table so the frontend coverage matrix reflects the computed temperatures.
Idempotent on the 5-column unique key; resolves ``mol_id`` → local
``molecule_id`` via the molecule library.

Usage:
    python scripts/import_e_intra_sidecars.py            # apply (default)
    python scripts/import_e_intra_sidecars.py --dry-run  # report only
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from common.logging import get_logger  # noqa: E402
from database.connection import session_scope  # noqa: E402
from features.common.e_intra_sidecar import import_sidecars_to_db, iter_sidecar_files  # noqa: E402

logger = get_logger("scripts.import_e_intra_sidecars")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report sidecar/entry counts without writing to the DB.",
    )
    args = parser.parse_args()

    if args.dry_run:
        files = list(iter_sidecar_files())
        print(f"[dry-run] {len(files)} sidecar file(s) found; no DB writes.")
        for p in files:
            print(f"  - {p.name}")
        return 0

    with session_scope() as session:
        result = import_sidecars_to_db(session)
        session.commit()

    print(
        "Imported E_intra sidecars: "
        f"{result['files']} file(s), {result['entries']} entr(ies), "
        f"{result['upserted']} upserted, {result['skipped']} skipped."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
