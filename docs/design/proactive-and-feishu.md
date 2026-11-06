# Proactive, Feishu, and Minimalist Trust Design

Status: **Accepted minimalist baseline (2026-11-06)**. Replaces the previously open Proactive, M6 Trust/Resources, and M7 Feishu/Export design topics with concrete, low-complexity mechanisms.

## 1. Cross-entry short-term hippocampus (`L0 Recent Pulse`)

Each Feishu entry (private chat, group Thread, document comment) maps to its own isolated Session so conversations never cross-contaminate. However, strict isolation causes "entry-silo amnesia" when the user switches from a group Thread to a document comment or DM 10 minutes later and says *"按刚才群里定的改"*.

**Mechanism (`L0 Recent Pulse`, ≤ 500 tokens):**
- When any Turn completes (`turn/end`), `nika` records a one-line micro-summary (≤ 80 chars) in a SQLite ring buffer (keeping the last 5 completed Turns across the user's Sessions).
- On the first Step of a new Session, `nika` injects those 5 lines alongside `AGENTS.md` and the `L1 Wiki Synapse Map`:
  ```text
  # Recent Activity Pulse (last 5 turns across entries)
  - [8m ago · Thread chatty-eval (session_a9, turn 3)] 确认 verbose 采用 JSONL + 16KiB 截断，仅覆盖一级子 agent
  - [42m ago · Doc TCC设计 (session_b2, turn 1)] 核对 trace rev 111，更新 branch 隔离口径
  ```
- If the user references recent cross-entry work, the model sees the `session_id` in `Recent Pulse` and calls `session_ctl(inspect_session="session_a9")` on demand. No multi-agent Router or shared global Session is needed.

## 2. Feishu documents & comments: Comment-as-Anchor + Virtual Markdown

Feishu's native nested Block JSON is error-prone for LLMs, and comment webhooks alone lack surrounding document context.

1. **Ingress Auto-Slice (`Comment-as-Anchor`):**
   - When woken by a document `@` comment, `nika`'s Feishu ingress automatically fetches the quoted anchor block plus ±2 surrounding blocks rendered as **Virtual Markdown with short block IDs (`[b11]`)**, and prepends them to the initial user message. The model sees the exact paragraph under discussion on Step 1 without spending a Tool Call.
2. **Virtual Markdown Editing (`feishu_doc`):**
   - Reading a document renders blocks as Markdown prefixed by `[b10]`, `[b11]`.
   - Editing accepts Markdown targeted at a block ID (`replace_block(doc_token, block_id="b11", markdown="...")` or `insert_after(...)`), compiles Markdown to Feishu blocks in Python, and performs an automatic read-back check.

## 3. Three-part Proactive protocol (Cognitive offloading, zero spam)

Proactive behavior in `nika` means **reducing the user's cognitive bandwidth**, never running a noisy cron bot that spams unsolicited messages:

1. **Ingress Pre-Hydration:** Before Step 1, `nika` parses incoming messages for Feishu Doc URLs, attachments, and known `L1 Synapse Map` aliases, pre-attaching document titles/metadata.
2. **Optimistic Wiki Sync with Receipt:** When a task verifies that a local `AgentWiki` entry lags behind an authoritative trace/repo, `nika` updates the Wiki via `wiki_upsert` during the Turn and appends a one-line footer receipt (`📝 Wiki: projects/tcc.md (active) · rev a1b2c3d`) so the user can ignore it if right or say *"撤回"* (`git revert`) if wrong.
3. **Single Live Status Card (In-place patch):** During multi-step execution, `nika` posts **one** Feishu Interactive Card and patches it in place (throttled to ≤ 1 patch / 2s) with current Step, active Tool, WorkingContext, and a `/stop` button. `WaitingRequest` (`ask_user`) renders on the same card, and final delivery replaces the card body with the final answer + telemetry footer (`🐾 46s · step 4 · 92% cache · 📝 Wiki rev a1b2`).

## 4. Occam's Razor cuts (Eliminating spec bloat)

1. **No `lite / pro / promax` budget profiles or `configure_budget` tool:**
   - Having a model spend a Tool Call to reconfigure a soft counter that never stops execution is pure overhead.
   - **Replacement:** Deterministic **Step Pacing Watermark**. Every 15 Steps in a Turn, Runtime appends a one-line hint to the latest Tool Result: `[Runtime: Step 15 reached; verify progress, converge, or call ask_user if blocked]`.
2. **No custom `trace/v1` or `aift/v1` schemas:**
   - `session_events` in SQLite is already the complete trace.
   - Standard SFT/AIFT training data is exported offline via a 15-line CLI command (`nika export --format openai-jsonl`) projecting `surface_op != 'none'` events.
3. **No pass-through Adapter wrappers:**
   - `nika` directly uses `nextloop`'s built-in `SQLiteEventStore`, `AppendOnlyContextBuilder`, and `OpenAI/AnthropicProvider`. `nika` only implements Feishu Ingress/Delivery and its concrete `ToolRuntime`.
4. **Simple Unix trust & 2 container locks (Replaces complex M6 RBAC):**
   - **Entry gate:** Feishu `allowlist(open_id)` at ingress.
   - **Behavior file protection:** OS-level read-only permissions (`chmod 444 AgentWiki/AGENTS.md AgentWiki/skills/**`), unlocked only when the user explicitly authorizes a behavior/skill update.
   - **Resource locks:** Exactly two in-process locks in the single container—`gui_lock` (serializing virtual desktop / stateful browser actions) and `wiki_git_lock` (serializing Wiki Git commits).
