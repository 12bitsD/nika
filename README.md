# nika-bot

A lightweight personal agent bot built around one AgentLoop, one container, Feishu, and a versioned AgentWiki.

Current stage: **architecture and feature design**. There is no runtime implementation yet.

## What it is for

nika-bot should make a personal agent easy to run and easy to change:

- talk and work with the agent through Feishu messages, Threads, documents, and document comments;
- inspect and modify code with the same AgentLoop used for ordinary chat;
- use a container browser or virtual desktop for BrowserUse and ComputerUse;
- keep long-term knowledge and Skills under one versioned `AgentWiki` root;
- record a complete Trajectory for every Session and export it only when explicitly requested.

It intentionally avoids a general-purpose multi-channel daemon, an external coding harness, a separate coding mode, agent-defined Hooks in the core loop, and an automatic self-improvement pipeline.

## Architecture at a glance

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
  context → model → tools → model …
  steer / compact / cancel / finalize
              │
      ┌───────┼──────────┐
      ▼       ▼          ▼
  Tool    BrowserUse   ComputerUse
 Catalog   (container)  (container)
      │       │          │
      ▼       ▼          ▼
  AgentWiki / files / shell / browser / virtual desktop / Feishu docs

Session Store: Session catalog + durable Trajectory + asset references
AgentWiki: Wiki knowledge + Skills, versioned with Git
```

**AgentLoop is an on-demand execution procedure, not a long-lived Session object.** Session owns durable state. AgentLoop consumes it, appends new facts, and releases the Session when the Turn ends.

## Confirmed feature direction

| Area | Value | Current approach |
|---|---|---|
| Feishu | One place for chat and document collaboration | Long-lived event connection; IM, Threads, document read/create/edit, comment triggers and replies |
| Coding | Better coding without another harness | One Tool Catalog plus an on-demand coding Skill; no coding mode |
| BrowserUse / ComputerUse | Complete web and desktop tasks | Control only the browser and virtual desktop inside the bot container; serialize shared GUI actions |
| AgentWiki | One place for evolving agent behavior, long-term knowledge, and Skill assets | `AGENTS.md`, `wiki/`, and `skills/`; shallow Wiki categories, grep-based retrieval, and a maintenance-generated INDEX |
| Skills | Reusable working methods without prompt bloat | Standard `SKILL.md`, dynamic metadata and current content loaded on demand |
| Trajectory | Explain what actually happened and support later analysis | Append-only Session events, asset references, `list_sessions`, `get_trajectory`, and explicit batch export |
| Models and budgets | Support different task sizes and models | Multiple providers, streaming, bounded retries, provider-reported usage, and soft `lite/pro/promax` guidance with `cap/used/remaining` and efficiency hints adjustable by the Agent |
| WorkingContext | Let the Agent maintain a lightweight reminder during work | One active user-level reminder per Session; set/clear append versions or markers, 2 KiB is a soft guideline, and compaction keeps only the latest active version after the task summary |
| Persistence | Recover after restart without turning memory into a second Wiki | SQLite with WAL and `synchronous=FULL`, persistent container storage, online backup plus asset snapshots, manual GC |

The feature list records **current decisions, not implemented capabilities**.

## Core execution semantics

- One Feishu entry maps to one Session: private chat, group Thread, partial document comment, or whole-document comment area.
- Ordinary messages all use steer semantics: idle input starts a new Turn; active-Turn input waits in the ordered buffer for the next safe model boundary. There is no independent-task `/queue` or read-only `/btw`.
- `WaitingRequest` is created only when runtime needs an answer to continue; the validated answer resumes the original request rather than starting a new Turn.
- `/stop` cancels the current AgentLoop and its tools; a later ordinary message starts a new Turn.
- Historical tool calls are never replayed automatically after cancellation or restart.
- Mandatory finalization uses `try/finally`; optional extensions do not own durable cleanup.
- Every Session produces Trajectory. There is no automatic export, automatic Wiki promotion, or automatic RSI.
- Compaction starts on user `/compact` or at 75% of the model context window. The internal `Compactor` uses the dedicated Compaction System Prompt with `AGENTS.md` and Conversation to reconstruct task state by future action value, then validates and appends the result. The next request uses the normal System Prompt, `AGENTS.md`, the new summary, and subsequent messages; old Trajectory is never rewritten.
- Agent-defined Hooks and fixed before/after Tool hook points are parked; recording and audit belong directly to Trajectory.

## Documentation

- [Discussion roadmap](docs/architecture/discussion-roadmap.md) — the controlling discussion plan, stage close criteria, current status, and parking lot.
- [AgentLoop core design](docs/design/agent-loop.md) — the M4 state machine, event ordering, cancellation, finalization, and interruption matrix.
- [ContextBuilder design](docs/design/context-builder.md) — confirmed M5 append-only and WorkingContext decisions plus the remaining context, cache, and compaction questions.
- [AgentWiki design](docs/design/agentwiki.md) — Wiki structure, grep-based consumption, independently maintained `AGENTS.md`, and maintenance-derived INDEX.
- [System Prompt](docs/design/system-prompt.md) — the selected M5 task-flow Prompt, Tool Catalog, and selection notes.
- [Compaction System Prompt](docs/design/compaction-prompt.md) — the dedicated summary Prompt and process contract produced through three optimization rounds.
- [Feature worklist](docs/architecture/feature-worklist.md) — feature-by-feature value, approach, and remaining decisions.
- [ADR-0002](docs/adr/0002-single-agent-loop.md) — current consolidated architecture baseline.
- [CONTEXT.md](CONTEXT.md) — canonical domain vocabulary.
- [ADR-0001](docs/adr/0001-unified-agent-runtime.md) — superseded runtime draft retained for history.

## Still being designed

- Detailed Tool schemas and descriptions.
- Proactive context management, reserved for a separate special topic after M5.
- Execution trust, credential isolation, and ownership of shared resources.
- Persistence schema, Feishu acceptance details, and backup/retention values.
- Implementation language, code layout, deployment details, and CI.

## Content policy

This is a public repository. Do not commit credentials, private Wiki content, real Session trajectories, internal endpoints, or personal identifiers.
