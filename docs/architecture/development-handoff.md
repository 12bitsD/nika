# nika product handoff

Last verified: 2026-11-06. Execution baseline: `main@96135332fb4e5b4d9e2621afd63af6803c2a886d`; repository split: nextloop ADR-0001. This is a dated handoff, not a second roadmap. Product status remains in [discussion-roadmap.md](discussion-roadmap.md).

## What nika is now

nika maintains the complete personal agent and superagent architecture: personal assistance, goal and verification ownership, Proactive behavior, AgentWiki, Skills, Feishu, concrete Tools, product data, and deployment. [nextloop](https://github.com/12bitsD/nextloop) is only the reusable execution library.

The split does not create a second Agent, Router, EventBus, or service. nika calls nextloop through adapters. nextloop does not know Feishu IDs, Wiki paths, or nika's desktop locks. The name superagent does not itself adopt Router/Worker, background jobs, or a multi-agent framework.

## Product flow

```text
Feishu IM / Thread / document comment
  → nika resolves entry → Session
  → nika adapters invoke nextloop
  → nextloop drives model, Tools, context, cancellation, and finalization
  → nika supplies concrete Tools, assets, and Feishu delivery
```

nextloop owns execution identities, input/final-response order, Tool admission and outcomes, event projection, cancellation, recovery, and delivery-only retry. nika owns channels, knowledge, concrete Tools, product state, and product acceptance.

## Current product assets

- [System Prompt](../design/system-prompt.md): selected task-flow Prompt and Tool Catalog.
- [Compaction Prompt](../design/compaction-prompt.md): selected task-state reconstruction Prompt.
- [AgentWiki](../design/agentwiki.md): Wiki structure, live grep/read, write authorization, retrieval budgets, and maintenance INDEX.
- [ADR-0002](../adr/0002-single-agent-loop.md): product architecture boundary.
- [Feature worklist](feature-worklist.md): product capabilities and remaining decisions.
- [Roadmap](discussion-roadmap.md): product topics and closure conditions.

nextloop's canonical execution documents are [AgentLoop](https://github.com/12bitsD/nextloop/blob/main/docs/design/agent-loop.md), [ContextBuilder](https://github.com/12bitsD/nextloop/blob/main/docs/design/context-builder.md), [capability review](https://github.com/12bitsD/nextloop/blob/main/docs/architecture/agent-loop-capability-review.md), and [research](https://github.com/12bitsD/nextloop/tree/main/docs/research). Former Loop paths in this repository contain navigation pointers only.

## Progress

- **M3 AgentWiki: done**, except Git synchronization and writer coordination, which belong to M6/M7.
- **nextloop M4 lifecycle baseline: recorded.** ReAct follow-up is open there.
- **M5 product integration: in progress.** Detailed Tool schemas and Adapter contracts remain.
- **Proactive: planned after M5.** Its value is accepted, but triggers, internal updates, user-facing distillation, and interruption policy are not designed.
- **M6–M9: pending.** Trust/resources, data/channels, engineering, and final closure are not closed.

There is no runtime implementation, test suite, Dockerfile, CI workflow, release, or deployment result. Prompt scores are text/scenario reviews, not live model success rates.

## Product questions that remain

| Area | What still needs a decision |
|---|---|
| Tool and Adapter contracts | Each Tool's schema, description, result, error, cancellation, timeout, unknown outcome, and large-result example; Adapter compatibility with nextloop |
| Proactive | Which events deserve internal updates or user notification, what nika may do without new authorization, and how to dedupe or stop notifications |
| Trust and resources | Actor versus process credentials; Shell/file writes cannot bypass Wiki authorization; workspace/profile/GUI/Wiki writer ownership, locks, and cleanup |
| Feishu and delivery | Entry identity, dedupe, delayed events, document block edits, comment races, long messages, cards, delivery receipts, and durable handoff |
| Data and operations | Product payload schema, exports, backup/restore, GC, asset retention, and disk-full behavior |
| Engineering | Language, dependencies, package layout, container supervision, health, CI, and migration |

## Reading order

1. [ADR-0002](../adr/0002-single-agent-loop.md) for the product boundary.
2. [Roadmap](discussion-roadmap.md) for current product topics and closure.
3. [Feature worklist](feature-worklist.md) for remaining product capabilities.
4. [AgentWiki](../design/agentwiki.md) and the two Prompt files for knowledge and content policy.
5. nextloop's [roadmap](https://github.com/12bitsD/nextloop/blob/main/docs/architecture/discussion-roadmap.md) and [feature worklist](https://github.com/12bitsD/nextloop/blob/main/docs/architecture/feature-worklist.md) for execution work.

The next implementation step is to finish Tool/Adapter contracts jointly with nextloop's ReAct protocol, then close Proactive and M6/M7 before choosing the engineering stack. No runtime implementation is authorized by this handoff.
