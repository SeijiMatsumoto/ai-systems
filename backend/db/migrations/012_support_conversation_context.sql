BEGIN;
ALTER TABLE support_conversations ADD COLUMN IF NOT EXISTS context_state JSONB;
COMMIT;
