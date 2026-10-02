# Coding Agent for a Private Codebase

**Status:** design scaffold. Contracts and the frontend architecture chart exist;
repository editing, model calls, execution sandbox, API and persistence do not.

## Task and output

- **Input:** a requested behavior change against a pinned synthetic fixture revision.
- **Server policy:** separate read/write paths, named editable test targets,
  protected acceptance targets, prebuilt environment digest and execution budgets.
- **Output:** a Git-generated diff, baseline/final validation evidence, explanation,
  remaining risks and a stop reason for human review.
- **Distinct architecture:** progressive code discovery and an isolated edit/test
  feedback loop. Tests inform repair; runtime checks govern permissions and output.

Open **Coding → System architecture** for five left-to-right stages: request,
preparation, agent, final validation and review. A two-box tool loop beneath the
agent shows permission checks and sandbox execution; details live inside the boxes.

## Proposed request flow

1. **Validate task and resolve policy.** Reject unknown fixtures/revisions and invalid
   inputs before a model call. Resolve permissions and targets from the trusted
   registry. User requests and repository text cannot expand this policy.
2. **Prepare the environment.** Provision a disposable workspace from the pinned
   source snapshot in a prebuilt, versioned execution environment. Run baseline
   validation. Record expected pre-existing failures; distinguish them from missing
   dependencies, broken test discovery or setup errors before starting the agent.
3. **Run one bounded agent.** Before every model call, validate context size, scope,
   recent observations and remaining cumulative budget. The agent chooses a typed
   search, read, edit or test operation, or finishes. It gets a compact repository
   map, relevant current file excerpts, recent test feedback and a bounded summary
   of prior work; old logs do not accumulate indefinitely.
4. **Check every tool call.** Search and reads use authorized paths in the current
   working tree. Writes use narrower write scope. Resolve paths and reject traversal,
   symlink escapes, protected files and stale edits. A named test target resolves to
   fixed argv/environment settings; model-provided shell commands are unavailable.
5. **Execute and observe.** Search/read/edits see the latest workspace. Refresh or
   invalidate symbol maps after changes. Exact-match replacements require the current
   file hash and one matching block; new files require an absent authorized path.
   Return structured, bounded observations, reject ambiguous edits without mutation
   and let the model retry within its budget. Tests can trigger bounded repair.
6. **Verify independently.** Freeze the final working tree, including new files;
   compute its content hash and diff against the immutable base. Check all changed
   paths and run required editable tests plus protected acceptance tests. Only the
   trusted runner reports status; record environment digest, exit status, collection
   counts and tree hash. Earlier test results cannot certify a later revision.
7. **Save and review.** Record steps, revisions, observations and usage throughout
   execution; save the final artifact and terminal reason. Missing, failed or stale
   evidence produces an explicit partial result. A human reviews behavior, exact
   diff, test changes and risks. No merge, push or external write is in scope.

## Component responsibilities

| Component | Boundary |
| --- | --- |
| Task/policy gate | Server owns scope, validation registry and budget ceilings |
| Fixture/environment preparation | Pinned base, prebuilt dependencies and baseline evidence; source snapshot is not the live retrieval index |
| Agent/harness | One model-directed loop; bounded context, tokens, tool calls, elapsed time and repair attempts |
| Tool dispatcher | All model-facing search/read/edit/test calls pass permission and argument checks |
| Execution sandbox/current tree | OS-enforced filesystem/network/process restrictions cover application code and subprocesses, even during allowlisted tests |
| Acceptance/diff gate | Independent final-revision validation and complete diff, including untracked additions and test edits |
| Run/artifact store | Incremental audit evidence plus final outcome; no durable recovery claim |
| Human reviewer | Decide whether the change satisfies the issue; tests do not prove correctness |

### Protected validation and execution

