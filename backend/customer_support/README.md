# Customer Support Agent

**Status:** architecture scaffold. There is no conversation API, customer store, or action executor yet.

## Demo contract

- **Input:** an authenticated synthetic customer message and conversation ID, with mock account/order state.
- **Output:** a policy-cited answer, a permitted action proposal or completed action state, or a reasoned handoff to a human. The proposed data shape is in `contracts.py`.
- **Dominant design decision:** policy knowledge comes from retrieval; customer/order state and transactions come from authoritative APIs with deterministic permission checks.

## Intended flow

```text
Customer identity -> conversation state -> policy retrieval + account lookup
                  -> answer or proposed action -> confirm / policy gate
                  -> customer response or human escalation
```

The first runnable slice should use synthetic orders and policies. Read-only tools can look up orders and policy passages. One mock action, such as canceling an eligible order, should validate customer ownership and policy conditions before execution. The UI should show the ordered policy and account lookups with exact inputs and results, ownership and action checks, policy citation, action decision, and escalation reason.

## Boundaries and acceptance

No real customers, payments, refunds, or external writes. Action retries must use an idempotency key. The demo is sufficient when an ordinary policy question is answered, an eligible action pauses for confirmation, an ineligible action is blocked, and an ambiguous case escalates with context for a human agent.
