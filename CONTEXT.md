# nika context

This file defines nika's product vocabulary. Execution terms such as AgentLoop, Turn, Run, AgentState, Compactor, and finalization are canonically defined in [nextloop CONTEXT](https://github.com/12bitsD/nextloop/blob/main/CONTEXT.md).

## Product knowledge and behavior

| Term | Definition |
|---|---|
| AgentWiki | nika's shared root for `AGENTS.md`, long-term Wiki content, and Skills. Wiki and Skills have separate consumption mechanisms. |
| Personal agent | nika's user-facing assistant for conversation, coding, documents, knowledge, and task completion. |
| Superagent | nika's product-level coordination of goals, verification, Proactive behavior, authorization, resources, and any future supervision or multi-agent collaboration explicitly chosen later. The name alone does not adopt Router/Worker, background jobs, or a multi-agent framework. |
| AGENTS.md | nika's independently maintained description of the Agent's evolving role, personality, and interaction style. It enters the first request as runtime context and is changed only by explicit user request. |
| System Prompt | nika's runtime-owned contract for action, verification, harness use, and delivery, maintained in `docs/design/system-prompt.md`. |
| Compaction Prompt | nika's dedicated Prompt for reconstructing current task state during nextloop compaction. |
| Wiki | The only long-term knowledge store, with shallow dynamic categories and self-describing Markdown entries. It is distinct from Session history and Trajectory and has no separate Memory service. |
| Wiki entry | One independently retrievable Markdown document with stable ID, kind, lifecycle state, summary, grep keys, and optional relations and freshness metadata. |
| Wiki INDEX | A regenerable maintenance inventory derived from entry headers. It is excluded from normal grep and is not required by model reads, writes, or retrieval. |
| Wiki Skill | The on-demand instructions for Wiki retrieval, writing, source handling, category creation, and maintenance. |
| Wiki write authorization | Runtime-derived permission for semantic Wiki changes. `draft_only` is the default; `curate` covers ordinary active knowledge within an authorized task or Run; `behavior` separately covers `AGENTS.md` and Skill changes. Provenance does not grant permission. |
| Skill | Instructions for a kind of work. Skills are discovered through a small index and loaded on demand. Current content is used at load time. |
| Coding Skill | The on-demand protocol for repository inspection, modification, testing, diff review, and delivery. Coding does not require a separate runtime mode. |
| WorkingContext | nika's short, user-level self-reminder content. At most one active version exists per Session; 2 KiB is a soft readability guideline. nextloop owns its append and compaction mechanics. |
| Proactive context management | A separate product mechanism for reducing the user's context-management burden through task framing, retrieval, distillation, and carefully limited notification. It is not WorkingContext or automatic self-improvement. |

## Product capabilities

| Term | Definition |
|---|---|
| BrowserUse | Browser interaction against the browser environment inside nika's container. |
| ComputerUse | GUI interaction against the virtual desktop inside nika's container. Already-performed actions cannot be undone by cancelling a later action. |
| GUI execution lock | The container-level serialization that prevents multiple Sessions from acting on the same virtual desktop concurrently. |
| Feishu document | A Feishu Docx document that nika can read, create, or edit through product Tools. |
| Document comment | A Feishu discussion location that can wake nika through an explicit `@` mention and receive a reply in the same area. |
| Asset reference | A durable pointer to a large observation such as a screenshot or Tool output, stored outside event payloads. |
| Budget profile | A named collection of soft optimization guidance: `lite`, `pro`, or `promax`. It is not an authorization boundary or a forced stop condition. |

## Product data and recovery

| Term | Definition |
|---|---|
| Session | A continuing conversation and its durable identity plus append-only Trajectory. Private chat, Thread, partial comment, and whole-document areas have separate mappings by default. |
| SessionCatalog | The product capability for listing Sessions, reading Trajectory, and exporting selected histories on demand. |
| Trace export | A full-fidelity export of runtime and interaction events for diagnosis and analysis. |
| AIFT export | A model-interaction projection for training workflows, distinct from full trace and Provider-specific chat-template conversion. |
| Long-term memory | Curated knowledge maintained in Wiki files. Trajectory is not automatically promoted into long-term memory. |
| Delivery | Feishu presentation and delivery of a committed result. Delivery retries never rerun the model or Tools. |
| Interruption recovery | Rebuilding product state from committed facts after process failure. Historical side effects are not automatically replayed. |
