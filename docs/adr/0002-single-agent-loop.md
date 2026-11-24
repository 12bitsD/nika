# ADR-0002: Consolidate nika as the personal superagent over nextloop

- Status: Accepted (refined 2026-11-06; extended 2026-11-24 by [harness.md](../design/harness.md))
- Date: 2026-10-26
- Updated: 2026-11-24
- Supersedes: [ADR-0001](0001-unified-agent-runtime.md)
- Scope: repository boundary, SQLite cross-entry recall, dual-repo Wiki H2-TOC search & Git receipts, Feishu interaction, deep tool catalog, and minimalist container trust

> **2026-11-24 Extension:** Nika grows from a single Feishu agent into a four-layer personal superagent harness: thin channel adapters (`FeishuAdapter`, `PocketAdapter`) around one internal event envelope, a pure-code deterministic scheduler sharing `nika.db` (3 tables: `ingress_events`, `threads`, `tasks`), a `1 main + 4 specialists` read-only config-pool with 3 internal tools (`dispatch_task`, `report_task`, `consult_peer` at `depth=1`), a native `pocket` RPC tool (no MCP wrapper, silent-by-default scheduled callbacks), and direct mounting of the existing work + personal Wiki repos. See [harness.md](../design/harness.md).

## 1. Direct reuse over pass-through wrappers

[nextloop](https://github.com/12bitsD/nextloop) owns the DSH-aligned Turn/Step driver, 4D integer coordinates, closed 5-variant `ToolOutcome` ADT, symmetric `parallel`/`exclusive` barrier truncation, `surface_op` watermark projection, `SQLiteEventStore`, internal `AgentLoop` context projection/compaction, and `OpenAI/AnthropicProvider`.

`nika` reuses those modules directly without pass-through wrappers, implementing only the product seams ([nextloop-adapter.md](../architecture/nextloop-adapter.md)):
- **Channel adapters** (`FeishuAdapter`, `PocketAdapter`) for ingress translation and source-specific Outbox delivery;
- **Deterministic scheduler** (`src/nika/scheduler.py`) for dedup, thread binding, and task stages;
- **`NikaToolRuntime` & dual-repo Wiki** (`src/nika/tools.py`, `src/nika/wiki.py`, `skills/wiki/SKILL.md`).

## 2. Entry isolation + raw SQLite cross-entry recall

Each Feishu entry maps to its own isolated Session (`chat_id` for DM, `thread_id` for group topics, `comment_id` for partial doc comments, `doc_token` for whole-doc comments); Pocket deliveries map to `pocket:delivery:<delivery_id>`.

To bridge context across entries without background LLM summary calls or prompt-prefix bloat, `session_ctl(action="recent" | "inspect")` queries `session_events` in SQLite directly (< 1ms) to list recent active Sessions (entry title, timestamp, raw first user input, and raw final reply snippet) and pull specific Turns on demand.

## 3. Consolidated Deep Tool Catalog

`nika` exposes a small set of orthogonal deep tools ([system-prompt.md](../design/system-prompt.md)), filtered per specialist allowlist:

- **`read`** (files, directory trees—replaces `ls`, and Wiki entries—replaces `wiki_read`), **`edit`**, **`write`**, **`grep`**, **`bash`**;
- **`wiki(action="search" | "upsert" | "revert")`** across the mounted work + personal Wiki repos (`src/nika/wiki.py` + `skills/wiki/SKILL.md`);
- **`pocket(method, params)`** (`main` only: native HTTP RPC to `/v1/rpc/{method}`, no MCP wrapper);
- **`feishu_doc(action="read" | "replace_section" | "append" | "reply_comment")`** (with automatic read-back verification);
- **`gui(target="browser" | "desktop")`** (serialized by `gui_lock`);
- **`session_ctl(action="recent" | "inspect" | "working_context" | "skill_view" | "ask_user")`**;
- **Internal orchestration:** `dispatch_task`, `report_task`, and `consult_peer` (`depth=1` hard lock);
- Deterministic **Step 15 Pacing Watermark** injected into Tool Results on long Turns (replacing `lite/pro/promax` and `configure_budget`).

## 4. Dual-repo Wiki (live H2-TOC search + Git receipts)

Full contract: [agentwiki.md](../design/agentwiki.md).
- **Direct mount, zero migration:** Reuses the existing work Wiki and personal Wiki (`0h`) repositories in their native formats rather than creating a third private Wiki schema.
- **Static core aliases in `AGENTS.md`:** High-frequency project/person aliases stay in frozen `AGENTS.md` (100% cache hit, zero dynamic prefix growth).
- **Live H2-TOC search:** `wiki(action="search")` uses `ripgrep` (< 5ms) to return repo/path, frontmatter + Markdown `## H2` line ranges + snippets.
- **Optimistic Git-backed writes:** `wiki(action="upsert")` commits to the target repo under `wiki_git_lock` and appends a one-line footer receipt (`📝 Wiki: <repo>:<path> (<state>) · rev <sha>`) for effortless `git revert`.

## 5. Proactive protocol & Feishu UX

Full contract: [proactive-and-feishu.md](../design/proactive-and-feishu.md).
- **Ingress Pre-Hydration & `Comment-as-Anchor`:** Automatically slices quoted document paragraphs (±2 paragraphs) and attaches mentioned doc titles before Step 1.
- **Optimistic Wiki Sync:** Proactively updates lagging Wiki entries with a single-line Git receipt rather than asking permission first.
- **Single Live Status Card:** Patches one Feishu card in place for progress, WorkingContext, `/stop`, `ask_user`, and final delivery.
- **Pocket silent boundary:** Scheduled Pocket tasks write results back to Pocket silently unless a reminder was requested or human intervention is required ([harness.md](../design/harness.md)).

## 6. Minimalist Trust, Storage, and Export

- **Trust:** Feishu `allowlist(open_id)` and Pocket Bearer auth at ingress + OS `chmod 444` on `AGENTS.md` and `skills/**` + two in-process locks (`gui_lock`, `wiki_git_lock`).
- **Storage & Export:** One WAL-mode `nika.db` (`synchronous=FULL`): `nextloop` owns `session_events`, Nika's scheduler owns `ingress_events` / `threads` / `tasks`, and content-addressed files live in `/data/assets/`, with a 15-line `nika export` CLI outputting standard OpenAI JSONL from `surface_op != 'none'` events.
