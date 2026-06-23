-- Asphalt Binder MD/ML Agent Database Schema
-- PostgreSQL version

-- Drop existing tables (for fresh install)
DROP TABLE IF EXISTS experiment_molecules CASCADE;
DROP TABLE IF EXISTS experiment_conditions CASCADE;
DROP TABLE IF EXISTS metric_array_artifacts CASCADE;
DROP TABLE IF EXISTS metrics CASCADE;
DROP TABLE IF EXISTS e_intra CASCADE;
DROP TABLE IF EXISTS experiments CASCADE;
DROP TABLE IF EXISTS molecules CASCADE;

-- Molecules table
CREATE TABLE molecules (
    id SERIAL PRIMARY KEY,
    mol_id VARCHAR(100) UNIQUE NOT NULL,
    smiles TEXT NOT NULL,
    name VARCHAR(255),
    sara_type VARCHAR(50) NOT NULL,  -- saturate, aromatic, resin, asphaltene
    molecular_weight FLOAT,
    formula VARCHAR(100),
    num_atoms INTEGER,
    num_heavy_atoms INTEGER,
    metadata_json JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX ix_molecules_mol_id ON molecules(mol_id);
CREATE INDEX ix_molecules_sara_type ON molecules(sara_type);
CREATE INDEX ix_molecules_sara_type_mol_id ON molecules(sara_type, mol_id);

-- Experiments table
CREATE TABLE experiments (
    id SERIAL PRIMARY KEY,
    exp_id VARCHAR(100) UNIQUE NOT NULL,
    run_tier VARCHAR(50) NOT NULL,  -- screening, confirm, viscosity, validation
    ff_type VARCHAR(50) NOT NULL,   -- bulk_ff, reaxff
    study_type VARCHAR(50) NOT NULL DEFAULT 'bulk',  -- bulk, layer_bulkff, single_molecule_vacuum
    status VARCHAR(50) NOT NULL DEFAULT 'pending',  -- pending, running, completed, failed

    -- Composition
    comp_asphaltene_wt FLOAT NOT NULL,
    comp_resin_wt FLOAT NOT NULL,
    comp_aromatic_wt FLOAT NOT NULL,
    comp_saturate_wt FLOAT NOT NULL,
    composition_error_l1 FLOAT,

    -- Build info
    target_atoms INTEGER,
    actual_atoms INTEGER,
    seed INTEGER,
    topology_hash VARCHAR(64),
    protocol_hash VARCHAR(64),

    -- Run parameters
    temperature_K FLOAT DEFAULT 298.0,
    pressure_atm FLOAT DEFAULT 1.0,

    -- Material / force-field context
    material_id VARCHAR(255),
    binder_type VARCHAR(100),
    structure_size VARCHAR(50),
    aging_state VARCHAR(50),
    force_field_name VARCHAR(100),
    force_field_version VARCHAR(50),

    -- Mechanical / selection context
    tensile_strain_rate_1_per_ps FLOAT,
    tensile_pull_velocity_a_per_fs FLOAT,
    shear_rate_1_per_ps FLOAT,
    failure_category VARCHAR(50),
    validity_domain_tags_json JSONB,
    selection_reason_json JSONB,
    build_result_json JSONB,
    protocol_result_json JSONB,
    lammps_result_json JSONB,

    -- Paths
    data_file_path TEXT,
    input_file_path TEXT,
    log_file_path TEXT,
    dump_file_path TEXT,

    -- Error tracking
    error_code VARCHAR(50),
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE INDEX ix_experiments_exp_id ON experiments(exp_id);
CREATE INDEX ix_experiments_run_tier ON experiments(run_tier);
CREATE INDEX ix_experiments_ff_type ON experiments(ff_type);
CREATE INDEX ix_experiments_material_id ON experiments(material_id);
CREATE INDEX ix_experiments_binder_type ON experiments(binder_type);
CREATE INDEX ix_experiments_aging_state ON experiments(aging_state);
CREATE INDEX ix_experiments_status ON experiments(status);
CREATE INDEX ix_experiments_status_tier ON experiments(status, run_tier);
CREATE INDEX ix_experiments_topology_protocol ON experiments(topology_hash, protocol_hash);

-- Extensible experiment condition rows (non-core query dimensions only)
CREATE TABLE experiment_conditions (
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
    UNIQUE(experiment_id, condition_key)
);

CREATE INDEX ix_experiment_conditions_experiment ON experiment_conditions(experiment_id);
CREATE INDEX ix_experiment_conditions_key ON experiment_conditions(condition_key);

-- Experiment-Molecule association
CREATE TABLE experiment_molecules (
    id SERIAL PRIMARY KEY,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    molecule_id INTEGER NOT NULL REFERENCES molecules(id) ON DELETE CASCADE,
    count INTEGER DEFAULT 1,
    weight_fraction FLOAT,
    UNIQUE(experiment_id, molecule_id)
);

CREATE INDEX ix_exp_mol_experiment ON experiment_molecules(experiment_id);
CREATE INDEX ix_exp_mol_molecule ON experiment_molecules(molecule_id);

CREATE TABLE metric_array_artifacts (
    id SERIAL PRIMARY KEY,
    content_hash VARCHAR(64) UNIQUE NOT NULL,
    storage_path TEXT NOT NULL,
    shape_json JSONB,
    ref_count INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX ix_metric_array_artifacts_content_hash ON metric_array_artifacts(content_hash);

-- Metrics table (scalar + array metrics, arrays stored as files)
CREATE TABLE metrics (
    id SERIAL PRIMARY KEY,
    experiment_id INTEGER REFERENCES experiments(id) ON DELETE CASCADE,
    exp_id VARCHAR(100) NOT NULL,  -- Denormalized for convenience
    metric_name VARCHAR(100) NOT NULL,
    namespace VARCHAR(50) NOT NULL,  -- bulk_ff, reaxff, etc.
    value FLOAT,
    unit VARCHAR(50) NOT NULL,
    uncertainty FLOAT,
    layer_index INTEGER,
    interface_index INTEGER,
    array_artifact_id INTEGER REFERENCES metric_array_artifacts(id) ON DELETE SET NULL,

    -- Array metric reference (stored as Parquet files)
    array_file_path TEXT,
    array_shape JSONB,  -- [n_rows, n_cols] or similar

    metadata_json JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(exp_id, metric_name, namespace)
);

CREATE INDEX ix_metrics_experiment_id ON metrics(experiment_id);
CREATE INDEX ix_metrics_exp_id ON metrics(exp_id);
CREATE INDEX ix_metrics_metric_name ON metrics(metric_name);
CREATE INDEX ix_metrics_namespace ON metrics(namespace);
CREATE INDEX ix_metrics_exp_metric ON metrics(exp_id, metric_name);
CREATE INDEX ix_metrics_namespace_metric ON metrics(namespace, metric_name);

-- E_intra cache table
CREATE TABLE e_intra (
    id SERIAL PRIMARY KEY,
    molecule_id INTEGER REFERENCES molecules(id) ON DELETE CASCADE,
    mol_id VARCHAR(100) NOT NULL,  -- Denormalized
    ff_name VARCHAR(50) NOT NULL,
    ff_version VARCHAR(20) NOT NULL,
    temperature_K FLOAT NOT NULL DEFAULT 298.0,
    e_intra FLOAT NOT NULL,
    e_components JSONB,  -- bond, angle, dihedral, etc.
    minimization_steps INTEGER,
    source_exp_id VARCHAR(100),  -- Experiment that computed this value
    averaging_window_ps FLOAT,
    n_samples INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(mol_id, ff_name, ff_version, temperature_K)
);

CREATE INDEX ix_e_intra_molecule_id ON e_intra(molecule_id);
CREATE INDEX ix_e_intra_mol_id ON e_intra(mol_id);
CREATE INDEX ix_e_intra_ff_name ON e_intra(ff_name);
CREATE INDEX ix_e_intra_lookup ON e_intra(mol_id, ff_name, ff_version, temperature_K);

-- Update timestamp triggers
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_molecules_updated_at
    BEFORE UPDATE ON molecules
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_experiments_updated_at
    BEFORE UPDATE ON experiments
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_e_intra_updated_at
    BEFORE UPDATE ON e_intra
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
