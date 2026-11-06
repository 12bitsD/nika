# nika architecture discussion roadmap

Purpose: track `nika`'s product architecture after applying Occam's Razor to eliminate speculative milestones.

Current stage: **Design closed — ready for implementation when authorized**. Both `nextloop` and `nika` architectural designs are converged.

## Fixed product guardrails

- **One execution kernel:** `nika` directly reuses `nextloop`'s Turn/Step driver, `SQLiteEventStore`, `AppendOnlyContextBuilder`, and `OpenAI/AnthropicProvider`.
- **Two real product adapters:** `FeishuDelivery` (ingress + single live status card) and `NikaToolRuntime` (the consolidated deep tool catalog).
- **Three-tier memory without Vector DB:**
  - `L0 Recent Pulse` (last 5 completed Turn micro-summaries across Feishu entries, ≤ 500 tokens);
  - `L1 Wiki Synapse Map` (`id → when/keys` index compiled from `AgentWiki`, ≤ 2 KiB);
  - `L2 AgentWiki files` (`wiki(action="search")` returning Frontmatter + H2 line-range TOC, read via standard `read`, written via optimistic Git-backed `wiki(action="upsert")` with single-line reply receipts).
- **Simple Unix trust & 2 locks:** Feishu `allowlist(open_id)` at ingress, OS `chmod 444` on `AGENTS.md` and `skills/**`, and two container locks (`gui_lock`, `wiki_git_lock`).

## Closed design map

| Area | Accepted minimalist design | Authoritative doc |
|---|---|---|
| Core execution & ReAct | DSH-aligned 4D coordinates, 5-variant `ToolOutcome` ADT, `surface_op` watermark projection | [nextloop AgentLoop](https://github.com/12bitsD/nextloop/blob/main/docs/design/agent-loop.md) |
| Adapter seam | Direct reuse of `nextloop` store/context/providers; `nika` implements only `NikaToolRuntime` and `FeishuDelivery` | [nextloop-adapter.md](nextloop-adapter.md) |
| AgentWiki (`src/nika/wiki.py` + `skills/wiki/SKILL.md`) | `L1 Synapse Map`, `when` triggers, H2-TOC search, optimistic Git-committed upsert + single-line receipt | [agentwiki.md](../design/agentwiki.md) |
| Proactive, Feishu & Trust | `L0 Recent Pulse`, `Comment-as-Anchor` Virtual Markdown, Single Live Status Card, Step 15 pacing watermark, `chmod 444` + 2 locks | [proactive-and-feishu.md](../design/proactive-and-feishu.md) |
| Prompts & Deep Tools | 200-word 4-part Compaction Prompt, task-flow System Prompt, and consolidated 7-group deep tool catalog | [system-prompt.md](../design/system-prompt.md), [compaction-prompt.md](../design/compaction-prompt.md) |

## Implementation sequence (when authorized)

1. **Phase 1 — `nextloop` core (`src/nextloop/`):** `contracts.py`, `loop.py`, `events.py`, `tools.py`, `context.py`, `sqlite.py`, `providers/{openai,anthropic}.py`, verified by the V1–V6 failure matrix.
2. **Phase 2 — `AgentWiki` module & skill (`src/nika/wiki.py` + `AgentWiki/skills/wiki/SKILL.md`):** `L1 Synapse Map` compiler, H2-TOC `search`, Git-backed `upsert`/`revert`, and behavior-file read-only guard.
3. **Phase 3 — `NikaToolRuntime` & `FeishuDelivery` (`src/nika/`):** Feishu long-connection ingress, `Comment-as-Anchor` Virtual Markdown, Single Live Status Card, `L0 Recent Pulse`, and container `gui` tools.
4. **Phase 4 — Container packaging & smoke verification:** Single Dockerfile, SQLite online backup + CLI JSONL export (`nika export`), and end-to-end Feishu/Wiki/GUI smoke tests.
