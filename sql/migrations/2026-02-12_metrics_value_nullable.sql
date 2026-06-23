-- Migration: allow NULL metrics.value for array-only metrics (rdf_curve, msd_curve, ...)
-- Date: 2026-02-12
--
-- PostgreSQL:
ALTER TABLE metrics
    ALTER COLUMN value DROP NOT NULL;

