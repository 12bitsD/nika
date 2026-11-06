# nika context

This file defines `nika`'s product vocabulary. Execution terms (`AgentLoop`, `Turn`, `Step`, `Attempt`, `WriterLease`, `SurfaceOp`, `ToolOutcome`) are canonically defined in [nextloop CONTEXT](https://github.com/12bitsD/nextloop/blob/main/CONTEXT.md).

## Memory & Knowledge

| Term | Definition |
|---|---|
| `AGENTS.md` | Persona, expression rules, and static core project/person aliases injected at Session start (`chmod 444`, 100% prompt-cache hit). |
| `AgentWiki` | The only long-term knowledge store (`AGENTS.md`, `wiki/**`, `skills/**`), implemented in `nika` as `src/nika/wiki.py` plus `AgentWiki/skills/wiki/SKILL.md`. |
| `when` trigger | Frontmatter field capturing symptoms, error patterns, or scenarios when an entry should be recalled, enabling cross-task memory connection via live `ripgrep`. |
| H2-TOC Search | `wiki(action="search")` output combining full YAML frontmatter, Markdown `## H2` headings with line ranges (`L12-L28`), and body snippets for single-hop `read` targeting. |
| Git Receipt | Single-line footer (`📝 Wiki: <path> (<state>) · rev <sha>`) appended when `wiki(action="upsert")` updates `wiki/**`, enabling zero-friction `git revert`. |
| Cross-entry SQLite Recall | `session_ctl(action="recent" \| "inspect")` querying raw first/last message snippets across recent Feishu Sessions directly from SQLite (< 1ms, zero LLM overhead). |

## Product capabilities & UX

| Term | Definition |
|---|---|
| `Comment-as-Anchor` | Feishu ingress mechanism that automatically slices the commented document passage ±2 surrounding paragraphs into Step 1 context. |
| Single Live Status Card | One Feishu Interactive Card per Turn patched in place (≤ 1 patch / 2s) for progress, WorkingContext, `/stop`, `ask_user`, and final delivery. |
| Deep Tool Catalog | Consolidated set of orthogonal tools (`read`, `edit`, `write`, `grep`, `bash`, `wiki`, `feishu_doc`, `gui`, `session_ctl`). |
| Step Pacing Watermark | Deterministic runtime hint injected at every 15 Steps in a Turn to prompt convergence, replacing `lite/pro/promax` and `configure_budget`. |
