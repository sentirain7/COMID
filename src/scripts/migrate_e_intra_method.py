#!/usr/bin/env python3
"""SQLite e_intra schema migration: 4-column UC → 5-column UC with method.

Adds the ``method`` column to ``e_intra`` and rebuilds the unique constraint
so that Method 1 (``single_molecule_vacuum``), Method 1a
(``single_molecule_vacuum_adaptive_cutoff``), and Method 2
(``single_molecule_periodic``) can co-exist for the same
``(mol_id, ff_name, ff_version, temperature_K)`` tuple without row aliasing.

Usage:
    python -m scripts.migrate_e_intra_method --dry-run   # Diagnose current state
    python -m scripts.migrate_e_intra_method --apply     # Backup + rebuild

Idempotent: re-running on an already-migrated DB is a no-op.

Pattern adapted from ``src/scripts/repair_e_intra_schema.py`` (v01.02.17).
PostgreSQL deployments should use a native ``ALTER TABLE ADD COLUMN`` +
``DROP CONSTRAINT`` + ``ADD CONSTRAINT`` migration instead of this script;
this tool is SQLite-specific.

See ``docs/architecture/ced-method-redesign-analysis.md`` (Workstream 2).
"""

from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


EXPECTED_UNIQUE_COLS = ["mol_id", "ff_name", "ff_version", "temperature_K", "method"]
DEFAULT_METHOD = "single_molecule_vacuum"
LEGACY_METHOD = "single_molecule_vacuum_extended_cutoff"
CANONICAL_METHOD = "single_molecule_vacuum_adaptive_cutoff"


class DiagnosticResult(NamedTuple):
    db_path: Path
    db_exists: bool
    table_exists: bool
    row_count: int
    has_method_column: bool
    has_correct_unique: bool
    current_unique_cols: list[str]
    expected_unique_cols: list[str]


def _get_db_path() -> Path:
    """Resolve SQLite DB path from DATABASE_URL or fall back to project default."""
    import os

    db_url = os.environ.get("DATABASE_URL", "")
    if db_url.startswith("sqlite:///"):
        return Path(db_url.replace("sqlite:///", ""))
    return _project_root / "asphalt_agent.db"


def _parse_unique_constraint(create_sql: str) -> list[str]:
    """Extract column names from the UNIQUE constraint in a CREATE TABLE SQL."""
    match = re.search(r"UNIQUE\s*\(\s*([^)]+)\s*\)", create_sql, re.IGNORECASE)
    if match:
        cols = match.group(1)
        return [c.strip().strip('"').strip("'") for c in cols.split(",")]
    return []


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def diagnose(db_path: Path | None = None) -> DiagnosticResult:
    if db_path is None:
        db_path = _get_db_path()

    if not db_path.exists():
        return DiagnosticResult(
            db_path=db_path,
            db_exists=False,
            table_exists=False,
            row_count=0,
            has_method_column=False,
            has_correct_unique=False,
            current_unique_cols=[],
            expected_unique_cols=EXPECTED_UNIQUE_COLS,
        )

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' AND name='e_intra'"
        )
        row = cur.fetchone()
        if row is None:
            return DiagnosticResult(
                db_path=db_path,
                db_exists=True,
                table_exists=False,
                row_count=0,
                has_method_column=False,
                has_correct_unique=False,
                current_unique_cols=[],
                expected_unique_cols=EXPECTED_UNIQUE_COLS,
            )
        create_sql = row[1] or ""
        cols = _table_columns(conn, "e_intra")
        unique_cols = _parse_unique_constraint(create_sql)
        row_count = conn.execute("SELECT COUNT(*) FROM e_intra").fetchone()[0]
        return DiagnosticResult(
            db_path=db_path,
            db_exists=True,
            table_exists=True,
            row_count=int(row_count),
            has_method_column="method" in cols,
            has_correct_unique=unique_cols == EXPECTED_UNIQUE_COLS,
            current_unique_cols=unique_cols,
            expected_unique_cols=EXPECTED_UNIQUE_COLS,
        )
    finally:
        conn.close()


