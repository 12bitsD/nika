# nika architecture discussion roadmap

Purpose: close nika's product architecture without duplicating nextloop's execution roadmap. This file controls product topics, order, and closure.

Current stage: **M5 — product capabilities and Adapter contracts**. nextloop independently owns ReAct, ContextBuilder, and execution-protocol work; the two repositories do not share implementation milestones.

## Fixed product guardrails

- nika owns the complete personal agent and superagent architecture; nextloop owns only the reusable execution protocol.
- Feishu is the primary channel, including documents and comments.
- Bot, BrowserUse, and ComputerUse run in one container.
- One AgentWiki root, with Wiki and Skill consumed differently.
- Every Session produces Trajectory; export is on demand, with no automatic RSI or Wiki promotion.
- Keep the product small: no generic EventBus, remote replay, task-card system, agent-defined Hooks, or unrelated platforms.
- Do not duplicate nextloop's execution contracts or create shared implementation milestones. Product work depends only on the versioned [nextloop Adapter contract](nextloop-adapter.md).

## Route

| Stage | Main question | Required output and close condition | Status |
|---|---|---|---|
| Reusable execution | Is the Loop protocol independently understandable and verifiable? | nextloop owns ReAct, Tool admission, ContextBuilder, projection, cancellation, recovery, and delivery-only retry | Delegated to [nextloop roadmap](https://github.com/12bitsD/nextloop/blob/main/docs/architecture/discussion-roadmap.md) |
| **M3 AgentWiki** | How should Wiki actually be consumed? | Structure, retrieval, writes, maintenance, and update semantics are decided | **Done** — [agentwiki.md](../design/agentwiki.md); Git synchronization and writer coordination belong to M6/M7 |
| **M5 Product integration** | Which concrete Tool and Adapter contracts does nika supply? | Detailed Tool schemas, Prompt content, and Adapter inputs/outputs are explicit | **In progress** — [system-prompt.md](../design/system-prompt.md) and [feature worklist](feature-worklist.md) |
| Proactive | How should nika reduce the user's context-management burden? | Task-phase detection, internal updates, user-facing distillation, authorization, and interruption policy are explicit | Planned after M5; value accepted, behavior not yet designed |
| M6 Trust and resources | What can each actor and process access, and who owns each resource? | Credentials, workspace, Wiki writers, browser profiles, GUI locks, and cleanup have explicit owners and failure behavior | Pending |
| M7 Data and channels | How do external systems observe and recover nika? | Event/adapter schemas, exports, Feishu acceptance, backup, and GC are consistent with nextloop's event envelope | Pending |
| M8 Engineering | How is the product implemented and verified? | Language, package layout, dependencies, container processes, health checks, and CI are chosen | Pending |
| M9 Closure | Is the complete product implementable? | End-to-end scenarios need no invented behavior, documents agree, and implementation phases have verification and stop conditions | Pending |

## Product topics

| Topic | Remaining work | Owner and close condition |
|---|---|---|
| Tool and Adapter contracts | Per-Tool schemas, descriptions, results, errors, cancellation, timeouts, unknown outcomes, and large results | Each concrete Tool has a complete contract compatible with nextloop's ToolRuntime interface |
| Feishu ingress and delivery | Identity, dedupe, delayed/ordered events, document edits, comments, long messages, cards, and delivery receipts | Real Feishu acceptance covers each entry and failure mode, with no second execution writer |
| Knowledge and Skills | Authorized writes, validation, Git publication, dynamic Skill compatibility, and Coding Skill behavior | Write→validate→commit→publish→effective behavior and failure returns are explicit |
| Proactive behavior | Trigger scenarios, internal updates, user-facing distillation, notification dedupe, cancellation, and authorization | Each scenario states what nika may do, when it may notify, and when it must stay silent |
| Engineering and acceptance | Language, dependencies, container supervision, health, CI, migrations, and full product acceptance | A fresh checkout can be built, tested, and run; each accepted capability has normal/failure/recovery evidence |

## Stage close criteria

### M5 — Product integration

- Every concrete Tool has a schema, description, result, error, cancellation, timeout, and large-result contract.
- nika's Adapter inputs and outputs match nextloop's public interfaces without private protocol branches.
- Prompt content and WorkingContext content policy are explicit and do not duplicate nextloop's execution mechanics.
- Feishu and product acceptance scenarios are identified before implementation starts.

### M6 — Trust and resources

- Actor permissions are distinguished from process credentials.
- Shell and file writes cannot bypass Wiki write authorization.
- Every workspace, browser profile, desktop, and Wiki writer has an owner, mutual-exclusion rule, cancellation, and crash-cleanup behavior.
- Unknown effects and resource restrictions survive Run closure and process recovery until verified settlement.

### M7 — Data and channels

- `session_events` remains the only execution-history authority, with no second product Snapshot.
- Trace and AIFT exports have stable schemas and preserve Tool Call/Result correlation.
- Feishu IM, documents, comments, and cards have concrete duplicate/delay/failure acceptance scenarios.
- Backup, restore, export, and GC preserve event/asset referential consistency.

### M8 — Engineering

Language choice accounts for nextloop integration, Feishu, SQLite, BrowserUse, ComputerUse, external Tool processes, and maintenance cost. A fresh checkout has a documented build, test, and run path.

### M9 — Final review

- All product feature rows have a value, approach, and either a closed contract or an explicitly deferred reason.
- Feishu document/comment and Browser/Computer scenarios can be walked through without inventing behavior.
- ADR, CONTEXT, README, feature worklist, and this roadmap agree with nextloop's public contracts.
- All accepted capabilities remain covered by implementation phases; unaccepted additions may be parked.
- Implementation starts only after explicit user confirmation.

## Parking lot

| Idea | Why it is parked | Reopen when |
|---|---|---|
| Agent-defined Hooks | Trajectory already covers recording and audit; no concrete scenario requires automatic behavior changes | A deterministic action cannot be left to the next model decision |
| Read-only `/btw` side questions | The main Session can answer progress without another completion path | A recurring scenario requires side questions that cannot affect the main task |
| Automatic RSI or Skill promotion | Trajectory and Skills are useful without automatic self-modification | A reviewed offline evaluation and approval policy exists |
| Cross-entry Session resume | One entry per Session is sufficient for the current workflow | A real user repeatedly needs continuation in another entry |
| Vector/semantic Wiki index | M3 selected bounded grep/read | Concrete retrieval failures demonstrate aliases and keyword search are insufficient |
| Generic EventBus and replay | Only the active Feishu renderer and authoritative writes need events | A second real subscriber or remote UI requires it |
| Multiple virtual desktops or remote devices | One container and one shared desktop are enough | Parallel GUI work becomes a measured requirement |
| External coding route or coding mode | One nextloop path gives complete Trajectory with less lifecycle duplication | Native external Session compatibility is explicitly reinstated |
| Automatic Wiki promotion | Raw execution history is not curated long-term knowledge | A user-selected curation workflow exists |

## Status maintenance

At every meaningful decision:

1. Update the owning design document and feature worklist.
2. Update this roadmap's status and parking lot.
3. Check links and `git diff --check`.
4. Commit and push so the next discussion starts from the repository rather than chat memory.

This roadmap does not authorize runtime implementation.
