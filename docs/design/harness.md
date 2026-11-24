# Nika Harness: Deterministic Scheduler, Specialist Pool, and Ecosystem Adapters

Status: **Accepted personal superagent harness baseline (2026-11-24)**. Extends [ADR-0002](../adr/0002-single-agent-loop.md) from a single-agent Feishu bot into a multi-channel, `1 main + 4 specialists` personal bot framework.

## 1. Four-layer architecture

```text
[External Ingress]  Feishu (DM / Thread / Doc Comment) · Pocket (/webhooks/pocket) · Future Apps
                     │ Thin channel adapters (FeishuAdapter / PocketAdapter)
                     ▼ Unified internal envelope {event_id, source, thread_key, prompt, reply_target}
[Scheduler]          Pure-code deterministic router + nika.db (WAL, shared with nextloop)
                     ingress_events (dedup) · threads (1-hop binding) · tasks (state + depth lock)
                     │ start Turn                         ▲ dispatch_task / report_task / consult_peer
                     ▼                                    │
[Execution]          nextloop AgentLoop (incl. context projection/compaction) + SQLiteEventStore
                     mounted with read-only Specialist Config Packs (1 main + 4 specialists)
                     │ Tool Calls (parallel read / exclusive write barriers)
                     ▼
[Capabilities]       ① Native tools (Dual-Wiki, local FS, Pocket RPC, internal orchestration)
                     ② MCP / HTTP plugins (Feishu Docs, third-party MCP servers)
                     ③ Device Link bridge (deferred until the standalone protocol ships)
```

A sidecar, physically separate **RSI repository** evaluates failure trajectories offline and evolves Specialist Config Packs; it never runs inside the online Turn loop.

## 2. One internal envelope, thin external adapters

Nika's core speaks **one** internal ingress format; each external app keeps its own native protocol at the edge:

```json
{
  "event_id": "feishu:om_... | pocket:<delivery_id>",
  "source": "feishu | pocket",
  "thread_key": "feishu:dm:<chat_id> | feishu:thread:<id> | feishu:comment:<doc>:<id> | pocket:delivery:<id>",
  "prompt": "...",
  "reply_target": {"kind": "feishu_card" | "pocket_callback", "...": "..."}
}
```

- **`FeishuAdapter`** (unchanged from [proactive-and-feishu.md](proactive-and-feishu.md)): `allowlist(open_id)`, `Comment-as-Anchor` (±2 paragraphs), isolated Sessions per DM / Thread / Comment, and one Single Live Status Card patched in place.
- **`PocketAdapter` (inbound scheduled tasks):**
  - Receives Pocket's native `POST /webhooks/pocket` (Bearer secret, unique `delivery_id`, `prompt`, `result_callback_url`, one-time `callback_token`).
  - Persists `ingress_events` and immediately returns `202 Accepted` (Pocket retries with the same `delivery_id`, which dedupes cleanly).
  - On completion, posts the summary to `POST /v1/deliveries/{delivery_id}/result` using the one-time `callback_token`.
  - **Default silent boundary:** Pocket-triggered runs write back to Pocket only. Nika pings the user on Feishu DM **only** when the task explicitly asks for a Feishu reminder, or when the run fails, hits a device lock (`409 CLOUD_LOCKED`), or pauses at `need_decision`.

## 3. Single-file SQLite ledger (3 tables, zero external brokers)

For a single-user bot, Redis, Postgres, and message queues are unnecessary. Nika's scheduler shares the same WAL-mode `nika.db` file with `nextloop`:

- `nextloop` exclusively owns `session_events` (and its writer-lease/tombstone tables). Nika never alters `nextloop`'s schema.
- Nika adds exactly **3 tables**:

| Table | Primary key | Purpose |
|---|---|---|
| `ingress_events` | `event_id` | Insert-or-ignore before enqueueing; duplicate webhook deliveries are dropped deterministically. |
| `threads` | `thread_key` | Maps an entry anchor to `(session_id, bound_specialist, active_task_id)` for 1-hop direct routing on follow-ups. |
| `tasks` | `task_id` | Stage ledger (`running` / `need_decision` / `blocked` / `done` / `failed`), `reply_target_json`, and `depth` counter. |

