-- Migration: add experiment attempt tracking fields for stale retry protection
-- Date: 2026-02-24
--
-- PostgreSQL:
ALTER TABLE experiments
    ADD COLUMN IF NOT EXISTS active_attempt_id VARCHAR(255);

ALTER TABLE experiments
    ADD COLUMN IF NOT EXISTS attempt_no INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS ix_experiments_active_attempt_id
    ON experiments (active_attempt_id);
