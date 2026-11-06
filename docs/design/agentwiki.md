# AgentWiki design

Status: **M3 refined with L1 Synapse Map, `when` triggers, H2-TOC search, and Git-backed optimistic writes**. Implemented in `nika` as one runtime module (`src/nika/wiki.py`) plus one built-in Skill (`AgentWiki/skills/wiki/SKILL.md`).

## Purpose

AgentWiki is the only long-term knowledge source for projects, concepts, people, playbooks, profiles, and evolving agent behavior. There is no separate Memory service, vector database, automatic Recall Subagent, or second curated fact store.

Wiki is distinct from Trajectory: Wiki holds curated long-term knowledge, while Trajectory remains the authoritative record of execution history.

## Dual implementation shape in `nika`

AgentWiki lives in the `nika` repository and consists of two parts:

1. **Runtime module (`src/nika/wiki.py`):**
   - Compiles the deterministic **L1 Synapse Map (`WIKI_MAP`, ≤ 2 KiB)** injected alongside `AGENTS.md` on Session start.
   - Provides three high-leverage tools: `wiki_search`, `wiki_read`, and `wiki_upsert`.
   - Enforces the hard read-only guard on behavior files (`AGENTS.md`, `skills/**`), lenient frontmatter normalization (Postel's Law), automatic per-upsert Git commits, and single-line delivery receipts.
2. **Built-in Skill (`AgentWiki/skills/wiki/SKILL.md`):**
   - Teaches the model how to write high-signal `when` triggers (symptoms and scenarios rather than static archival labels), how to navigate via `L1 Synapse Map` → `wiki_search` (with H2 TOC) → targeted `wiki_read`, and when to curate knowledge proactively.

## Accepted directory structure

```text
AgentWiki/
  AGENTS.md           # role, persona, and expression style (behavior-locked)
  wiki/
    INDEX.md          # maintenance inventory generated offline; ignored by runtime search
    inbox/            # uncertain, transient, or unconfirmed drafts
    projects/
    concepts/
    people/
    playbooks/
    profiles/
    references/
  skills/
    wiki/SKILL.md     # built-in Wiki consumption & curation skill (behavior-locked)
```

Categories under `wiki/` are shallow conventions, not a closed enum. The Agent may create a new lowercase plural ASCII directory when needed.

## Four core mechanisms

### 1. L1 Synapse Map (`WIKI_MAP`, ≤ 2 KiB) — Zero-cost cold start & jargon resolution

Without an initial map, a model either suffers from cold-start amnesia (not knowing that "配置隔离" maps to `projects/tcc.md`) or wastes steps running blind `grep` calls on every turn.

- On Session start (cached in the immutable initial prefix alongside `AGENTS.md`), `src/nika/wiki.py` compiles a compact **L1 Synapse Map** (target ≤ 1.5–2 KiB, ~400–500 tokens) from `active` entry headers:
  ```text
  # Wiki Synapse Map (id: when / keys)
  [projects] tcc: 动态配置中心, namespace, branch隔离, mr隔离 | chatty-eval: highway, 429静默重试, chatcmpl_id
  [people] linhao: 林昊, 碳烤小火龙
  [playbooks] retry-observability-trap: 排查静默重试、任务假活、429限流未上报、外层拿不到request_id时
  ```
- Because it sits in the Session's initial message prefix, it hits **100% KV Cache** on every subsequent Step.
- When the user mentions an alias, person, or symptom that matches the Synapse Map, the model can jump straight to `wiki_read` or a targeted `wiki_search` in one step.

### 2. Self-describing headers with `when` triggers (Conditioned-reflex memory)

Static archives describe *what happened in the past*; great agent memory describes *when to recall this in the future*. Every Markdown entry starts with a concise YAML frontmatter header:

```yaml
---
id: retry-observability-trap
kind: playbook
state: active
when: 排查静默重试、任务假活、429限流未上报、外层事件循环拿不到底层SDK错误或chatcmpl_id时
summary: 底层 model-chain 自动重试会吞掉单次 attempt 错误，必须在 retry 层透传 observer 事件与错误元数据。
keys: chatty-cli highway 429 retry chatcmpl_id mirage
related: chatty-eval-capability
verified: 2026-11-06
---
```

- `id`: stable unique identifier across moves.
- `kind`: category (`project`, `playbook`, `person`, `concept`, `profile`, `reference`, etc.).
- `state`: `draft` (unconfirmed/working note), `active` (curated fact/SOP), or `superseded` (historical, with `replaced_by`).
- `when`: symptom-, intent-, or scenario-driven trigger phrase enabling cross-task memory connection.
- `summary`: one-line takeaway.
- `keys`: exact identifiers, aliases, error codes, and jargon.
- `verified`: `YYYY-MM-DD` date of last factual verification.

### 3. Two-stage retrieval (`wiki_search` with H2 TOC + targeted `wiki_read`)

Instead of forcing 4–5 round-trips (`ls` → `grep(headers)` → `grep(body)` → `read`), `src/nika/wiki.py` exposes two fast primitives:

1. **`wiki_search(query, *, kind=None, state=None)`:**
   - Searches frontmatter (`id`, `when`, `keys`, `summary`) and body text via ripgrep in one call (automatically excluding `INDEX.md`).
   - For every matched file, returns:
     - **Full frontmatter header** (`id`, `state`, `verified`, `when`, `summary`, `related`);
     - **Markdown `## H2` Table of Contents with line ranges** (e.g., `L12-L28 ## 当前隔离模型`, `L56-L78 ## 遗留与风险`);
     - **Top body match snippets** (±2 lines with line numbers).
2. **`wiki_read(path_or_id, *, start_line=1, end_line=200)`:**
   - Resolves either a relative path (`projects/tcc.md`) or an entry `id` (`tcc`).
   - Reads the exact section line range identified from the `wiki_search` H2 TOC.

### 4. Git-backed optimistic writes + single-line receipt (`wiki_upsert`)

Bureaucratic runtime write-permission state machines (`draft_only` vs. `curate` NLP classification) block proactive assistance. Instead, `src/nika/wiki.py` uses **hard boundary protection + optimistic Git-backed knowledge writes**:

- **Hard lock on behavior files:** `AGENTS.md` and `skills/**` are strictly read-only to `wiki_upsert` and file/shell tools unless unlocked by an explicit user command or confirmed `WaitingRequest`.
- **Optimistic `wiki_upsert(path, frontmatter, body, source_refs)` on `wiki/**`:**
  - The model may write `state: draft` for tentative notes or `state: active` when recording user-confirmed facts or verified task conclusions (with `source_refs` citing the Session/Turn or document URL).
  - **Lenient normalization (Postel's Law):** If `summary` or `keys` slightly exceed recommended lengths, `wiki_upsert` normalizes/trims whitespace and records a soft warning rather than failing the Step.
  - **Automatic Git commit & single-line receipt:** Every `wiki_upsert` automatically creates an atomic Git commit (`wiki(turn): upsert <id> [state] → <short_sha>`) and returns a receipt token. The final reply appends a compact one-line footer:
    `📝 Wiki: projects/tcc.md (active) · rev a1b2c3d`
  - If the user disagrees with any proactive update, a casual reply ("撤掉刚才那条 wiki") lets the Agent run `git revert a1b2c3d` deterministically.

## Maintenance and Compaction

- `wiki/INDEX.md` is regenerated offline/periodically for human browsing and hygiene checks (duplicate IDs, broken `related` links, stale `draft` entries). Normal model reads and writes never depend on `INDEX.md`.
- `AGENTS.md` and the `L1 Synapse Map` stay frozen within a Session to preserve prompt cache hits, refreshing only on a new Session or explicit user request.
- Compaction reconstructs active task state via [compaction-prompt.md](compaction-prompt.md) without re-copying full Wiki files that can be re-read by `id`.
