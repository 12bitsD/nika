# AgentLoop core design

- Status: M4 architecture baseline
- Date: 2026-10-27
- Scope: execution state, input, model and Tool ordering, cancellation, finalization, and interruption recovery

## 1. Core model

AgentLoop is an on-demand execution procedure, not a long-lived Session object.

- `Session` owns durable identity and append-only Trajectory.
- `SessionManager` resolves an entry, enforces single-writer execution, and creates or ends Runs.
- `session_events` is the only execution-history authority. There is no persistent Snapshot or second truth.
- The current Conversation is a projection derived from the latest compaction event and subsequent events, or from all Session events when no compaction exists.
- AgentLoop drives `ContextBuilder`, `ModelProvider`, `ToolRuntime`, `Compactor`, and `TrajectoryRecorder`; it owns sequencing, not every implementation.

Ordinary chat and coding use this same loop. There is no external coding harness or coding mode.

## 2. Identities

- `session_id`: durable conversation identity.
- `turn_id`: one accepted input through finalization.
- `run_id`: one concrete execution attempt within a Turn; the normal path has one Run per Turn.
- `model_call_id`: one logical model request. Retries of that request share this identity.
- `attempt_id` or `attempt_seq`: one Provider attempt within a model call.
- `request_id`: one WaitingRequest.
- `final_message_id`: the committed response used by delivery and recovery.

Model retry is not a new Run and does not reset budgets, cancellation, or lease state. New ordinary input after completion or cancellation creates a new Turn and `run_id`.

## 3. State transitions

```text
Idle
  → Streaming

Streaming
  → ExecutingTool       when the model returns Tool Calls
  → Compacting          before the next model request at ≥75%
  → WaitingRequest      when runtime needs an answer
  → WindingDown         on final response, cancellation, or terminal error

ExecutingTool
  → Streaming           after Tool Results are committed
  → Compacting          before the next model request at ≥75%
  → WaitingRequest      when runtime needs an answer
  → WindingDown         on cancellation or terminal error

Compacting
  → Streaming           after a valid compaction event is committed
  → WindingDown         on cancellation or terminal failure

WaitingRequest
  → previous state      after a valid answer is accepted
  → WindingDown         on cancellation or terminal error

WindingDown
  → Idle                after finalization and delivery close
```

`WindingDown` never returns to `Streaming`. Input that arrives after the final response is committed waits for a later Turn.

Externally, `RunStatus` remains `Running` or `Stopped`. Detailed outcomes such as failed, cancelled, interrupted, unknown, and delivery_unknown are diagnostic outcomes, not separate user workflows. `RunStopped` does not by itself mean the user has received the response.

## 4. Durable event and delivery order

The ordinary success path is:

```text
accept input
→ append input/turn/run start records
→ Idle → Streaming
→ append model_call and Provider attempt
→ stream deltas to the renderer only
→ commit the complete assistant response and Provider usage
→ Streaming → WindingDown
→ settle any incomplete Tool Calls
→ persist final execution facts
→ release model/Tool/browser/computer execution resources
→ deliver final_message_id and record delivery
→ mark finalization finished and AgentState Idle
→ release the Session writer lease
```

Execution resources are not the Session writer lease. The lease is released only after delivery closes or a durable delivery owner has taken responsibility. A later Turn must not overtake the previous final response.

A delivery failure retries only delivery with the same `final_message_id`; it never reruns the model. A response and its corresponding execution events are committed before final delivery, so a crash cannot produce “the user saw it but the system never saved it.”

Trajectory stores complete logical events, not every SSE delta. Streamed deltas are ephemeral presentation events.

## 5. Tool Calls

The baseline Tool path contains no before/after Hook:

```text
assistant response with tool_calls
→ commit the assistant message and Tool Call intents
→ check budget
→ ToolRuntime executes serially in model-provided order
→ commit Tool Result and assets
→ inject results into the next model request
```

The call intent is committed before side effects. If the process dies afterward, recovery knows which call was pending and does not blindly repeat it.

- Budget exhaustion prevents execution and ends the Turn with `budget_exceeded`.
- A normal Tool error is returned to the model; it is not automatically a Turn failure.
- A large result is saved as an asset before its reference is committed in the Tool Result.
- A cancelled or unknown result is recorded honestly and is not rewritten as success.
- Later independent read-only Tools may be parallelized only if a real need appears. The baseline is serial execution for deterministic ordering and resource safety.

Every attempted Tool Call counts toward the current budget, including failed or rejected calls. Parallel calls count individually when introduced.

## 6. Steer and input buffer

All ordinary messages use steer semantics. There is no independent-task FIFO or `/queue` command.

- Idle input starts a new Turn.
- Active-Turn input is held in the Session's ordered steer buffer and injected at the next safe model boundary.
- During model streaming, steer waits for the current response. It does not alter the in-flight request.
- During Tool execution, steer waits for the Tool Result to be committed and is included before the next model request.
- During Provider retry backoff, steer may be injected before the next attempt within the same Run.
- During compaction, steer waits for the compaction event and is injected afterward.
- After a final response is committed, steer waits for a later Turn.

The buffer is required for ordering; it is not a separate independent-task queue. Multiple steer inputs retain original order and may be injected as one batch. `steer_accepted` and `steer_injected` are separate Trajectory events, and the injection records the corresponding `model_call_id`.

