# nika architecture discussion roadmap

Purpose: track `nika`'s product architecture and local end-to-end implementation order.

Current stage: **Design closed — ready for local end-to-end implementation across `nextloop` and `nika`**.

## Fixed guardrails

- **One execution kernel (`nextloop`):** 4D integer coordinates, 5-variant `ToolOutcome` ADT, symmetric `parallel`/`exclusive` barrier truncation, `surface_op` watermark projection, `SQLiteEventStore`, `AppendOnlyContextBuilder`, and `OpenAI/AnthropicProvider`.
- **Two product adapters (`nika`):** `FeishuDelivery` (ingress + Single Live Status Card) and `NikaToolRuntime` (the consolidated deep tool catalog).
- **Cache-safe memory without Vector DB or dynamic prefix bloat:**
  - Static core aliases in frozen `AGENTS.md`;
  - `AgentWiki` (`src/nika/wiki.py` + `skills/wiki/SKILL.md`): `when` symptom triggers, sub-5ms `ripgrep` H2-TOC search, read via standard `read`, and optimistic Git-backed `upsert`/`revert` with single-line reply receipts;
  - Raw SQLite cross-entry recall via `session_ctl(action="recent" | "inspect")`.
- **Simple Unix trust & 2 locks:** Feishu `allowlist(open_id)` at ingress, OS `chmod 444` on `AGENTS.md` and `skills/**`, and two container locks (`gui_lock`, `wiki_git_lock`).

## Closed design map

| Area | Accepted minimalist design | Authoritative doc |
|---|---|---|
| Core execution & ReAct | DSH-aligned 4D coordinates, 5-variant `ToolOutcome` ADT, symmetric `exclusive` barrier truncation, `surface_op` watermark projection | [nextloop AgentLoop](https://github.com/12bitsD/nextloop/blob/main/docs/design/agent-loop.md) |
| Adapter seam | Direct reuse of `nextloop` store/context/providers; `nika` implements only `NikaToolRuntime` and `FeishuDelivery` | [nextloop-adapter.md](nextloop-adapter.md) |
| AgentWiki (`src/nika/wiki.py` + `skills/wiki/SKILL.md`) | Static core aliases in `AGENTS.md`, `when` triggers, H2-TOC search, optimistic Git-committed upsert + single-line receipt | [agentwiki.md](../design/agentwiki.md) |
| Proactive, Feishu & Trust | Raw SQLite `recent`/`inspect`, `Comment-as-Anchor` slicing, Single Live Status Card, Step 15 pacing watermark, `chmod 444` + 2 locks | [proactive-and-feishu.md](../design/proactive-and-feishu.md) |
| Prompts & Deep Tools | 200-word 4-part Compaction Prompt, task-flow System Prompt, and consolidated deep tool catalog | [system-prompt.md](../design/system-prompt.md), [compaction-prompt.md](../design/compaction-prompt.md) |

## Local end-to-end implementation sequence

1. **Step 1 — `nextloop` core (`src/nextloop/`):** `contracts.py`, `loop.py`, `events.py`, `tools.py`, `context.py`, `sqlite.py`, `providers/{openai,anthropic}.py`, verified by the V1–V6 failure matrix.
2. **Step 2 — `AgentWiki` module & skill (`src/nika/wiki.py` + `AgentWiki/skills/wiki/SKILL.md`):** Sub-5ms `ripgrep` H2-TOC `search`, Git-backed `upsert`/`revert`, and `chmod 444` behavior-file guard.
3. **Step 3 — `NikaToolRuntime` & `FeishuDelivery` (`src/nika/`):** Feishu ingress, `Comment-as-Anchor` slicing, Single Live Status Card, SQLite `recent`/`inspect`, and container `gui` tools.
4. **Step 4 — Local end-to-end loop verification & release:** Verify `nika` + `nextloop` end-to-end locally before cutting formal package releases.
