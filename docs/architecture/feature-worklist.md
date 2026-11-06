# nika feature worklist

Purpose: track `nika`'s consolidated product modules. Reusable execution features live in [nextloop's worklist](https://github.com/12bitsD/nextloop/blob/main/docs/architecture/feature-worklist.md).

## Core product modules to implement in `nika`

| Module | Responsibility | Accepted minimalist design |
|---|---|---|
| `src/nika/wiki.py` + `AgentWiki/skills/wiki/SKILL.md` | Long-term memory & cross-task connection | `when` symptom triggers, sub-5ms `ripgrep` H2-TOC `wiki(action="search")`, optimistic Git-backed `upsert`/`revert` with single-line receipt, and `chmod 444` guard on `AGENTS.md`/`skills/**` ([agentwiki.md](../design/agentwiki.md)) |
| `src/nika/feishu.py` (`FeishuDelivery` & Ingress) | Feishu IM, Threads, Docs, Comments, and Cards | `allowlist(open_id)`, `Comment-as-Anchor` auto-slicing (±2 paragraphs), section-based doc edits with read-back verification, and Single Live Status Card in-place patching ([proactive-and-feishu.md](../design/proactive-and-feishu.md)) |
| `src/nika/tools.py` (`NikaToolRuntime`) | Deep Tool Catalog & container locks | `read` (files + dir trees + Wiki), `edit`, `write`, `grep`, `bash`, `wiki`, `feishu_doc`, `gui(browser\|desktop)`, `session_ctl(recent\|inspect\|working_context\|skill_view\|ask_user)`; `gui_lock` and `wiki_git_lock`; Step 15 pacing watermark ([system-prompt.md](../design/system-prompt.md)) |
| `src/nika/cli.py` | Container entrypoint, backup & export | Wire `nextloop.AgentLoop` with `SQLiteEventStore`, `AppendOnlyContextBuilder`, and `OpenAI/AnthropicProvider`; provide `nika export` (15-line OpenAI JSONL exporter from `surface_op != 'none'`) and SQLite online backup |

## Explicitly cut

- Background LLM micro-summary generation (`L0`) and dynamic prompt-prefix Wiki index (`L1`) that bloat prefixes or break KV cache.
- Custom `[b11]` Markdown-to-Feishu-Block bidirectional compiler.
- `lite / pro / promax` budget profiles and `configure_budget` tool.
- Separate `ls`, `wiki_read`, `clear_working_context`, `list_sessions`, `get_trajectory`, and `export_trajectories` tools.
- Custom `trace/v1` and `aift/v1` export specs.
- Pass-through Adapter wrappers around `nextloop`'s store, context builder, and providers.
