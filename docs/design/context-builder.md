# ContextBuilder design

Status: **M5 in progress**. This document records confirmed context and cache decisions separately from proposals that still need discussion. It does not authorize runtime implementation.

## Purpose

ContextBuilder assembles each provider-facing model request from Session projections and current execution state. Its primary optimization is prompt-cache reuse through an immutable, append-only request prefix, subject to correctness, relevance, and provider capacity limits.

A Session and its Trajectory can outlive any individual model request. The provider context window is a per-request capacity limit, not a Session-sized store. Prompt caching can reduce cost and latency, but cached tokens still occupy the provider context window.

## Confirmed decisions

### Append-only provider-visible content

Within one compaction boundary and a fixed set of prompt revisions, previously submitted Tool definitions, system content, and conversation messages remain unchanged. New assistant messages, Tool Calls, Tool Results, user input, steer, and WorkingContext versions are appended rather than inserted into or replacing earlier content.

This is a logical provider-visible content-prefix guarantee; canonical serialization and each provider's wire mapping remain M5 implementation-contract work. Compaction creates a new Conversation prefix, while the underlying Trajectory remains append-only and immutable.

The intended cache model is:

```text
Request N
= established provider-visible prefix + current appended content

Request N+1
= the same established content, unchanged
+ newly committed assistant / tool / user / WorkingContext content
```

Correctness and relevance take precedence over cache hit rate. A required compaction or an accepted revision change may establish a new prefix; routine model calls must not do so accidentally.

### System Prompt, AGENTS.md, and Tools

The top-level request shape is `tools[] + system + messages[]`. The former `stable / context / volatile` System Prompt tiering is removed.

System Prompt is a small runtime-owned contract for action, verification, trust, and harness usage. It does not contain the evolving persona, recent tasks, Wiki snapshots, WorkingContext, budget balances, dynamic request IDs, or per-call timestamps. Tool-specific arguments belong in Tool schemas rather than a central Prompt manual.

`AgentWiki/AGENTS.md` maintains the Agent's evolving role, personality, and interaction style. Its snapshot is injected as a separate runtime context message in the first request of a Session, not compiled into System Prompt, and is changed or refreshed only when the user explicitly requests it. Skill metadata is separate from the runtime-owned System Prompt and dynamic at the point of use: a later Skill load may read the current version, with updated context appended rather than rewritten. Wiki entries are likewise read live with `grep → read`, without a required revision record or a default recent-task snapshot.

Tools use a small static catalog with clear semantics. The runtime resolves Session, workspace, credentials, defaults, validation, retries, resource ownership, large-output assets, and error normalization so the model does not repeat those details. There is no universal `execute(action, payload)` Tool and no Tool Search in the baseline. An MCP adapter and allowlist configuration are reserved, but MCP is disabled and contributes no schemas by default.

### WorkingContext is append-versioned

WorkingContext is a short, user-level self-reminder maintained by the Agent. A Session has at most one active WorkingContext at a time; Run and Session are lifetime scopes, not two parallel reminder slots.

- `set_working_context(content, scope="run" | "session")` appends a new active version. The newest version supersedes the previous active version, including across scopes. Identical content and scope return `WorkingContext unchanged` without appending a message.
- `clear_working_context()` clears the current active version. Clearing an already empty context returns `WorkingContext is already empty` without appending a message.
- No `reason` field is required. Tool Results are short success or error text, not a lifecycle-state schema. Revisions remain internal to Runtime and Trajectory.
- Active messages use `[WorkingContext · run]` or `[WorkingContext · session]` followed by the reminder. Clear and Run expiry append `[WorkingContext cleared · scope]` or `[WorkingContext expired · scope]`; old bytes are never rewritten.
- Content is trimmed, nonempty, and at most 2 KiB UTF-8. Oversized input is rejected rather than silently truncated. Long-term knowledge, large plans, and hidden reasoning do not belong here.
- After a valid set or clear, Runtime commits the Tool Result and state event, appends the corresponding user-level message, then appends pending steer before the next model call. Actual user input therefore follows the Agent's self-reminder.
- Run-scoped context expires at Run finalization. Recovery from an interrupted Run appends the missing expiry before a new Turn. Session-scoped context expires only through replacement or an explicit clear.
- Compaction preserves only the latest active WorkingContext, immediately after the latest task summary and before subsequent messages. Older versions and clear/expiry markers are omitted; if no active context exists, none is injected.
- The user-level role provides salience, not user authorization. WorkingContext cannot override system rules, actual user instructions, or Tool permissions.

This supersedes both the earlier replace/remove design and the later revision/status-heavy Tool Result and message-envelope proposal.

### Proactive is a separate mechanism

The value of proactive behavior is accepted: the Bot should reduce the user's context-management burden and release cognitive bandwidth by organizing task context, verifying facts within existing authorization, and surfacing only meaningful decisions and state changes.

That behavior is not implemented by WorkingContext or ContextBuilder alone. Task-phase detection, update triggers, user-facing distillation, and interruption policy require a separate design topic after the M5 context baseline is closed.

## Remaining M5 decisions

### 1. System Prompt and Tool Catalog

Finalize each Tool's schema and description. The runtime-owned System Prompt and first static Tool Catalog are selected in [system-prompt.md](system-prompt.md). The top-level `tools[] + system + messages[]` shape, independent `AGENTS.md` bootstrap, removal of System Prompt tiers, and absence of baseline Tool Search are accepted.

### 2. Revisions and provider cache planning

Define when model, Tool, Skill, and project-context revisions may change; canonical serialization; OpenAI/Kimi implicit caching; Anthropic explicit cache breakpoints; and when retries must preserve request bytes. The WorkingContext contract is closed: one active version per Session, short Tool Results, 2 KiB content, and compaction immediately after the task summary.

### 3. Content budgets

Assign budgets to system content, Tool schemas, Skill index, Conversation, WorkingContext, and multimodal content. Define what is loaded on demand or stored as an asset instead of occupying the request.

### 4. Usage and preflight

Finalize provider-reported usage, anchored estimates, full local fallback estimates, the 75% compaction trigger, and whether the hard admission check explicitly includes `input + reserved output` capacity. The output-reserve rule is still a proposal, not an accepted addition.

### 5. Compaction details

Finalize the compaction instruction, validation, failure/cancellation/crash behavior, second-overflow handling, the new cache boundary, and whether manual `/compact` belongs in the first version. The summary is a normal Agent-generated task summary without a fixed schema or mandatory Wiki/Skill/revision checklist.

### 6. Budget-change boundaries

Define when Run and Session budget changes take effect, including shrinking, expansion, timeout recalculation, and interactions with in-flight operations.

## Verification requirements for the eventual implementation

- Two ordinary model calls preserve all earlier provider-visible content and append only new committed events.
- WorkingContext set, replacement, clear, Run expiry, and compaction follow the append-versioned contract without rewriting old events.
- Tool Calls and Tool Results remain complete and correctly paired across every request and compaction boundary.
- Equivalent inputs produce canonical, explainable request bytes; accepted revision changes are explicit and measurable.
- Cache misses caused by compaction or revision changes are distinguishable from accidental serialization drift.
- Compaction uses the same System Prompt and `AGENTS.md`, produces a nonempty and smaller task summary, preserves runtime state in Session, and keeps the latest active WorkingContext.
- The 75% trigger, provider-capacity admission check, compaction failure, and provider-overflow recovery are exercised at their exact boundaries.
