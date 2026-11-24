# nika implementation plan & development loop

Status: **Approved lean implementation baseline & distilled 5-stage Agent Loop (2026-11-24)**. Product contract: [harness.md](../design/harness.md). Module scope: [feature-worklist.md](feature-worklist.md).

## 1. Verified upstream facts

- **`nextloop` version:** `API_VERSION = "1.1.0rc1"`, `EVENT_SCHEMA_VERSION = "1.1"`. Pin exact version at startup and fail closed on mismatch.
- **Direct kernel reuse:** Projection, WorkingContext damping, and compaction live inside `nextloop.AgentLoop` / `driver.py`. Nika instantiates `Harness` / `AgentLoop` directly with shared `SQLiteEventStore`, `ModelProvider`, and `DeliveryOwner`.
- **Skills & batch barriers:** Reuse `nextloop`'s `SkillRegistry` / `skill_view` and whole-batch validation (`parallel` read vs `exclusive` write truncation, 5-variant `ToolOutcome`).
- **Pocket protocol:** Inbound `POST /webhooks/pocket` carries `{delivery_id, todo_id, agent_id, prompt, scheduled_for, result_callback_url, callback_token}` with `Bearer` secret and expects `200`/`202`. Result callback posts `{result_summary, result_payload?}` with `Bearer <callback_token>`; `409 DELIVERY_CANCELLED` / `409 DELIVERY_EXPIRED` settles silently without retry or Feishu alert.

## 2. Process topology & module layout

```text
ASGI HTTP app (/webhooks/feishu, /webhooks/pocket, /healthz)
  ├─ FeishuAdapter ─┐
  └─ PocketAdapter ─┴→ Scheduler.ingest(IngressEnvelope)
                         ├─ NikaLedger (nika.db WAL: ingress_events, threads, tasks)
                         ├─ HarnessRegistry (session_id → nextloop.Harness)
                         ├─ shared SQLiteEventStore(nika.db) + ModelProvider
                         └─ NikaToolRuntime (.scope(identity, pack) → ScopedToolRuntime)
                              ├─ native tools: wiki, read/edit/write/grep/bash, pocket, feishu_doc, session_ctl
                              └─ internal orchestration: dispatch_task, report_task, consult_peer(depth=1)
```

| File under `src/nika/` | Responsibility |
|---|---|
| `contracts.py` | `IngressEnvelope`, `ReplyTarget`, `SpecialistPack`, `SessionIdentity`, `TaskRecord` — Nika-owned frozen dataclasses and `StrEnum`s only. |
| `db.py` | `NikaLedger`: sole writer for Nika's 3 SQLite tables (`ingress_events`, `threads`, `tasks`), offloaded via `asyncio.to_thread` under one serialized lock with short `BEGIN IMMEDIATE` transactions. |
| `packs.py` | Strict `nika.specialist/v1` pack loader (`specialists/<name>/{pack.toml,prompt.md,skills/}` + `specialists/_shared/RED_LINES.md`); validates allowlists and fails closed on startup. |
| `tools.py` | `NikaToolRuntime` & `ScopedToolRuntime`: filters `catalog()` per specialist allowlist, validates batches strictly against visible tools, and enforces caller identity on `execute()`. |
| `wiki.py` | Dual-repo (`work`, `personal`) `ripgrep` + `## H2` line-range TOC search, per-repo Git `upsert`/`revert` under `wiki_git_lock` with single-line `<repo>:<path>@<sha>` receipts. |
| `sessions.py` | Raw SQLite `session_ctl(recent | inspect | working_context)` across `session_events`. |
| `workspace.py` | Path-contained `read`, `edit`, `write`, `grep`, and process-group `bash` (secret env vars stripped, `os.killpg` on timeout/cancel, `top_talent` restricted to scratch roots, protected behavior files denied). |
| `pocket.py` | `PocketAdapter` (`/webhooks/pocket` + callback sender with silent `409` handling) and `PocketRpcClient` (`POST /v1/rpc/{method}` with deterministic `request_id` on writes). |
| `feishu.py` / `feishu_doc.py` | Feishu ingress (`allowlist`, `Comment-as-Anchor` ±2 paragraphs, `/stop` interception), Single Live Status Card (≤1 patch/2s, DM card-thread dispatch binding), and section-based `feishu_doc` edits with mandatory read-back verification. |
| `orchestration.py` / `scheduler.py` / `delivery.py` | Deterministic ingress routing, `dispatch_task`, `report_task` (`done | need_decision | blocked | handoff`), artifact-only blind `consult_peer` (`depth=1` hard cap), `NikaDelivery`, and startup crash recovery. |
| `http_app.py` / `cli.py` | Minimal `h11` + `asyncio` ASGI server and `nika serve / check / backup / export / recover` CLI. |