## 4. `1 main + 4 specialists` config packs & 3 internal tools

One public Nika identity; no separate IM bot accounts per specialist.

- **Routing:** Unbound messages go to `main` (1-hop fast path for quick queries). Heavy multi-minute work is dispatched to a named specialist, binding the current `thread_key` to that specialist's Task Session (never locking the user's main DM window). Follow-ups in that thread route 1-hop directly to the bound specialist; out-of-scope requests return to `main`.
- **Persistence:** What persists long-term is the **read-only Specialist Config Pack** (System Prompt, Skills, tool allowlist—the unit of RSI evolution), not an infinite conversation. Each Task keeps a multi-turn Session until `report_task`, then the Session is recycled; cross-Task continuity flows through the dual-repo Wiki and `main`.

| Specialist | Core value | Hard boundaries |
|---|---|---|
| `main` | Chief of staff: turn fuzzy thoughts into crisp decisions, track global state, manage Pocket schedules, gatekeep dispatch | No `bash`, code edits, or remote device control (keeps DM fast and clean) |
| `top_talent` | Always Day One explorer: `0→0.1` wild PoCs, new-tech tasting, zero-prior blind testing (`clean_context`), adversarial challenger | Isolated scratch dirs / temp worktrees only; no main branch or canonical Wiki writes |
| `coder` | Pragmatic Geek engineer: `0.1→1` mergeable delivery, minimal data structures, full-lifecycle edge cases, empirical test rigor | Owns dev-box / Pod debugging; high-risk actions must pause at `need_decision` |
| `doc_research` | Researcher × minimalist editor: primary-source research, paper teardown, clutter-to-clarity docs; primary Wiki curator | No `bash` or remote execution (blocks prompt-injection via external content) |
| `eval` | Strict judge: high-discrimination Rubrics, batch failure root-cause attribution over read-only trajectories | Never edits product code or specialist configs directly |

**Internal orchestration is exactly 3 tools:**

1. `dispatch_task` (`main` only): create a Task with a named specialist pack and bind the calling `thread_key`.
2. `report_task` (the 4 specialists only): close a Task with status (`done` / `need_decision` / `blocked`) and summary for Outbox delivery.
3. `consult_peer` (`main`, `coder`, `doc_research`): blind peer review—pass only the artifact under review, never the chain-of-thought. Scheduler enforces **`depth >= 1` rejection** in code (no recursive agent-to-agent loops). Multi-reviewer debates are `main` issuing parallel `consult_peer` calls in one batch, digested silently in the background.

## 5. Outbound capability channels (including native `pocket` RPC)

All model-initiated actions flow through `NikaToolRuntime` (allowlist per specialist, whole-batch schema validation, `parallel` vs `exclusive` barriers):

- **Channel ① — Native tools:**
  - **Dual-repo Wiki (`wiki`):** Nika mounts the user's two existing Git-backed knowledge repositories directly—a **work Wiki** (`workwiki`) and a **personal Wiki** (`0h`)—with zero migration and **no third private Wiki schema**. `wiki(action="search")` runs `ripgrep` across both repos and returns matched snippets + `## H2` line ranges for targeted `read`; `upsert` / `revert` issue native Git commits / reverts per repo under `wiki_git_lock`, emitting a one-line `repo:path@short_sha` receipt.
  - **Local workspace:** `read`, `edit`, `write`, `grep`, `bash`.
  - **Pocket (`pocket(method, params)`, `main` only):** Direct HTTP `POST {POCKET_URL}/v1/rpc/{method}` with a scoped agent token—**no MCP wrapper**. Read methods (`event.list`, `todo.list`) are `parallel`; mutating methods auto-generate `request_id` and run as `exclusive`. `409 CLOUD_LOCKED` (phone-local lock) is returned verbatim to the model.
