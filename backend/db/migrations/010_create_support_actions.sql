BEGIN;
CREATE TABLE IF NOT EXISTS support_orders (
 order_id VARCHAR(64) PRIMARY KEY, customer_id VARCHAR(64) NOT NULL,
 version INTEGER NOT NULL CHECK (version >= 1), fixture_version VARCHAR(64) NOT NULL, payload JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_support_orders_customer_id ON support_orders(customer_id);
CREATE TABLE IF NOT EXISTS support_proposals (
 id UUID PRIMARY KEY, run_id UUID NOT NULL REFERENCES llm_runs(id),
 conversation_id UUID NOT NULL REFERENCES support_conversations(id), customer_id VARCHAR(64) NOT NULL,
 idempotency_key VARCHAR(128) NOT NULL UNIQUE, state VARCHAR(16) NOT NULL,
 order_version INTEGER NOT NULL, policy_fingerprint VARCHAR(64) NOT NULL, payload JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS support_cases (
 id UUID PRIMARY KEY, run_id UUID NOT NULL REFERENCES llm_runs(id),
 conversation_id UUID NOT NULL REFERENCES support_conversations(id), customer_id VARCHAR(64) NOT NULL,
 idempotency_key VARCHAR(128) NOT NULL UNIQUE, payload JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_support_cases_customer_id ON support_cases(customer_id);
CREATE TABLE IF NOT EXISTS support_receipts (
 id UUID PRIMARY KEY, proposal_id UUID NOT NULL UNIQUE REFERENCES support_proposals(id),
 decision_run_id UUID NOT NULL REFERENCES llm_runs(id), decision VARCHAR(16) NOT NULL, payload JSONB NOT NULL
);
COMMIT;
