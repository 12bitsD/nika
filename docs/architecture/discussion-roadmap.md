# Architecture discussion roadmap

Purpose: finish the architecture without losing decisions or the main thread. This file is the controlling plan for discussion. The [feature worklist](feature-worklist.md) tracks individual features; this roadmap controls their order and closure.

Current stage: **M5 — Context, cache, and compaction**. No runtime implementation is authorized by this roadmap.

## Fixed guardrails

These decisions should not be reopened without an explicit change of product direction:

- One AgentLoop for ordinary chat and coding; no external coding harness or coding mode.
- One container for Bot, BrowserUse, and ComputerUse; no remote device bridge.
- Feishu is the primary channel, including documents and document comments.
- One `AgentWiki` root, with Wiki and Skill consumed through different mechanisms.
- Every Session produces Trajectory; export is on demand, with no automatic RSI or automatic Wiki promotion.
- Keep the system small. Do not add a generic EventBus, remote event replay, task-card system, agent-defined Hooks, or unrelated platform features.

## Route

| Stage | Mission | Main question | Required output and close condition | Status |
|---|---|---|---|---|
| Research | M1, M2 | What do yomi, Hermes, OpenAI, and Anthropic already prove? | Primary-source notes for runtime, Trajectory, compaction, Skill, and extension mechanisms | Done |
| Core | **M4** | What exactly happens inside AgentLoop? | State transitions, event order, Tool concurrency, cancellation, finalization, and failure paths are unambiguous in all listed scenarios | **Done** — [agent-loop.md](../design/agent-loop.md) |
| Context | M5 | What exactly does the model see, and how is it compacted? | Deterministic ContextBuilder, revision/cache rules, 75% compaction, WorkingContext, and budget behavior are consistent with M4 | **In progress** — [context-builder.md](../design/context-builder.md) |
| Resources | M6 | What can each actor and process access, and who owns each resource? | Trust/credential rules, resource ownership, locks, concurrency, and crash cleanup cover every Tool and shared resource | Pending; depends on M4 |
| Data and channels | M7 | What is authoritative, and how do external systems observe it? | Session/event/projection schema, Trajectory/export contracts, Feishu acceptance, backup, and GC are consistent | Pending; depends on M5 and M6 |
| Engineering | M8 | How is the design implemented and verified? | Language, package layout, dependencies, container processes, storage mounts, health checks, and CI levels are chosen | Pending; depends on M7 |
| Special topic | **M3** | How should Wiki actually be consumed? | A dedicated comparison and decision for bootstrap, retrieval, automatic recall, writeback, cache, and compaction | **Done** — [agentwiki.md](../design/agentwiki.md); Git synchronization and writer coordination belong to M6/M7 |
| Special topic | Proactive | How should the Bot reduce the user's context-management burden? | A separate mechanism for task-phase detection, internal updates, user-facing distillation, authorization boundaries, and interruption policy | Planned after M5; value accepted, behavior not yet designed |
| Closure | M9 | Is the architecture complete and implementable? | End-to-end review, no unowned big questions, synchronized docs, and a staged implementation plan | Pending; depends on M3, Proactive, and M8 |

M5 and M6 may be discussed in parallel after M4 if their inputs stop changing. M7 must not be used to resolve new questions by silently changing M5 or M6; any change goes back to the owning stage and is recorded there first.

## Stage close criteria

### M4 — AgentLoop

Close only when these walks are all deterministic:

1. ordinary text response;
2. one and multiple Tool calls;
3. steer during model streaming and during Tool execution;
4. compaction before and during a Tool-driven task;
5. WaitingRequest and its answer;
6. `/stop` at every state and a later new Turn;
7. model, Tool, persistence, and process failures.

The output must define where Trajectory events and Session writes occur in each path.

### M5 — Context and compaction

Close only when every model request can be explained by a deterministic assembly rule:

- stable prefix, Skill/Wiki revisions, Session history, WorkingContext, and current input have a defined order;
- within a compaction boundary and fixed revisions, provider-visible content is immutable and append-only, including WorkingContext versions and invalidation markers;
- model, Skill, Wiki, and `AGENTS.md` updates have explicit effective boundaries;
- compaction has a defined trigger, Agent-generated task summary, validation, failure path, recovery, and new cache boundary;
- budget changes take effect at a defined point.

