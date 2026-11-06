# nika requirements map

This map records accepted product requirements and their minimalist verification targets.

| ID | Requirement and user value | Authoritative design | Status and acceptance required |
|---|---|---|---|
| N1 | Talk privately, in Threads, and at document comments with cross-entry awareness | [Proactive & Feishu](../design/proactive-and-feishu.md) | **Design closed.** Feishu allowlist, dedupe, `L0 Recent Pulse` ring buffer, and Single Live Status Card |
| N2 | Read and edit Feishu documents/comments without raw Block JSON | [Comment-as-Anchor & Virtual Markdown](../design/proactive-and-feishu.md#2-feishu-documents--comments-comment-as-anchor--virtual-markdown) | **Design closed.** Auto-sliced comment context, `[b11]` Markdown replacement, and read-back check |
| N3 | Complete chat and coding through one execution path and 7 deep tools | [System Prompt](../design/system-prompt.md) | **Design closed.** Consolidated deep tool catalog (`read` handles files, directories, and Wiki) |
| N4 | Directly reuse `nextloop` without pass-through wrappers | [Adapter contract](nextloop-adapter.md) | **Design closed.** Direct use of `nextloop` SQLite/Context/Provider; implement `NikaToolRuntime` and `FeishuDelivery` |
| N5 | Recall and connect long-term knowledge (`src/nika/wiki.py` + `skills/wiki/SKILL.md`) | [AgentWiki](../design/agentwiki.md) | **Design closed.** `L1 Synapse Map` (≤ 2 KiB), `when` triggers, H2-TOC `wiki(action="search")`, and `read` |
| N6 | Proactively curate Wiki knowledge while protecting behavior files | [AgentWiki writes](../design/agentwiki.md#4-git-backed-optimistic-writes--single-line-receipt-wiki_upsert) | **Design closed.** Optimistic Git-committed `wiki(action="upsert")` + single-line receipt; OS `chmod 444` on `AGENTS.md` and `skills/**` |
| N7 | Use container Browser and desktop safely | [ADR-0002](../adr/0002-single-agent-loop.md) | **Design closed.** Unified `gui(target="browser" \| "desktop")` serialized by `gui_lock` |
| N8 | Maintain a damped WorkingContext reminder and sharp Compaction | [Compaction Prompt](../design/compaction-prompt.md) | **Design closed.** 200-word 4-part Compaction Prompt + `nextloop` WorkingContext damping |
| N9 | Reduce cognitive load via deterministic Proactive mechanisms | [Proactive protocol](../design/proactive-and-feishu.md#3-three-part-proactive-protocol-cognitive-offloading-zero-spam) | **Design closed.** Ingress Pre-Hydration, Optimistic Wiki Sync with Receipt, and Single Live Status Card |
| N10 | Keep trust, locks, storage, and export simple | [Occam's Razor cuts](../design/proactive-and-feishu.md#4-occams-razor-cuts-eliminating-spec-bloat) | **Design closed.** Feishu `allowlist`, `chmod 444`, 2 container locks (`gui_lock`, `wiki_git_lock`), SQLite backup, and `nika export` CLI |
