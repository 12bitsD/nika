# Feature worklist

Purpose: close the architecture feature by feature. Each row states the user value, the currently accepted approach, and what still needs a decision. “Accepted approach” does not mean the feature is implemented. **Open** marks a material design choice that should be closed before implementation.

## Core execution

| Feature | Value | Current approach | Remaining decision |
|---|---|---|---|
| AgentLoop | One understandable execution path for chat and coding | On-demand procedure outside Session; explicit state machine, model/tool order, cancellation, finalization, and interruption recovery. Baseline: [agent-loop.md](../design/agent-loop.md) | M4 baseline closed; remaining work is event schema, numeric timeouts, and implementation tests |
| SessionManager | Continue conversations without long-lived loop objects | Resolve entry to Session, enforce single-writer execution, create/end Runs | Lease recovery and stale-run detection after process failure |
| Session identity | Keep unrelated conversations separate | One private chat, Thread, partial comment, or whole-document area per Session | Explicit cross-entry resume can remain a later option |
| Mailbox and steer | Accept follow-up or redirection without a separate task-queue mode | Every ordinary message uses steer semantics: idle starts a Turn; active input is ordered in the Session buffer and injected at the next safe model boundary; acceptance and injection are recorded separately | Exact merge point and behavior while executing a non-model Tool |
| WaitingRequest | Pause for input that is required to continue the current execution | Runtime-created request with `request_id` and Run identity; free text answers bypass the steer buffer; validated answers resume the original Tool/model request; duplicates and stale answers have no new effects | Feishu presentation, timeout UX, and exact `request_user_input` result schema |
| Cancellation and finalization | Stop honestly without replaying side effects | Cancel current loop and children, settle incomplete calls, persist, release, then deliver | Stop timeout and handling of actions whose outcome cannot be confirmed |
| ContextBuilder | Make every model request explainable, reproducible, and cache-friendly | One deterministic Prompt assembly point; within a compaction boundary and fixed revisions, previous provider-visible content remains unchanged and new content is appended. Selected Prompt: [system-prompt.md](../design/system-prompt.md). Context contract: [context-builder.md](../design/context-builder.md) | **Open / M5:** detailed Tool schemas and descriptions, content budgets, revision/cache planners, usage preflight, compaction details, and budget-change boundaries |
| Compaction | Continue long Sessions within a bounded context without rewriting history | Internal `Compactor`, not a Tool: check before every model request at 75%; use the same System Prompt, `AGENTS.md`, and Conversation with a final summarize instruction and Tools disabled. The Agent keeps necessary task context without a fixed schema. Validate nonempty, actual reduction, unchanged bootstrap content, and complete Tool pairing; append a compaction event and rebuild from it plus later events. Provider overflow forces full compaction once, with no second retry or unreviewed lossy fallback | Compaction instruction, failure/cancellation/crash behavior, second-overflow handling, new cache boundary, and optional manual `/compact`; optional `compaction_model` is deferred |
| WorkingContext | Let the Agent maintain a lightweight current reminder | One active user-level reminder per Session; set/clear append versions or markers without rewriting old content. Tool Results are short text; content is limited to 2 KiB. Compaction keeps only the latest active version immediately after the task summary | **Closed design** — implementation tests remain for idempotency, scope expiry, event ordering, and compaction position |
| Budget profiles | Match resources to task size without administrator micromanagement | `lite/pro/promax`; default `pro`; Agent can configure Run or Session budgets | Exact change-effective boundaries and whether any values need adjustment after real usage; no administrator hard ceiling |
| Proactive context management | Release the user's cognitive bandwidth by reducing manual task framing, retrieval, distillation, and follow-up | Separate later mechanism, not a responsibility of WorkingContext or ContextBuilder alone; its value is accepted but it is not in the current runtime baseline | **Open / special topic after M5:** task-phase detection, internal update triggers, user-facing distillation, authorization boundaries, and interruption policy |

## Tools and channels

| Feature | Value | Current approach | Remaining decision |
|---|---|---|---|
| Tool Catalog and ToolRuntime | One capability surface with consistent execution | Static Tool Catalog, cancellation, timeouts, output limits, per-resource serialization | **Open:** serial versus parallel calls and complete resource ownership rules |
| Coding Skill | Better repository work without a separate mode | On-demand instructions for inspection, modification, testing, diff review, and delivery | Concrete Skill content is implementation work, not a new runtime mode |
| BrowserUse | Complete browser tasks inside the same environment | Container browser, per-Session contexts where useful, observations in Trajectory | Browser distribution and profile/login-state policy after language choice |
| ComputerUse | Operate desktop applications without a remote device | Container virtual desktop, container-level GUI lock, action and observation recording | Virtual desktop stack, application set, crash recovery, coordinate scaling |
| Feishu IM | Natural chat, group, and Thread interaction | Long-lived connection, identity and dedupe, private/group/Thread routing | Real-client acceptance matrix and failure/retry behavior |
| Feishu documents | Read and produce collaborative documents | Read, create, and edit documents through the same Bot capabilities | Detailed block-edit behavior and size/rate-limit handling |
| Document comments | Wake the Bot at the exact discussion location | `@` trigger, comment history, partial/whole routing, reply in the comment area | Whether participating comments later allow follow-ups without `@`; current default is strict `@` |
| Cards and Tool trace | See progress, control execution, and inspect Tool use | Cards for status/interaction; Tool trace is a view over Trajectory | Minimum useful card set and presentation details |

