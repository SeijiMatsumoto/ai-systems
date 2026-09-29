# Internal Knowledge + Action Assistant

**Status:** architecture scaffold. There is no source index, action executor, or assistant API yet.

## Demo contract

- **Input:** an authenticated synthetic user asking about mock documents, tickets, and policy records, possibly requesting an action.
- **Output:** a cited answer, source freshness/limits, and an action proposal with an approval state. The proposed data shape is in `contracts.py`.
- **Dominant design decision:** filter sources by the user's access **before** retrieval and separate read-only answer tools from action tools governed by policy and approval.

## Intended flow

```text
User identity -> ACL filter -> lexical + semantic search -> cited answer
             -> optional action proposal -> policy check -> approval -> execute
```

The first runnable slice should use a small synthetic corpus with two users who have different access. A deterministic retrieval layer should filter by user/source ACL, rank results, and preserve exact locators. A mock action, such as creating a task, should remain a proposal until approved. The UI should show citations, the access boundary, and the approval transition.

## Boundaries and acceptance

No live company data or external writes. Retrieved text is data, not instructions. The demo is sufficient when an allowed question cites the right source, an unauthorized document never enters the model context, and an action is blocked until a separate approval decision is recorded. Repeated execution should use an idempotency key.