def _backup(db_path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = db_path.with_name(f"{db_path.stem}.backup_{timestamp}{db_path.suffix}")
    shutil.copy2(db_path, backup_path)
    return backup_path


def _rebuild_table(conn: sqlite3.Connection) -> None:
    """Rebuild e_intra with method column and 5-column UC, preserving rows."""
    cols = _table_columns(conn, "e_intra")
    has_method = "method" in cols

    conn.execute(
        """
        CREATE TABLE e_intra_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            molecule_id INTEGER,
            mol_id VARCHAR(100) NOT NULL,
            ff_name VARCHAR(50) NOT NULL,
            ff_version VARCHAR(20) NOT NULL,
            temperature_K FLOAT NOT NULL DEFAULT 298.0,
            method VARCHAR(50) NOT NULL DEFAULT 'single_molecule_vacuum',
            e_intra FLOAT NOT NULL,
            e_components JSON,
            minimization_steps INTEGER,
            source_exp_id VARCHAR(100),
            averaging_window_ps FLOAT,
            n_samples INTEGER,
            created_at DATETIME,
            updated_at DATETIME,
            FOREIGN KEY (molecule_id) REFERENCES molecules(id),
            CONSTRAINT uq_e_intra_method UNIQUE
                (mol_id, ff_name, ff_version, temperature_K, method)
        )
        """
    )

    if has_method:
        conn.execute(
            """
            INSERT INTO e_intra_new (
                id, molecule_id, mol_id, ff_name, ff_version, temperature_K,
                method, e_intra, e_components, minimization_steps,
                source_exp_id, averaging_window_ps, n_samples,
                created_at, updated_at
            )
            SELECT
                id, molecule_id, mol_id, ff_name, ff_version, temperature_K,
                CASE
                    WHEN method = ? THEN ?
                    ELSE COALESCE(method, ?)
                END,
                e_intra, e_components, minimization_steps,
                source_exp_id, averaging_window_ps, n_samples,
                created_at, updated_at
            FROM e_intra
            """,
            (LEGACY_METHOD, CANONICAL_METHOD, DEFAULT_METHOD),
        )
    else:
        conn.execute(
            """
            INSERT INTO e_intra_new (
                id, molecule_id, mol_id, ff_name, ff_version, temperature_K,
                method, e_intra, e_components, minimization_steps,
                source_exp_id, averaging_window_ps, n_samples,
                created_at, updated_at
            )
            SELECT
                id, molecule_id, mol_id, ff_name, ff_version, temperature_K,
                ?, e_intra, e_components, minimization_steps,
                source_exp_id, averaging_window_ps, n_samples,
                created_at, updated_at
            FROM e_intra
            """,
            (DEFAULT_METHOD,),
        )

    conn.execute("DROP TABLE e_intra")
    conn.execute("ALTER TABLE e_intra_new RENAME TO e_intra")

    # Recreate indexes (5-column lookup + per-column secondary indexes).
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_e_intra_lookup "
        "ON e_intra (mol_id, ff_name, ff_version, temperature_K, method)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS ix_e_intra_molecule_id ON e_intra(molecule_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_e_intra_mol_id ON e_intra(mol_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_e_intra_ff_name ON e_intra(ff_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_e_intra_temperature_K ON e_intra(temperature_K)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_e_intra_method ON e_intra(method)")


def apply(db_path: Path | None = None, *, do_backup: bool = True) -> dict:
    if db_path is None:
        db_path = _get_db_path()

    diag = diagnose(db_path)
    result: dict = {
        "db_path": str(db_path),
        "before": {
            "table_exists": diag.table_exists,
            "row_count": diag.row_count,
            "has_method_column": diag.has_method_column,
            "has_correct_unique": diag.has_correct_unique,
            "current_unique_cols": diag.current_unique_cols,
        },
        "applied": False,
        "skipped_reason": None,
        "backup_path": None,
    }

    if not diag.db_exists:
        result["skipped_reason"] = "DB file does not exist (will be created on first use)"
        return result
    if not diag.table_exists:
        result["skipped_reason"] = "e_intra table does not exist (will be created by ORM metadata)"
        return result
    if diag.has_method_column and diag.has_correct_unique:
        result["skipped_reason"] = "Already migrated (idempotent no-op)"
        return result

    if do_backup:
        backup_path = _backup(db_path)
        result["backup_path"] = str(backup_path)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("BEGIN")
        _rebuild_table(conn)
        conn.commit()
        result["applied"] = True
    except Exception as exc:
        conn.rollback()
        result["error"] = repr(exc)
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.close()

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="Diagnose without writing")
    parser.add_argument("--apply", action="store_true", help="Apply migration")
    parser.add_argument("--no-backup", action="store_true", help="Skip backup before apply")
    parser.add_argument("--db-path", type=Path, help="Override DB path")
    args = parser.parse_args()

    db_path = args.db_path or _get_db_path()

    if args.dry_run or not args.apply:
        diag = diagnose(db_path)
        print(f"DB: {diag.db_path}")
        print(f"  exists: {diag.db_exists}")
        print(f"  e_intra table: {diag.table_exists}")
        if diag.table_exists:
            print(f"  rows: {diag.row_count}")
            print(f"  has method column: {diag.has_method_column}")
            print(f"  current UC: {diag.current_unique_cols}")
            print(f"  expected UC: {diag.expected_unique_cols}")
            print(f"  needs migration: {not diag.has_correct_unique}")
        return 0

    result = apply(db_path, do_backup=not args.no_backup)
    print(result)
    return 0 if result.get("applied") or result.get("skipped_reason") else 1


if __name__ == "__main__":
    sys.exit(main())
