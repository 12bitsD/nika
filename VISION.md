# nika vision

Status: accepted minimalist product direction (refined 2026-11-06).

## Goal

Build a **personal agent and superagent** for one user's real work in Feishu. `nika` reduces cognitive load across chat, coding, documents, comments, and container-based Browser/Computer tasks—without framework ceremony, cache-busting dynamic prefixes, or notification spam.

## Core design principles

- **Direct kernel reuse, zero pass-through wrappers:** `nika` uses [nextloop](https://github.com/12bitsD/nextloop)'s Turn/Step driver, symmetric `parallel`/`exclusive` barrier truncation, `SQLiteEventStore`, `AppendOnlyContextBuilder`, and `OpenAI/AnthropicProvider` directly, implementing only Feishu Ingress/Delivery and its concrete `ToolRuntime`.
- **Cache-safe memory without a Vector DB or dynamic prefix bloat:**
  - **Static core aliases in `AGENTS.md`:** High-frequency project/person aliases sit in the frozen Session prefix (100% KV cache hit, zero scaling ceiling).
  - **`AgentWiki` (`src/nika/wiki.py` + `skills/wiki/SKILL.md`):** Conditioned-reflex `when` triggers, sub-5ms `ripgrep` search returning YAML frontmatter + Markdown `## H2` line ranges (TOC), and optimistic Git-backed writes with single-line reply receipts (`📝 Wiki: ... · rev <sha>`).
  - **Raw SQLite cross-entry recall:** `session_ctl(action="recent" | "inspect")` queries recent active Feishu Sessions directly from SQLite (< 1ms, zero background LLM calls).
- **Deep, orthogonal tools:** `read` (handles files, directory trees, and Wiki entries alike), `edit`, `write`, `grep`, `bash`, `wiki`, `feishu_doc`, `gui`, and `session_ctl`.
- **Proactive = cognitive offloading, not spam:** Ingress Pre-Hydration (`Comment-as-Anchor` slicing ±2 paragraphs around a doc comment), optimistic Wiki sync with a Git revert receipt, and a **Single Live Status Card** patched in place.
- **Unix simplicity for trust & ops:** Feishu `allowlist(open_id)`, OS `chmod 444` on behavior files (`AGENTS.md`, `skills/**`), two in-process container locks (`gui_lock`, `wiki_git_lock`), and a 15-line CLI export from SQLite.

See [ADR-0002](docs/adr/0002-single-agent-loop.md), [AgentWiki](docs/design/agentwiki.md), and [Proactive & Feishu](docs/design/proactive-and-feishu.md).