## AgentWiki and self-extension

| Feature | Value | Current approach | Remaining decision |
|---|---|---|---|
| AgentWiki root | One versioned home for evolving agent behavior, long-term knowledge, and Skill assets | `AGENTS.md`, `wiki/`, and `skills/` share Git sync/versioning but not consumption semantics | Synchronization and publication workflow details |
| Wiki | Recover long-term facts and SOP without a separate memory service | Shallow dynamic categories, self-describing Markdown entries, live `grep → read` retrieval, bounded `ls` for writes, stable-ID relations, structural validation, and a maintenance-generated INDEX excluded from normal grep. Writes default to `draft_only`; ordinary active writes need `curate`, behavior files need `behavior`. Retrieval defaults: 10 header candidates, 20 body matches with 5 per file and 2 context lines, 16 KiB grep/read outputs and 200-line reads. Baseline: [agentwiki.md](../design/agentwiki.md) | M3 closed; Git synchronization and writer coordination belong to M6/M7 |
| SkillLoader | Reuse working methods without injecting every Skill | Standard `SKILL.md`, metadata index outside runtime-owned System Prompt, current content loaded on demand; updated context is appended rather than pinned for a Turn. Wiki Skill teaches Wiki usage | Compatibility policy for dynamic Skill changes |
| WorkingContext vs Skill | Keep two kinds of behavior guidance distinct | WorkingContext is a current reminder, Skill is reusable instructions | No automatic promotion between them or automatic RSI |

## Trajectory and data

| Feature | Value | Current approach | Remaining decision |
|---|---|---|---|
| TrajectoryRecorder | Know what actually happened in every Session | Mandatory append-only logical events in the AgentLoop, not optional instrumentation; the only execution-history authority | **Open:** field-level event schema and projection/rebuild rules |
| Assets | Preserve large observations without bloating event payloads | Store files separately and reference them with content identity | Asset lifecycle, size limits, deduplication, and backup format |
| SessionCatalog | Find Sessions and inspect their history | `list_sessions`, `get_trajectory` with cursor-based pagination | Filter fields, access rules, and handling of incomplete records |
| Batch export | Analyze or reuse Sessions only when explicitly requested | On-demand archive with manifest and one JSONL per Session; no background export | Streaming archive layout and failure/resume behavior |
| `trace/v1` | Preserve full evidence for diagnosis | Full runtime and interaction events | Final versioned field definitions |
| `aift/v1` | Reuse model interactions for training workflows | `session_id`, `messages`, `tools`, and necessary metadata; tool calls/results correlated | Provider-specific chat-template conversion remains a separate projection |
| Session projection | Restore current context without replaying side effects or keeping a second persistent truth | Derive from Trajectory starting at the latest compaction and subsequent events; current WorkingContext, budget, workspace, and delivery state are computed from events | Exact projection and validation rules for interrupted or malformed events |

## Operations and engineering

| Feature | Value | Current approach | Remaining decision |
|---|---|---|---|
| Persistent storage | Recover Sessions after restart | SQLite with WAL and `synchronous=FULL` on a persistent container volume; each state change is one append-only event with no persistent Snapshot; assets external and persisted before event references; no FTS in the core write path; synchronous authoritative writes | Exact schema, migration, transaction, and corruption recovery. No dedicated storage benchmark is required unless real latency or contention appears |
| Backup | Avoid losing operational history | SQLite online backup plus asset snapshots; raw Trajectory stays out of public Git | Schedule, destination, encryption, retention, and restore drills |
| GC | Bound disk usage | Manual, dry-run capable, age filters, active/pinned exclusions; no default auto-delete | Disk budget, retention values, and asset cleanup ordering |
| Execution trust and credentials | Allow rich Tools without exposing every resource to every process | Current baseline does not add a read-only approval matrix or administrator budget ceiling | **Open:** actor trust, secret injection, child-process environment, browser login state, network/file reach |
| Deployment | One reproducible environment for Bot and GUI work | Single container with Bot, browser, and virtual desktop | Process supervision, health checks, persistent mounts, and resource limits |
| Language and code layout | Keep the system stable and easy to modify | Candidates: Rust or Python; container Browser/Computer ecology is a primary factor | **Open:** language, package layout, dependency policy |
| CI | Catch regressions as features are implemented | GitHub-hosted public repository; CI not yet defined | **Open:** formatting, tests, container build, and real smoke-test levels |

## Parking lot

| Idea | Why it is parked | Reopen when |
|---|---|---|
| Agent-defined Hooks | Trajectory already covers recording and audit; no current scenario requires automatically changing subsequent behavior | A concrete deterministic action is required that cannot be left to the next model decision; then design the event, activation, recursion, timeout, and failure semantics |
| Read-only `/btw` side questions | An IM bot can answer progress through the main Session; a separate completion adds concurrency without a concrete use case | A recurring scenario needs side questions that must not affect the main task |
