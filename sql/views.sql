-- Asphalt Binder MD/ML Agent Database Views
-- PostgreSQL version

-- View: Experiment summary with key metrics
CREATE OR REPLACE VIEW v_experiment_summary AS
SELECT
    e.exp_id,
    e.run_tier,
    e.ff_type,
    e.status,
    e.comp_asphaltene_wt,
    e.comp_resin_wt,
    e.comp_aromatic_wt,
    e.comp_saturate_wt,
    e.composition_error_l1,
    e.actual_atoms,
    e.temperature_K,
    e.created_at,
    e.completed_at,
    e.error_code,
    -- Key metrics
    (SELECT value FROM metrics WHERE exp_id = e.exp_id AND metric_name = 'density' LIMIT 1) as density,
    (SELECT value FROM metrics WHERE exp_id = e.exp_id AND metric_name = 'ced' LIMIT 1) as ced,
    (SELECT value FROM metrics WHERE exp_id = e.exp_id AND metric_name = 'solubility_parameter' LIMIT 1) as solubility_parameter
FROM experiments e;

-- View: Molecule usage statistics
CREATE OR REPLACE VIEW v_molecule_usage AS
SELECT
    m.mol_id,
    m.smiles,
    m.sara_type,
    m.molecular_weight,
    COUNT(DISTINCT em.experiment_id) as experiment_count,
    SUM(em.count) as total_molecules_used,
    AVG(em.weight_fraction) as avg_weight_fraction
FROM molecules m
LEFT JOIN experiment_molecules em ON m.id = em.molecule_id
GROUP BY m.id, m.mol_id, m.smiles, m.sara_type, m.molecular_weight;

-- View: E_intra cache coverage
CREATE OR REPLACE VIEW v_e_intra_coverage AS
SELECT
    m.sara_type,
    ei.ff_name,
    ei.ff_version,
    COUNT(DISTINCT m.mol_id) as total_molecules,
    COUNT(DISTINCT ei.mol_id) as cached_molecules,
    ROUND(100.0 * COUNT(DISTINCT ei.mol_id) / NULLIF(COUNT(DISTINCT m.mol_id), 0), 2) as coverage_pct
FROM molecules m
LEFT JOIN e_intra ei ON m.mol_id = ei.mol_id
GROUP BY m.sara_type, ei.ff_name, ei.ff_version;

-- View: Metric statistics by tier
CREATE OR REPLACE VIEW v_metric_stats_by_tier AS
SELECT
    e.run_tier,
    m.metric_name,
    m.namespace,
    COUNT(*) as count,
    ROUND(AVG(m.value)::numeric, 4) as avg_value,
    ROUND(MIN(m.value)::numeric, 4) as min_value,
    ROUND(MAX(m.value)::numeric, 4) as max_value,
    ROUND(STDDEV(m.value)::numeric, 4) as std_value
FROM metrics m
JOIN experiments e ON m.exp_id = e.exp_id
WHERE e.status = 'completed'
GROUP BY e.run_tier, m.metric_name, m.namespace;

-- View: Daily experiment counts
CREATE OR REPLACE VIEW v_daily_experiments AS
SELECT
    DATE(created_at) as date,
    run_tier,
    status,
    COUNT(*) as count
FROM experiments
GROUP BY DATE(created_at), run_tier, status
ORDER BY date DESC, run_tier, status;

-- View: Composition space coverage
CREATE OR REPLACE VIEW v_composition_coverage AS
SELECT
    ROUND(comp_asphaltene_wt * 10) / 10 as asphaltene_bin,
    ROUND(comp_resin_wt * 10) / 10 as resin_bin,
    ROUND(comp_aromatic_wt * 10) / 10 as aromatic_bin,
    ROUND(comp_saturate_wt * 10) / 10 as saturate_bin,
    COUNT(*) as experiment_count,
    COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed_count,
    AVG(CASE WHEN status = 'completed' THEN composition_error_l1 END) as avg_comp_error
FROM experiments
GROUP BY
    ROUND(comp_asphaltene_wt * 10) / 10,
    ROUND(comp_resin_wt * 10) / 10,
    ROUND(comp_aromatic_wt * 10) / 10,
    ROUND(comp_saturate_wt * 10) / 10;

-- View: Failed experiments analysis
CREATE OR REPLACE VIEW v_failed_experiments AS
SELECT
    exp_id,
    run_tier,
    ff_type,
    error_code,
    error_message,
    retry_count,
    comp_asphaltene_wt,
    comp_resin_wt,
    comp_aromatic_wt,
    comp_saturate_wt,
    actual_atoms,
    created_at
FROM experiments
WHERE status = 'failed'
ORDER BY created_at DESC;

-- View: Tier progression summary
CREATE OR REPLACE VIEW v_tier_progression AS
WITH tier_counts AS (
    SELECT
        topology_hash,
        run_tier,
        COUNT(*) as count,
        SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed
    FROM experiments
    WHERE topology_hash IS NOT NULL
    GROUP BY topology_hash, run_tier
)
SELECT
    topology_hash,
    MAX(CASE WHEN run_tier = 'screening' THEN completed ELSE 0 END) as screening_completed,
    MAX(CASE WHEN run_tier = 'confirm' THEN completed ELSE 0 END) as confirm_completed,
    MAX(CASE WHEN run_tier = 'viscosity' THEN completed ELSE 0 END) as viscosity_completed,
    MAX(CASE WHEN run_tier = 'validation' THEN completed ELSE 0 END) as validation_completed
FROM tier_counts
GROUP BY topology_hash;
