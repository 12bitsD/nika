# nika context

This file defines `nika`'s product vocabulary. Execution terms (`AgentLoop`, `Turn`, `Step`, `Attempt`, `WriterLease`, `SurfaceOp`, `ToolOutcome`) are canonically defined in [nextloop CONTEXT](https://github.com/12bitsD/nextloop/blob/main/CONTEXT.md).

## Harness & Routing

| Term | Definition |
|---|---|
| Unified Internal Envelope | Single ingress shape `{event_id, source, thread_key, prompt, reply_target}` consumed by Nika's core; external apps translate to/from it in thin channel adapters (`FeishuAdapter`, `PocketAdapter`). |
| Deterministic Scheduler | Pure-code glue (`src/nika/scheduler.py`) owning dedup, thread binding, and task stages in `nika.db`—never inferring routing state from free-form model text. |
| Specialist Config Pack | Read-only bundle (System Prompt, Skills, tool allowlist) for `main`, `top_talent`, `coder`, `doc_research`, or `eval`; mounted per Task and evolved offline by a separate RSI repo. |
| 1-hop Thread Binding | Mapping `thread_key` → specialist Task Session so follow-ups in the same Feishu thread/comment reach that specialist directly without re-entering `main`. |
| `consult_peer` (`depth=1`) | Blind artifact-only peer review tool; scheduler rejects any nested call (`depth >= 1`) to prevent recursive agent loops. |
| Pocket Silent Boundary | Scheduled Pocket tasks write results back to Pocket via one-time `callback_token` and stay off Feishu unless a reminder was requested or the run fails / locks / needs a decision. |

## Memory & Knowledge

| Term | Definition |
|---|---|
| `AGENTS.md` | Persona, expression rules, and static core project/person aliases injected at Session start (`chmod 444`, 100% prompt-cache hit). |
| Dual-repo Wiki | Nika's long-term memory formed by mounting the existing work (`workwiki`) and personal (`0h`) Git repositories directly—no third private Wiki schema. |
| H2-TOC Search | `wiki(action="search")` output combining repo/path, native frontmatter, Markdown `## H2` headings with line ranges (`L12-L28`), and body snippets for single-hop `read` targeting. |
| Git Receipt | Single-line footer (`📝 Wiki: <repo>:<path> (<state>) · rev <sha>`) appended when `wiki(action="upsert")` commits to a mounted Wiki repo, enabling zero-friction `git revert`. |
| Cross-entry SQLite Recall | `session_ctl(action="recent" \| "inspect")` querying raw first/last message snippets across recent Sessions directly from SQLite (< 1ms, zero LLM overhead). |

## Product capabilities & UX

| Term | Definition |
|---|---|
| `Comment-as-Anchor` | Feishu ingress mechanism that automatically slices the commented document passage ±2 surrounding paragraphs into Step 1 context. |
| Single Live Status Card | One Feishu Interactive Card per Turn patched in place (≤ 1 patch / 2s) for progress, WorkingContext, `/stop`, `ask_user`, and final delivery. |
| Deep Tool Catalog | Consolidated set of orthogonal tools (`read`, `edit`, `write`, `grep`, `bash`, `wiki`, `pocket`, `feishu_doc`, `gui`, `session_ctl`) plus 3 internal orchestration tools (`dispatch_task`, `report_task`, `consult_peer`). |
| Step Pacing Watermark | Deterministic runtime hint injected at every 15 Steps in a Turn to prompt convergence, replacing `lite/pro/promax` and `configure_budget`. |
