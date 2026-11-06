# nika product handoff

Last verified: 2026-11-06. Both [nextloop](https://github.com/12bitsD/nextloop) and `nika` architectural designs are converged and ready for local end-to-end implementation.

## Architecture summary

1. **Execution kernel (`nextloop`):**
   - DSH-aligned Turn/Step driver with 4D integer coordinates (`session_id`, `turn`, `step`, `attempt`) + `writer_epoch`.
   - Closed 5-variant `ToolOutcome` ADT (`Completed`, `Skipped`, `Cancelled`, `UncertainSettled`, `UncertainHanging`).
   - Symmetric `parallel`/`exclusive` barrier scheduling: any error or uncertainty on an `exclusive` barrier call automatically truncates the rest of the batch as `Skipped`.
   - In-memory single-actor `Inbox` serialization + SQLite crash invariants + `surface_op` (`append | epoch | none`) O(Δ) watermark projection.
2. **Product superagent (`nika`):**
   - Directly reuses `nextloop`'s `SQLiteEventStore`, `AppendOnlyContextBuilder`, and `OpenAI/AnthropicProvider` without pass-through wrappers.
   - **Memory & Cross-Entry Recall:** Static core aliases in frozen `AGENTS.md` + `AgentWiki` (`src/nika/wiki.py` + `AgentWiki/skills/wiki/SKILL.md` with `when` symptom triggers, sub-5ms `ripgrep` H2-TOC search, and optimistic Git-backed writes with single-line receipts) + raw SQLite cross-entry recall via `session_ctl(action="recent" | "inspect")`.
   - **Feishu & Proactive UX:** `Comment-as-Anchor` auto-slicing (±2 paragraphs), section-based document edits with mandatory read-back check, Ingress Pre-Hydration, and a Single Live Status Card patched in place.
   - **Consolidated Deep Tools:** `read` (files, directories, Wiki), `edit`, `write`, `grep`, `bash`, `wiki`, `feishu_doc`, `gui`, and `session_ctl`.
   - **Minimalist trust:** Feishu `allowlist(open_id)` + OS `chmod 444` on `AGENTS.md`/`skills/**` + two container locks (`gui_lock`, `wiki_git_lock`).

## Key documents

1. [ADR-0002](../adr/0002-single-agent-loop.md) — product architecture baseline.
2. [AgentWiki design](../design/agentwiki.md) — `src/nika/wiki.py` + `skills/wiki/SKILL.md` contract.
3. [Proactive, Feishu & Trust](../design/proactive-and-feishu.md) — SQLite cross-entry recall, `Comment-as-Anchor`, Single Live Status Card, and Occam's Razor cuts.
4. [System Prompt & Deep Tools](../design/system-prompt.md) and [Compaction Prompt](../design/compaction-prompt.md).
5. [Roadmap](discussion-roadmap.md) and [Feature worklist](feature-worklist.md).
