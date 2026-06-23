-- Phase 2: metric provenance columns
-- Adds layer/interface provenance to canonical metric rows.

ALTER TABLE metrics ADD COLUMN IF NOT EXISTS layer_index INTEGER;
ALTER TABLE metrics ADD COLUMN IF NOT EXISTS interface_index INTEGER;
