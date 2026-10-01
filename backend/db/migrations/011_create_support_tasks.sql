BEGIN;
CREATE TABLE IF NOT EXISTS support_tasks (
    id UUID PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES support_conversations(id) ON DELETE CASCADE,
    checkpoint JSONB NOT NULL,
    last_run_id UUID REFERENCES llm_runs(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_support_tasks_conversation_id ON support_tasks(conversation_id);
ALTER TABLE support_outputs ADD COLUMN IF NOT EXISTS task_id UUID REFERENCES support_tasks(id);
CREATE INDEX IF NOT EXISTS ix_support_outputs_task_id ON support_outputs(task_id);
COMMIT;