- **Channel ② — MCP / HTTP plugins:** `feishu_doc` (mandatory read-back verification) and standard third-party MCP servers configured in `nextloop`.
- **Channel ③ — Device Link (deferred):** Cross-Pod / Mac / Windows / Linux node control is developed as a standalone protocol and repository first (device naming, `alive / missed`, remote Exec, `≤500MB` file transfer). Nika's tool bridge is designed only after Device Link ships.

## 6. Settled operational & edge-case contracts (2026-11-24)

1. **Deployment topology (local-first):** The self-hosted Nika daemon runs as a **long-lived local macOS process** (`launchd` / CLI), reading and writing the work (`workwiki`) and personal (`0h`) Wiki repos directly on disk with zero Git-sync middleware. A single HTTPS tunnel/reverse-proxy endpoint exposes `/webhooks/feishu` and `/webhooks/pocket` to external services. Remote Pods are only execution targets for `coder` later via Device Link.
2. **Follow-ups after Task close:** `threads` retains `last_specialist` and `last_task_id` after `report_task` closes and recycles a Session. A follow-up on the same `thread_key` with no active Task spawns a **fresh Session with the same specialist pack**, auto-hydrating the last N messages of the prior Task Session from `session_events`—without bouncing through `main`. Only an explicit topic switch or `handoff` returns the thread to `main`.
3. **Stop & out-of-scope handoff:**
   - Scheduler intercepts `/stop` (and explicit cancel commands) at ingress by `thread_key` and calls `AgentLoop.cancel(session_id)` directly—no extra LLM tool needed.
   - A specialist returns out-of-scope requests via `report_task(status="handoff", reason=...)`; scheduler unbinds the thread and re-enqueues the original prompt to `main`.
4. **Pocket callback & routing edge cases:**
   - Inbound Pocket webhook payload: `{delivery_id, todo_id, agent_id, prompt, scheduled_for, result_callback_url, callback_token}` with `Authorization: Bearer <agent_secret>`, expecting `200`/`202`.
   - Result callback: `POST {result_callback_url}` with `Authorization: Bearer <callback_token>` and `{result_summary, result_payload?}`.
   - If Pocket returns `409 DELIVERY_CANCELLED` or `409 DELIVERY_EXPIRED` on callback, the adapter **silently drops the result** (no retry, no Feishu alert).
   - Pocket-triggered runs have no Feishu thread and always start on `main`.
5. **Behavior-file & workspace guards in code:** Because `git pull` resets file modes to `644`, write protection on `AGENTS.md`, `specialists/**`, and `skills/**` is enforced **in `NikaToolRuntime`, `workspace.py`, and `wiki.py`**. Host `read`/`edit`/`write`/`grep`/`bash` enforce strict path containment to the allowed workspace roots (`top_talent` is further restricted to isolated scratch/worktree roots), strip daemon credentials (`NIKA_*`, `FEISHU_*`, `POCKET_*`) from subprocess environments, and run `bash` in its own process group (`start_new_session=True`) so timeouts or `/stop` kill the entire child tree cleanly without spawning a disposable container on every command. Wiki mutations go exclusively through the `wiki` tool.
6. **Crash recovery:** On startup, after `nextloop` recovers its Sessions, the scheduler scans `tasks` for `running` rows: invokes `AgentLoop.recover()` to repair interrupted Turns and re-deliver pending `FinalMessage`s. Pocket's webhook does not carry `expires_at`, so Pocket Tasks store `expires_at = NULL` and treat callback `409 DELIVERY_EXPIRED/CANCELLED` as the authoritative expiry boundary (never guessing TTL locally).
7. **Specialist identity plumbing:** `nextloop`'s `ToolRuntime` receives only `session_id`/`turn`/`step`. Scheduler wraps each specialist's runtime in a thin **scoped read-only view** (filtering `catalog()` and enforcing the allowlist in `execute()`) and maintains an in-memory + SQLite mapping `session_id → (specialist, task_id, depth)` so `dispatch_task` / `report_task` / `consult_peer` enforce caller identity and `depth=1` deterministically.
