# nika feature worklist

Purpose: track `nika`'s consolidated product modules. Reusable execution features live in [nextloop's worklist](https://github.com/12bitsD/nextloop/blob/main/docs/architecture/feature-worklist.md).

## Core product modules to implement in `nika`

| Module | Responsibility | Accepted minimalist design |
|---|---|---|
| `src/nika/scheduler.py` | Deterministic routing, dedup & task ledger | Unified internal event envelope; shared `nika.db` (WAL) with 3 tables (`ingress_events`, `threads`, `tasks`); 1-hop thread-to-specialist binding; `consult_peer` `depth=1` hard lock ([harness.md](../design/harness.md)) |
| `specialists/**` (read-only config packs) | `1 main + 4 specialists` persona & allowlists | `main`, `top_talent`, `coder`, `doc_research`, `eval` packs (SP + Skills + tool allowlist), loaded as-is by scheduler; evolved offline by a separate RSI repo ([harness.md](../design/harness.md)) |
| `src/nika/feishu.py` (`FeishuAdapter`) | Feishu IM, Threads, Docs, Comments, and Cards | `allowlist(open_id)`, `Comment-as-Anchor` auto-slicing (±2 paragraphs), section-based doc edits with read-back verification, and Single Live Status Card in-place patching ([proactive-and-feishu.md](../design/proactive-and-feishu.md)) |
| `src/nika/pocket.py` (`PocketAdapter` + `pocket` tool) | Pocket scheduled ingress & native RPC client | Inbound `POST /webhooks/pocket` → `202 Accepted` + one-time callback write-back (silent on Feishu by default); outbound `pocket(method, params)` direct HTTP to `/v1/rpc/{method}` without MCP ([harness.md](../design/harness.md)) |
| `src/nika/wiki.py` + `skills/wiki/SKILL.md` | Long-term memory & cross-task connection | Mounts existing work (`workwiki`) and personal (`0h`) Git repos directly; sub-5ms `ripgrep` H2-TOC `wiki(action="search")`, native Git `upsert`/`revert` with `repo:path@sha` receipt, `chmod 444` guard on `AGENTS.md`/`skills/**` ([agentwiki.md](../design/agentwiki.md)) |
| `src/nika/tools.py` (`NikaToolRuntime`) | Deep Tool Catalog, orchestration tools & locks | `read`, `edit`, `write`, `grep`, `bash`, `wiki`, `pocket`, `feishu_doc`, `gui`, `session_ctl`, plus `dispatch_task` / `report_task` / `consult_peer`; `gui_lock` and `wiki_git_lock`; Step 15 pacing watermark ([system-prompt.md](../design/system-prompt.md)) |
| `src/nika/cli.py` | Container entrypoint, backup & export | Wire `nextloop.AgentLoop` with `SQLiteEventStore`, scheduler, channel adapters, and `OpenAI/AnthropicProvider`; `nika export` (15-line OpenAI JSONL exporter from `surface_op != 'none'`) and SQLite online backup |

## Explicitly cut

- Background LLM micro-summary generation (`L0`) and dynamic prompt-prefix Wiki index (`L1`) that bloat prefixes or break KV cache.
- A separate third private Wiki repository/schema: Nika mounts the existing work and personal Wiki Git repos directly.
- Redis, Postgres, message queues, or a separate scheduler database for a single-user deployment.
- An MCP wrapper around first-party Pocket APIs (native HTTP `/v1/rpc/{method}` is already clean and scoped).
- Multiple public IM bot accounts per specialist, free-form inter-agent group chat, and recursive `consult_peer` (`depth > 1`).
- Custom `[b11]` Markdown-to-Feishu-Block bidirectional compiler.
- `lite / pro / promax` budget profiles and `configure_budget` tool.
- Separate `ls`, `wiki_read`, `clear_working_context`, `list_sessions`, `get_trajectory`, and `export_trajectories` tools.
- Custom `trace/v1` and `aift/v1` export specs.
- Pass-through Adapter wrappers around `nextloop`'s store, context builder, and providers.
- Coupling Nika's harness to unfinished Device Link transport details before the standalone protocol ships.
