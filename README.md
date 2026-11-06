# nika

A lightweight personal agent bot for Feishu, coding, documents, and container-based Browser/Computer work, powered by [nextloop](https://github.com/12bitsD/nextloop).

Status: **product architecture and feature design**. There is no runtime implementation yet.

## Product boundary

nika and nextloop have separate responsibilities:

- **nextloop** owns the reusable execution protocol: AgentLoop, ContextBuilder, ReAct, Tool admission and outcomes, event projection, cancellation, recovery, and delivery-only retry.
- **nika** owns the product: Feishu channels and documents, AgentWiki, Skills, Prompt content, concrete Tools, credentials, deployment, and Proactive behavior.

Do not maintain a second copy of nextloop's execution design here. Former Loop paths contain navigation pointers only.

## Product architecture

```text
Feishu IM / Threads / documents / comments
              │
              ▼
      nika routing and adapters
              │
              ▼
         nextloop
  model / Tool / context / recovery
              │
              ▼
nika concrete Tools and product state
  Wiki / Skills / assets / Feishu delivery
```

[nika ADR-0002](docs/adr/0002-single-agent-loop.md) is the product baseline. [nextloop ADR-0001](https://github.com/12bitsD/nextloop/blob/main/docs/adr/0001-embeddable-agent-loop.md) is the reusable execution-library baseline.

## Confirmed product direction

| Area | Current approach |
|---|---|
| Feishu | Private chat, group Thread, document read/create/edit, comment triggers and replies; long-lived event connection |
| Coding | One nextloop execution path plus an on-demand coding Skill; no separate coding mode or external coding harness |
| BrowserUse / ComputerUse | Container browser and virtual desktop; shared GUI actions serialized |
| AgentWiki | `AGENTS.md`, `wiki/`, and `skills/`; shallow categories, live grep/read, maintenance-generated INDEX |
| Skills | Standard `SKILL.md`, dynamic metadata and current content loaded on demand |
| Prompt | Runtime System Prompt, independently maintained `AGENTS.md`, and a dedicated Compaction Prompt |
| Trajectory | Append-only Session events, asset references, `list_sessions`, `get_trajectory`, and explicit batch export |
| WorkingContext | One active user-level reminder per Session; content policy is product-owned, mechanism is owned by nextloop |
| Models and budgets | Multiple providers, streaming, bounded retries, provider-reported usage, soft `lite/pro/promax` guidance |
| Persistence | SQLite WAL and `synchronous=FULL`, persistent container storage, online backup plus assets, manual GC |

These are design decisions, not implemented capabilities.

## Product documents

- [Discussion roadmap](docs/architecture/discussion-roadmap.md) — product topics, order, and close conditions.
- [Development handoff](docs/architecture/development-handoff.md) — current product state and reading path.
- [Feature worklist](docs/architecture/feature-worklist.md) — product capabilities and remaining decisions.
- [System Prompt](docs/design/system-prompt.md) — selected task-flow Prompt and Tool Catalog.
- [Compaction Prompt](docs/design/compaction-prompt.md) — selected task-state reconstruction Prompt.
- [AgentWiki design](docs/design/agentwiki.md) — Wiki structure, consumption, writes, and maintenance.
- [ADR-0002](docs/adr/0002-single-agent-loop.md) — current product architecture baseline.
- [CONTEXT.md](CONTEXT.md) — product domain vocabulary.
- [ADR-0001](docs/adr/0001-unified-agent-runtime.md) — superseded runtime draft retained for history.

## Execution documents

- [nextloop AgentLoop](https://github.com/12bitsD/nextloop/blob/main/docs/design/agent-loop.md)
- [nextloop ContextBuilder](https://github.com/12bitsD/nextloop/blob/main/docs/design/context-builder.md)
- [nextloop roadmap](https://github.com/12bitsD/nextloop/blob/main/docs/architecture/discussion-roadmap.md)
- [nextloop feature worklist](https://github.com/12bitsD/nextloop/blob/main/docs/architecture/feature-worklist.md)
- [nextloop research](https://github.com/12bitsD/nextloop/tree/main/docs/research)

## Still being designed

- Detailed Tool schemas and product Adapter contracts.
- Proactive context management and notification policy.
- Execution trust, credentials, and shared-resource ownership.
- Feishu acceptance, event schema, backup, and retention details.
- Implementation language, package layout, deployment, and CI.

Implementation begins only after the roadmap is closed and the user explicitly confirms it.

## Content policy

This is a public repository. Do not commit credentials, private Wiki content, real Session trajectories, internal endpoints, or personal identifiers.
