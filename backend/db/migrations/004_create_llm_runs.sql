BEGIN;

CREATE TABLE IF NOT EXISTS llm_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    system_key VARCHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    logfire_trace_id VARCHAR(32),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    CONSTRAINT ck_llm_runs_status
        CHECK (status IN ('pending', 'running', 'completed', 'failed'))
);

CREATE INDEX IF NOT EXISTS ix_llm_runs_system_created_at
    ON llm_runs (system_key, created_at);

CREATE INDEX IF NOT EXISTS ix_llm_runs_status
    ON llm_runs (status);

COMMIT;
