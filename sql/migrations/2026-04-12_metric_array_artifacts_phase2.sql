-- Phase 2: metric array artifact ownership linkage
-- Adds artifact registry and FK from metrics to shared array artifacts.

CREATE TABLE IF NOT EXISTS metric_array_artifacts (
    id SERIAL PRIMARY KEY,
    content_hash VARCHAR(64) UNIQUE NOT NULL,
    storage_path TEXT NOT NULL,
    shape_json JSONB,
    ref_count INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_metric_array_artifacts_content_hash
    ON metric_array_artifacts(content_hash);

ALTER TABLE metrics ADD COLUMN IF NOT EXISTS array_artifact_id INTEGER
    REFERENCES metric_array_artifacts(id) ON DELETE SET NULL;
