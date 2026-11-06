# nika

A minimalist personal agent and superagent for Feishu, coding, documents, and container-based Browser/Computer work, powered by [nextloop](https://github.com/12bitsD/nextloop).

Status: **Architecture converged and simplified (2026-11-06)**. Ready for local end-to-end implementation.

## Architecture at a glance

```text
Feishu IM / Threads / Document Comments (Comment-as-Anchor auto-slice)
              │
              ▼
   FeishuDelivery & Ingress (allowlist + Single Live Status Card)
   + Bootstrap: frozen System Prompt + AGENTS.md (persona + static core aliases)
              │
              ▼
          nextloop (reused directly, zero pass-through wrappers)
   4D coords · Turn/Step driver · 5-variant ToolOutcome ADT · symmetric barrier truncation · O(Δ) surface_op SQLite
              │
              ▼
   NikaToolRuntime (Consolidated Deep Tools + gui_lock & wiki_git_lock)
   read / edit / write / grep / bash / wiki / feishu_doc / gui / session_ctl
```

## Key engineering highlights

| Area | Design |
|---|---|
| **Execution kernel** | Directly reuses [nextloop](https://github.com/12bitsD/nextloop)'s DSH-aligned Turn/Step driver, symmetric `parallel`/`exclusive` barrier truncation, `SQLiteEventStore`, `AppendOnlyContextBuilder`, and `OpenAI/AnthropicProvider` |
| **Knowledge & Memory** | Static core aliases in frozen `AGENTS.md` + **`AgentWiki`** (`src/nika/wiki.py` + `skills/wiki/SKILL.md` with `when` symptom triggers, sub-5ms `ripgrep` H2-TOC search, and optimistic Git-committed writes + single-line receipts) + raw SQLite cross-entry recall via `session_ctl(action="recent" \| "inspect")` |
| **Feishu & Docs** | `Comment-as-Anchor` auto-slicing (±2 paragraphs around comment), section-based document edits with mandatory read-back verification, and a **Single Live Status Card** patched in place |
| **Deep Tool Catalog** | `read` (covers files, directory trees, and Wiki entries), `edit`, `write`, `grep`, `bash`, `wiki`, `feishu_doc`, `gui`, and `session_ctl` |
| **Minimalist Trust** | Feishu `allowlist(open_id)` at ingress, OS `chmod 444` on `AGENTS.md`/`skills/**`, deterministic Step 15 pacing watermark, and two container locks (`gui_lock`, `wiki_git_lock`) |

## Product documents

- [VISION.md](VISION.md) — goals, values, and scope.
- [ADR-0002](docs/adr/0002-single-agent-loop.md) — consolidated product architecture baseline.
- [AgentWiki design](docs/design/agentwiki.md) — `when` triggers, H2-TOC search, and Git receipts (`src/nika/wiki.py` + `skills/wiki/SKILL.md`).
- [Proactive, Feishu, and Minimalist Trust](docs/design/proactive-and-feishu.md) — SQLite cross-entry recall, `Comment-as-Anchor`, Single Live Status Card, and Occam's Razor cuts.
- [System Prompt & Deep Tools](docs/design/system-prompt.md) and [Compaction Prompt](docs/design/compaction-prompt.md).
- [nextloop Adapter contract](docs/architecture/nextloop-adapter.md) — direct module reuse plus the two product adapters.
- [Roadmap](docs/architecture/discussion-roadmap.md), [Requirements](docs/architecture/requirements.md), [Feature worklist](docs/architecture/feature-worklist.md), and [Handoff](docs/architecture/development-handoff.md).
- [CONTEXT.md](CONTEXT.md) — product domain vocabulary.

## Content policy

This is a public repository. Do not commit credentials, private Wiki content, real Session trajectories, internal endpoints, or personal identifiers.
