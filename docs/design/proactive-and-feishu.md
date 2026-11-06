# Proactive, Feishu, and Minimalist Trust Design

Status: **Accepted minimalist baseline (2026-11-06)**.

## 1. Cross-entry recall via raw SQLite queries (No background LLM summary bloat)

Each Feishu entry (private chat, group Thread, document comment) maps to its own isolated Session so conversations never cross-contaminate.

Instead of running a background LLM call after every Turn to generate micro-summaries—or injecting a dynamic summary list into Session start (which misses long-lived DM Sessions and pollutes prompt cache)—`nika` uses the facts already sitting in SQLite:

- **`session_ctl(action="recent", limit=5)`:** Queries `session_events` directly in < 1ms and returns the last N recently active Sessions across all Feishu entries, showing `(session_id, entry_title, updated_at, first_user_message[:100], last_final_reply[:100])`.
- **`session_ctl(action="inspect", session_id=..., last_turns=2)`:** Pulls the exact user/assistant messages from that target Session when the user says *"按刚才群里定的改"* or *"把刚才那个 task grill 一下"*.
- Zero background LLM calls, zero cache invalidation, and works identically in brand-new Threads and month-old DM Sessions.

## 2. Feishu documents & comments: Comment-as-Anchor + Read-back verification

1. **Ingress Auto-Slice (`Comment-as-Anchor`):**
   - When woken by a document `@` comment, `nika`'s Feishu ingress automatically fetches the quoted anchor text plus ±2 surrounding paragraphs and prepends them to the initial user message. The model sees the exact passage under discussion on Step 1 without spending a Tool Call.
2. **Reliable Document Editing (`feishu_doc`):**
   - Avoids inventing a custom `[b11]` Markdown-to-Block bidirectional compiler that breaks on nested lists, tables, or existing comment anchors.
   - `feishu_doc` uses mature section/paragraph locator operations (`read`, `replace_section`, `append`, `reply_comment`) and automatically reads back the modified section to verify the edit landed cleanly.

## 3. Three-part Proactive protocol (Cognitive offloading, zero spam)

Proactive behavior in `nika` means **reducing the user's cognitive bandwidth**, never running a noisy cron bot:

1. **Ingress Pre-Hydration:** Before Step 1, `nika` extracts Feishu Doc tokens and attachment metadata from the incoming message and attaches their titles/paths to the initial user message.
2. **Optimistic Wiki Sync with Receipt:** When a task verifies that a local `AgentWiki` entry lags behind an authoritative trace/repo, `nika` updates the Wiki via `wiki(action="upsert")` and appends a one-line footer receipt (`📝 Wiki: projects/tcc.md (active) · rev a1b2c3d`) so the user can ignore it if right or say *"撤回"* (`git revert`) if wrong.
3. **Single Live Status Card (In-place patch):** During multi-step execution, `nika` posts **one** Feishu Interactive Card per Turn and patches it in place (throttled to ≤ 1 patch / 2s) with current Step, active Tool, WorkingContext, and a `/stop` button. `ask_user` (`WaitingRequest`) renders on the same card, and final delivery replaces the card body with the final answer + telemetry footer (`🐾 46s · step 4 · 92% cache · 📝 Wiki rev a1b2`).

## 4. Occam's Razor cuts

1. **No `lite / pro / promax` budget profiles or `configure_budget` tool:** Replaced by a deterministic **Step 15 Pacing Watermark** injected into Tool Results on long Turns.
2. **No custom `trace/v1` or `aift/v1` schemas:** `session_events` in SQLite is the trace; `nika export` outputs standard OpenAI JSONL from `surface_op != 'none'` events in 15 lines of Python.
3. **No pass-through Adapter wrappers:** `nika` directly uses `nextloop`'s `SQLiteEventStore`, `AppendOnlyContextBuilder`, and `OpenAI/AnthropicProvider`, implementing only `FeishuDelivery` and `NikaToolRuntime`.
4. **Simple Unix trust & 2 container locks:** Feishu `allowlist(open_id)` at ingress, OS `chmod 444` on `AGENTS.md` and `skills/**`, and two in-process locks (`gui_lock`, `wiki_git_lock`).
