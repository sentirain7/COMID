#!/usr/bin/env python3
"""
One-shot integrity repair for inconsistent experiment lifecycle states.

Repairs common corruption:
- status='running' while completed_at is already set
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def main() -> int:
    db_path = Path("asphalt_agent.db")
    if not db_path.exists():
        print("Database not found:", db_path)
        return 1

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rows = cur.execute(
        """
        SELECT exp_id, status, completed_at
        FROM experiments
        WHERE status = 'running' AND completed_at IS NOT NULL
        """
    ).fetchall()

    if not rows:
        print("No inconsistent rows found.")
        conn.close()
        return 0

    exp_ids = [r["exp_id"] for r in rows]
    print(f"Found {len(exp_ids)} inconsistent rows.")
    for exp_id in exp_ids:
        print(" -", exp_id)

    cur.execute(
        """
        UPDATE experiments
        SET status = 'completed', updated_at = CURRENT_TIMESTAMP
        WHERE status = 'running' AND completed_at IS NOT NULL
        """
    )
    conn.commit()
    conn.close()

    print(f"Updated {len(exp_ids)} rows to status='completed'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
