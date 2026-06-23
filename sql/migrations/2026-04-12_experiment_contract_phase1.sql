-- Phase 1: experiment storage contract alignment
-- Adds core material/FF/mechanical context columns and experiment_conditions table.

ALTER TABLE experiments ADD COLUMN IF NOT EXISTS material_id VARCHAR(255);
ALTER TABLE experiments ADD COLUMN IF NOT EXISTS binder_type VARCHAR(100);
ALTER TABLE experiments ADD COLUMN IF NOT EXISTS structure_size VARCHAR(50);
ALTER TABLE experiments ADD COLUMN IF NOT EXISTS aging_state VARCHAR(50);
ALTER TABLE experiments ADD COLUMN IF NOT EXISTS force_field_name VARCHAR(100);
ALTER TABLE experiments ADD COLUMN IF NOT EXISTS force_field_version VARCHAR(50);
ALTER TABLE experiments ADD COLUMN IF NOT EXISTS tensile_strain_rate_1_per_ps FLOAT;
ALTER TABLE experiments ADD COLUMN IF NOT EXISTS tensile_pull_velocity_a_per_fs FLOAT;
ALTER TABLE experiments ADD COLUMN IF NOT EXISTS shear_rate_1_per_ps FLOAT;
ALTER TABLE experiments ADD COLUMN IF NOT EXISTS failure_category VARCHAR(50);
ALTER TABLE experiments ADD COLUMN IF NOT EXISTS validity_domain_tags_json JSONB;
ALTER TABLE experiments ADD COLUMN IF NOT EXISTS selection_reason_json JSONB;
ALTER TABLE experiments ADD COLUMN IF NOT EXISTS build_result_json JSONB;
ALTER TABLE experiments ADD COLUMN IF NOT EXISTS protocol_result_json JSONB;
ALTER TABLE experiments ADD COLUMN IF NOT EXISTS lammps_result_json JSONB;

CREATE INDEX IF NOT EXISTS ix_experiments_material_id ON experiments(material_id);
CREATE INDEX IF NOT EXISTS ix_experiments_binder_type ON experiments(binder_type);
CREATE INDEX IF NOT EXISTS ix_experiments_aging_state ON experiments(aging_state);

CREATE TABLE IF NOT EXISTS experiment_conditions (
    id SERIAL PRIMARY KEY,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    condition_key VARCHAR(100) NOT NULL,
    value_type VARCHAR(20) NOT NULL,
    value_number FLOAT,
    value_text TEXT,
    value_bool BOOLEAN,
    value_json JSONB,
    unit VARCHAR(50),
    source VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_experiment_condition_key UNIQUE (experiment_id, condition_key)
);

CREATE INDEX IF NOT EXISTS ix_experiment_conditions_experiment
    ON experiment_conditions(experiment_id);
CREATE INDEX IF NOT EXISTS ix_experiment_conditions_key
    ON experiment_conditions(condition_key);
