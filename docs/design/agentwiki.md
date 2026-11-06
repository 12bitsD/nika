# AgentWiki design

Status: **Accepted minimalist baseline (2026-11-06)**. Implemented in `nika` as one runtime module (`src/nika/wiki.py`) plus one built-in Skill (`AgentWiki/skills/wiki/SKILL.md`).

## Purpose

AgentWiki is the only long-term knowledge store for projects, concepts, people, playbooks, profiles, and evolving agent behavior. There is no separate Memory service, vector database, or precompiled in-memory index that bloats the prompt prefix as files grow.

Wiki holds curated long-term knowledge; Trajectory holds execution history.

## Dual implementation shape in `nika`

1. **Runtime module (`src/nika/wiki.py`):**
   - Exposes `wiki(action="search" | "upsert" | "revert", ...)`.
   - Uses `ripgrep` for sub-5ms live scanning across YAML frontmatter (`id`, `when`, `keys`, `summary`) and Markdown bodies, automatically extracting **`## H2` section headings with line ranges (TOC)** for matched files.
   - Enforces OS-level read-only protection on behavior files (`AGENTS.md`, `skills/**`), lenient frontmatter normalization, automatic per-upsert Git commits, and single-line delivery receipts.
2. **Built-in Skill (`AgentWiki/skills/wiki/SKILL.md`):**
   - Teaches the model how to write symptom-driven `when` triggers, how to navigate via `wiki(action="search")` → H2 line ranges → `read(path, start_line, end_line)`, and when to curate knowledge proactively.

## Directory structure

```text
AgentWiki/
  AGENTS.md           # persona, expression style, and core static project aliases (chmod 444)
  wiki/
    INDEX.md          # offline maintenance inventory; ignored by runtime search
    inbox/            # uncertain or unconfirmed drafts
    projects/
    concepts/
    people/
    playbooks/
    profiles/
    references/
  skills/
    wiki/SKILL.md     # built-in Wiki skill (chmod 444)
```

Categories under `wiki/` are shallow conventions; the Agent may create a new lowercase plural ASCII directory when needed.

## Core mechanisms

### 1. Static core aliases in `AGENTS.md` + live `ripgrep` (100% cache safety, zero scaling ceiling)

Dynamically injecting a compiled index of all Wiki entries into the prompt prefix breaks down as the Wiki grows to hundreds of files and invalidates the LLM prefix KV cache whenever an entry is added.

- **Core static aliases** (the ~10 active projects and key people the user talks about daily) live directly in `AGENTS.md`, which is frozen in the Session prefix (100% cache hit).
- Everything else is discovered live in < 5ms via `wiki(action="search")`.

### 2. Self-describing headers with `when` triggers (Conditioned-reflex memory)

Static archives only record *what happened*; usable memory records *when to recall this in the future*. Every Markdown entry starts with a concise YAML header:

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

- `id`: stable unique identifier.
- `kind`: category (`project`, `playbook`, `person`, `concept`, `profile`, `reference`).
- `state`: `draft` (unconfirmed), `active` (curated fact/SOP), or `superseded` (with `replaced_by`).
- `when`: symptom, error pattern, or scenario that should trigger recall across tasks.
- `summary`: one-line conclusion.
- `keys`: exact identifiers, aliases, and error codes.
- `verified`: `YYYY-MM-DD` date of last verification.

### 3. Single-hop search with H2 TOC (`wiki(action="search")` → `read`)

When the model calls `wiki(action="search", query="429 chatcmpl")`, `src/nika/wiki.py` runs `ripgrep` (excluding `INDEX.md`) and returns for each matched file:

1. **Full YAML frontmatter** (`id`, `state`, `verified`, `when`, `summary`, `related`);
2. **Markdown `## H2` Table of Contents with line ranges** (e.g., `L12-L28 ## 当前隔离模型`, `L56-L78 ## 遗留与风险`);
3. **Top body match snippets** (±2 lines with line numbers).

The model then reads the exact section via standard `read("AgentWiki/wiki/projects/tcc.md", start_line=56, end_line=78)` without blind full-file reads or a separate `wiki_read` tool.

### 4. Git-backed optimistic writes + single-line receipt (`wiki(action="upsert" | "revert")`)

Instead of fragile NLP write-permission classifiers in Runtime:

- **Hard OS lock on behavior files:** `AGENTS.md` and `skills/**` are `chmod 444` (read-only), unlocked only on explicit user instruction.
- **Optimistic `upsert` on `wiki/**`:**
  - The model writes `state: draft` for tentative notes or `state: active` for verified facts/conclusions (with `source_refs`).
  - Overlong header fields are trimmed/normalized with a soft warning rather than failing the Step.
  - Every `upsert` automatically creates an atomic Git commit (`wiki(turn): upsert <id> [state] → <short_sha>`) and appends a one-line receipt to the reply footer:
    `📝 Wiki: projects/tcc.md (active) · rev a1b2c3d`
  - If the user says *"撤了"*, `wiki(action="revert", rev="a1b2c3d")` runs `git revert` immediately.
