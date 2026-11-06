# nika vision

Status: accepted minimalist product direction (refined 2026-11-06).

## Goal

Build a **personal agent and superagent** for one user's real work in Feishu. `nika` reduces cognitive load across chat, coding, documents, comments, and container-based Browser/Computer tasks—without framework ceremony or notification spam.

## Core design principles

- **Direct kernel reuse, zero pass-through wrappers:** `nika` uses [nextloop](https://github.com/12bitsD/nextloop)'s Turn/Step driver, `SQLiteEventStore`, `AppendOnlyContextBuilder`, and `OpenAI/AnthropicProvider` directly, implementing only Feishu Ingress/Delivery and its concrete `ToolRuntime`.
- **Three-tier memory without a Vector DB:**
  - **`L0 Recent Pulse` (≤ 500 tokens):** Last 5 completed Turn micro-summaries across Feishu entries, preventing entry-silo amnesia.
  - **`L1 Wiki Synapse Map` (≤ 2 KiB):** Compact `id → when/keys` index injected at Session start with 100% prompt-cache hit.
  - **`L2 AgentWiki` (`src/nika/wiki.py` + `skills/wiki/SKILL.md`):** Conditioned-reflex `when` triggers, H2-TOC `wiki(action="search")`, and optimistic Git-backed writes with single-line reply receipts (`📝 Wiki: ... · rev <sha>`).
- **Deep, orthogonal tools:** 7 tool groups (`read`, `edit`, `write`, `grep`, `bash`, `wiki`, `feishu_doc`, `gui`, `session_ctl`) where `read` handles files, directory trees, and Wiki entries alike.
- **Proactive = cognitive offloading, not spam:** Ingress Pre-Hydration (`Comment-as-Anchor` slicing ±2 blocks as Virtual Markdown), optimistic Wiki sync with a Git revert receipt, and a **Single Live Status Card** patched in place.
- **Unix simplicity for trust & ops:** Feishu `allowlist(open_id)`, OS `chmod 444` on behavior files (`AGENTS.md`, `skills/**`), two in-process container locks (`gui_lock`, `wiki_git_lock`), and a 15-line CLI export from SQLite.

See [ADR-0002](docs/adr/0002-single-agent-loop.md), [AgentWiki](docs/design/agentwiki.md), and [Proactive & Feishu](docs/design/proactive-and-feishu.md).
