-- CPU Rerun Analysis Jobs Table
-- Tracks CPU-only rerun jobs for precise E_inter calculation (kspace yes)
-- Part of E_inter precision analysis feature (v01.02.17+)

CREATE TABLE IF NOT EXISTS analysis_jobs (
    id SERIAL PRIMARY KEY,
    analysis_job_id VARCHAR(100) UNIQUE NOT NULL,

    -- Foreign key to experiments
    exp_id VARCHAR(100) NOT NULL REFERENCES experiments(exp_id) ON DELETE CASCADE,

    -- Job type and status
    analysis_type VARCHAR(50) NOT NULL DEFAULT 'cpu_rerun_einter',
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending, queued, running, completed, failed

    -- Configuration and results (JSONB for flexibility)
    config_json JSONB,          -- CPU rerun config (ff_type, metrics requested, etc.)
    metrics_json JSONB,         -- Requested metrics list
    result_json JSONB,          -- Parsed results (precise e_inter values)
    reason_codes_json JSONB,    -- Recommendation reason codes, trigger source

    -- Celery task tracking
    celery_task_id VARCHAR(255),
    error_message TEXT,

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    wall_time_seconds FLOAT
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS ix_analysis_jobs_exp_id ON analysis_jobs(exp_id);
CREATE INDEX IF NOT EXISTS ix_analysis_jobs_status ON analysis_jobs(status);
CREATE INDEX IF NOT EXISTS ix_analysis_jobs_celery_task_id ON analysis_jobs(celery_task_id);
CREATE INDEX IF NOT EXISTS ix_analysis_jobs_status_created ON analysis_jobs(status, created_at);

COMMENT ON TABLE analysis_jobs IS 'CPU rerun analysis jobs for precise E_inter calculation with long-range kspace contributions';
COMMENT ON COLUMN analysis_jobs.analysis_type IS 'Type of analysis: cpu_rerun_einter (v1), future: cpu_rerun_layer_matrix';
COMMENT ON COLUMN analysis_jobs.status IS 'Job status lifecycle: pending -> queued -> running -> completed/failed';
