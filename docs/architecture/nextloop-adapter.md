# nika ↔ nextloop Adapter contract

Status: consumer integration contract, not a dependency on nextloop's internal design documents or roadmap.

## Independence rule

nika and nextloop have independent goals, requirements, design, implementation, tests, and releases. nika does not jointly own ReAct or execution-protocol decisions, and nextloop does not jointly own personal agent or superagent decisions.

The only runtime dependency between them is a **versioned public contract**. The current contract is [nextloop's Loop interface and ownership](https://github.com/12bitsD/nextloop/blob/main/docs/design/loop-interface.md), **v1-draft**. Internal documents in either repository are not an integration dependency.

## Adapter surface nika supplies

- `EventStore`: nika SQLite events, transactions, idempotency, lease/fence, and recovery.
- `ModelProvider`: nika-selected model routes, streaming, usage, output, and errors.
- `ContextBuilder`: nika Prompt and product context policy assembled into the public CandidateRequest shape.
- `Compactor`: nika Compaction Prompt integrated through the public CompactionRequest/Result shape.
- `ToolRuntime`: nika's concrete Feishu, file, shell, Browser, Computer, Wiki, and history Tools.
- `DeliveryOwner`: Feishu delivery and durable handoff.

Each Adapter maps nika-specific data to the public contract; it must not create a second Loop, hidden retry path, or second fact source.

## Independent acceptance

nextloop independently proves the protocol with fake adapters. nika independently proves:

- each public field can be produced without reading nextloop implementation code;
- each returned outcome is mapped to an honest nika product result;
- there is no private branch for Feishu, Wiki, WorkingContext content, or desktop resources;
- a contract version mismatch fails closed with a clear diagnostic instead of silently changing semantics;
- nika's real model, Feishu, Browser/Computer, Wiki, and recovery acceptance passes using the selected contract version.

A nextloop internal refactor must not require a nika change when the public contract and event schema are unchanged. A nika product change must not require a nextloop change when the public contract is unchanged.

## Version policy

- Public API and event-schema versions are evaluated independently.
- nika records the supported API and event-schema versions in its Adapter configuration and release notes.
- A consumer release depends only on an accepted contract version, not on a nextloop branch, commit, design discussion, or unreleased change.
- New public behavior first appears in a versioned contract and conformance suite, then in nika's Adapter.

## Ownership of failures

- **Contract violation:** owning side fixes it without bypassing the contract.
- **Adapter mapping bug:** nika fixes the mapping in nika.
- **Loop protocol bug:** nextloop fixes the protocol and publishes a compatible update when possible.
- **Product behavior or acceptance failure:** nika owns the fix and evidence.

See [N4 in the requirements map](requirements.md) for the integration requirement and its acceptance ownership.
