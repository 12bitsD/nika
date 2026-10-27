# ADR-0002: Consolidate on one AgentLoop and a container-native AgentWiki

- Status: Accepted as the current architecture baseline
- Date: 2026-10-26
- Supersedes: [ADR-0001](0001-unified-agent-runtime.md)
- Scope: product shape, runtime, Session, Trajectory, capabilities, AgentWiki, budgets, and current operational defaults

## Context

The bot should be small, easy to modify, and optimized for one real environment rather than a general agent daemon. The architecture has deliberately converged on the following:

- ordinary chat and coding use the same AgentLoop;
- there is no separate Kimi Code route, KimiCodeBridge, or coding runtime mode;
- Bot, BrowserUse, and ComputerUse all operate inside one container;
- every Session produces a complete Trajectory, with export only on demand;
- Wiki and Skill share an `AgentWiki` root but keep distinct consumption semantics;
- the exact Wiki consumption model is intentionally deferred to a dedicated deep dive.

ADR-0001's two-Engine design is superseded because it would duplicate lifecycle management already present in an external harness, complicate complete Trajectory capture, and provide less value than a single native execution path.

**2026-10-27 update:** Agent-defined Hooks are removed from the baseline. Trajectory already covers recording and audit. A Hook becomes relevant only when a concrete scenario requires automatically changing subsequent behavior, not merely recording what happened.

## Current architecture

```text
Feishu IM and document comments
              │
              ▼
      Conversation routing
      one entry → one Session
              │
              ▼
       SessionManager
  mapping + per-Session writer lock
              │
              ▼
        AgentLoop
  state + steer + model + tools
  budget + compaction + cancel
  finalization + Trajectory
              │
      ┌───────┼─────────┐
      ▼       ▼         ▼
  Tool    BrowserUse  ComputerUse
 Catalog   (container)  (container)
      │       │         │
      ▼       ▼         ▼
  AgentWiki / virtual desktop / browser / shell / files / Feishu docs

Session Store: Session catalog + append-only Trajectory + asset references
AgentWiki: Wiki knowledge + Skills, versioned with Git
```

There is one model/tool execution path. Coding quality comes from repository tools and an on-demand coding Skill, not from a separate runtime mode.

## 1. Session identity and lifecycle

One entry maps to one Session by default:

| Entry | Session mapping |
|---|---|
| Private chat | One `chat_id` maps to one Session; `/new` explicitly starts another |
| Group topic | One Feishu Thread maps to one Session |
| Partial document comment | One `comment_id` maps to one Session |
| Whole-document comments | One document maps to one shared Session |

Session metadata includes its entry, workspace, creation time, and current state. Changing a code workspace does not implicitly create a Session, but it is recorded in Trajectory.

The default is no cross-entry continuation. An explicit resume-by-Session-ID capability may be added later without changing this default.

### AgentLoop is outside Session

`Session` is durable data. `AgentLoop` is an on-demand execution procedure, not the long-term owner of a Session.

`SessionManager` resolves the entry, enforces single-writer execution, and creates or ends Runs. A new input may create a fresh AgentLoop from the persisted Session. An active Run has a lease and `run_id`; late events from an older Run are discarded.

The Mailbox belongs to the Session, so pending input does not depend on the lifetime of an AgentLoop object. It is a single ordered steer buffer; control commands bypass it.

## 2. AgentLoop semantics

### State

`AgentState` uses:

- `Idle`
- `Streaming`
- `ExecutingTool`
- `Compacting`
- `WaitingRequest`
- `WindingDown`

The externally meaningful `RunStatus` remains simple: `Running` or `Stopped`. Diagnostics may contain error detail, but there is no reason-specific retry workflow.

### Steer and stop

All ordinary messages use steer semantics; there is no separate independent-task FIFO or `/queue` command. When the AgentLoop is idle, a message starts a new Turn. While a Turn is active, the message is held in the Session's ordered input buffer and injected at the next safe model boundary. The buffer is an implementation requirement for ordering, not a separate task queue with different semantics.

