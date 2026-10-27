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

### WorkingContext is append-versioned

WorkingContext is a short, user-level self-reminder maintained by the Agent during execution. It is not long-term Wiki memory, a permission channel, or the proactive mechanism itself.

- `set_working_context` appends a new version. The newest active version supersedes earlier versions; it does not rewrite their provider-visible bytes.
- `clear_working_context` appends an invalidation marker. It does not delete earlier messages.
- No `reason` field is required.
- The default scope is the current Run; Session scope is explicit.
- When a Run ends with an active Run-scoped WorkingContext, an appended invalidation marker closes it for later Runs.
- Older versions and invalidation markers can remain in the current provider-visible history until compaction. They are not the latest active reminder.
- Compaction preserves only the latest active WorkingContext, or none if it was cleared or expired. Old Trajectory events remain unchanged.
- The user-level role provides salience, not user authorization. WorkingContext cannot override system rules, actual user instructions, or Tool permissions.
- Set, clear, and Run-expiry events are recorded in Trajectory.

This supersedes the earlier design in which WorkingContext was replaced or removed in place and only the latest text was injected as a dynamic request-tail overlay.

### Proactive is a separate mechanism

The value of proactive behavior is accepted: the Bot should reduce the user's context-management burden and release cognitive bandwidth by organizing task context, verifying facts within existing authorization, and surfacing only meaningful decisions and state changes.

That behavior is not implemented by WorkingContext or ContextBuilder alone. Task-phase detection, update triggers, user-facing distillation, and interruption policy require a separate design topic after the M5 context baseline is closed.

## Remaining M5 decisions

### 1. Request structure and system tiers

Define the final `tools / system / messages` contract and the contents and ordering of `stable / context / volatile` system tiers, including Skill index and Session/runtime information.

### 2. WorkingContext concrete contract

Define the provider message envelope, size limit, exact set/clear event ordering, Run and Session expiry details, validation, and compacted representation.

### 3. Revisions and provider cache planning

Define when model, Tool, Skill, and project-context revisions may change; canonical serialization; OpenAI/Kimi implicit caching; Anthropic explicit cache breakpoints; and when retries must preserve request bytes.

### 4. Content budgets

Assign budgets to system content, Tool schemas, Skill index, Conversation, WorkingContext, and multimodal content. Define what is loaded on demand or stored as an asset instead of occupying the request.

### 5. Usage and preflight

Finalize provider-reported usage, anchored estimates, full local fallback estimates, the 75% compaction trigger, and whether the hard admission check explicitly includes `input + reserved output` capacity. The output-reserve rule is still a proposal, not an accepted addition.

### 6. Compaction details

Finalize the summary schema, protected and recent suffixes, validation, failure/cancellation/crash behavior, second-overflow handling, the new cache boundary, and whether manual `/compact` belongs in the first version.

### 7. Budget-change boundaries

Define when Run and Session budget changes take effect, including shrinking, expansion, timeout recalculation, and interactions with in-flight operations.

## Verification requirements for the eventual implementation

- Two ordinary model calls preserve all earlier provider-visible content and append only new committed events.
- WorkingContext set, replacement, clear, Run expiry, and compaction follow the append-versioned contract without rewriting old events.
- Tool Calls and Tool Results remain complete and correctly paired across every request and compaction boundary.
- Equivalent inputs produce canonical, explainable request bytes; accepted revision changes are explicit and measurable.
- Cache misses caused by compaction or revision changes are distinguishable from accidental serialization drift.
- The 75% trigger, provider-capacity admission check, compaction failure, and provider-overflow recovery are exercised at their exact boundaries.
