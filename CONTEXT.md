# Context

This file is the project's canonical glossary. It contains domain concepts only, not implementation choices.

## Agent knowledge and behavior

| Term | Definition |
|---|---|
| AgentWiki | The shared root for `AGENTS.md`, long-term Wiki content, and Skills. Wiki and Skills have separate consumption mechanisms. |
| System Prompt | The small runtime-owned contract for action, verification, harness use, and delivery. The selected text is maintained in `docs/design/system-prompt.md`, separately from the evolving `AGENTS.md` persona. |
| AGENTS.md | The independently maintained description of the Agent's evolving role, personality, and interaction style. A snapshot enters the first request as runtime context rather than being compiled into System Prompt and is changed or refreshed only when the user explicitly requests it. |
| Wiki | The only long-term knowledge store, with shallow dynamic categories and self-describing Markdown entries. It is distinct from Session history and Trajectory and has no separate Memory service. |
| Wiki entry | One independently retrievable Markdown document with a stable ID, kind, lifecycle state, summary, grep keys, and optional relations and freshness metadata. |
| Wiki INDEX | A regenerable maintenance inventory derived from entry headers. It is excluded from normal grep and is not required by model reads, writes, or retrieval. |
| Wiki Skill | The on-demand instructions for Wiki retrieval, writing, source handling, category creation, and maintenance. |
| Wiki write authorization | The Runtime-derived permission for semantic Wiki changes. `draft_only` is the default; `curate` covers ordinary active knowledge within an authorized task or Run; `behavior` separately covers `AGENTS.md` and Skill changes. Provenance does not itself grant permission. |
| Skill | Instructions that teach the Agent how to perform a kind of work. Skills are discovered through a small index and loaded on demand rather than injected in full. |
| WorkingContext | A short, user-level self-reminder maintained by the Agent, with at most one active version per Session. New versions and invalidation markers are appended without rewriting earlier content; compaction keeps only the latest active version immediately after the task summary. It is scoped to a Run or Session and is neither long-term Wiki memory nor the separate proactive mechanism. |

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
| Compactor | The internal mechanism that uses a dedicated Compaction System Prompt to reconstruct current task state by future action value, validates the result, and appends a compaction event. It is not a Tool and never rewrites old Trajectory. |
| Cache boundary | The start of a new provider-cache prefix. Compaction and explicit model, Tool, or System Prompt changes create one; ordinary messages and dynamic Skill or WorkingContext updates are appended to preserve the previous prefix. |
| Preflight | The admission check before each model request. It computes complete input and the active output reserve, enters Compacting at 75% input occupancy or when `I + O` exceeds Provider capacity, and rechecks after compaction. |
| WaitingRequest | A runtime-created request for user input that blocks the current execution. At most one is pending per Session; its validated answer resumes the original Tool Call or model request rather than starting a new Turn. Ordinary end-of-turn questions do not create this state. |
| WindingDown | Mandatory finalization is still in progress; execution is not yet fully stopped. |

## Input and control

| Term | Definition |
|---|---|
| Mailbox | The Session-owned ordered input buffer. It persists independently of any individual AgentLoop object and preserves input until a safe injection point. |
| Steer | The semantics of every ordinary message: idle input starts a new Turn; active-Turn input is buffered and injected at the next safe model boundary without immediately interrupting an active model request or tool action. |
| Control input | Commands such as stop that bypass the steer buffer because they act on the current execution. |
| Cancellation | A request to stop the current AgentLoop, model request, tools, and child processes. Late events from an older Run are discarded rather than attached to a new Turn. |
| Tool call budget | A soft target for efficient Tool use. Every attempted call counts, including failed or rejected calls. Exceeding the target marks `over_budget` and prompts an efficiency review rather than stopping the Run. |
| Budget profile | A named collection of soft resource guidance: `lite`, `pro`, or `promax`. Profiles are Agent-adjustable configuration, not authorization boundaries or hard stop limits. |
| Time budget | Soft wall-clock guidance for a Run, separate from per-request and per-Tool timeouts. Expiry reminds the Agent to assess progress rather than forcibly terminating work. |
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