During model streaming, steer waits for the current response; during Tool execution it waits for the Tool Result to be saved. After a final response is committed, further steer is deferred to the next Turn rather than reversing WindingDown into Streaming. Multiple steer inputs preserve their original order and may be injected as one batch. Acceptance and actual injection are recorded separately in Trajectory, with the corresponding model_call_id. A later independent request can therefore redirect the current task; it is not guaranteed a separate FIFO Turn.

`/stop` cancels the current AgentLoop and propagates cancellation to the model request, tools, and child processes. A later ordinary message starts a new Turn with steer semantics. No special retry command is required. Pending, not-yet-injected steer remains available for a later Turn unless the user explicitly clears it.

Historical tool calls are never replayed automatically after cancellation or restart. Incomplete calls are recorded as cancelled or unknown.

### WaitingRequest

A `WaitingRequest` is created only when the runtime explicitly needs user input to continue the current execution. An ordinary question at the end of a model response does not create this state; the user's reply to such a question starts a new Turn.

Each Session has at most one pending request. The request records its `request_id`, Session, Turn, Run, originating Tool or Agent, response shape, and the state to resume. While it is pending, the next ordinary free-text message is treated as the answer rather than entering the steer buffer. Option callbacks carry the `request_id` directly. Other steer input remains task guidance rather than an answer.

After an answer arrives, the runtime validates that the request is still pending and belongs to the current Run. It records and closes the request, then either returns the answer to the originating Tool Call or injects it into the next model request. Duplicate answers return the existing outcome without repeating effects. Late, expired, or cancelled answers never approve a new action and are not silently converted into a new task. No timeout or absence of an answer is treated as approval.

A small `request_user_input` capability may create such a request when missing information genuinely blocks progress. It supports one question with free text or a small option set, not a complex multi-question form.

### Finalization and shutdown

Mandatory finalization uses `try/finally`:

1. settle incomplete tool calls;
2. persist authoritative Session and Run events;
3. release model, Tool, browser, and computer execution resources;
4. deliver `final_message_id` and record the delivery result;
5. mark finalization finished and AgentState `Idle`, then release the Session writer lease.

Execution resources are not the Session writer lease. The lease is released only after delivery closes or a durable delivery owner has accepted responsibility, so a later Turn cannot overtake the previous final response. Delivery failure retries only delivery with the same `final_message_id`; it never reruns the model.

Optional extensions do not own mandatory persistence or cleanup.

Shutdown stops new intake, cancels active Runs, completes required authoritative writes, and closes channel and execution resources. Late events are checked against their `run_id`.

There is no generic EventBus or event replay in the current design. A single `AgentEvent` stream feeds the active Feishu renderer, while authoritative Session state is written synchronously. The complete M4 state machine and recovery matrix are in [agent-loop.md](../design/agent-loop.md).

### Exclusions

The current architecture excludes Checkpoint, conversation Rewind, and read-only `/btw` side questions. File recovery belongs to Git. A new conversational context starts with a new Session.

Agent-defined Hooks and fixed before/after Tool hook points are also excluded from the baseline. The core Tool path is simply: record the call, execute through ToolRuntime, record the result and Trajectory, then continue with the next model request.

## 3. Tool and execution capabilities

The Tool Catalog is statically registered. The current direction does not add a separate read-only approval matrix or an administrator budget ceiling. Execution still has timeouts, output limits, cancellation, and environment constraints.

### Coding

There is no coding mode. Ordinary chat and coding use the same AgentLoop and Tool Catalog. A coding Skill is loaded on demand to guide repository inspection, modification, testing, diff review, and delivery verification.

### BrowserUse and ComputerUse

Bot, browser, and virtual desktop run in the same container. There is no remote Mac or external device bridge in the current design.

- BrowserUse controls a container browser; browser contexts may be isolated per Session.
- ComputerUse controls the container virtual desktop and its applications.
- The virtual desktop is a container-level shared resource, so GUI actions are serialized with a container-level lock.
- Cancelling a Run stops later actions but does not undo a click or other action already performed.

