BEGIN;

ALTER TABLE research_runs
    ADD COLUMN IF NOT EXISTS resumed_from_run_id UUID;

INSERT INTO llm_runs (
    id, system_key, status, logfire_trace_id, created_at, started_at, finished_at
)
SELECT
    id, 'research_workflow', status::text, trace_id,
    created_at, started_at, completed_at
FROM research_runs
ON CONFLICT (id) DO NOTHING;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM research_runs r
        JOIN llm_runs l ON l.id = r.id
        WHERE l.system_key <> 'research_workflow'
    ) THEN
        RAISE EXCEPTION 'research run ID collides with another system in llm_runs';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_research_runs_llm_run'
    ) THEN
        ALTER TABLE research_runs
            ADD CONSTRAINT fk_research_runs_llm_run
            FOREIGN KEY (id) REFERENCES llm_runs(id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_research_runs_resumed_from'
    ) THEN
        ALTER TABLE research_runs
            ADD CONSTRAINT fk_research_runs_resumed_from
            FOREIGN KEY (resumed_from_run_id) REFERENCES research_runs(id);
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS research_run_steps (
    run_id UUID NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    payload JSONB NOT NULL,
    PRIMARY KEY (run_id, sequence)
);

COMMIT;
