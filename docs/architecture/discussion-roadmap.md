# nika architecture discussion roadmap

Purpose: track `nika`'s product architecture and local end-to-end implementation order.

Current stage: **Personal superagent harness design closed (2026-11-24) — ready for local end-to-end implementation across `nextloop` and `nika`**.

## Fixed guardrails

- **One execution kernel (`nextloop`):** 4D integer coordinates, 5-variant `ToolOutcome` ADT, symmetric `parallel`/`exclusive` barrier truncation, `surface_op` watermark projection, `SQLiteEventStore`, internal `AgentLoop` context projection/compaction, and `OpenAI/AnthropicProvider`.
- **Deterministic pure-code harness (`nika`):**
  - Thin channel adapters (`FeishuAdapter`, `PocketAdapter`) translating into one internal event envelope `{event_id, source, thread_key, prompt, reply_target}`;
  - Scheduler sharing `nika.db` (WAL) with `nextloop`, owning only `ingress_events`, `threads`, and `tasks` (zero external brokers);
  - `1 main + 4 specialists` read-only config packs with 1-hop thread binding and 3 internal tools (`dispatch_task`, `report_task`, `consult_peer` locked at `depth=1`).
- **Cache-safe memory without Vector DB, dynamic prefix bloat, or a third Wiki schema:**
  - Static core aliases in frozen `AGENTS.md`;
  - Dual-repo Wiki (`src/nika/wiki.py` + `skills/wiki/SKILL.md`) mounting existing work (`workwiki`) and personal (`0h`) Git repos directly: sub-5ms `ripgrep` H2-TOC search, standard `read`, and per-repo Git `upsert`/`revert` receipts;
  - Raw SQLite cross-entry recall via `session_ctl(action="recent" | "inspect")`.
- **Simple Unix trust & 2 locks:** Feishu `allowlist(open_id)` and Pocket Bearer auth at ingress, OS `chmod 444` on `AGENTS.md` and `skills/**`, and two container locks (`gui_lock`, `wiki_git_lock`).

## Closed design map

| Area | Accepted minimalist design | Authoritative doc |
|---|---|---|
| Harness, Pocket & Specialist pool | Four-layer scheduler, unified envelope, Pocket silent boundary + native RPC, `1+4` specialists, SQLite 3 tables | [harness.md](../design/harness.md) |
| Core execution & ReAct | DSH-aligned 4D coordinates, 5-variant `ToolOutcome` ADT, symmetric `exclusive` barrier truncation, `surface_op` watermark projection | [nextloop AgentLoop](https://github.com/12bitsD/nextloop/blob/main/docs/design/agent-loop.md) |
| Adapter seam | Direct reuse of `nextloop` store/context/providers; `nika` owns channel adapters, scheduler, and `NikaToolRuntime` | [nextloop-adapter.md](nextloop-adapter.md) |
| Dual-repo Wiki (`src/nika/wiki.py` + `skills/wiki/SKILL.md`) | Mount work + personal Wikis as-is, static core aliases in `AGENTS.md`, H2-TOC search, per-repo Git upsert + single-line receipt | [agentwiki.md](../design/agentwiki.md) |
| Proactive, Feishu & Trust | Raw SQLite `recent`/`inspect`, `Comment-as-Anchor` slicing, Single Live Status Card, Step 15 pacing watermark, `chmod 444` + 2 locks | [proactive-and-feishu.md](../design/proactive-and-feishu.md) |
| Prompts & Deep Tools | 200-word 4-part Compaction Prompt, task-flow System Prompt, and consolidated deep tool catalog | [system-prompt.md](../design/system-prompt.md), [compaction-prompt.md](../design/compaction-prompt.md) |

## Local end-to-end implementation sequence

1. **Step 1 — `nextloop` core (`src/nextloop/`):** Done in `nextloop` 1.0 (`contracts.py`, `loop.py`, `events.py`, `tools.py`, `context.py`, `sqlite.py`, `providers/`, verified by the V1–V6 failure matrix).
2. **Step 2 — Scheduler & dual-repo Wiki (`src/nika/scheduler.py`, `src/nika/wiki.py`):** `nika.db` 3-table migrations, `ingress_events` dedup, `threads`/`tasks` transitions, `depth=1` guard, and cross-repo `ripgrep` H2-TOC `search` + Git `upsert`/`revert`.
3. **Step 3 — `NikaToolRuntime`, `FeishuAdapter` & `PocketAdapter` (`src/nika/`):** Specialist config packs (`specialists/**`), `pocket` native RPC tool, `/webhooks/pocket` ingress + silent callback, Feishu `Comment-as-Anchor` slicing, Single Live Status Card, and `session_ctl` recall.
4. **Step 4 — Local end-to-end loop verification & release:** Verify `nika` + `nextloop` end-to-end locally (Feishu DM/Thread dispatch + follow-up 1-hop routing, Pocket mock scheduler delivery + callback, Wiki search/revert) before cutting formal package releases. Device Link integration follows only after the standalone protocol ships.