The agent may modify explicitly permitted development tests. The protected acceptance
suite, target registry and runner are outside its writable tree and excluded from
agent reads/tools. A trusted verifier executes the protected suite against the frozen
candidate in a fresh restricted test process with the same versioned dependencies.
The test runner/control plane must be protected from candidate code; result collection
must not trust a pass message or result file that candidate code can fabricate.
Protected tests still provide limited coverage, not a security or correctness proof.

An allowlisted test command can import hostile edited code. The execution environment
must restrict filesystem access, network, subprocess resources and host mounts, omit
secrets, and terminate the entire process group on timeout/cancellation. A disposable
Git checkout alone does not enforce these boundaries. Network-disabled operation relies
on prebuilt dependencies; adding a dependency requires a new approved fixture image.

### Contracts and limits

`contracts.py` describes task/policy inputs, budgets, search/read/exact-edit/create/test
requests, runtime observations, validation evidence and the review artifact. Search
observations identify file/line locations at their recorded tree hash. Model-facing
validation requests cannot select protected targets. Runtime-owned observations and
results must be constructed by trusted code, not accepted from model output.

Schemas enforce shape and basic bounds only. A future runtime must enforce path
containment, authorization, unique text matching, hash freshness, independent test
collection, cumulative budgets, and final evidence consistency. Budget defaults are
illustrative and have not been calibrated. The final validation stage needs a reserved
share of the run budget; if that is exhausted, return `budget_exhausted` with missing
validation explicitly recorded rather than implying readiness.

Incremental persistence makes the walkthrough inspectable if a run fails. Automatic
crash recovery is deferred: an interrupted run should be marked incomplete, never
replayed blindly. A future resume design would need tool IDs, reconciled filesystem
state and idempotent mutation handling.

## Interview tradeoffs

- **Lexical/symbol search and progressive reads:** useful for precise identifiers and
  dependencies; current-tree reads avoid stale context. Embeddings can be added if
  measured discovery failures justify the indexing/freshness complexity.
- **One agent:** repair depends on observations, so a feedback loop fits better than
  a predetermined pipeline. Multiple agents are unnecessary for the small slice.
- **Exact edits, Git-generated output:** lower formatting burden than model-generated
  unified diffs. Ambiguous/stale matches are rejected; matching text alone does not
  establish semantic correctness.
- **Named commands and prebuilt dependencies:** narrower capabilities and repeatable
  environments, at the cost of supporting fewer tasks than a general coding product.
- **Protected final tests:** reduce the risk of passing by weakening editable tests;
  baseline comparisons and human review still matter.

## Future acceptance cases

These are design criteria, not executed test claims:

- Correct change with baseline and final-revision validation.
- Failed development test followed by bounded repair.
- Search/read after an edit returns current code; changed symbol maps refresh.
- Broader permitted reads do not grant broader writes; all search results obey scope.
- Traversal, symlink, protected-test and command-registry changes are rejected.
- Stale hash and duplicate replacement matches leave files unchanged.
- Weakened editable assertions cannot replace protected acceptance evidence.
- Executed code cannot access host secrets/network or forge authoritative results.
- Setup failure, zero collected tests, timeout, cancellation and exhausted budgets
  yield explicit partial outcomes.
- Final diff includes new files; validation becomes stale after any subsequent edit.
- Failed persistence is visible; interrupted runs do not claim resumability.

## Comparison references

The scaffold was reviewed against these primary sources. Its proposals are design
choices for this demo, not claims to reproduce those products:

- [Anthropic: Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)
  — environmental feedback, tool design, test iteration and human review.
- [Anthropic: Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
  — progressive discovery, targeted reads and bounded working context.
- [Anthropic: Claude Code sandboxing](https://www.anthropic.com/engineering/claude-code-sandboxing)
  — separate filesystem/network enforcement covering spawned processes.
- [Aider: Repository map](https://aider.chat/docs/repomap.html)
  — compact symbol/dependency context with a token budget.
- [SWE-agent paper](https://arxiv.org/abs/2405.15793)
  — agent-computer interfaces for repository navigation, editing and testing.
