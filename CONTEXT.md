# nika context

This file defines `nika`'s product vocabulary. Execution terms (`AgentLoop`, `Turn`, `Step`, `Attempt`, `WriterLease`, `SurfaceOp`, `ToolOutcome`) are canonically defined in [nextloop CONTEXT](https://github.com/12bitsD/nextloop/blob/main/CONTEXT.md).

## Three-tier context & memory (`L0 / L1 / L2`)

| Term | Definition |
|---|---|
| `L0 Recent Pulse` | Short-term cross-entry ring buffer (last 5 completed Turn micro-summaries across Feishu entries, ≤ 500 tokens) injected at Session start to prevent entry-silo amnesia. |
| `L1 Wiki Synapse Map` | Compact `id → when/keys` index (≤ 2 KiB) compiled from `active` `AgentWiki` headers and injected alongside `AGENTS.md` at Session start (100% prompt-cache hit). |
| `L2 AgentWiki` | The only long-term knowledge store (`AGENTS.md`, `wiki/**`, `skills/**`), implemented in `nika` as `src/nika/wiki.py` plus `AgentWiki/skills/wiki/SKILL.md`. |
| `when` trigger | Frontmatter field capturing symptoms, intents, or scenarios when an entry should be recalled, enabling cross-task memory connection without a Vector DB. |
| Git Receipt | Single-line footer (`📝 Wiki: <path> (<state>) · rev <sha>`) appended when `wiki(action="upsert")` updates `wiki/**`, enabling zero-friction `git revert`. |

## Product capabilities & UX

| Term | Definition |
|---|---|
| `Comment-as-Anchor` | Feishu ingress mechanism that automatically slices the commented document block ±2 surrounding blocks as Virtual Markdown (`[b11]`) into Step 1 context. |
| Virtual Markdown | Representation of Feishu Docx blocks as `[b10]`, `[b11]` Markdown lines so the model can read and edit documents without touching raw Feishu Block JSON. |
| Single Live Status Card | One Feishu Interactive Card per Turn patched in place (≤ 1 patch / 2s) for progress, WorkingContext, `/stop`, `ask_user`, and final delivery. |
| Deep Tool Catalog | Consolidated set of orthogonal tools (`read`, `edit`, `write`, `grep`, `bash`, `wiki`, `feishu_doc`, `gui`, `session_ctl`). |
| Step Pacing Watermark | Deterministic runtime hint injected at every 15 Steps in a Turn to prompt convergence, replacing `lite/pro/promax` and `configure_budget`. |
