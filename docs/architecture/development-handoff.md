# nika product handoff

Last verified: 2026-11-24. Both [nextloop](https://github.com/12bitsD/nextloop) (1.0 core implemented) and `nika` (personal superagent harness design closed) are ready for local end-to-end implementation.

## Architecture summary

1. **Execution kernel (`nextloop`):**
   - DSH-aligned Turn/Step driver with 4D integer coordinates (`session_id`, `turn`, `step`, `attempt`) + `writer_epoch`.
   - Closed 5-variant `ToolOutcome` ADT (`Completed`, `Skipped`, `Cancelled`, `UncertainSettled`, `UncertainHanging`).
   - Symmetric `parallel`/`exclusive` barrier scheduling: any error or uncertainty on an `exclusive` barrier call automatically truncates the rest of the batch as `Skipped`.
   - In-memory single-actor `Inbox` serialization + SQLite crash invariants + `surface_op` (`append | epoch | none`) O(Δ) watermark projection.
2. **Personal superagent harness (`nika`):**
   - Directly reuses `nextloop`'s `SQLiteEventStore`, internal `AgentLoop` context projection/compaction, and `OpenAI/AnthropicProvider` without pass-through wrappers.
   - **Thin Channel Adapters & Unified Envelope:** `FeishuAdapter` and `PocketAdapter` translate native events into `{event_id, source, thread_key, prompt, reply_target}`; Pocket scheduled tasks ack `202` and write back via one-time `callback_token` (silent on Feishu by default).
   - **Deterministic Scheduler (`src/nika/scheduler.py`):** Shares WAL-mode `nika.db` with `nextloop` and adds only 3 tables (`ingress_events`, `threads`, `tasks`); routes unbound messages to `main` and bound follow-ups 1-hop to the owning specialist.
   - **`1 main + 4 specialists`:** Read-only config packs (`main`, `top_talent`, `coder`, `doc_research`, `eval`), Task-scoped Sessions recycled on `report_task`, and exactly 3 internal tools (`dispatch_task`, `report_task`, blind `consult_peer` hard-locked at `depth=1`). Offline RSI repo evolves config packs separately.
   - **Memory & Cross-Entry Recall:** Static core aliases in frozen `AGENTS.md` + dual-repo Wiki (`src/nika/wiki.py` mounting existing work `workwiki` and personal `0h` Git repos directly, sub-5ms `ripgrep` H2-TOC search, per-repo Git receipts) + raw SQLite `session_ctl(action="recent" | "inspect")`.
   - **Feishu & Proactive UX:** `Comment-as-Anchor` auto-slicing (±2 paragraphs), section-based document edits with mandatory read-back check, Ingress Pre-Hydration, and a Single Live Status Card patched in place.
   - **Consolidated Deep Tools:** `read`, `edit`, `write`, `grep`, `bash`, `wiki`, `pocket` (native `/v1/rpc/{method}`, no MCP wrapper), `feishu_doc`, `gui`, `session_ctl`, plus the 3 orchestration tools.
   - **Minimalist trust:** Feishu `allowlist(open_id)` + Pocket Bearer auth + OS `chmod 444` on `AGENTS.md`/`skills/**` + two container locks (`gui_lock`, `wiki_git_lock`). Device Link bridge waits for the standalone protocol repo.

## Key documents

1. [Harness design](../design/harness.md) — **current authoritative baseline (2026-11-24)**.
2. [ADR-0002](../adr/0002-single-agent-loop.md) — single-agent foundation and 2026-11-24 extension note.
3. [Dual-repo Wiki design](../design/agentwiki.md) — `src/nika/wiki.py` + `skills/wiki/SKILL.md` contract.
4. [Proactive, Feishu & Trust](../design/proactive-and-feishu.md) — SQLite cross-entry recall, `Comment-as-Anchor`, Single Live Status Card, and Occam's Razor cuts.
5. [System Prompt & Deep Tools](../design/system-prompt.md) and [Compaction Prompt](../design/compaction-prompt.md).
6. [Roadmap](discussion-roadmap.md), [Requirements](requirements.md), and [Feature worklist](feature-worklist.md).