## 3. Lean single-source-of-truth SQLite schema (`nika.db`)

Every fact is stored in one authoritative column (strict SSOT):

```sql
CREATE TABLE IF NOT EXISTS ingress_events (
    event_id    TEXT PRIMARY KEY,
    source      TEXT NOT NULL CHECK (source IN ('feishu', 'pocket')),
    thread_key  TEXT NOT NULL,
    task_id     TEXT NOT NULL,
    received_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id           TEXT PRIMARY KEY,
    session_id        TEXT NOT NULL UNIQUE,
    parent_task_id    TEXT,
    origin_event_id   TEXT,
    origin_call_id    TEXT,
    thread_key        TEXT NOT NULL,
    kind              TEXT NOT NULL CHECK (kind IN ('ingress', 'dispatch', 'consult')),
    specialist        TEXT NOT NULL CHECK (specialist IN ('main', 'top_talent', 'coder', 'doc_research', 'eval')),
    depth             INTEGER NOT NULL CHECK (depth IN (0, 1)),
    status            TEXT NOT NULL CHECK (status IN ('queued', 'running', 'need_decision', 'blocked', 'done', 'failed')),
    report_status     TEXT CHECK (report_status IS NULL OR report_status IN ('done', 'need_decision', 'blocked', 'handoff')),
    prompt            TEXT NOT NULL,
    reply_target_json TEXT,
    summary           TEXT,
    final_message_id  TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS tasks_consult_call_idx
    ON tasks(parent_task_id, origin_call_id) WHERE kind = 'consult';

CREATE TABLE IF NOT EXISTS threads (
    thread_key      TEXT PRIMARY KEY,
    active_task_id  TEXT UNIQUE,
    last_session_id TEXT,
    last_specialist TEXT,
    last_task_id    TEXT,
    updated_at      TEXT NOT NULL
);
```

## 4. Master Agent Development & Verification Loop

```text
Outer progression: Stage 0 (Verifier Foundation) → Stage 1 (Dialog Backbone) → Stage 2 (Tools & Pocket) → Stage 3 (1+4 Specialists & Blind Peer) → Stage 4 (Recovery & Daemon)
                                        │
          ┌─────────────────────────────┴─────────────────────────────┐
          ▼                  5 fixed Steps inside each Stage          │
  [Step 1 Tests & Eval First]                                         │
          │ Write failing black-box tests + live k3.1-pro Eval cases  │
          ▼                                                           │
  [Step 2 Minimal Build + Dual Gate] ◄── Fail: fix code or prompt ────┤
          │ Pass verify.sh (pytest/bits/ruff/mypy) + eval.py (live)   │
          ▼                                                           │
  [Step 3 De-duplicate & Simplify]   ◄── Regressed: revert & redo ────┤
          │ 3-pass DRY + SSOT check + zero-ref dead-code removal      │
          ▼                                                           │
  [Step 4 Zero-Context 3-Axis Blind Review]                           │
          │ 3 isolated read-only sub-agents: Standards / Spec / Risk  │
          ▼                                                           │
  [Step 5 Adjudicate & Full Regression] ── Real bug: red test first ──┘
          │ Reject speculative bloat + 100% cumulative Feature Eval
          ▼
     Commit Stage (code & prompt commits separated) → Next Stage
```

