BEGIN;

CREATE TABLE IF NOT EXISTS incident_simulation_outputs (
    run_id UUID PRIMARY KEY REFERENCES llm_runs(id) ON DELETE CASCADE,
    response_payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_incident_simulation_outputs_created_at
    ON incident_simulation_outputs (created_at);

COMMIT;
