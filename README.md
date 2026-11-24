# nika

A minimalist personal superagent and bot framework for Feishu, Pocket, coding, documents, and cross-device work, powered by [nextloop](https://github.com/12bitsD/nextloop).

Status: **Personal superagent harness design converged (2026-11-24)**. Ready for local end-to-end implementation.

## Architecture at a glance

```text
Feishu (DM / Thread / Doc Comment) · Pocket (/webhooks/pocket) · Future Apps
              │ Thin channel adapters (FeishuAdapter / PocketAdapter)
              ▼ Unified internal envelope {event_id, source, thread_key, prompt, reply_target}
   Deterministic Scheduler (pure code, shared nika.db WAL — 3 tables, zero external MQ)
   ingress_events (dedup) · threads (1-hop specialist binding) · tasks (stage + depth=1 lock)
              │
              ▼
          nextloop (reused directly, zero pass-through wrappers)
   1 main + 4 read-only Specialist Config Packs · Turn/Step driver · symmetric barriers · SQLite
              │
              ▼
   NikaToolRuntime (allowlist per specialist · whole-batch validation · parallel/exclusive)
   ① Native: Dual-Wiki (work + personal repos), local FS, pocket RPC, dispatch/report/consult
   ② MCP / HTTP: feishu_doc (read-back verified), third-party MCP servers
   ③ Device Link: standalone cross-device protocol (integrated after it ships)
```

## Key engineering highlights

| Area | Design |
|---|---|
| **Harness & Routing** | Four-layer personal bot framework: thin channel adapters → deterministic pure-code scheduler (no LLM state guessing) → `1 main + 4 specialists` (`top_talent`, `coder`, `doc_research`, `eval`) on `nextloop` → native/MCP/Device Link capabilities ([harness.md](docs/design/harness.md)) |
| **Specialist Collaboration** | Single public Nika identity, 1-hop thread binding to specialist Task Sessions, read-only config packs evolved by an offline RSI repo, and exactly 3 internal tools (`dispatch_task`, `report_task`, blind `consult_peer` hard-locked at `depth=1`) |
| **Pocket Integration** | Inbound native webhook (`202 Accepted` + one-time callback write-back, **silent by default** on Feishu unless reminded or blocked); outbound native `pocket(method, params)` HTTP tool to `/v1/rpc/{method}` with **no MCP wrapper** |
| **Execution kernel** | Directly reuses [nextloop](https://github.com/12bitsD/nextloop)'s Turn/Step driver, `parallel`/`exclusive` barrier truncation, `SQLiteEventStore`, internal `AgentLoop` context projection/compaction, and `OpenAI/AnthropicProvider` |
| **Knowledge & Memory** | Static core aliases in frozen `AGENTS.md` + **Dual-repo Wiki** (mounts existing work & personal Git repos directly, `ripgrep` H2-TOC search, Git-backed `upsert`/`revert` receipts) + raw SQLite cross-entry recall via `session_ctl` |
| **Feishu & Docs** | `Comment-as-Anchor` auto-slicing (±2 paragraphs), section-based document edits with mandatory read-back verification, and a **Single Live Status Card** patched in place |
| **Minimalist Trust** | Feishu `allowlist(open_id)` and Pocket Bearer auth at ingress, OS `chmod 444` on `AGENTS.md`/`skills/**`, deterministic Step 15 pacing watermark, and two container locks (`gui_lock`, `wiki_git_lock`) |

## Product documents

- [VISION.md](VISION.md) — goals, values, and scope.
- [Harness design](docs/design/harness.md) — **current authoritative baseline (2026-11-24)**: four-layer scheduler, unified envelope, Pocket adapter & silent boundary, `1+4` specialists, SQLite 3-table ledger, and dual-repo Wiki.
- [Implementation plan & development loop](docs/architecture/implementation-plan.md) — module layout, verified upstream facts, SQLite DDL, milestones M1–M6, and A–G development loop.
- [ADR-0002](docs/adr/0002-single-agent-loop.md) — consolidated single-agent foundation (extended by `harness.md`).
- [AgentWiki design](docs/design/agentwiki.md) — dual-repo mount, H2-TOC search, and Git receipts (`src/nika/wiki.py`).
- [Proactive, Feishu, and Minimalist Trust](docs/design/proactive-and-feishu.md) — SQLite cross-entry recall, `Comment-as-Anchor`, Single Live Status Card, and Occam's Razor cuts.
- [System Prompt & Deep Tools](docs/design/system-prompt.md) and [Compaction Prompt](docs/design/compaction-prompt.md).
- [nextloop Adapter contract](docs/architecture/nextloop-adapter.md) — direct module reuse and product-side seams.
- [Roadmap](docs/architecture/discussion-roadmap.md), [Requirements](docs/architecture/requirements.md), [Feature worklist](docs/architecture/feature-worklist.md), and [Handoff](docs/architecture/development-handoff.md).
- [CONTEXT.md](CONTEXT.md) — product domain vocabulary.

## Content policy

This is a public repository. Do not commit credentials, private Wiki content, real Session trajectories, internal endpoints, or personal identifiers.
