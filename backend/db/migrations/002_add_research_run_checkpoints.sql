BEGIN;

ALTER TABLE research_runs
    ADD COLUMN IF NOT EXISTS checkpoint_stage VARCHAR(50),
    ADD COLUMN IF NOT EXISTS checkpoint_payload JSONB;

COMMIT;
