# nika feature worklist

Purpose: track `nika`'s consolidated product capabilities after Occam's Razor simplification. Reusable execution features live in [nextloop's worklist](https://github.com/12bitsD/nextloop/blob/main/docs/architecture/feature-worklist.md).

## Core product modules to implement in `nika`

| Module | Responsibility | Accepted minimalist design |
|---|---|---|
| `src/nika/wiki.py` + `AgentWiki/skills/wiki/SKILL.md` | Long-term memory & cross-task connection | `L1 Synapse Map` (≤ 2 KiB), `when` symptom triggers, H2-TOC `wiki(action="search")`, optimistic Git-backed `upsert`/`revert` with single-line receipt, and `chmod 444` guard on `AGENTS.md`/`skills/**` ([agentwiki.md](../design/agentwiki.md)) |
| `src/nika/feishu.py` (`FeishuDelivery` & Ingress) | Feishu IM, Threads, Docs, Comments, and Cards | `allowlist(open_id)`, `L0 Recent Pulse` (5-turn ring buffer), `Comment-as-Anchor` auto-slicing, Virtual Markdown (`[b11]`) doc editing, and Single Live Status Card in-place patching ([proactive-and-feishu.md](../design/proactive-and-feishu.md)) |
| `src/nika/tools.py` (`NikaToolRuntime`) | Deep Tool Catalog & container locks | `read` (files + dir trees + Wiki), `edit`, `write`, `grep`, `bash`, `wiki`, `feishu_doc`, `gui(browser\|desktop)`, `session_ctl`; `gui_lock` and `wiki_git_lock`; Step 15 pacing watermark ([system-prompt.md](../design/system-prompt.md)) |
| `src/nika/cli.py` | Container entrypoint, backup & export | Wire `nextloop.AgentLoop` with `SQLiteEventStore`, `AppendOnlyContextBuilder`, and `OpenAI/AnthropicProvider`; provide `nika export` (15-line OpenAI JSONL exporter from `surface_op != 'none'`) and SQLite online backup |

## Explicitly cut by Occam's Razor

- `lite / pro / promax` budget profiles and `configure_budget` tool (replaced by deterministic Step 15 pacing watermark).
- Separate `ls`, `wiki_read`, `clear_working_context`, `list_sessions`, `get_trajectory`, and `export_trajectories` tools (folded into `read` and `session_ctl`).
- Custom `trace/v1` and `aift/v1` export specs (replaced by raw SQLite `session_events` and standard OpenAI JSONL CLI export).
- Pass-through Adapter wrappers around `nextloop`'s store, context builder, and providers.
- Complex multi-tier runtime RBAC for Wiki writes (replaced by optimistic Git commits + single-line receipt on `wiki/**` and OS `chmod 444` on `AGENTS.md` / `skills/**`).
