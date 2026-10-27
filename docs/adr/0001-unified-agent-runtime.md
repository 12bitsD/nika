# ADR-0001: Unify execution around AgentLoop

- Status: Superseded by [ADR-0002](0002-single-agent-loop.md)
- Date: 2026-10-26
- Scope: Runtime structure, execution semantics, cancellation, finalization, and current persistence defaults

## Context

The bot should remain small and easy to modify. The current direction is not to port a general-purpose agent daemon with many frontends, channels, providers, and extension protocols.

The following product constraints are already confirmed:

- Feishu is the primary channel.
- Wiki files are the long-term memory.
- Document access and waking the bot by mentioning it in a document comment are required capabilities.
- Ordinary messages use the bot's own agent execution.
- `/kimicode` provides a separate, explicit route to Kimi Code. The bot does not rewrite the prompt or summarize the result through its own model.
- A Kimi Code route can be resumed by session ID. Follow-up messages in the same Feishu thread continue on that route until `/exit`.
- `/stop` stops the current Run without leaving the Kimi Code route. `/exit` leaves the route but preserves the Kimi Code session, history, and working directory.

Runtime and AgentLoop should be designed as one cohesive structure rather than independent lifecycle mechanisms scattered across router, conductor, adapter, and storage code.

## Decision

### 1. One small AgentRuntime

`AgentRuntime` owns only the registry of Sessions to AgentLoops, lazy creation, and collective shutdown. It does not own conversation behavior or provider-specific execution.

### 2. One AgentLoop per Session

Each `AgentLoop` is the execution authority for one Session and owns:

- mailbox and input ordering;
- the state machine;
- Engine invocation;
- steer, cancellation, budgets, and timeouts;
- compaction transitions when compaction is introduced;
- incomplete tool-call settlement;
- authoritative persistence and finalization;
- optional lifecycle notifications.

The `AgentRuntime` does not duplicate these responsibilities.

### 3. Two Engines behind the same execution semantics

Two real execution mechanisms exist:

- `ModelEngine`: the bot's own model/tool loop.
- `KimiCodeEngine`: direct Kimi Code session, process, and protocol management.

Shared input, state, cancellation, and finalization semantics live in `AgentLoop`. Engine-specific capabilities stay inside the corresponding Engine. The direct Kimi Code route does not pass through `ModelEngine`.

### 4. Reuse the state-machine semantics

`AgentState` uses:

- `Idle`
- `Streaming`
- `ExecutingTool`
- `Compacting`
- `WaitingRequest`
- `WindingDown`

`WaitingRequest` covers native Kimi Code questions and authorization requests.

`RunStatus` remains separate: `Running`, `Stopping`, or `Stopped(reason)`. For example, `ExecutingTool` plus `Stopping` means that stop has been requested but the tool has not confirmed termination.

`Compacting` reserves the state transition only; the actual compaction strategy remains an open topic.

### 5. Support steer without conflating it with stop

The Mailbox has two input classes:

- ordinary queue: FIFO;
- steer: higher priority, injected at the next safe model boundary.

Control commands such as `/stop` and `/exit` bypass both queues. Steer does not immediately interrupt an active model request or tool call.

### 6. Propagate cancellation and report it honestly

Each Run has its own cancellation token, propagated to model requests, tools, and child processes. A new Run receives a new token rather than resetting shared cancellation state.

If execution has not confirmed termination, the Run remains `Stopping`. It must not be reported as stopped. History must distinguish user cancellation, shutdown, failure, and normal completion.

### 7. Mandatory finalization uses `try/finally`, not hooks

Core finalization is deterministic and local:

1. settle incomplete tool calls as cancelled or unknown;
2. persist authoritative Session and Run state;
3. release execution resources;
4. publish completion and deliver the result.

Hooks are optional lifecycle notifications after the corresponding core transition. They do not own persistence, cleanup, or the right to delay completion indefinitely. External filesystem hooks are not required by this decision and remain a separate discussion.

A process kill or machine failure is outside the guarantee of both `try/finally` and hooks.

### 8. Use a minimal graceful shutdown

Shutdown proceeds in this order:

1. stop accepting new inputs;
2. cancel active Runs;
3. wait for required authoritative writes and settlement;
4. close channel and Engine connections.

There is no long external hook chain in the mandatory shutdown path.

### 9. Make the tool-call budget dynamic

The default tool-call budget is **200 attempts per Run**.

Configuration may be overridden globally, per chat, per Session, and per Run. The effective value is read during execution so a mid-Run change can take effect. An Agent may adjust its own budget only within an administrator-defined hard ceiling; increases above that ceiling require user authorization.

Every attempted tool call counts, including failed or rejected calls. Parallel calls count individually. A total Run timeout remains a separate guard.

### 10. Settle incomplete tool calls and never replay them implicitly

A tool call whose outcome is cancelled or unknown is recorded as such. Restart restores conversation and routing state only; it never re-executes a historical tool call automatically.

### 11. Keep the current event and persistence path direct

There is no generic EventBus or event-replay mechanism in the current design:

- an Engine emits one `AgentEvent` stream for the active Feishu renderer;
- the AgentLoop writes authoritative Session and Run state synchronously;
- non-authoritative logs and metrics may be asynchronous.

A generic publish/subscribe system, per-Session persistence queues, backpressure, drain protocols, and replay should be introduced only when real additional subscribers or measured I/O pressure require them.

### 12. Exclude `/btw` and Checkpoint/Rewind

The current architecture does not include `/btw`, Checkpoint, or Rewind. File recovery belongs to Git. Conversation rewind is explicitly not included; a new context starts through a new Session.

## Consequences

- Runtime ownership is concentrated and testable through `AgentLoop`, while Engine differences remain local.
- Bot and Kimi Code execution share lifecycle semantics without forcing Kimi Code through the bot model.
- Steer, stop, waiting, and finalization have distinct meanings and can be tested independently.
- Mandatory durability does not depend on optional extensions.
- The design avoids a generic event system and persistence queue until their costs are justified.
- Without event replay, remote UI clients and independent event subscribers are not supported.
- Without Checkpoint/Rewind, earlier conversational states cannot be restored; Git only restores files.
- Engine-specific behavior must still be mapped honestly. In particular, an unsupported native Kimi Code interaction must fail explicitly rather than being simulated through the bot model.

## Open topics

These are not decided by this ADR:

- Provider/model selection, streaming details, retry policy, token budgeting, and compaction behavior;
- the concrete Tool set, permission levels, and approval policy;
- external Hook mechanisms and their failure policy;
- detailed Feishu rendering, document APIs, and comment interaction behavior;
- Session retention, garbage collection, asynchronous persistence, and deployment;
- implementation language and repository code layout.
