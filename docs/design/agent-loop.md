# AgentLoop core design

- Status: M4 state-machine and lifecycle baseline; ReAct execution-protocol follow-up open (2026-11-02)
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
  → Compacting          when preflight requires compaction before the next request
  → WaitingRequest      when runtime needs an answer
  → WindingDown         on final response, cancellation, or terminal error

ExecutingTool
  → Streaming           after Tool Results are committed
  → Compacting          when preflight requires compaction before the next request
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
→ account for usage and apply soft budget guidance
→ ToolRuntime executes serially in model-provided order
→ commit Tool Result and assets
→ inject results into the next model request
```

The call intent is committed before side effects. If the process dies afterward, recovery knows which call was pending and does not blindly repeat it.

- Tool-call and time budgets are soft guidance: exhaustion records `over_budget` and prompts an efficiency review without preventing execution. Explicit cancellation, per-call timeouts, Provider constraints, and execution failures retain their separate semantics.
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

Before every model request, AgentLoop evaluates the complete newly assembled request under the [usage and preflight contract](context-builder.md#usage-and-preflight). A valid Provider-usage anchor is preferred, then Provider token counting where available, then a complete local estimate; missing usage is never zero.

When input `I` reaches **75%** of the model context window or `I + O` exceeds Provider capacity, the loop enters `Compacting` before that request; Providers with separate input/output limits apply them independently. It never interrupts an in-flight model request or Tool action; the current response or Tool Result is saved first.

`Compactor` is an internal module, not a Tool:

1. A summary request uses the dedicated [compaction-prompt.md](compaction-prompt.md), `AGENTS.md`, and current Conversation with a final summarize instruction and no Tool definitions or execution. The Agent reconstructs task state by future action value rather than preserving complete Tool transcripts or a fixed field list.
2. Validation requires a nonempty, meaningfully smaller result, unchanged normal System Prompt and `AGENTS.md`, valid request structure, and successful `I + O` preflight. Runtime state remains in Session, and the latest active WorkingContext is preserved separately after the summary.
3. An append-only compaction event records the summary and model usage. The next request is normal System Prompt + `AGENTS.md` + the task summary + the latest active WorkingContext, if any + subsequent messages; old Trajectory is never rewritten.

Compaction starts on user `/compact`, the 75% input threshold, or a preflight capacity violation. `/compact` runs immediately while Idle and otherwise at the next safe model boundary. Failed or unusable summaries are not committed; the previous projection remains and the failure is reported. Provider overflow permits one compaction, not an unbounded sequence. A fresh compaction that still cannot produce an admissible request ends with the error.

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
- internal Compactor at the 75% input threshold or preflight capacity violation, with immutable Trajectory;
- explicit WaitingRequest routing;
- cancellation and finalization before the writer lease is released;
- event-derived recovery with no automatic replay of historical side effects.

Still implementation-level work: exact event schemas, Feishu rendering, numeric timeout values, SQLite migration, package structure, and concrete tests. These do not change the established state-machine baseline. The 2026-11-02 review additionally identified an open ReAct execution-protocol contract, recorded in §13 below; the existing state machine does not by itself close that contract.

## 12. Internal structure and module interfaces

**Direction confirmed on 2026-11-02:** keep the overall architecture simple, implement the full agreed capability scope, and refine the details. AgentLoop itself must have clear internal structure and appropriate abstraction. A single execution path must remain understandable as its capabilities grow.

The decomposition below is a working design for that requirement. Module responsibilities are explicit; names, file layout, and concrete interfaces remain part of M8. This section does not select a language or claim implementation.

### Driver and private execution flows

AgentLoop presents a small interface for driving one Run using an acquired Session execution context. Internally, separate the following responsibilities:

| Module / flow | Owns | Interface outcome or constraint |
|---|---|---|
| Loop driver | Current Run's execution sequencing, legal AgentState transitions, safe model boundaries, and entry into mandatory finalization | Owns the single live state transition path; delegates complete operations and consumes their explicit outcomes |
| Input handling | Selecting ordered pending steer at a safe boundary; validating and routing answers to the current WaitingRequest | Uses the Session-owned Mailbox and request identity; never creates another queue or independently starts a Turn |
| Model invocation | One admitted logical model request, Provider attempts, streaming, usage, bounded retry, and partial-output classification | Returns a complete response, cancellation/failure, or a need to rebuild the request; never starts another Run or dispatches Tools |
| Tool batch execution | Executing the committed call intents in order; correlating each Result; returning a suspended request, completed batch, cancellation, or failure | Calls ToolRuntime for actual execution and resource handling; does not implement Tool-specific behavior or run the next model request |
| Finalization | Settling incomplete calls, committing final facts, releasing execution resources, and closing or durably handing off final delivery | One mandatory path for normal completion, stop, and failure; the driver completes it before SessionManager releases the writer lease |

The driver should read as the execution protocol: obtain eligible input, assemble and admit a request, invoke the model, handle the returned Tools or final response, and finalize. Provider protocol handling, Tool-specific branches, SQL, and Feishu rendering live in the modules that own them.

ContextBuilder, Compactor, ModelProvider adapters, ToolRuntime, Session Store, and channel delivery retain their existing interfaces. Internal flows compose these modules rather than introducing another implementation of their rules. For example, ContextBuilder owns the complete candidate and preflight rules; model invocation executes that admitted candidate, and the driver coordinates compaction and rebuilding when needed.

### State and commit ownership

- The Session writer lease covers a single execution writer, including its awaited internal flows. These flows do not become independent background writers. Ingress must still accept pending input and propagate stop while model or Tool execution is waiting, without obtaining a second execution writer. Its durable acceptance and lease-fencing protocol remain SessionManager / Store coordination concerns for M6/M7.
- The driver owns live AgentState transitions. Flows return explicit outcomes and narrow execution handles rather than sharing a mutable object containing every Session and Run field. Pure transition checks may be private functions; a separate state-machine framework is unnecessary.
- Input handling owns accepted-to-injected correlation; model invocation owns model-call / attempt records and complete response commits; Tool batch execution owns per-call outcome recording; finalization owns closing execution and delivery facts. SessionManager owns Run creation, writer leases, and process-start recovery. The exact events and transaction groups are defined in M7.
- Each durable effect has one commit owner. For a response with Tool Calls, commit the response and call intents before dispatch; return committed identities to the Tool batch flow. ToolRuntime returns an execution outcome, including durable asset references where needed; the batch flow records the correlated result. A failed required commit prevents the next side effect or model request.
- Runtime observations remain observations until committed. In-memory projections are derived state, not another persistent authority; no internal module keeps its own conflicting copy of Run status, budget, pending input, or delivery state.

### Retry, waiting, cancellation, and recovery

- Model invocation retries identical bytes only under the current M5 rules. If new steer requires a changed request, it yields to the driver for input injection, ContextBuilder/preflight, and a new logical model-call identity within the same Run. Partial output follows the interruption rules; it is not silently resent as an untouched request.
- WaitingRequest retains its originating Tool/model continuation. An answer resumes that operation rather than calling the Tool again. Input handling validates identity and shape; the driver controls the resulting AgentState transition. The remaining free-text answer-versus-guidance UX must still be closed in the channel contract.
- Stop signals reach the active model, Tool, compactor, or wait promptly through the same Run cancellation mechanism. Propagating that signal does not grant a background callback authority to mutate Run state. Cancellation observations return to the owning flow and converge on finalization; cleanup and required writes must still execute after cancellation is requested.
- Finalization is one module, not one indivisible step. Its checkpoints and execution handles make incomplete cleanup, unknown outcomes, and delivery-only retries distinguishable. Required cleanup has a bounded deadline independent of the cancelled execution signal; concrete deadlines belong to resource design. Repeated settlement checks committed identities and progress to avoid repeating completed effects. Process-start recovery can reuse safe settlement and delivery operations from committed facts without resuming the old instruction pointer or rerunning side effects.
- SessionManager and Store validate Run/lease identity on commits. Late old-Run callbacks cannot bypass that check merely because they originated in a previously valid internal flow.

### Extraction and verification discipline

Extract a module when it owns a coherent rule, lifecycle, failure behavior, or a real adapter seam. A module may begin as private functions in one file; every function does not need a class, trait, or package. Concrete functions are sufficient where no behavior varies. Provider, storage, delivery, clock, and process-control seams can accept dependencies for deterministic verification where they are actually needed.

Keep interfaces smaller than the behavior they encapsulate. Callers should not have to reproduce retry policy, persistence order, or cleanup sequencing. Avoid an interface per AgentState, pass-through manager layers, a universal action interpreter, or a general workflow/EventBus framework. State names describe execution; they do not prescribe the file structure.

Review the structure through its interfaces:

1. Changing Provider retry behavior stays within model invocation and its adapter; changing Tool execution behavior stays within ToolRuntime and the relevant Tool implementation.
2. Repeated answers, steer during retry, stop during a Tool, failed commits, and late callbacks can be exercised without involving a real Feishu client or model.
3. Cross-flow tests still verify the actual ordering: intent before effect, result before the next model call, final facts before delivery, and delivery responsibility before writer release.
4. Persistence failures and process termination are tested through Store and recovery interfaces. Tests do not assume that an in-memory mock proves durability.
5. Adding an agreed capability reuses the shared lifecycle guarantees. Any required change to the driver is explicit and justified by a new execution transition rather than Tool- or channel-specific details.

## 13. ReAct execution-protocol follow-up

Recorded on 2026-11-02 after the user identified the missing explicit ReAct design. The model → Tool → Observation → model cycle already exists in §5. The remaining contract is how model outputs become valid runtime decisions, including malformed, partial, and terminal responses.

The open items are response classification, executable Tool Call conditions, correlated Observations, continuation/termination behavior, and Provider-supplied reasoning-related fields. Their required cases and close artifacts are maintained in the [G0 review](../architecture/agent-loop-capability-review.md#react-execution-protocol-gap). This is a design follow-up, not a new Reasoner/Planner module or an implementation claim.

The established lifecycle, serial execution, soft-budget policy, and no-replay recovery rules remain the inputs to this work. A model protocol terminal signal does not certify business success; concrete result validation and user-facing completion claims need task evidence. The [capability comparison](../architecture/agent-loop-capability-review.md) distinguishes existing contracts from proposed additions inspired by the external survey.
