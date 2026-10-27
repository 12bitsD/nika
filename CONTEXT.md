# Context

This file is the project's canonical glossary. It contains domain concepts only, not implementation choices.

## Agent knowledge and behavior

| Term | Definition |
|---|---|
| AgentWiki | The shared root for long-term Wiki content and Skills. Wiki and Skills have separate consumption mechanisms. |
| Wiki | The long-term knowledge and SOP store. Wiki is distinct from Session history and Trajectory. Its detailed consumption model is reserved for a dedicated deep dive. |
| Skill | Instructions that teach the Agent how to perform a kind of work. Skills are discovered through a small index and loaded on demand rather than injected in full. |
| WorkingContext | A short, replaceable, user-level reminder maintained by the Agent during execution. It is scoped to a Run or Session and is not long-term Wiki memory. |

## Execution

| Term | Definition |
|---|---|
| AgentLoop | The execution algorithm that consumes a Session and an input, drives model and tool interactions, and writes results back to the Session. It has no long-term identity and is created on demand. |
| SessionManager | The coordinator that resolves an entry to a Session, enforces single-writer execution, and creates or ends Runs. |
| Session | A continuing conversation and its durable identity plus append-only Trajectory. Current WorkingContext, budget, workspace, and delivery state are derived from events rather than stored as a second persistent Snapshot. |
| Session projection | The current model-facing view derived from Trajectory. It starts at the latest compaction event and applies later events without replaying their side effects. |
| Turn | The complete handling of one user input until the AgentLoop becomes idle, including model calls, tool calls, waiting, and finalization. |
| Run | One concrete execution attempt. A later input starts a new Turn rather than requiring a special retry workflow. |
| RunStatus | The externally meaningful execution state: `Running` or `Stopped`. Diagnostic detail may be recorded without defining a separate user workflow for each reason. |
| Interruption | An unclosed old Run caused by process failure or an unknown execution loss. Recovery closes the old Run and starts a new Turn from committed facts; it does not resume historical side effects. |
| AgentState | What the AgentLoop is currently doing: `Idle`, `Streaming`, `ExecutingTool`, `Compacting`, `WaitingRequest`, or `WindingDown`. |
| Compactor | The internal mechanism that deterministically cleans old context, requests a structured summary when needed, validates it, and appends a compaction event for subsequent projections. It is not a Tool and never rewrites old Trajectory. |
| WaitingRequest | A runtime-created request for user input that blocks the current execution. At most one is pending per Session; its validated answer resumes the original Tool Call or model request rather than starting a new Turn. Ordinary end-of-turn questions do not create this state. |
| WindingDown | Mandatory finalization is still in progress; execution is not yet fully stopped. |

## Input and control

| Term | Definition |
|---|---|
| Mailbox | The Session-owned ordered input buffer. It persists independently of any individual AgentLoop object and preserves input until a safe injection point. |
| Steer | The semantics of every ordinary message: idle input starts a new Turn; active-Turn input is buffered and injected at the next safe model boundary without immediately interrupting an active model request or tool action. |
| Control input | Commands such as stop that bypass the steer buffer because they act on the current execution. |
| Cancellation | A request to stop the current AgentLoop, model request, tools, and child processes. Late events from an older Run are discarded rather than attached to a new Turn. |
| Tool call budget | The maximum number of tool calls a Run may attempt. Every attempted call counts, including failed or rejected calls; parallel calls count individually. |
| Budget profile | A named collection of resource budgets: `lite`, `pro`, or `promax`. Profiles are Agent-adjustable configuration, not authorization boundaries. |
| Finalization | Mandatory work after output stops: settling incomplete tool calls, saving authoritative state, releasing resources, and only then publishing completion. |

## Capabilities

| Term | Definition |
|---|---|
| Coding skill | The on-demand working protocol for repository inspection, modification, testing, diff review, and delivery. Coding does not require a separate runtime mode. |
| BrowserUse | Browser interaction against the browser environment inside the bot's container. |
| ComputerUse | GUI interaction against the virtual desktop inside the bot's container. Already-performed actions cannot be undone by cancelling a later action. |
| GUI execution lock | The container-level serialization that prevents multiple Sessions from acting on the same virtual desktop concurrently. |

## Trajectory

| Term | Definition |
|---|---|
| Trajectory | The append-only factual record of a Session: inputs, model activity, tool calls and results, GUI actions and observations, configuration changes, compaction, cancellation, and finalization. |
| SessionCatalog | The atomic capability for listing Sessions, reading their Trajectory, and exporting selected Trajectories on demand. |
| Trace export | A full-fidelity export of runtime and interaction events for diagnosis and analysis. |
| AIFT export | A model-interaction projection intended for training workflows. It is distinct from the full trace and from any provider-specific chat-template conversion. |
| Asset reference | A durable pointer to a large Trajectory artifact such as a screenshot or large tool output, stored outside the event payload itself. |

## Memory and recovery

| Term | Definition |
|---|---|
| Long-term memory | Curated knowledge maintained in Wiki files. Trajectory is not automatically promoted into long-term memory. |
| Conversation rewind | Restoring an earlier conversational state. This is not part of the current architecture; file restoration through Git is a separate concern. |
