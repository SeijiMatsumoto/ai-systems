BEGIN;

CREATE TABLE IF NOT EXISTS knowledge_mock_tasks (
    id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES knowledge_answer_outputs(run_id) ON DELETE CASCADE,
    idempotency_key VARCHAR(120) NOT NULL UNIQUE,
    task_type VARCHAR(40) NOT NULL CHECK (task_type = 'support_follow_up'),
    title VARCHAR(120) NOT NULL,
    description TEXT NOT NULL,
    source_id VARCHAR(120) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_knowledge_mock_tasks_run_id UNIQUE (run_id)
);

COMMIT;
