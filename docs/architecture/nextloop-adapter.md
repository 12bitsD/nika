# nika ↔ nextloop Adapter contract

Status: minimalist consumer integration contract (refined 2026-11-06; extended for the personal superagent harness on 2026-11-24).

## No pass-through wrappers (Deep module reuse)

`nextloop` provides the core implementations of:

- `AgentLoop` Turn/Step driver, closed 5-variant `ToolOutcome` ADT, and symmetric `parallel`/`exclusive` barrier truncation;
- `SQLiteEventStore` (with `(session_id, seq)` invariants and `surface_op` epoch watermark indexing);
- Internal context projection & compaction inside `AgentLoop` / `driver.py` (frozen messages, WorkingContext damping, and 75% preflight—there is no standalone builder class to wrap);
- `OpenAIProvider` and `AnthropicProvider` (stateless SSE streaming adapters).

`nika` **directly instantiates and reuses** those built-in `nextloop` modules instead of wrapping them in redundant pass-through classes.

## Product-side seams owned by `nika`

1. **Thin Channel Adapters (`FeishuAdapter`, `PocketAdapter`):**
   - Translate each external app's native webhook/event format into Nika's single internal envelope `{event_id, source, thread_key, prompt, reply_target}` and immediately acknowledge (`202 Accepted` for Pocket scheduled deliveries).
   - Own source-specific Outbox delivery: Feishu Single Live Status Card in-place patching, and Pocket one-time `callback_token` summary write-back (silent on Feishu by default).
2. **Deterministic Scheduler (`src/nika/scheduler.py`):**
   - Pure-code router sharing `nika.db` (WAL) with `nextloop`: `ingress_events` dedup, `threads` 1-hop specialist binding, and `tasks` stage ledger + `consult_peer` `depth=1` hard lock.
   - Mounts the selected read-only Specialist Config Pack (`main`, `top_talent`, `coder`, `doc_research`, `eval`) before invoking `AgentLoop.run` / `steer` / `cancel`.
3. **`NikaToolRuntime` (`src/nika/tools.py`, `ToolRuntime` Protocol):**
   - Registers consolidated deep tools (`read`, `edit`, `write`, `grep`, `bash`, `wiki`, `pocket`, `feishu_doc`, `gui`, `session_ctl`) plus the 3 internal orchestration tools (`dispatch_task`, `report_task`, `consult_peer`), filtered by specialist allowlist.
   - Classifies `read`, `grep`, `wiki(action="search")`, read-only `pocket` RPC methods, and read-only `session_ctl` actions as `parallel`, and mutating/GUI tools as `exclusive` barriers (where any failure or uncertainty automatically truncates subsequent unstarted calls in the batch).
   - Enforces the two container-level locks (`gui_lock` and `wiki_git_lock`) and maps tool results to `nextloop`'s 5-variant `ToolOutcome` ADT (`Completed`, `Skipped`, `Cancelled`, `UncertainSettled`, `UncertainHanging`).

Full product contracts live in [harness.md](../design/harness.md), [agentwiki.md](../design/agentwiki.md), and [proactive-and-feishu.md](../design/proactive-and-feishu.md).

## Version & independence policy

- Both repositories remain physically separate (`nextloop` and `nika`), verified first as a local end-to-end loop before packaging releases.
- `nika` pins `nextloop`'s `API_VERSION` and `EVENT_SCHEMA_VERSION` and fails closed on mismatch.
