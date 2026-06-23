"""Regression tests for SQLite e_intra schema repair/backfill."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.repair_e_intra_schema import apply_repair, diagnose


def _create_common_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE molecules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mol_id VARCHAR(100) NOT NULL UNIQUE
        );
        CREATE TABLE experiments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exp_id VARCHAR(100) NOT NULL UNIQUE,
            study_type VARCHAR(100),
            status VARCHAR(50),
            additive_mol_id VARCHAR(100),
            temperature_K FLOAT,
            force_field_name VARCHAR(50),
            force_field_version VARCHAR(20)
        );
        CREATE TABLE metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exp_id VARCHAR(100) NOT NULL,
            metric_name VARCHAR(100) NOT NULL,
            value FLOAT
        );
        INSERT INTO molecules (mol_id) VALUES ('mol_001');
        INSERT INTO experiments (
            exp_id, study_type, status, additive_mol_id, temperature_K,
            force_field_name, force_field_version
        ) VALUES
            ('exp_213', 'single_molecule_vacuum', 'completed', 'mol_001', 213.0, 'GAFF2', '2.11'),
            ('exp_233', 'single_molecule_vacuum', 'completed', 'mol_001', 233.0, 'GAFF2', '2.11');
        INSERT INTO metrics (exp_id, metric_name, value) VALUES
            ('exp_213', 'potential_energy', -100.0),
            ('exp_233', 'potential_energy', -110.0);
        """
    )


def _create_legacy_e_intra(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE e_intra (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            molecule_id INTEGER,
            mol_id VARCHAR(100) NOT NULL,
            ff_name VARCHAR(50) NOT NULL,
            ff_version VARCHAR(20) NOT NULL,
            temperature_K FLOAT NOT NULL DEFAULT 298.0,
            e_intra FLOAT NOT NULL,
            e_components JSON,
            minimization_steps INTEGER,
            source_exp_id VARCHAR(100),
            averaging_window_ps FLOAT,
            n_samples INTEGER,
            created_at DATETIME,
            updated_at DATETIME,
            UNIQUE (mol_id, ff_name, ff_version)
        );
        CREATE INDEX ix_e_intra_molecule_id ON e_intra(molecule_id);
        INSERT INTO e_intra (
            id, molecule_id, mol_id, ff_name, ff_version, temperature_K,
            e_intra, source_exp_id
        ) VALUES (7, 1, 'mol_001', 'GAFF2', '2.11', 213.0, -100.0, 'exp_213');
        """
    )


def _create_temperature_aware_e_intra(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE e_intra (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            molecule_id INTEGER,
            mol_id VARCHAR(100) NOT NULL,
            ff_name VARCHAR(50) NOT NULL,
            ff_version VARCHAR(20) NOT NULL,
            temperature_K FLOAT NOT NULL DEFAULT 298.0,
            e_intra FLOAT NOT NULL,
            e_components JSON,
            minimization_steps INTEGER,
            source_exp_id VARCHAR(100),
            averaging_window_ps FLOAT,
            n_samples INTEGER,
            created_at DATETIME,
            updated_at DATETIME,
            UNIQUE (mol_id, ff_name, ff_version, temperature_K)
        );
        CREATE INDEX ix_e_intra_molecule_id ON e_intra(molecule_id);
        """
    )


def test_apply_repair_rebuilds_legacy_unique_and_backfills(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    _create_common_tables(conn)
    _create_legacy_e_intra(conn)
    conn.commit()
    conn.close()

    before = diagnose(db_path)
    assert before.has_correct_unique is False
    assert before.backfill_candidates == 2

    result = apply_repair(db_path)

    assert result["error"] is None
    assert result["table_rebuilt"] is True
    assert result["rows_migrated"] == 1
    assert result["rows_backfilled"] == 1

    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM e_intra").fetchone()[0] == 2
        rows = conn.execute(
            "SELECT id, temperature_K, e_intra FROM e_intra ORDER BY temperature_K"
        ).fetchall()
        assert rows == [(7, 213.0, -100.0), (8, 233.0, -110.0)]
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='e_intra'"
        ).fetchone()[0]
        assert "temperature_K" in sql
        # e_intra UNIQUE now includes the method column (uq_e_intra_method).
        # Normalize whitespace — the constraint spans multiple lines in the DDL.
        sql_normalized = " ".join(sql.split())
        assert (
            "CONSTRAINT uq_e_intra_method UNIQUE "
            "(mol_id, ff_name, ff_version, temperature_K, method)"
        ) in sql_normalized
        index_names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='e_intra'"
            )
        }
        assert "ix_e_intra_molecule_id" in index_names
    finally:
        conn.close()


def test_apply_repair_skips_rebuild_when_schema_is_already_correct(tmp_path: Path) -> None:
    db_path = tmp_path / "current.db"
    conn = sqlite3.connect(db_path)
    _create_common_tables(conn)
    _create_temperature_aware_e_intra(conn)
    conn.commit()
    conn.close()

    before = diagnose(db_path)
    assert before.has_correct_unique is True

    result = apply_repair(db_path)

    assert result["error"] is None
    assert result["table_rebuilt"] is False
    assert result["rows_migrated"] == 0
    assert result["rows_backfilled"] == 2

    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM e_intra").fetchone()[0] == 2
    finally:
        conn.close()
