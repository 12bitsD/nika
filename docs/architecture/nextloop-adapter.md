# nika ↔ nextloop Adapter contract

Status: minimalist consumer integration contract (refined 2026-11-06).

## No pass-through wrappers (Deep module reuse)

`nextloop` provides the core implementations of:

- `SQLiteEventStore` (with `(session_id, seq)` invariants and `surface_op` epoch watermark indexing);
- `AppendOnlyContextBuilder` (with frozen messages, WorkingContext damping, and 75% preflight);
- `OpenAIProvider` and `AnthropicProvider` (stateless SSE streaming adapters).

`nika` **directly instantiates and reuses** those built-in `nextloop` modules instead of wrapping them in redundant pass-through classes.

## The only two adapters `nika` implements

1. **`NikaToolRuntime` (`ToolRuntime` Protocol):**
   - Registers the consolidated deep tools (`read`, `edit`, `write`, `grep`, `bash`, `wiki`, `feishu_doc`, `gui`, `session_ctl`).
   - Classifies `read`, `grep`, `wiki(action="search")`, and read-only `session_ctl` actions as `parallel`, and mutating/GUI tools as `exclusive` barriers (where any failure or uncertainty automatically truncates subsequent unstarted calls in the batch).
   - Enforces the two container-level locks (`gui_lock` and `wiki_git_lock`) and maps tool results to `nextloop`'s closed 5-variant `ToolOutcome` ADT (`Completed`, `Skipped`, `Cancelled`, `UncertainSettled`, `UncertainHanging`).
2. **`FeishuDelivery` (`DeliveryOwner` & Ingress):**
   - Maps Feishu IM, Thread, and Document Comment events (with `Comment-as-Anchor` auto-slicing and frozen `System Prompt + AGENTS.md` bootstrap) into `AgentLoop.run` / `steer` / `cancel`.
   - Patches a single live Feishu Interactive Status Card during the Turn and delivers the committed `final_message_id` (plus any single-line `📝 Wiki` Git receipt) on completion.

## Version & independence policy

- Both repositories remain physically separate (`nextloop` and `nika`), verified first as a local end-to-end loop before packaging releases.
- `nika` pins `nextloop`'s `API_VERSION` and `EVENT_SCHEMA_VERSION` and fails closed on mismatch.
