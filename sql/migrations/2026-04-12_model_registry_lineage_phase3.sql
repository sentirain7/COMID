-- Phase 3: ML model registry lineage and feature contract metadata

ALTER TABLE ml_model_versions
    ADD COLUMN IF NOT EXISTS actual_feature_set VARCHAR(10),
    ADD COLUMN IF NOT EXISTS per_target_feature_sets_json JSONB,
    ADD COLUMN IF NOT EXISTS feature_schema_hash VARCHAR(64),
    ADD COLUMN IF NOT EXISTS training_manifest_hash VARCHAR(64),
    ADD COLUMN IF NOT EXISTS capability_manifest_json JSONB;

CREATE INDEX IF NOT EXISTS ix_model_versions_actual_feature
    ON ml_model_versions(actual_feature_set);