### M6 — Trust and resources

Close only when every execution resource has an owner and lifecycle:

- actor permissions are distinguished from process credentials;
- shell, browser, desktop, Git workspace, and Wiki writes have explicit access rules;
- every shared resource is Session-private, globally shared with a lock, or explicitly exclusive;
- cancellation and process failure release or mark every resource without pretending side effects were undone.

### M7 — Data and channels

Close only when:

- `session_events` is the sole authority for execution history; Session projections and Conversation views are derived from the latest compaction event and subsequent events, with no persistent Snapshot to keep synchronized;
- trace and AIFT exports have stable schemas and preserve Tool Call/Result correlation;
- Feishu IM, documents, comments, and cards have concrete acceptance scenarios, including duplicate and delayed events;
- backup, restore, and GC preserve referential consistency between events and assets.

### M8 — Engineering

Close only when a fresh checkout can be built, tested, and run by a documented path. Language choice must account for AgentLoop, Feishu, SQLite, BrowserUse, ComputerUse, external Tool processes, and maintenance cost—not just benchmark performance.

### M9 — Final review

Close only when:

- all feature rows have a value, an approach, and either a closed contract or an explicitly deferred reason;
- the seven M4 scenarios plus Feishu document and Browser/Computer scenarios can be walked through without inventing behavior;
- ADR, CONTEXT, README, feature worklist, and this roadmap agree;
- remaining open topics are genuinely outside the implementation baseline;
- the implementation phases have verification and stop conditions.

## Discussion protocol for every feature

Use the same short loop:

1. **Value** — what user outcome requires this feature? Remove it if there is no concrete outcome.
2. **Scenarios** — name the success path and the important failure/concurrent path.
3. **Approach** — choose the smallest mechanism that handles those scenarios.
4. **Verification** — state exactly how the feature would be demonstrated or tested.
5. **Record** — update the feature worklist and any affected ADR/CONTEXT entry, then commit.

A feature is not closed because its name or happy path is agreed. It closes when its behavior, failure handling, ownership, and verification are all explicit.

## How to handle divergence

When a useful but out-of-stage idea appears:

1. Record it in the parking lot below with the reason and the condition that would make it worth reopening.
2. Do not spend the current stage designing it.
3. Return to the current stage's unresolved question in the same reply.
4. If it changes an accepted decision, explicitly say so and create a superseding ADR instead of silently editing history.

## Parking lot

| Idea | Why it is parked | Reopen when |
|---|---|---|
| Agent-defined Hooks | Trajectory already covers recording and audit; no current scenario requires automatically changing subsequent behavior | A concrete deterministic action is required that cannot be left to the next model decision; then design activation, recursion, timeout, and failure semantics afresh |
| Read-only `/btw` side questions | An IM bot can answer progress through the main Session; a separate read-only completion adds concurrency and prompt complexity without a concrete use case | A recurring scenario needs side questions that must not affect the main task |
| Automatic RSI or automatic Skill promotion | Trajectory and Skills are useful without an automatic self-modification loop | There is a reviewed offline evaluation and approval policy |
| Cross-entry Session resume | One entry per Session is simpler and covers the current workflow | A real user repeatedly needs to continue the same work in another entry |
| Vector/semantic Wiki index | Exact Wiki consumption is deferred to M3; no need to preselect infrastructure | M3 demonstrates that aliases and keyword retrieval are insufficient |
| Generic EventBus and event replay | There is only the active Feishu renderer and direct authoritative writes | A second real subscriber or remote UI requires it |
| Multiple virtual desktops or remote devices | One container and one shared desktop are enough for the baseline | Parallel GUI work becomes a measured requirement |
| External Kimi Code route or coding mode | One native AgentLoop gives complete Trajectory and less lifecycle duplication | A requirement for native external Session compatibility is explicitly reinstated |
| Automatic Wiki promotion from Trajectory | Raw execution history is not curated long-term knowledge | A user-selected curation workflow exists |

## Status maintenance

At every stage close or meaningful decision:

1. Update the affected feature row and ADR/CONTEXT entries.
2. Update this roadmap's stage status and parking lot.
3. Check links and `git diff --check`.
4. Commit and push so the next discussion starts from the repository rather than chat memory.

The roadmap does not authorize implementation. Implementation starts only after M9 and explicit user confirmation.
