# ADR-0002: Consolidate nika as the personal superagent over nextloop

- Status: Accepted (refined 2026-11-06)
- Date: 2026-10-26
- Updated: 2026-11-06
- Supersedes: [ADR-0001](0001-unified-agent-runtime.md)
- Scope: repository boundary, SQLite cross-entry recall, `AgentWiki` H2-TOC search & Git receipts, Feishu interaction, deep tool catalog, and minimalist container trust

## 1. Direct reuse over pass-through wrappers

[nextloop](https://github.com/12bitsD/nextloop) owns the DSH-aligned Turn/Step driver, 4D integer coordinates, closed 5-variant `ToolOutcome` ADT, symmetric `parallel`/`exclusive` barrier truncation, `surface_op` watermark projection, `SQLiteEventStore`, `AppendOnlyContextBuilder`, and `OpenAI/AnthropicProvider`.

`nika` reuses those modules directly without pass-through wrappers, implementing only:
- **`FeishuDelivery` & Ingress** (Feishu events, `Comment-as-Anchor` slicing, Single Live Status Card);
- **`NikaToolRuntime` & `AgentWiki`** (`src/nika/wiki.py`, `AgentWiki/skills/wiki/SKILL.md`, and the consolidated deep tools).

## 2. Entry isolation + raw SQLite cross-entry recall

Each Feishu entry maps to its own isolated Session (`chat_id` for DM, `thread_id` for group topics, `comment_id` for partial doc comments, `doc_token` for whole-doc comments).

To bridge context across entries without background LLM summary calls or prompt-prefix bloat, `session_ctl(action="recent" | "inspect")` queries `session_events` in SQLite directly (< 1ms) to list recent active Sessions (entry title, timestamp, raw first user input, and raw final reply snippet) and pull specific Turns on demand.

## 3. Consolidated Deep Tool Catalog

`nika` exposes a small set of orthogonal deep tools ([system-prompt.md](../design/system-prompt.md)):

- **`read`** (files, directory trees—replaces `ls`, and `AgentWiki` entries—replaces `wiki_read`), **`edit`**, **`write`**, **`grep`**, **`bash`**;
- **`wiki(action="search" | "upsert" | "revert")`** (`src/nika/wiki.py` + `AgentWiki/skills/wiki/SKILL.md`);
- **`feishu_doc(action="read" | "replace_section" | "append" | "reply_comment")`** (with automatic read-back verification);
- **`gui(target="browser" | "desktop")`** (serialized by `gui_lock`);
- **`session_ctl(action="recent" | "inspect" | "working_context" | "skill_view" | "ask_user")`**;
- Deterministic **Step 15 Pacing Watermark** injected into Tool Results on long Turns (replacing `lite/pro/promax` and `configure_budget`).

## 4. AgentWiki (`when` triggers + live H2-TOC search + Git receipts)

Full contract: [agentwiki.md](../design/agentwiki.md).
- **Static core aliases in `AGENTS.md`:** High-frequency project/person aliases stay in frozen `AGENTS.md` (100% cache hit, zero dynamic prefix growth).
- **Conditioned-reflex `when` triggers:** Frontmatter records symptom/scenario triggers so past playbooks surface during new tasks.
- **Live H2-TOC search:** `wiki(action="search")` uses `ripgrep` (< 5ms) to return YAML frontmatter + Markdown `## H2` line ranges + snippets.
- **Optimistic Git-backed writes:** `wiki(action="upsert")` commits every change to Git and appends a one-line footer receipt (`📝 Wiki: <path> (<state>) · rev <sha>`) for effortless `git revert`.

## 5. Proactive protocol & Feishu UX

Full contract: [proactive-and-feishu.md](../design/proactive-and-feishu.md).
- **Ingress Pre-Hydration & `Comment-as-Anchor`:** Automatically slices quoted document paragraphs (±2 paragraphs) and attaches mentioned doc titles before Step 1.
- **Optimistic Wiki Sync:** Proactively updates lagging Wiki entries with a single-line Git receipt rather than asking permission first.
- **Single Live Status Card:** Patches one Feishu card in place for progress, WorkingContext, `/stop`, `ask_user`, and final delivery.

## 6. Minimalist Trust, Storage, and Export

- **Trust:** Feishu `allowlist(open_id)` at ingress + OS `chmod 444` on `AGENTS.md` and `skills/**` + two in-process locks (`gui_lock`, `wiki_git_lock`).
- **Storage & Export:** `nextloop`'s `session_events` table in SQLite (`WAL`, `synchronous=FULL`) plus content-addressed `/data/assets/` files, with a 15-line `nika export` CLI outputting standard OpenAI JSONL from `surface_op != 'none'` events.