Screenshots and other large observations are stored as assets and referenced from Trajectory rather than embedded as large binary event payloads.

## 4. AgentWiki

The accepted structure is:

```text
AgentWiki/
  AGENTS.md
  wiki/
    INDEX.md          # generated for maintenance, not required by the model
    inbox/
    projects/
    concepts/
    people/
    playbooks/
    profiles/
    references/
  skills/
```

The root provides shared Git versioning and synchronization. Wiki is the only long-term knowledge source; there is no separate Memory service or automatic Recall Subagent. Wiki and Trajectory remain distinct: Wiki stores curated knowledge, while Trajectory records execution facts. Raw Trajectory is not automatically promoted into Wiki.

`AGENTS.md` contains the Agent's evolving role, personality, and interaction style. It is maintained independently from the runtime-owned System Prompt and injected as a separate runtime context message at Session bootstrap.

### Wiki consumption

The baseline is [agentwiki.md](../design/agentwiki.md): shallow dynamic categories, self-describing Markdown headers, `grep → read` retrieval, bounded `ls` for write-time discovery, and structural write validation. There is no mandatory `list`, semantic Recall service, vector index, or per-entry INDEX.

Each entry owns its `id`, `kind`, `state`, `summary`, `keys`, and optional `related`, `verified`, and `replaced_by` metadata. Relations use stable IDs rather than paths. Lifecycle states are `draft`, `active`, and `superseded`.

`wiki/INDEX.md` is generated from entry headers by maintenance. It is excluded from normal Wiki grep and is never required for reads, writes, or immediate retrieval. It exists for global inventory and long-term maintenance, not as a model bootstrap dependency.

### Skills follow progressive disclosure

Skills use standard `SKILL.md` packages with metadata and optional scripts, references, and assets.

The Agent receives a small, stable index of names, descriptions, paths, and content hashes separately from the runtime-owned System Prompt. When a task matches, the Agent calls a Skill-loading tool and receives the full instructions as a tool result. Supporting files are read on demand rather than injected with the index.

The current Turn keeps a stable Skill index; a later Turn may load a new version. There is one Wiki-backed Skill source rather than a hierarchy of overlapping sources. `skills/wiki/SKILL.md` teaches Wiki retrieval, writing, source handling, category creation, and maintenance without duplicating that manual in System Prompt.

### Deferred agent-defined Hooks

Agent-defined Hooks are in the roadmap parking lot, not in the current AgentWiki structure or AgentLoop contract. Recording, audit, and Tool traces are produced directly by Trajectory.

This topic should reopen only for a concrete requirement that must automatically change subsequent execution—for example, a deterministic action that cannot be left to the next model decision. At that point the event, activation, timeout, recursion, and failure semantics need a fresh design rather than reviving the old proposal by default.

## 5. Trajectory and SessionCatalog

Every Session produces an append-only Trajectory. Recording is a core AgentLoop responsibility, not an optional extension or an RSI feature.

Recorded events include:

- user input, steer, model requests and output;
- tool-call parameters, results, errors, and duration;
- Browser/Computer actions and observations;
- WorkingContext and budget changes;
- compaction;
- cancellation and finalization;
- Session creation, recovery, and workspace changes.

Conversation is a model-facing projection of this record. Compaction adds a new event and does not rewrite old events.

`SessionCatalog` provides three atomic operations:

```text
list_sessions(filter, cursor, limit)
get_trajectory(session_id, after_seq?, limit?)
export_trajectories(session_ids, format, destination)
```

Batch export is explicit and synchronous from the caller's perspective. It streams data into an archive with a manifest and one JSONL file per Session. There is no background export or automatic training pipeline.

Two export projections are defined:

- `trace/v1`: full runtime and interaction events for diagnosis and analysis;
- `aift/v1`: a model-interaction projection containing `session_id`, `messages`, `tools`, and necessary metadata. Assistant tool calls and tool results remain correlated; internal runtime events are omitted by default.

