# Coding Agent for a Private Codebase

**Status:** architecture scaffold. There is no repository-editing agent or execution sandbox yet.

## Demo contract

- **Input:** an issue against a small, versioned fixture repository plus allowed paths.
- **Output:** a reviewable unified diff, explanation, test/build results, and remaining risks. The proposed data shape is in `contracts.py`.
- **Dominant design decision:** progressive code-aware discovery and isolated execution, with deterministic tests and human review before any merge.

## Intended flow

```text
Issue -> repo map / lexical and symbol search -> targeted reads
      -> bounded edit/test loop in isolated workspace -> diff + results
      -> human review
```

The first runnable slice should use one fixture issue with a small regression test. Tools should expose search, read, edit, and test operations within a disposable checkout. The runtime, rather than the model, should enforce allowed paths, execution limits, and network restrictions. The UI should show files inspected, edits made, test feedback, and the final diff.

## Boundaries and acceptance

No access to the user's actual private repos, no production credentials, and no automatic PR merge. The demo is sufficient when the agent identifies the correct file, proposes a passing change, shows failed and passing validation attempts, and leaves the final diff for review. A separate fixture should show that an out-of-scope edit is rejected.
