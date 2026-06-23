-- Migration: Add temperature_K to e_intra table for temperature-aware E_intra storage
-- Changes unique key from (mol_id, ff_name, ff_version) to (mol_id, ff_name, ff_version, temperature_K)

-- Step 1: Add new columns
ALTER TABLE e_intra ADD COLUMN IF NOT EXISTS temperature_K REAL NOT NULL DEFAULT 298.0;
ALTER TABLE e_intra ADD COLUMN IF NOT EXISTS source_exp_id VARCHAR(100);
ALTER TABLE e_intra ADD COLUMN IF NOT EXISTS averaging_window_ps REAL;
ALTER TABLE e_intra ADD COLUMN IF NOT EXISTS n_samples INTEGER;

-- Step 2: Drop old unique constraint (PostgreSQL)
ALTER TABLE e_intra DROP CONSTRAINT IF EXISTS uq_e_intra;

-- Step 3: Drop old index
DROP INDEX IF EXISTS ix_e_intra_lookup;

-- Step 4: Create new temperature-aware unique constraint and index
ALTER TABLE e_intra ADD CONSTRAINT uq_e_intra_temp UNIQUE (mol_id, ff_name, ff_version, temperature_K);
CREATE INDEX IF NOT EXISTS ix_e_intra_lookup ON e_intra(mol_id, ff_name, ff_version, temperature_K);

-- Note: Existing rows are backfilled with temperature_K=298.0 (default).
-- For SQLite: constraints cannot be dropped with ALTER TABLE. Use the ORM
-- auto-create path (Base.metadata.create_all) which generates the correct schema.