Pending, not-yet-injected steer is retained after `/stop` for a later Turn unless explicitly cleared.

## 7. Compaction

Before every model request, AgentLoop evaluates the newly assembled request. Provider usage is preferred; local estimation is a fallback.

At **75%** of the model context window, the loop enters `Compacting` before that request. It never interrupts an in-flight model request or Tool action; the current response or Tool Result is saved first.

`Compactor` is an internal module, not a Tool:

1. Deterministic cleanup removes duplicates, bounds old large outputs with asset references, removes inline binary payloads, and preserves Tool Call/Result pairing and required recent messages. There is no separate frequently running micro-compaction.
2. An internal model request produces a structured summary of the current goal, constraints, decisions, completed work, active work and next steps, open questions, required results and assets, budget, waiting state, and latest active WorkingContext.
3. Validation requires a nonempty summary and verifies current goal, unfinished work, latest active WorkingContext, Run identity, budget, waiting state, and Tool pairing.
4. An append-only compaction event records the summary and model usage. Later Conversation projections derive from this event and subsequent events; old Trajectory is never rewritten.

Failed summarization or validation leaves the previous projection intact. Provider overflow may force full compaction once within the same Run; a second overflow is terminal and does not loop or use an unreviewed lossy fallback.

## 8. WaitingRequest

A WaitingRequest is created only when runtime needs input to continue. An ordinary end-of-turn question does not create this state; its reply starts a new Turn.

Each Session has at most one pending request, recording `request_id`, Session, Turn, Run, origin, response shape, and resume state.

- Free-text answers bypass the steer buffer and resume the original request after validation.
- Option callbacks carry `request_id`.
- Other steer input remains guidance, not an answer.
- A Tool-originated answer returns to the same Tool Call; an Agent-originated answer enters the next model request.
- Duplicate answers return the existing outcome without repeating effects.
- Late, expired, or cancelled answers never approve a new action and are not silently converted into a new task.
- No timeout or missing answer is treated as approval.

A small `request_user_input` capability may create one such request for a single question with free text or a small option set.

## 9. `/stop`

`/stop` cancels only the current Turn. It does not erase Session history, committed results, file changes, or pending steer.

- `Idle`: no-op; does not clear input.
- `Streaming`: cancel the Provider request; retain partial output as partial, not as a complete answer.
- `ExecutingTool`: cancel supported child processes and actions; do not undo writes or clicks already performed; mark unstarted calls as unexecuted.
- `Compacting`: cancel the summary request and keep the previous projection; do not commit partial compaction.
- `WaitingRequest`: cancel the request; later answers and buttons are stale.
- `WindingDown`: preserve committed outcomes, finish required persistence and delivery, and do not start another Turn.
- Retry backoff: cancel the wait and do not start another attempt.

If the final response was already committed, stop is too late and the Turn completes rather than being rewritten as cancelled.

A stop is not reported complete until the current execution has exited or its uncertainty is recorded, partial/cancelled/unknown facts are saved, and execution resources are released. Later ordinary input starts a new Turn with a new `run_id`; late events from the old Run are discarded or recorded only as old-Run diagnostics.

## 10. Failure and interruption matrix

`interrupted` is a diagnostic outcome for an unclosed old Run, not a promise to resume from the same instruction pointer.

| Interruption point | Recovery rule |
|---|---|
| Provider attempt failed, timed out, or disconnected | Retry within the same Run within bounds; terminal errors enter finalization |
| Model produced output but it was never committed | Do not deliver or treat it as an authoritative response; old Run is interrupted |
| Tool Call intent committed but execution never started | Mark interrupted; never auto-execute on recovery |
| Tool started but no result was committed | Mark outcome unknown; subsequent Turns should inspect actual state rather than blindly replay |
| Tool returned but its result could not be committed | Do not continue to the next model request as if the result were authoritative |
| Compaction failed or was not committed | Keep the previous projection and do not commit partial compaction |
| Final response committed but not delivered | Recover by `final_message_id` and retry delivery only |
| Delivery succeeded externally but receipt was not committed | Mark delivery_unknown; use idempotency or lookup where possible and never rerun the model |

On process start, SessionManager:

1. Finds Runs with start records but no closing records.
2. Checks whether any real execution is still alive instead of trusting old `running` fields.
3. Appends `run_interrupted` for dead executions and releases stale leases.
4. Rebuilds the current projection from Trajectory without replaying side effects.
5. Handles committed-but-undelivered final messages by `final_message_id`.
6. Leaves unknown Tool outcomes unknown and invalidates stale WaitingRequests.

Orphan assets may be cleaned by GC. A previously committed compaction event is used; an uncommitted one has no effect.

## 11. M4 closure and remaining implementation details

The following are baseline decisions, not open architecture questions:

- one AgentLoop outside Session;
- single ordered steer buffer with safe injection points;
- one normal Run per Turn, Provider retries as attempts;
- serial Tool execution with intent recorded before side effects;
- internal Compactor at 75%, with immutable Trajectory;
- explicit WaitingRequest routing;
- cancellation and finalization before the writer lease is released;
- event-derived recovery with no automatic replay of historical side effects.

Still implementation-level work: exact event schemas, Feishu rendering, numeric timeout values, SQLite migration, package structure, and concrete tests. These do not change the M4 baseline.
