# nika product handoff

Last verified: 2026-11-06. Both [nextloop](https://github.com/12bitsD/nextloop) and `nika` architectural designs have been converged and simplified via Occam's Razor.

## Architecture summary

1. **Execution kernel (`nextloop`):**
   - DSH-aligned Turn/Step driver with 4D integer coordinates (`session_id`, `turn`, `step`, `attempt`) + `writer_epoch`.
   - Closed 5-variant `ToolOutcome` ADT (`Completed`, `Skipped`, `Cancelled`, `UncertainSettled`, `UncertainHanging`).
   - In-memory single-actor `Inbox` serialization + SQLite crash invariants + `surface_op` (`append | epoch | none`) O(Δ) watermark projection.
2. **Product superagent (`nika`):**
   - Directly reuses `nextloop`'s `SQLiteEventStore`, `AppendOnlyContextBuilder`, and `OpenAI/AnthropicProvider` without pass-through wrappers.
   - **Three-tier memory:** `L0 Recent Pulse` (last 5 Turn summaries across Feishu entries, ≤ 500 tokens) + `L1 Wiki Synapse Map` (`id → when/keys`, ≤ 2 KiB) + `L2 AgentWiki` (`src/nika/wiki.py` + `AgentWiki/skills/wiki/SKILL.md` with H2-TOC search and optimistic Git-backed writes with single-line receipts).
   - **Feishu & Proactive UX:** `Comment-as-Anchor` auto-slicing, Virtual Markdown (`[b11]`) document editing, Ingress Pre-Hydration, and a Single Live Status Card patched in place.
   - **Consolidated Deep Tools:** `read` (files, directories, Wiki), `edit`, `write`, `grep`, `bash`, `wiki`, `feishu_doc`, `gui`, and `session_ctl`.
   - **Minimalist trust:** Feishu `allowlist(open_id)` + OS `chmod 444` on `AGENTS.md`/`skills/**` + two container locks (`gui_lock`, `wiki_git_lock`).

## Key documents

1. [ADR-0002](../adr/0002-single-agent-loop.md) — product architecture baseline.
2. [AgentWiki design](../design/agentwiki.md) — `src/nika/wiki.py` + `skills/wiki/SKILL.md` contract.
3. [Proactive, Feishu & Trust](../design/proactive-and-feishu.md) — `L0 Recent Pulse`, Virtual Markdown, Single Live Status Card, and Occam's Razor cuts.
4. [System Prompt & Deep Tools](../design/system-prompt.md) and [Compaction Prompt](../design/compaction-prompt.md).
5. [Roadmap](discussion-roadmap.md) and [Feature worklist](feature-worklist.md).
