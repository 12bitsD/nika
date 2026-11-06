# nika vision

Status: accepted product direction, not an implemented system or release.

## Goal

Build a **personal agent and superagent** for one user's real work. nika should reduce the effort required to start, continue, verify, and recover tasks—not merely answer messages.

The main entry is Feishu. The agent works across chat, coding, documents, comments, and container-based Browser/Computer tasks. It should reduce the user's context-management burden rather than create more of it.

## What the user should be able to do

- Talk privately, in a group Thread, or at an exact document comment.
- Ask for code investigation and modification with verification.
- Use browser and desktop capabilities inside one container.
- Continue a Session without repeatedly supplying old projects, decisions, or task state.
- Inspect what actually happened through Trajectory and export it only when needed.
- Receive concise help recovering context, identifying the next decision, and finishing work.
- Control what becomes long-term knowledge, agent behavior, or a reusable Skill.

## Design values

- **One execution path.** nika uses nextloop for chat and coding; there is no external coding harness or second runtime.
- **Product behavior stays here.** Personal agent and superagent behavior—goals, verification, Proactive behavior, authorization, resources, and future supervision—belongs to nika, not nextloop.
- **Engineering carries deterministic work.** Tool interfaces stay small. Runtime resolves Session, workspace, credentials, validation, retries, assets, and errors instead of pushing them into Prompt.
- **Wiki is long-term memory.** Markdown and a Wiki Skill are enough; no Memory service or Recall Subagent.
- **Facts and recovery are explicit.** Trajectory is append-only. Unknown effects are not presented as success or blindly replayed.
- **Proactive means less attention required.** nika should retrieve, organize, and summarize when useful, not send more notifications or invent goals.
- **Every capability has acceptance evidence.** Design confirmation, implementation, tests, and live acceptance are separate claims.

## Repository boundary

[nextloop](https://github.com/12bitsD/nextloop) owns the reusable AgentLoop, ContextBuilder, ReAct, Tool protocol, event projection, cancellation, recovery, and delivery-only retry.

nika owns personal agent and superagent behavior, Feishu, AgentWiki, Skills, Prompt content, concrete Tools, credentials, deployment, and Proactive behavior. The two repositories meet only through documented Adapter interfaces.

## Non-goals

- A general multi-channel daemon or another complete Agent platform.
- A separate coding mode, external coding harness, or Router/Worker framework by default.
- A dedicated Memory service, vector store, automatic Recall Subagent, or automatic RSI.
- A generic EventBus, remote replay, task-card system, or agent-defined Hooks.
- Remote device bridges, multiple virtual desktops, or background jobs without a concrete use case.
- Treating any candidate capability as accepted merely because another project demonstrates it.

## Current direction

- **M3 is complete:** AgentWiki structure and consumption are decided.
- **M5 is active:** detailed Tool schemas and nextloop Adapter contracts are being completed.
- **Next:** Proactive behavior, then M6 trust/resources, M7 data/channels, M8 engineering, and M9 final review.
- **Not started:** runtime, CI, release, deployment, or live model A/B evaluation.

## How success is judged

- The user can start or resume work without repeating unnecessary context.
- nika produces verified outcomes and distinguishes completed, unverified, and blocked work.
- Cancellation, failure, and recovery preserve facts without duplicating side effects.
- Every accepted capability has normal, failure, and recovery acceptance evidence.
- The system remains small enough for one person to understand and change.

See [requirements](docs/architecture/requirements.md) for capability ownership and acceptance, and [development handoff](docs/architecture/development-handoff.md) for the current state.
