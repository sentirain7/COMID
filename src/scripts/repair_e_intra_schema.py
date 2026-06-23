#!/usr/bin/env python3
"""One-shot SQLite e_intra schema repair + backfill tool (v01.02.17).

Fixes SQLite unique constraint mismatch where temperature_K was dropped.
PostgreSQL supports ALTER TABLE DROP/ADD CONSTRAINT; SQLite does not.

Usage:
    python -m scripts.repair_e_intra_schema --dry-run   # Diagnose current state
    python -m scripts.repair_e_intra_schema --apply     # Backup + repair + backfill

This script:
1. Diagnoses if the e_intra table's unique constraint includes temperature_K
2. If not, rebuilds the table with proper constraint
3. Backfills E_intra from completed single_molecule_vacuum experiments
"""

from __future__ import annotations

import argparse
import re
import shutil
import sqlite3

# Ensure src is in path for imports
import sys
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


class DiagnosticResult(NamedTuple):
    """Result of schema diagnosis."""

    db_path: Path
    db_exists: bool
    table_exists: bool
    row_count: int
    has_correct_unique: bool
    current_unique_cols: list[str]
    expected_unique_cols: list[str]
    backfill_candidates: int


def _get_db_path() -> Path:
    """Get SQLite database path from environment or default."""
    import os

    db_url = os.environ.get("DATABASE_URL", "")
    if db_url.startswith("sqlite:///"):
        return Path(db_url.replace("sqlite:///", ""))
    # Default fallback
    return _project_root / "asphalt_agent.db"


def _parse_unique_constraint(create_sql: str) -> list[str]:
    """Extract column names from UNIQUE constraint in CREATE TABLE SQL."""
    # Match: UNIQUE (col1, col2, col3)
    match = re.search(r"UNIQUE\s*\(\s*([^)]+)\s*\)", create_sql, re.IGNORECASE)
    if match:
        cols = match.group(1)
        return [c.strip().strip('"').strip("'") for c in cols.split(",")]
    return []


def diagnose(db_path: Path | None = None) -> DiagnosticResult:
    """Diagnose current e_intra schema state."""
    if db_path is None:
        db_path = _get_db_path()

    expected_cols = ["mol_id", "ff_name", "ff_version", "temperature_K"]
    result = DiagnosticResult(
        db_path=db_path,
        db_exists=db_path.exists(),
        table_exists=False,
        row_count=0,
        has_correct_unique=False,
        current_unique_cols=[],
        expected_unique_cols=expected_cols,
        backfill_candidates=0,
    )

    if not db_path.exists():
        return result

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()

        # Check table existence
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='e_intra'")
        if cursor.fetchone() is None:
            return result

        result = result._replace(table_exists=True)

        # Get row count
        cursor.execute("SELECT COUNT(*) FROM e_intra")
        result = result._replace(row_count=cursor.fetchone()[0])

        # Get CREATE TABLE SQL to parse unique constraint
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='e_intra'")
        row = cursor.fetchone()
        if row:
            create_sql = row[0]
            current_cols = _parse_unique_constraint(create_sql)
            result = result._replace(current_unique_cols=current_cols)
            result = result._replace(has_correct_unique=(set(current_cols) == set(expected_cols)))

        # Count backfill candidates (using direct columns, matching _backfill_from_experiments)
        try:
            cursor.execute("""
                SELECT COUNT(DISTINCT e.exp_id)
                FROM experiments e
                JOIN metrics m ON e.exp_id = m.exp_id
                WHERE e.study_type = 'single_molecule_vacuum'
                  AND e.status = 'completed'
                  AND e.additive_mol_id IS NOT NULL
                  AND m.metric_name = 'potential_energy'
                  AND m.value IS NOT NULL
            """)
            result = result._replace(backfill_candidates=cursor.fetchone()[0])
        except sqlite3.OperationalError:
            # metrics table might not exist
            pass

    finally:
        conn.close()

    return result


