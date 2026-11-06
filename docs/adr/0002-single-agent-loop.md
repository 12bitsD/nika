# ADR-0002: Consolidate nika as the personal superagent over nextloop

- Status: Accepted (refined 2026-11-06 with Occam's Razor simplifications)
- Date: 2026-10-26
- Updated: 2026-11-06
- Supersedes: [ADR-0001](0001-unified-agent-runtime.md)
- Scope: repository boundary, three-tier context/memory (`L0/L1/L2`), Feishu Virtual Markdown, deep tool catalog, Proactive protocol, and minimalist container trust

## 1. Direct reuse over pass-through wrappers

[nextloop](https://github.com/12bitsD/nextloop) owns the DSH-aligned Turn/Step driver, 4D integer coordinates, closed 5-variant `ToolOutcome` ADT, `surface_op` watermark projection, `SQLiteEventStore`, `AppendOnlyContextBuilder`, and `OpenAI/AnthropicProvider`.

`nika` reuses those modules directly without pass-through wrappers, implementing only:
- **`FeishuDelivery` & Ingress** (Feishu events, `Comment-as-Anchor` slicing, Single Live Status Card);
- **`NikaToolRuntime` & `AgentWiki`** (`src/nika/wiki.py`, `AgentWiki/skills/wiki/SKILL.md`, and the consolidated deep tools).

## 2. Entry isolation + `L0 Recent Pulse` (Cross-entry awareness)

Each Feishu entry maps to its own isolated Session (`chat_id` for DM, `thread_id` for group topics, `comment_id` for partial doc comments, `doc_token` for whole-doc comments).

To prevent cross-entry amnesia without merging Sessions, `nika` maintains an **`L0 Recent Pulse` ring buffer** (the last 5 completed Turn micro-summaries across entries, ≤ 500 tokens) and injects it into the initial context of any new Session alongside `AGENTS.md` and the `L1 Wiki Synapse Map`. When the user refers to recent work in another thread, the model pulls details on demand via `session_ctl(inspect_session=...)`.

## 3. Consolidated Deep Tool Catalog

Instead of ~18 granular tools, `nika` exposes a small set of deep, orthogonal tools ([system-prompt.md](../design/system-prompt.md)):

- **`read`** (reads files, directories as trees—replacing `ls`, and `AgentWiki` entries—replacing `wiki_read`), **`edit`**, **`write`**, **`grep`**, **`bash`**;
- **`wiki(action="search" | "upsert" | "revert")`** (implemented in `src/nika/wiki.py` + guided by `AgentWiki/skills/wiki/SKILL.md`);
- **`feishu_doc(action="read" | "replace_block" | "insert_after" | "reply_comment")`** (Virtual Markdown with `[b11]` block tags);
- **`gui(target="browser" | "desktop")`** (container browser and virtual desktop serialized by `gui_lock`);
- **`session_ctl(working_context?, skill_view?, inspect_session?, ask_user?)`**.

Redundant `lite/pro/promax` budget profiles and `configure_budget` are removed in favor of a deterministic **Step 15 Pacing Watermark** injected by Runtime into Tool Results when a Turn runs long.

## 4. AgentWiki (`L1 Synapse Map` + `when` triggers + Git receipts)

Full contract: [agentwiki.md](../design/agentwiki.md).
- **L1 Synapse Map (`≤ 2 KiB`):** Compiled from `active` headers and injected at Session start (100% prompt-cache hit).
- **Conditioned-reflex `when` triggers:** Frontmatter records symptom/scenario triggers so past playbooks surface during new tasks.
- **H2-TOC search:** `wiki(action="search")` returns full Frontmatter + Markdown `## H2` line ranges + snippets.
- **Optimistic Git-backed writes:** `wiki(action="upsert")` commits every change to Git and appends a one-line footer receipt (`📝 Wiki: <path> (<state>) · rev <sha>`) to the reply for effortless `git revert`.

## 5. Proactive protocol & Feishu UX

Full contract: [proactive-and-feishu.md](../design/proactive-and-feishu.md).
- **Ingress Pre-Hydration & `Comment-as-Anchor`:** Automatically slices quoted document blocks (±2 blocks as Virtual Markdown) and resolves mentioned aliases before Step 1.
- **Optimistic Wiki Sync:** Proactively updates lagging Wiki entries with a single-line Git receipt rather than asking permission first.
- **Single Live Status Card:** Patches one Feishu card in place for progress, WorkingContext, `/stop`, `ask_user`, and final delivery.

## 6. Minimalist Trust, Storage, and Export

- **Trust:** Feishu `allowlist(open_id)` at ingress + OS `chmod 444` on `AGENTS.md` and `skills/**` + two in-process locks (`gui_lock`, `wiki_git_lock`).
- **Storage & Export:** `nextloop`'s `session_events` table in SQLite (`WAL`, `synchronous=FULL`) plus content-addressed `/data/assets/` files. Custom `trace/v1` and `aift/v1` formats are replaced by direct SQLite queries and a simple `nika export` CLI outputting standard OpenAI-format JSONL from `surface_op != 'none'` events.