A provider-specific training chat template is a later conversion from `aift/v1`, not the authoritative Session format.

## 6. Provider, compaction, and budgets

Multiple model providers and models are supported through configuration. Streaming and bounded retries are supported. Retry honors `Retry-After` where available and uses bounded exponential backoff with jitter.

The evolving M5 contract is in [context-builder.md](../design/context-builder.md). Within one compaction boundary and fixed prompt revisions, provider-visible content is immutable and append-only: previous Tool definitions, system content, conversation messages, and WorkingContext versions are not rewritten. New committed content is appended to maximize prompt-cache reuse. Compaction may establish a new Conversation prefix without rewriting Trajectory.

Context usage comes from provider-reported usage when available. A local estimate is only a fallback. Before every model request, AgentLoop evaluates the newly assembled request, including subsequent Tool Results, steer, WorkingContext, and Skill changes.

Compaction starts at **75%** of the model context window. It never interrupts an in-flight model request or Tool action: the current response or Tool Result is saved first. Steer arriving during compaction waits until compaction completes and is injected before the next model request.

### Compactor mechanism

Compaction is an internal `Compactor` module, not a Tool in the Tool Catalog. It runs four phases:

1. **Deterministic cleanup** removes duplicate Tool Results, bounds old large outputs with head/tail preservation and asset references, removes inline binary payloads, and preserves Tool Call/Result pairing plus required recent messages. There is no separate frequently running micro-compaction; this phase runs only as part of full compaction.
2. **Internal model summarization** uses a direct model request rather than a Tool Call. The summary preserves the current goal, user constraints, confirmed decisions, completed work, active work and next steps, open questions, required Tool Results and asset references, current budget, waiting state, and latest active WorkingContext. The current Session model is the default; a separate `compaction_model` is a later optional optimization.
3. **Validation** requires a nonempty summary and verifies that the current goal, unfinished work, latest active WorkingContext, Run identity, budget, waiting state, and Tool Call/Result pairing remain recoverable.
4. **Append-only commit** appends the compaction event and its model usage. Subsequent Conversation projections are derived from the latest compaction event and the events after it; there is no persistent Snapshot to synchronize. Old Trajectory is never rewritten and is not automatically promoted to Wiki.

If summarization or validation fails, the previous event-derived projection remains authoritative and no partial compaction event is committed. The failed oversized request is not sent as though compaction had succeeded.

If the provider rejects a request for context overflow despite the 75% check, AgentLoop may force full compaction once and retry the same logical request within the same Run. A second overflow is terminal; it does not loop or fall back to an unreviewed lossy truncation. The summary request reuses the unchanged history prefix where possible; the new compaction-derived projection becomes a new prompt-cache boundary.

Only the latest active WorkingContext is preserved through compaction; superseded versions and invalidation markers are omitted from the new projection.

### WorkingContext

WorkingContext is a short, user-level self-reminder maintained by the Agent:

- `set_working_context` appends a new version rather than rewriting earlier provider-visible content; the newest active version supersedes earlier versions;
- `clear_working_context` appends an invalidation marker rather than deleting history;
- no `reason` field is required;
- default scope is the current Run, with Session scope available for continuation across Turns;
- a Run ending with active Run-scoped WorkingContext appends an invalidation marker so later Runs do not treat it as active;
- older versions and invalidation markers remain in the current provider-visible history until compaction, which keeps only the latest active version or none after clear/expiry;
- its user-level role does not rewrite the real user message or override system rules, current user instructions, or tool permissions;
- set, clear, and Run-expiry operations are recorded in Trajectory.

This append-versioned contract supersedes the earlier replace/remove and dynamic-tail-overlay design.

### Proactive is separate

Proactive context management is a later, independent mechanism. Its accepted value is to reduce the user's context-management burden and release cognitive bandwidth, but task-phase detection, update triggers, user-facing distillation, and interruption policy are not responsibilities of WorkingContext or ContextBuilder alone.

### Budget profiles