def _backup_database(db_path: Path) -> Path:
    """Create timestamped backup of database."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = (
        db_path.parent / f"{db_path.stem}.backup_e_intra_repair_{timestamp}{db_path.suffix}"
    )
    shutil.copy2(db_path, backup_path)
    return backup_path


def _rebuild_e_intra_table(conn: sqlite3.Connection) -> int:
    """Rebuild e_intra table with correct unique constraint.

    Returns:
        Number of rows migrated.
    """
    cursor = conn.cursor()

    # Check if old table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='e_intra'")
    if cursor.fetchone() is None:
        # Table doesn't exist, create it fresh (PR 2: 5-column UC with method)
        cursor.execute("""
            CREATE TABLE e_intra (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                molecule_id INTEGER,
                mol_id VARCHAR(100) NOT NULL,
                ff_name VARCHAR(50) NOT NULL,
                ff_version VARCHAR(20) NOT NULL,
                temperature_K REAL NOT NULL DEFAULT 298.0,
                method VARCHAR(50) NOT NULL DEFAULT 'single_molecule_vacuum',
                e_intra REAL NOT NULL,
                e_components JSON,
                minimization_steps INTEGER,
                source_exp_id VARCHAR(100),
                averaging_window_ps REAL,
                n_samples INTEGER,
                created_at DATETIME,
                updated_at DATETIME,
                CONSTRAINT uq_e_intra_method UNIQUE
                    (mol_id, ff_name, ff_version, temperature_K, method),
                FOREIGN KEY (molecule_id) REFERENCES molecules(id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_e_intra_molecule_id ON e_intra(molecule_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_e_intra_mol_id ON e_intra(mol_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_e_intra_ff_name ON e_intra(ff_name)")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS ix_e_intra_temperature_K ON e_intra(temperature_K)"
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_e_intra_method ON e_intra(method)")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS ix_e_intra_lookup "
            "ON e_intra(mol_id, ff_name, ff_version, temperature_K, method)"
        )
        return 0

    # Detect whether the existing table already has the method column.
    cursor.execute("PRAGMA table_info(e_intra)")
    has_method = any(row[1] == "method" for row in cursor.fetchall())

    # Create new table with correct schema (PR 2: 5-column UC).
    cursor.execute("DROP TABLE IF EXISTS e_intra_new")
    cursor.execute("""
        CREATE TABLE e_intra_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            molecule_id INTEGER,
            mol_id VARCHAR(100) NOT NULL,
            ff_name VARCHAR(50) NOT NULL,
            ff_version VARCHAR(20) NOT NULL,
            temperature_K REAL NOT NULL DEFAULT 298.0,
            method VARCHAR(50) NOT NULL DEFAULT 'single_molecule_vacuum',
            e_intra REAL NOT NULL,
            e_components JSON,
            minimization_steps INTEGER,
            source_exp_id VARCHAR(100),
            averaging_window_ps REAL,
            n_samples INTEGER,
            created_at DATETIME,
            updated_at DATETIME,
            CONSTRAINT uq_e_intra_method UNIQUE
                (mol_id, ff_name, ff_version, temperature_K, method),
            FOREIGN KEY (molecule_id) REFERENCES molecules(id)
        )
    """)

    # Migrate data (handle duplicates by keeping latest per 5-tuple)
    if has_method:
        cursor.execute("""
            INSERT INTO e_intra_new (
                id, molecule_id, mol_id, ff_name, ff_version, temperature_K,
                method, e_intra, e_components, minimization_steps, source_exp_id,
                averaging_window_ps, n_samples, created_at, updated_at
            )
            SELECT
                id, molecule_id, mol_id, ff_name, ff_version, temperature_K,
                COALESCE(method, 'single_molecule_vacuum'),
                e_intra, e_components, minimization_steps, source_exp_id,
                averaging_window_ps, n_samples, created_at, updated_at
            FROM e_intra
            GROUP BY mol_id, ff_name, ff_version, temperature_K, method
            HAVING id = MAX(id)
        """)
    else:
        cursor.execute("""
            INSERT INTO e_intra_new (
                id, molecule_id, mol_id, ff_name, ff_version, temperature_K,
                method, e_intra, e_components, minimization_steps, source_exp_id,
                averaging_window_ps, n_samples, created_at, updated_at
            )
            SELECT
                id, molecule_id, mol_id, ff_name, ff_version, temperature_K,
                'single_molecule_vacuum',
                e_intra, e_components, minimization_steps, source_exp_id,
                averaging_window_ps, n_samples, created_at, updated_at
            FROM e_intra
            GROUP BY mol_id, ff_name, ff_version, temperature_K
            HAVING id = MAX(id)
        """)
    migrated = cursor.rowcount

    # Swap tables
    cursor.execute("DROP TABLE e_intra")
    cursor.execute("ALTER TABLE e_intra_new RENAME TO e_intra")

    # Recreate indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_e_intra_molecule_id ON e_intra(molecule_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_e_intra_mol_id ON e_intra(mol_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_e_intra_ff_name ON e_intra(ff_name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_e_intra_temperature_K ON e_intra(temperature_K)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_e_intra_method ON e_intra(method)")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_e_intra_lookup "
        "ON e_intra(mol_id, ff_name, ff_version, temperature_K, method)"
    )

    return migrated


def _backfill_from_experiments(conn: sqlite3.Connection) -> int:
    """Backfill E_intra from completed single_molecule_vacuum experiments.

    Uses experiments table direct columns (additive_mol_id, temperature_K,
    force_field_name, force_field_version) instead of parsing metadata_json
    for improved reliability.

    Returns:
        Number of rows backfilled.
    """
    from contracts.policies.forcefield import get_ff_display_label, get_ff_version

    cursor = conn.cursor()

    # SSOT FF defaults
    default_ff_name = get_ff_display_label("bulk_ff_gaff2")
    default_ff_version = get_ff_version("bulk_ff_gaff2")

    # Get completed single_molecule_vacuum experiments using direct columns
    # This is more robust than parsing metadata_json
    cursor.execute("""
        SELECT DISTINCT
            e.exp_id,
            e.additive_mol_id,
            e.temperature_K,
            e.force_field_name,
            e.force_field_version,
            m.value as pe_value
        FROM experiments e
        JOIN metrics m ON e.exp_id = m.exp_id
        WHERE e.study_type = 'single_molecule_vacuum'
          AND e.status = 'completed'
          AND e.additive_mol_id IS NOT NULL
          AND m.metric_name = 'potential_energy'
          AND m.value IS NOT NULL
    """)
    experiments = cursor.fetchall()

    if not experiments:
        return 0

    now = datetime.now().isoformat()

    backfilled = 0
    for exp_id, mol_id, temp_k, ff_name_exp, ff_version_exp, pe_value in experiments:
        try:
            # Use experiment's FF values or fall back to SSOT defaults
            ff_name = ff_name_exp if ff_name_exp else default_ff_name
            ff_version = ff_version_exp if ff_version_exp else default_ff_version
            temperature_K = temp_k if temp_k is not None else 298.0

            # Check if already exists
            cursor.execute(
                """
                SELECT id FROM e_intra
                WHERE mol_id = ? AND ff_name = ? AND ff_version = ? AND temperature_K = ?
            """,
                (mol_id, ff_name, ff_version, temperature_K),
            )

            if cursor.fetchone() is not None:
                continue  # Skip existing

            # Get molecule_id for FK
            cursor.execute("SELECT id FROM molecules WHERE mol_id = ?", (mol_id,))
            mol_row = cursor.fetchone()
            molecule_id = mol_row[0] if mol_row else None

            # Insert
            cursor.execute(
                """
                INSERT INTO e_intra (
                    molecule_id, mol_id, ff_name, ff_version, temperature_K,
                    e_intra, source_exp_id, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    molecule_id,
                    mol_id,
                    ff_name,
                    ff_version,
                    temperature_K,
                    pe_value,
                    exp_id,
                    now,
                    now,
                ),
            )
            backfilled += 1

        except (TypeError, ValueError):
            continue

    return backfilled


def apply_repair(db_path: Path | None = None) -> dict:
    """Apply schema repair and backfill.

    Returns:
        Dict with repair statistics.
    """
    if db_path is None:
        db_path = _get_db_path()

    result = {
        "db_path": str(db_path),
        "backup_path": None,
        "table_rebuilt": False,
        "rows_migrated": 0,
        "rows_backfilled": 0,
        "error": None,
    }

    if not db_path.exists():
        result["error"] = f"Database not found: {db_path}"
        return result

    diagnostic = diagnose(db_path)

    # Backup first
    try:
        backup_path = _backup_database(db_path)
        result["backup_path"] = str(backup_path)
    except Exception as e:
        result["error"] = f"Backup failed: {e}"
        return result

    # Connect and repair
    conn = sqlite3.connect(str(db_path))
    try:
        # Rebuild table only when the live SQLite constraint is still legacy.
        # Backfill remains useful after a previous schema-only repair.
        if diagnostic.has_correct_unique:
            result["table_rebuilt"] = False
        else:
            rows_migrated = _rebuild_e_intra_table(conn)
            result["table_rebuilt"] = True
            result["rows_migrated"] = rows_migrated

        # Backfill from experiments
        rows_backfilled = _backfill_from_experiments(conn)
        result["rows_backfilled"] = rows_backfilled

        conn.commit()

    except Exception as e:
        conn.rollback()
        result["error"] = f"Repair failed: {e}"

    finally:
        conn.close()

    return result


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="SQLite e_intra schema repair tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m scripts.repair_e_intra_schema --dry-run
    python -m scripts.repair_e_intra_schema --apply
    python -m scripts.repair_e_intra_schema --dry-run --db /path/to/db.sqlite
""",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Diagnose schema without making changes",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply repair (creates backup first)",
    )
    parser.add_argument(
        "--db",
        type=Path,
        help="Path to SQLite database (default: from DATABASE_URL or asphalt_agent.db)",
    )

    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        parser.print_help()
        return

    db_path = args.db

    if args.dry_run:
        diag = diagnose(db_path)
        print("=" * 60)
        print("E_intra Schema Diagnostic Report")
        print("=" * 60)
        print(f"Database path: {diag.db_path}")
        print(f"Database exists: {diag.db_exists}")
        print(f"Table exists: {diag.table_exists}")
        print(f"Current row count: {diag.row_count}")
        print(f"Expected unique columns: {diag.expected_unique_cols}")
        print(f"Current unique columns: {diag.current_unique_cols}")
        print(f"Has correct unique constraint: {diag.has_correct_unique}")
        print(f"Backfill candidates (completed experiments): {diag.backfill_candidates}")
        print("=" * 60)

        if diag.has_correct_unique:
            print("STATUS: Schema is correct. No repair needed.")
        else:
            print("STATUS: Schema needs repair.")
            print("Run with --apply to fix.")

    if args.apply:
        print("Applying repair...")
        result = apply_repair(db_path)

        print("=" * 60)
        print("E_intra Schema Repair Report")
        print("=" * 60)
        print(f"Database path: {result['db_path']}")
        print(f"Backup path: {result['backup_path']}")
        print(f"Table rebuilt: {result['table_rebuilt']}")
        print(f"Rows migrated: {result['rows_migrated']}")
        print(f"Rows backfilled: {result['rows_backfilled']}")

        if result["error"]:
            print(f"ERROR: {result['error']}")
            sys.exit(1)
        else:
            print("=" * 60)
            print("SUCCESS: Schema repair completed.")


if __name__ == "__main__":
    main()
