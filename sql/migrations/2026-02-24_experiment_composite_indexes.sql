-- Migration: add composite indexes for experiment status/attempt queries
-- Date: 2026-02-24
--
-- PostgreSQL:
CREATE INDEX IF NOT EXISTS ix_experiments_expid_attempt
    ON experiments (exp_id, active_attempt_id);

CREATE INDEX IF NOT EXISTS ix_experiments_status_updated_at
    ON experiments (status, updated_at);