| Profile | Tool calls | Run timeout | Single model output | Tool output |
|---|---:|---:|---:|---:|
| `lite` | 50 | 5 min | 8K tokens | 20 KB |
| `pro` | 200 | 20 min | 32K tokens | 40 KB |
| `promax` | 800 | 60 min | 64K tokens | 100 KB |

`pro` is the default. `configure_budget` can select a profile or override values for the current Run or Session. There is no administrator hard ceiling. A Run that is already exhausted ends; it is not silently extended after the fact.

Every attempted tool call counts, including failed or rejected calls. Parallel calls count individually.

## 7. Feishu

Feishu is the primary channel, using long-lived event connections rather than requiring a public webhook.

The target capability level is the relevant yomi Feishu behavior:

- private chat, group mention, and Thread routing;
- message deduplication and sender identity checks;
- document read, create, and edit;
- document-comment mention triggers, comment history, and replies;
- partial-comment Session isolation and whole-document shared Sessions;
- long-message handling, reactions, status and interaction cards;
- Tool trace rendered from Trajectory rather than a separate instrumentation system.

Platform-specific response fallbacks and comment-read races should reuse verified yomi behavior rather than being rediscovered.

## 8. Persistence, backup, and GC

Authoritative Session and Run writes are synchronous before final delivery. Asynchronous work is limited to backup, export, and non-authoritative telemetry.

Storage uses **SQLite with WAL and `synchronous=FULL`**. Each state change is committed as one append-only event; there is no persistent Snapshot to keep synchronized. Large observations and outputs live as external assets referenced by events; an asset is persisted before its event may reference it. The core write path does not maintain FTS or other secondary indexes beyond those required for Session, event, and delivery queries. No dedicated storage benchmark is required for this choice; revisit optimization only if real latency or contention appears.

Session and Trajectory data live on persistent container storage. Backups use SQLite online backup plus asset snapshots. Raw Trajectories are not committed to the public repository.

GC is required for disk safety but is manually initiated in the current design. It supports dry-run, age filters, and active/pinned exclusions. There is no default automatic deletion of Sessions.

## Consequences

- One execution path owns all native Sessions and can produce complete Trajectory.
- Coding, chat, BrowserUse, and ComputerUse no longer require alignment across two harnesses.
- AgentLoop is replaceable because durable state belongs to Session, not to a long-lived loop object.
- AgentWiki provides one versioned root for long-term knowledge and Skill instructions.
- The architecture avoids a generic EventBus, remote device bridge, external coding harness, coding mode, agent-defined Hooks, automatic RSI, and automatic Trajectory export.
- Full Trajectory increases storage and data-sensitivity requirements; backup and export handling must treat it as private operational data.
- A shared virtual desktop limits concurrent GUI execution unless more displays are introduced later.

## Open topics

The live feature-by-feature status and remaining decisions are tracked in [feature-worklist.md](../architecture/feature-worklist.md).

- **AgentLoop internals** — M4 baseline closed in [agent-loop.md](../design/agent-loop.md); remaining work is event schema, numeric timeouts, and implementation tests.
- **Prompt assembly** — one deterministic ContextBuilder, revision policy, multi-model switching, and prompt-cache behavior.
- **Execution trust and resources** — actor trust, credential isolation, child-process environment, browser login state, and ownership of shared resources.
- **Session projection and recovery** — exact event-to-context projection, validation of interrupted or malformed events, and recovery behavior. There is no persistent Snapshot or second execution-history authority.
- **M3: Wiki consumption** — bootstrap, retrieval, automatic recall, writeback, caching, and compaction for Wiki content.
- Implementation language, code layout, deployment details, and CI. Rust and Python remain the candidates; container Browser/Computer ecology is a primary deciding factor.
- Detailed compaction summary structure and preservation policy beyond the 75% trigger and provider-usage anchor.
- Exact persistence schema, backup schedule, and retention values.
- Provider-specific conversion from `aift/v1` to a concrete training chat template.
- Deferred agent-defined Hooks and any future RSI policy. These are parked, not part of the current baseline.
