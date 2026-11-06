# nika feature worklist

Purpose: track product capabilities. **Open** marks a material design or verification choice. No row implies runtime implementation. Reusable execution features are tracked in [nextloop's worklist](https://github.com/12bitsD/nextloop/blob/main/docs/architecture/feature-worklist.md).

## Product integration

| Feature | Value | Current approach | Remaining decision |
|---|---|---|---|
| nextloop integration | Reuse one independently verified execution protocol | nika supplies EventStore, ModelProvider, ContextBuilder, Compactor, ToolRuntime, and DeliveryOwner adapters | Detailed Adapter contracts and compatibility verification |
| Tool Catalog | Small, intention-clear capabilities with runtime-owned defaults, validation, errors, and large-result handling | Static catalog with `ls/grep/read/write/edit/shell/skill_view/feishu_doc/browser_use/computer_use` and execution/history controls | **Open:** detailed schemas, descriptions, result formats, cancellation, timeout, and examples |
| Coding Skill | Better repository work without another runtime mode | On-demand instructions for inspection, modification, testing, diff review, and delivery | Concrete Skill content and validation workflow |
| WorkingContext content | Short, current self-reminders that do not become long-term memory | One active version per Session; 2 KiB is a soft guideline; content is not a permission channel | Implementation tests for content lifecycle, owned by nextloop |
| Budget profiles | Match optimization guidance to task size without forced termination | `lite/pro/promax`, default `pro`; changes apply after commit and return `cap/used/remaining` plus an efficiency hint | Result content, effective timing, over-budget guidance, Run versus Session defaults |
| Proactive context management | Reduce manual task framing, retrieval, distillation, and follow-up | Separate product mechanism, not WorkingContext or automatic RSI | **Open:** task phases, triggers, user-facing distillation, authorization, and interruption policy |

## Feishu and concrete capabilities

| Feature | Value | Current approach | Remaining decision |
|---|---|---|---|
| Feishu IM | Natural private, group, and Thread interaction | Long-lived connection, identity and dedupe, private/group/Thread routing | Real-client acceptance matrix and failure/retry behavior |
| Feishu documents | Read and produce collaborative documents | Read, create, and edit through product Tools | Detailed block-edit behavior and size/rate-limit handling |
| Document comments | Wake at the exact discussion location | Explicit `@` trigger, comment history, partial/whole routing, reply in place | Whether participating comments later allow follow-ups without `@`; current default is strict `@` |
| Cards and Tool trace | See progress, control execution, and inspect Tool use | Cards for status/interaction; Tool trace is a Trajectory view | Minimum useful card set and presentation details |
| BrowserUse | Complete browser tasks in the product container | Container browser with per-Session contexts where useful | Browser distribution and profile/login-state policy after language choice |
| ComputerUse | Operate desktop applications without remote devices | Container virtual desktop with a container-level GUI lock | Virtual desktop stack, application set, crash recovery, coordinate scaling |

## AgentWiki and behavior assets

| Feature | Value | Current approach | Remaining decision |
|---|---|---|---|
| AgentWiki root | One versioned home for agent behavior, knowledge, and Skills | `AGENTS.md`, `wiki/`, and `skills/` share Git versioning but not consumption semantics | Synchronization and publication workflow |
| Wiki (`src/nika/wiki.py` + `skills/wiki/SKILL.md`) | Recover and connect long-term facts/SOPs without a Vector DB | L1 Synapse Map (≤ 2 KiB), `when` symptom triggers, `wiki_search` with H2 TOC, `wiki_read`, and Git-backed optimistic `wiki_upsert` with single-line receipts ([agentwiki.md](../design/agentwiki.md)) | Module and built-in Skill implementation in `nika` |
| Wiki write protection | Proactive knowledge curation without silent behavior tampering | Optimistic Git-committed writes + reply receipt on `wiki/**`; hard read-only lock on `AGENTS.md` and `skills/**` unless explicitly unlocked | Enforcement across `wiki_upsert`, file, and shell tools |
| SkillLoader | Reuse working methods without injecting every Skill | Standard `SKILL.md`, metadata outside System Prompt, current content loaded on demand | Compatibility policy for dynamic Skill changes |
| `AGENTS.md` and Prompt | Maintain evolving behavior without rewriting runtime Prompt | Independent `AGENTS.md` refresh only on explicit user request; selected System and Compaction Prompts remain product documents | Refresh and compatibility verification |

## Product data and operations

| Feature | Value | Current approach | Remaining decision |
|---|---|---|---|
| TrajectoryRecorder | Know what happened in every Session | Mandatory append-only events through nextloop, with product-specific payloads as needed | Product payload schema and projection/rebuild rules |
| Assets | Preserve large observations without large event payloads | External content-addressed files with references and previews | Lifecycle, size limits, deduplication, backup format, GC ordering |
| SessionCatalog | Find Sessions and inspect history | `list_sessions`, cursor-based `get_trajectory`, explicit export | Filters, access rules, incomplete records |
| Batch export | Analyze or reuse Sessions only on request | On-demand archive with manifest and one JSONL per Session; no background export | Streaming layout and failure/resume behavior |
| `trace/v1` | Preserve full evidence | Full runtime and interaction events | Final versioned fields |
| `aift/v1` | Reuse model interactions for training workflows | `session_id`, `messages`, `tools`, and correlated Tool Calls/Results | Provider-specific template conversion remains separate |
| Persistent storage | Recover after restart | SQLite WAL and `synchronous=FULL`, authoritative synchronous writes, no persistent Snapshot | Exact schema, migration, transactions, corruption recovery |
| Backup | Avoid losing operational history | SQLite online backup plus asset snapshots; raw Trajectory stays out of public Git | Schedule, destination, encryption, retention, restore drills |
| GC | Bound disk usage | Manual, dry-run capable, age filters, active/pinned exclusions; no default auto-delete | Disk budget, retention, asset cleanup ordering |

## Trust and engineering

| Feature | Value | Current approach | Remaining decision |
|---|---|---|---|
| Execution trust and credentials | Rich Tools without exposing every resource to every process | Runtime-derived authorization; no generic read-only approval matrix or administrator budget ceiling | **Open:** actor trust, secret injection, child-process environment, browser login state, network/file reach |
| Deployment | One reproducible product container | Bot, browser, and virtual desktop in one container | Process supervision, health checks, mounts, resource limits |
| Language and code layout | Stable, maintainable product and Adapter code | Candidates: Rust or Python; Browser/Computer and nextloop integration ecology matter | **Open:** language, package layout, dependency policy |
| CI | Catch product and integration regressions | Public GitHub repository with contract and product smoke levels | **Open:** formatting, tests, container build, real smoke-test levels |

## Parking lot

- Agent-defined Hooks and fixed before/after Tool hooks.
- Read-only `/btw` side questions.
- Automatic RSI, Wiki promotion, or Skill promotion.
- Cross-entry Session resume by default.
- Vector/semantic Wiki index unless grep demonstrably fails.
- Generic EventBus and remote replay.
- Multiple virtual desktops or remote device bridges.
- External coding Harness or coding mode.
