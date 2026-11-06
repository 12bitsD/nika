# ADR-0002: Consolidate nika as the product layer over nextloop

- Status: Accepted as the current product architecture baseline
- Date: 2026-10-26
- Updated: 2026-11-06 for the nextloop repository split
- Supersedes: [ADR-0001](0001-unified-agent-runtime.md)
- Scope: Feishu, product capabilities, AgentWiki, Prompt content, concrete Tools, product data, deployment, and Proactive behavior

## Context

nika is a lightweight personal Bot built around Feishu, coding, documents, and one container for BrowserUse and ComputerUse. The product and reusable execution protocol now have separate repositories.

[nextloop ADR-0001](https://github.com/12bitsD/nextloop/blob/main/docs/adr/0001-embeddable-agent-loop.md) defines the reusable execution-library boundary. This ADR retains only nika's product decisions and does not duplicate nextloop's execution protocol.

## 1. Repository and execution boundary

[nextloop](https://github.com/12bitsD/nextloop) owns AgentLoop, ContextBuilder, ReAct, Tool validation and outcomes, event projection, cancellation, recovery, and delivery-only retry.

nika owns:

- Feishu ingress, routing, documents, comments, cards, and delivery;
- AgentWiki, `AGENTS.md`, Skills, and knowledge-write authorization;
- System Prompt and Compaction Prompt content;
- concrete Tool implementations, credentials, and resource supervision;
- product data, deployment, backup, GC, and Proactive behavior.

nika uses nextloop through adapters. Product-specific needs must not be patched into the public Loop contract, and nextloop must not depend on nika's Feishu IDs, Wiki paths, or desktop locks.

## 2. Entry and Session identity

One entry maps to one Session by default:

| Entry | Session mapping |
|---|---|
| Private chat | One `chat_id`; `/new` explicitly starts another |
| Group topic | One Feishu Thread |
| Partial document comment | One `comment_id` |
| Whole-document comments | One shared document Session |

There is no default cross-entry continuation. An explicit resume-by-Session-ID capability may be added later. Workspace changes are recorded and do not implicitly create a new Session.

The execution lifecycle, input ordering, and final-response commit rules belong to nextloop. nika supplies entry identity, ingress events, and the DeliveryOwner.

## 3. Product capabilities

The concrete Tool Catalog is statically registered with small, intention-clear interfaces. Runtime resolves Session, workspace, credentials, defaults, validation, retries, resource ownership, large-output assets, and error normalization so the model does not repeat them.

There is no universal `execute(action, payload)` Tool and no baseline Tool Search. An MCP adapter and allowlist configuration are reserved, but MCP is disabled and contributes no schemas by default.

### Coding

Ordinary chat and coding share nextloop's AgentLoop. Coding quality comes from repository Tools and an on-demand coding Skill, not a separate runtime mode or external coding harness.

### BrowserUse and ComputerUse

Bot, browser, and virtual desktop run in the same container. There is no remote Mac or device bridge.

- BrowserUse controls a container browser, with per-Session contexts where useful.
- ComputerUse controls the container virtual desktop.
- Shared GUI actions are serialized with a container-level lock.
- Cancelling a Run stops later actions but does not undo clicks or writes already performed.

Screenshots and large observations are stored as assets and referenced from Trajectory.

## 4. AgentWiki and behavior assets

The accepted structure is:

```text
AgentWiki/
  AGENTS.md
  wiki/
    INDEX.md          # generated for maintenance, excluded from normal grep
    inbox/
    projects/
    concepts/
    people/
    playbooks/
    profiles/
    references/
  skills/
```

Wiki is the only long-term knowledge source. There is no separate Memory service, automatic Recall Subagent, vector store, or second curated fact store. Wiki and Trajectory remain distinct; raw Trajectory is not automatically promoted into Wiki.

The consumption and maintenance contract is in [agentwiki.md](../design/agentwiki.md):

- shallow, dynamically extensible categories;
- self-describing Markdown headers with `id/kind/state/summary/keys` and optional relations and freshness metadata;
- live `grep → read` retrieval, with bounded `ls` for write-time discovery;
- stable-ID relations and structural write validation;
- a maintenance-generated INDEX that is not required by the model.

Writes default to `draft_only`. Ordinary active knowledge requires `curate` within an explicitly authorized task or Run. Changes to `AGENTS.md` or Skills require separate `behavior` authorization. Provenance does not itself grant write permission.

`AGENTS.md` contains the Agent's evolving role, personality, and interaction style. It is maintained independently of System Prompt and changed or refreshed only by explicit user request. Skills use standard `SKILL.md` packages and current content at the point of use.

## 5. Prompt and content policy

The selected runtime-owned System Prompt and first Tool Catalog are in [system-prompt.md](../design/system-prompt.md). It guides task classification, evidence lookup, execution, verification, and delivery; it does not contain evolving persona, recent tasks, Wiki snapshots, budget balances, dynamic request IDs, or per-call timestamps.

The dedicated [compaction-prompt.md](../design/compaction-prompt.md) is supplied by nika to nextloop. It reconstructs current task state by future action value rather than requiring complete Tool transcripts or a fixed summary schema.

WorkingContext content is a short, user-level self-reminder, with one active version per Session and 2 KiB as a soft readability guideline. nextloop owns its append, expiry, and compaction mechanics. It is not long-term Wiki memory, a permission channel, or Proactive behavior.

Budget profiles remain `lite/pro/promax` with `pro` as default. Tool-call counts and time budgets are soft optimization signals, not forced stop conditions. Runtime marks `over_budget` and gives efficiency guidance. Provider capacity, explicit cancellation, per-Tool timeouts, and terminal runtime failures remain separate constraints.

## 6. Feishu

Feishu is the primary channel, using long-lived event connections. Target behavior matches the relevant verified yomi behavior:

- private chat, group mention, and Thread routing;
- message deduplication and sender identity checks;
- document read, create, and edit;
- document-comment mention triggers, comment history, and replies;
- partial-comment Session isolation and whole-document shared Sessions;
- long-message handling, reactions, status and interaction cards;
- Tool trace rendered from Trajectory rather than a separate instrumentation system.

Platform-specific response fallbacks and comment-read races should reuse verified yomi behavior. Feishu delivery retries never rerun the model or Tools.

## 7. Product data and operations

Session and Trajectory data live on persistent container storage. The event envelope, projection, and recovery algorithm belong to nextloop; nika supplies the deployed Store and asset policy.

Storage uses SQLite with WAL and `synchronous=FULL`. Large observations and outputs live as external assets persisted before their references. The core write path does not maintain FTS or secondary indexes beyond those needed for Session, event, and delivery queries.

`SessionCatalog` supports `list_sessions`, cursor-based `get_trajectory`, and explicit batch export. Export projections are:

- `trace/v1`: full runtime and interaction events for diagnosis;
- `aift/v1`: model-interaction projection with Session, messages, Tools, and correlated Tool Calls/Results.

Batch export is explicit, with a manifest and one JSONL per Session. There is no background export or automatic training pipeline.

Backups use SQLite online backup plus asset snapshots. Raw Trajectories are not committed to public Git. GC is manual, supports dry-run, age filters, and active/pinned exclusions, and has no default automatic deletion of Sessions.

## 8. Proactive and exclusions

Proactive context management is a separate product mechanism intended to reduce the user's context-management burden. Task-phase detection, internal updates, user-facing distillation, authorization, and interruption policy are designed separately from WorkingContext and nextloop.

The following are outside the current product baseline:

- external coding Harness or a separate coding mode;
- generic EventBus, remote event replay, or task-card system;
- agent-defined Hooks or fixed before/after Tool hooks;
- read-only `/btw` side questions or a separate task FIFO;
- conversation rewind or automatic historical Tool replay;
- automatic RSI, automatic Wiki promotion, or automatic Skill promotion;
- remote device bridges or multiple virtual desktops.

## 9. Current implementation boundary

There is no runtime implementation, release, or deployment result. Language, package layout, CI, concrete resource protocols, event schemas, and real Feishu acceptance remain open. Execution protocol work continues in nextloop's [discussion roadmap](https://github.com/12bitsD/nextloop/blob/main/docs/architecture/discussion-roadmap.md); product integration continues in nika's [discussion roadmap](../architecture/discussion-roadmap.md).
