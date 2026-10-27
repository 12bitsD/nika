# AgentWiki design

Status: **M3 in progress**. The storage and consumption structure is accepted; write authorization, output budgets, and compaction behavior remain open. This document does not authorize runtime implementation.

## Purpose

AgentWiki is the only long-term knowledge source for projects, concepts, people, SOPs, profiles, and evolving agent behavior. There is no separate Memory service, automatic Recall Subagent, vector store, or second curated fact store in the baseline.

Wiki is distinct from Trajectory: Wiki holds curated long-term knowledge, while Trajectory remains the authoritative record of execution history. Raw Trajectory is not automatically promoted into Wiki.

## Accepted structure

```text
AgentWiki/
  AGENTS.md
  wiki/
    INDEX.md          # generated for maintenance; not required by model reads or writes
    inbox/            # uncertain, unclassified, or unconfirmed entries
    projects/
    concepts/
    people/
    playbooks/
    profiles/
    references/
  skills/
```

These categories are conventions, not a closed enum. The Agent may create a shallow, lowercase, plural ASCII category when none of the existing categories is appropriate. Deep taxonomies are avoided; cross-category relationships use entry IDs rather than directory inheritance.

`AGENTS.md` is the independently maintained home for the Agent's role, personality, long-term interaction style, and evolving preferences. It is not compiled into the runtime-owned System Prompt. A snapshot is injected as a separate runtime context message in the first request of a Session, with lower authority than the System Prompt. Project-level `AGENTS.md` files in code workspaces remain project context and are a different concern.

## Entries are self-describing

Each entry is a Markdown file with a small frontmatter header:

```yaml
---
id: chatty-eval-capability
kind: project
state: active
summary: Chatty/Highway evaluation background, verification methods, and confirmed lessons.
keys: chatty chatty-cli highway highway-agents 429 retry chatcmpl verbose
related: highway-e2e-verification silent-retry-observability
verified: 2026-10-27
---
```

The minimum required fields are `id`, `kind`, `summary`, and `keys`.

- `id` is a stable, unique identifier. Relations use IDs rather than paths so entries can move without breaking references.
- `kind` describes what the entry is and may expand with new categories.
- `summary` lets the Agent judge relevance from a grep result before reading the body.
- `keys` contains likely future search terms, including meaningful names, aliases, technical concepts, and error codes. It is not an unreadable encoding or an exhaustive bag of words.
- `related` links independently useful entries by ID.
- `verified` supports freshness decisions. File modification time alone does not reconfirm the content.

Lifecycle state is lightweight:

- `draft`: unconfirmed or unclassified; retrievable but must be treated cautiously.
- `active`: currently valid curated knowledge.
- `superseded`: retained history, with `replaced_by` pointing to the current entry when available.

An entry should cover one independently retrievable topic. Large project files are not split mechanically; a concept or lesson gets its own entry only when independent retrieval or reuse justifies it.

## Model consumption path

Normal retrieval is deliberately small:

```text
grep headers or body
→ judge path / kind / state / summary / keys
→ grep within selected files when useful
→ read only the required section or line range
→ optionally follow related IDs
```

There is no mandatory `list` operation or INDEX read in the model workflow. A future `list` may be added as a derived display convenience, but it would have no independent storage or maintenance requirement.

Runtime Wiki grep excludes generated INDEX and other explicitly generated maintenance files by default, preventing duplicate hits. Grep supports path narrowing, context lines, and result limits. `scope="headers"` is an engineering convenience for searching frontmatter without requiring complex regular expressions; it is not a semantic Recall system.

`ls` is retained only for bounded filesystem discovery. It returns directories and filenames without summaries and is primarily used before writes. It is distinct from the removed summary-heavy `list` catalog.

## Write path

The Wiki Skill teaches the Agent to:

1. run bounded `ls` to discover existing categories;
2. grep names, aliases, and keys to avoid duplicates;
3. use an existing suitable category or create a new shallow one;
4. put uncertain or unclassified material in `inbox/` rather than forcing a poor fit;
5. write one Markdown entry with a self-describing header and sourced body;
6. check a few likely future queries when practical, so the entry is discoverable and its summary is useful;
7. avoid editing INDEX or maintaining duplicate summaries.

Runtime write validation is structural, not a claim about truth: required fields, unique IDs, safe paths, supported lifecycle values, parseable frontmatter, resolvable `related` IDs, and valid `replaced_by` references. Concurrent writer ownership is an M6 resource concern.

New knowledge is grep-able immediately after writing. No maintenance run is required before it can be used.

## Maintenance INDEX and lifecycle

`wiki/INDEX.md` is a maintenance artifact, not a second fact source. A deterministic maintenance operation scans entry headers and regenerates one root inventory with paths, kinds, summaries, lifecycle states, and freshness information. It need not be current between runs and carries its generation time.

Maintenance may also report duplicate IDs or aliases, suspicious duplicate categories, missing headers, broken relations, orphaned entries, stale or superseded knowledge, and oversized files. Deterministic INDEX regeneration may be automatic; semantic merges, moves, splits, and category changes follow their separate authorization rules.

The Agent's normal read and write paths never depend on INDEX being present or up to date. This preserves a low-cognitive-overhead model interface while retaining a global inventory for long-term maintenance.

## Wiki Skill

`skills/wiki/SKILL.md` is the authoritative guide for Wiki consumption and maintenance. It explains when to grep or read, how to write useful `summary` and `keys`, how to inspect `state` and `verified`, how to follow `related`, how to create categories and entries, and how to preserve sources and uncertainty.

System Prompt does not duplicate this manual. Skill metadata is supplied separately from the runtime-owned System Prompt, and the Skill body is loaded on demand.

## Remaining M3 decisions

- **Write authorization:** who may create drafts, mark entries active, replace knowledge, and approve semantic maintenance.
- **Retrieval budgets:** exact grep result limits, pagination, body/output caps, and behavior when matches remain too broad after narrowing.
- **Compaction and caching:** which recalled Wiki content, references, and lifecycle metadata survive compaction, and how bootstrap snapshots are refreshed without unnecessary prefix invalidation.
- **Synchronization:** Git publication and concurrent writer behavior, coordinated with M6/M7 rather than duplicated here.
- **Refresh boundaries:** when a Session may adopt a new `AGENTS.md` snapshot or Wiki Skill revision.

No vector database, knowledge graph, dedicated Memory manager, automatic Recall Subagent, or mandatory per-entry INDEX is part of the current baseline. These are reconsidered only after concrete failure cases show that the accepted structure cannot handle them.
