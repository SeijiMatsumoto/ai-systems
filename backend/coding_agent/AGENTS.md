# Coding Agent guide

## Approved scope

Design scaffold only. The user deliberately deferred the runnable agent to focus on
other projects. Maintain contracts, architecture documentation and the frontend
architecture chart. Do not add a model adapter, execution runner, API, database
migration, fixture ingestion or runnable chat without a newly approved phase plan.

## Design decisions

- One bounded agent chooses progressive discovery, edits, tests, repair and stopping.
- Server registry resolves separate read/write scope, named editable tests, protected
  acceptance tests, pinned source and prebuilt environment. Inputs cannot grant access.
- The immutable base is for comparison; all agent search/read tools inspect the current
  working tree. Refresh changed symbol maps and carry revision locators in observations.
- Every model call gets deterministic scope/context/budget checks. Every tool call,
  including search, passes the same checked dispatcher.
- Exact text replacements require current file hash and one match; file creation requires
  an absent permitted path. Git computes the final unified diff, including new files.
- A disposable checkout is not a sandbox. Restrict filesystem/network/process access,
  protect runner/control plane from candidate code and omit host secrets.
- Baseline validation distinguishes pre-existing failures from environment errors.
  Freeze/hash final tree; independent protected validation cannot be weakened by edits.
  Missing, zero-test or stale evidence never certifies readiness.
- Persist observations/revisions/usage incrementally. Full crash resume remains deferred.
  Stop budgets are illustrative; reserve capacity for independent final validation.
- No extra Jev/reviewer model is required without a distinct semantic decision.
  Human review ends the demo; passing tests do not prove correctness.

## Verification for scaffold edits

Import/validate changed contracts offline; use Ruff on changed Python files.
For frontend changes, build, lint, run existing tests and inspect the rendered
architecture modal. No live model calls or code execution experiments are needed.
