-- Migration: Add study_type column to experiments table
-- Enables proper filtering between bulk, layer, single_molecule_vacuum experiments

ALTER TABLE experiments ADD COLUMN IF NOT EXISTS study_type VARCHAR(50) NOT NULL DEFAULT 'bulk';
CREATE INDEX IF NOT EXISTS ix_experiments_study_type ON experiments(study_type);

-- Backfill existing layered experiments (have lineage rows)
UPDATE experiments SET study_type = 'layer_bulkff'
WHERE exp_id IN (SELECT DISTINCT exp_id FROM layered_experiment_sources);
