BEGIN;
CREATE TABLE IF NOT EXISTS support_demo_sessions (
    id UUID PRIMARY KEY,
    customer_id VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS support_conversations (
    id UUID PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES support_demo_sessions(id) ON DELETE CASCADE,
    active_run_id UUID REFERENCES llm_runs(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_support_conversations_session_id ON support_conversations(session_id);
CREATE TABLE IF NOT EXISTS support_outputs (
    run_id UUID PRIMARY KEY REFERENCES llm_runs(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES support_conversations(id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    response_payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_support_outputs_conversation_id ON support_outputs(conversation_id);
COMMIT;
