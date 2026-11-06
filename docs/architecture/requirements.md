# nika requirements map

This map records accepted product requirements and their verification ownership. It does not replace the linked contracts. Status describes design and implementation separately; no requirement is implemented by being listed here.

| ID | Requirement and user value | Authoritative design | Status and acceptance required |
|---|---|---|---|
| N1 | Talk privately, in groups/Threads, and at document comments | [ADR-0002 §6](../adr/0002-single-agent-loop.md) | **M7 open.** Real Feishu identity, dedupe, delay/order, reply, rate-limit, and recovery acceptance |
| N2 | Read, create, and edit Feishu documents and comments | [ADR-0002 §6](../adr/0002-single-agent-loop.md) | **M7 open.** Block edit, read-back, comment race, partial success, and target-object verification |
| N3 | Complete chat and coding through one execution path | [nextloop AgentLoop](https://github.com/12bitsD/nextloop/blob/main/docs/design/agent-loop.md), [Coding Skill](../design/system-prompt.md) | **M5 open.** Adapter contract, code inspection/modification, relevant tests, and delivery verification |
| N4 | Reuse a verified Loop instead of maintaining a second runtime | [nextloop ADR-0001](https://github.com/12bitsD/nextloop/blob/main/docs/adr/0001-embeddable-agent-loop.md) | **M5 open.** EventStore/Provider/ContextBuilder/Compactor/ToolRuntime/DeliveryOwner adapter compatibility |
| N5 | Recover long-term projects, concepts, people, SOPs, and preferences | [AgentWiki](../design/agentwiki.md) | **M3 closed.** Live grep/read, source/state/freshness, and dynamic-category checks; Git publication is M6/M7 |
| N6 | Control what becomes knowledge or agent behavior | [AgentWiki write path](../design/agentwiki.md#write-path-and-authorization) | **M6 open.** `draft_only`, `curate`, and `behavior` authorization through every write path, including Shell/files |
| N7 | Use Browser and desktop capabilities safely in one container | [ADR-0002 §3](../adr/0002-single-agent-loop.md) | **M6/M8 open.** Browser profiles, GUI lock, observation, cancellation, crash cleanup, and real smoke |
| N8 | Maintain a short current reminder without creating another memory | [nextloop WorkingContext](https://github.com/12bitsD/nextloop/blob/main/docs/design/context-builder.md#workingcontext-is-append-versioned) | **Closed design.** Idempotency, scope expiry, event order, and compaction-position tests remain |
| N9 | Reconstruct a smaller task context without losing future action correctness | [Compaction Prompt](../design/compaction-prompt.md) | **Closed design.** Full-history versus compacted continuation evaluation and Provider capacity tests remain |
| N10 | Adjust optimization guidance without forcibly stopping work | [nextloop budgets](https://github.com/12bitsD/nextloop/blob/main/docs/design/context-builder.md#budget-profiles-and-change-boundaries) | **Closed design.** Run/Session effective timing, `cap/used/remaining`, and `over_budget` behavior tests remain |
| N11 | Inspect and export execution history on demand | [ADR-0002 §7](../adr/0002-single-agent-loop.md) | **M7 open.** Cursor reads, manifest, `trace/v1`, `aift/v1`, Tool pairing, and partial-export failure checks |
| N12 | Recover Sessions and assets after process failure or restart | [nextloop recovery](https://github.com/12bitsD/nextloop/blob/main/docs/design/agent-loop.md#10-failure-and-interruption-matrix) | **M7 open.** Kill each commit window; no automatic replay, stale lease recovery, and asset reference checks |
| N13 | Back up, restore, and bound operational data | [ADR-0002 §7](../adr/0002-single-agent-loop.md) | **M7/M8 open.** Online backup, asset snapshots, retention, restore drills, GC ordering, and disk-full handling |
| N14 | Reduce the user's context-management burden through Proactive behavior | [Roadmap Proactive](discussion-roadmap.md) | **Special topic open.** Trigger, internal action, user-facing distillation, notification dedupe, cancellation, and authorization |
| N15 | Keep execution credentials and shared resources isolated | [Roadmap M6](discussion-roadmap.md) | **M6 open.** Actor/process credential separation, workspace/profile/GUI/Wiki writer ownership, locks, and cleanup |
| N16 | Build, test, run, and maintain the product reproducibly | [Roadmap M8/M9](discussion-roadmap.md) | **M8/M9 open.** Language, dependencies, container supervision, health, CI, migration, and full-capability acceptance |

## Cross-repository rule

Requirements N3, N4, N8, N9, N10, and N12 rely on nextloop's public contract. nika may add product-specific payloads and acceptance cases, but must not fork those contracts privately. Feishu, AgentWiki, Proactive behavior, concrete Tools, and deployment requirements remain nika-owned.
