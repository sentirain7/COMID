#!/usr/bin/env python3
"""Idempotent admin migration: bulk_ff → bulk_ff_gaff2.

Migrates persisted OPLS-AA identifiers to GAFF2 across all relevant tables.
Run this script BEFORE deploying the OPLS-removal code changes.

Usage:
    python scripts/migrate_bulk_ff_to_gaff2.py                  # execute migration
    python scripts/migrate_bulk_ff_to_gaff2.py --dry-run         # preview only
    python scripts/migrate_bulk_ff_to_gaff2.py --verify          # verify zero stale rows
"""

from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import create_engine, text


MIGRATIONS: list[tuple[str, str, str]] = [
    # (table, column, condition)
    ("experiments", "ff_type", "ff_type = 'bulk_ff'"),
    ("amorphous_cells", "ff_type", "ff_type = 'bulk_ff'"),
    ("metrics", "namespace", "namespace = 'bulk_ff'"),
    ("additive_usage_rule", "ff_type", "ff_type = 'bulk_ff'"),
]

LITERATURE_MIGRATION = (
    "literature_evidence",
    "force_field",
    "force_field LIKE '%OPLS%'",
)


def get_engine(database_url: str):
    """Create a SQLAlchemy engine from the given URL."""
    return create_engine(database_url)


def count_stale(engine, table: str, condition: str) -> int:
    """Count rows matching the stale condition."""
    with engine.connect() as conn:
        result = conn.execute(text(f"SELECT COUNT(*) FROM {table} WHERE {condition}"))  # noqa: S608
        return result.scalar() or 0


def migrate(engine, *, dry_run: bool = False) -> dict[str, int]:
    """Run all migrations. Returns dict of table→rows_affected."""
    results: dict[str, int] = {}

    for table, column, condition in MIGRATIONS:
        count = count_stale(engine, table, condition)
        results[table] = count
        if count > 0 and not dry_run:
            with engine.begin() as conn:
                conn.execute(
                    text(f"UPDATE {table} SET {column} = 'bulk_ff_gaff2' WHERE {condition}")  # noqa: S608
                )
            print(f"  ✓ {table}.{column}: {count} rows updated")
        elif count > 0:
            print(f"  [dry-run] {table}.{column}: {count} rows would be updated")
        else:
            print(f"  - {table}.{column}: 0 rows (already clean)")

    # Literature evidence: OPLS → GAFF2 (different pattern)
    lit_table, lit_col, lit_cond = LITERATURE_MIGRATION
    lit_count = count_stale(engine, lit_table, lit_cond)
    results[lit_table] = lit_count
    if lit_count > 0 and not dry_run:
        with engine.begin() as conn:
            conn.execute(
                text(f"UPDATE {lit_table} SET {lit_col} = 'GAFF2' WHERE {lit_cond}")  # noqa: S608
            )
        print(f"  ✓ {lit_table}.{lit_col}: {lit_count} rows updated")
    elif lit_count > 0:
        print(f"  [dry-run] {lit_table}.{lit_col}: {lit_count} rows would be updated")
    else:
        print(f"  - {lit_table}.{lit_col}: 0 rows (already clean)")

    return results


def verify(engine) -> bool:
    """Verify zero stale rows remain. Returns True if clean."""
    clean = True
    for table, _column, condition in MIGRATIONS:
        count = count_stale(engine, table, condition)
        status = "✓ clean" if count == 0 else f"✗ {count} stale rows!"
        print(f"  {table}: {status}")
        if count > 0:
            clean = False

    lit_table, _lit_col, lit_cond = LITERATURE_MIGRATION
    lit_count = count_stale(engine, lit_table, lit_cond)
    status = "✓ clean" if lit_count == 0 else f"✗ {lit_count} stale rows!"
    print(f"  {lit_table}: {status}")
    if lit_count > 0:
        clean = False

    return clean


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate bulk_ff → bulk_ff_gaff2 across all DB tables."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without applying them.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify that no stale bulk_ff rows remain.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Database URL (defaults to DATABASE_URL env var).",
    )
    args = parser.parse_args()

    database_url = args.database_url or os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: No database URL. Set DATABASE_URL or use --database-url.", file=sys.stderr)
        return 1

    engine = get_engine(database_url)

    if args.verify:
        print("Verifying migration status...")
        clean = verify(engine)
        return 0 if clean else 1

    mode = "DRY-RUN" if args.dry_run else "EXECUTING"
    print(f"Migration: bulk_ff → bulk_ff_gaff2 [{mode}]")
    print()
    migrate(engine, dry_run=args.dry_run)
    print()

    if not args.dry_run:
        print("Verifying...")
        clean = verify(engine)
        if clean:
            print("\nMigration complete. All tables clean.")
        else:
            print("\nWARNING: Some stale rows remain!", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
