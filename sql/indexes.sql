-- Asphalt Binder MD/ML Agent Database Indexes
-- PostgreSQL version
-- Additional performance indexes beyond those in schema.sql

-- =============================================================================
-- Partial Indexes for Common Queries
-- =============================================================================

-- Index only pending experiments for queue processing
CREATE INDEX IF NOT EXISTS ix_experiments_pending
ON experiments(created_at)
WHERE status = 'pending';

-- Index only running experiments for monitoring
CREATE INDEX IF NOT EXISTS ix_experiments_running
ON experiments(exp_id)
WHERE status = 'running';

-- Index failed experiments for retry processing
CREATE INDEX IF NOT EXISTS ix_experiments_failed_retry
ON experiments(error_code, retry_count)
WHERE status = 'failed' AND retry_count < 3;

-- =============================================================================
-- Composite Indexes for Join Performance
-- =============================================================================

-- For experiment-molecule lookups with SARA type filtering
CREATE INDEX IF NOT EXISTS ix_exp_mol_with_sara
ON experiment_molecules(experiment_id, molecule_id);

-- For metrics lookup with time range
CREATE INDEX IF NOT EXISTS ix_metrics_exp_created
ON metrics(exp_id, created_at DESC);

-- =============================================================================
-- Indexes for Text Search (if needed)
-- =============================================================================

-- GIN index for JSONB metadata search
CREATE INDEX IF NOT EXISTS ix_molecules_metadata_gin
ON molecules USING GIN (metadata_json);

CREATE INDEX IF NOT EXISTS ix_metrics_metadata_gin
ON metrics USING GIN (metadata_json);

CREATE INDEX IF NOT EXISTS ix_e_intra_components_gin
ON e_intra USING GIN (e_components);

-- =============================================================================
-- Indexes for Aggregation Queries
-- =============================================================================

-- For composition binning queries
CREATE INDEX IF NOT EXISTS ix_experiments_composition
ON experiments(comp_asphaltene_wt, comp_resin_wt, comp_aromatic_wt, comp_saturate_wt)
WHERE status = 'completed';

-- For daily stats queries
CREATE INDEX IF NOT EXISTS ix_experiments_created_date
ON experiments(DATE(created_at), run_tier, status);

-- =============================================================================
-- BRIN Indexes for Time-Series Data
-- =============================================================================

-- BRIN index for experiments created_at (good for large tables with natural ordering)
CREATE INDEX IF NOT EXISTS ix_experiments_created_brin
ON experiments USING BRIN (created_at);

CREATE INDEX IF NOT EXISTS ix_metrics_created_brin
ON metrics USING BRIN (created_at);

-- =============================================================================
-- Hash Indexes for Exact Match Lookups
-- =============================================================================

-- Hash index for topology_hash exact lookups
CREATE INDEX IF NOT EXISTS ix_experiments_topology_hash_hash
ON experiments USING HASH (topology_hash)
WHERE topology_hash IS NOT NULL;

-- Hash index for protocol_hash exact lookups
CREATE INDEX IF NOT EXISTS ix_experiments_protocol_hash_hash
ON experiments USING HASH (protocol_hash)
WHERE protocol_hash IS NOT NULL;

-- =============================================================================
-- Analyze Tables for Query Planner
-- =============================================================================

ANALYZE molecules;
ANALYZE experiments;
ANALYZE experiment_molecules;
ANALYZE metrics;
ANALYZE e_intra;
