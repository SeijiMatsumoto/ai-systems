BEGIN;

DO $$
BEGIN
    CREATE TYPE research_run_status AS ENUM (
        'pending',
        'running',
        'completed',
        'failed'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END;
$$;

CREATE TABLE IF NOT EXISTS research_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_fingerprint VARCHAR(64) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    as_of TIMESTAMPTZ NOT NULL,
    status research_run_status NOT NULL DEFAULT 'pending',

    request_payload JSONB NOT NULL,
    briefing_payload JSONB,
    verification_payload JSONB,
    usage_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_payload JSONB,
    checkpoint_stage VARCHAR(50),
    checkpoint_payload JSONB,
    trace_id VARCHAR(32),

    model_name VARCHAR NOT NULL,
    prompt_version VARCHAR NOT NULL,
    tool_version VARCHAR NOT NULL,
    schema_version VARCHAR NOT NULL DEFAULT '1',

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_research_runs_request_fingerprint
    ON research_runs (request_fingerprint);

CREATE INDEX IF NOT EXISTS ix_research_runs_symbol
    ON research_runs (symbol);

CREATE INDEX IF NOT EXISTS ix_research_runs_status
    ON research_runs (status);

CREATE UNIQUE INDEX IF NOT EXISTS uq_research_runs_active_fingerprint
    ON research_runs (request_fingerprint)
    WHERE status IN ('pending', 'running');

COMMIT;