### Three non-negotiable rules

1. **Zero LLM mocking in behavioral Eval:** `scripts/eval.py` calls live `kimi-k3.1-pro` (thinking enabled) against real temporary SQLite/Git/ASGI sandboxes. Transient gateway `429`/`5xx`/network errors are retried and classified as `infra_error`, never conflated with model failures.
2. **Separate code commits from prompt/behavior commits:** Structural code edits and `prompt.md` / tool-description edits land in separate commits; any prompt/schema edit re-runs affected Feature Evals.
3. **Monotonic assertions:** Step 1 assertions and `bits` rules are never weakened or suppressed without a documented external-contract reason.

### Stage roadmap & cumulative `kimi-k3.1-pro` Feature Eval matrix

| Stage | Deliverables | Mandatory Live `kimi-k3.1-pro` Feature Evals (accumulated into regression) |
|---|---|---|
| **Stage 0: Verifier Foundation** | `pyproject.toml`, `bits.toml`, `src/nika/` skeleton, `scripts/verify.sh`, `scripts/eval.py` | **F0 Connectivity & Dual-Gate Judge Probe**: live `kimi-k3.1-pro` tool-call + deterministic check + independent `kimi-k3.1-pro` delivery judge |
| **Stage 1: Dialog Backbone** | Lean 3-table `NikaLedger`, Feishu core ingress & Single Live Status Card, `main` pack, dual-repo `wiki`, `session_ctl`, `/stop` | **F1 Triage & Alignment** (direct reply vs clarifying options vs dispatch extraction)<br>**F2 Dual-Repo Wiki** (`search` H2-TOC → targeted `read`, `upsert` real Git commit + `rev` receipt, `revert`)<br>**F3 Cross-Entry Recall** (`session_ctl` `recent → inspect` on "do what we agreed earlier") |
| **Stage 2: Tools & Pocket** | Path-contained `read/edit/write/grep/bash`, `feishu_doc` section edit + mandatory read-back, native `pocket` RPC tool, `/webhooks/pocket` adapter | **F4 Pocket Read/Write & Lock** (check conflict before idempotent write; honest report on `409 CLOUD_LOCKED` with zero retry loop)<br>**F5 Pocket Silent Boundary** (routine task writes callback only with `0` Feishu messages; reminder/error sends `1` Feishu alert)<br>**F6 Feishu Doc Anchor Edit** (target section edited + read-back verified, neighbor sections untouched, single reply) |
| **Stage 3: `1+4` Specialists & Blind Peer** | 5 specialist packs (`main`, `top_talent`, `coder`, `doc_research`, `eval`) + `_shared/RED_LINES.md`, `ScopedToolRuntime`, DM card-thread binding, `dispatch_task` / `report_task` / `handoff` / `consult_peer(depth=1)` | **F7 `coder` Test-Closed Delivery** (fix real bug, run `pytest`, remove dead code before `report_task(done)`; reject protected path writes; pause at `need_decision` on destructive ops)<br>**F8 Thread Routing & Handoff** (1-hop bound follow-up; out-of-scope alarm edit `handoff`s back to `main`; closed-card follow-up resumes specialist)<br>**F9 Clean-Context Blind `consult_peer`** (artifact-only payload, `depth=1` blocks nested consult, `top_talent` cuts planted over-engineering) |
| **Stage 4: Recovery, Canary & Daemon** | Startup crash/delivery recovery, `nika serve / check / backup / export / recover`, `launchd` template, live Pocket + Feishu smoke integration | Full `verify.sh` fault/recovery suite + **100% pass across cumulative `F0`–`F9` live `kimi-k3.1-pro` Evals** + live local daemon HTTP end-to-end verification |
