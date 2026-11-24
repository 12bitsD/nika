# Long-term Wiki design (Dual-repo mount)

Status: **Accepted dual-repo baseline (2026-11-24)**. Supersedes the 2026-11-06 proposal to create a separate `AgentWiki/` directory with a custom YAML schema.

Harness context: [harness.md](harness.md).

## Purpose

Nika's long-term knowledge lives directly in the user's **two existing Git-backed Wiki repositories**—the **work Wiki** (`workwiki`) and the **personal Wiki** (`0h`)—rather than a third, newly invented `AgentWiki/` store. There is no separate Memory service, vector database, or precompiled in-memory index that bloats the prompt prefix as files grow.

Wiki holds curated long-term knowledge; `session_events` in SQLite holds execution history.

## Dual-repo mount shape in `nika`

1. **Zero migration, native formats preserved:**
   - Each repository keeps its own directory conventions, frontmatter/atomic-record format, and built-in maintenance rules (e.g., work entries go to the work Wiki; personal projects and life go to `0h`).
   - `AGENTS.md` and `skills/**` in each repo remain OS-protected (`chmod 444`).
2. **Runtime module (`src/nika/wiki.py`) + built-in Skill (`skills/wiki/SKILL.md`):**
   - Exposes `wiki(action="search" | "upsert" | "revert", repo="work" | "personal" | "all", ...)`.
   - Teaches the model when to search across both repos, how to read matched `## H2` line ranges via standard `read`, and which repo owns a given piece of knowledge.

## Core mechanisms

### 1. Static core aliases in `AGENTS.md` + live `ripgrep` (100% cache safety, zero scaling ceiling)

Dynamically injecting a compiled index of all Wiki entries into the prompt prefix breaks down as the Wikis grow and invalidates the LLM prefix KV cache whenever an entry is added.

- **Core static aliases** (the ~10 active projects and key people the user talks about daily) live directly in `AGENTS.md`, frozen in the Session prefix (100% cache hit).
- Everything else is discovered live in < 5ms via `wiki(action="search")`.

### 2. Native per-repo metadata (no forced schema rewrite)

Each Wiki already encodes retrieval triggers in its own native convention (e.g., `aliases` / `when` / `keys` frontmatter or atomic `FACT` / `DECISION` / `GAP` records). Nika's `wiki.py` indexes them as-is with `ripgrep` instead of imposing a new header format on either repository.

### 3. Single-hop search with H2 TOC (`wiki(action="search")` → `read`)

When the model calls `wiki(action="search", query="429 chatcmpl")`, `src/nika/wiki.py` runs `ripgrep` across the mounted Wiki roots (excluding generated `INDEX.md` inventories) and returns for each matched file:

1. **Repo tag + relative path + header/frontmatter**;
2. **Markdown `## H2` Table of Contents with line ranges** (e.g., `L12-L28 ## 当前隔离模型`);
3. **Top body match snippets** (±2 lines with line numbers).

The model then reads the exact section via standard `read(path, start_line=..., end_line=...)` without blind full-file reads or a separate `wiki_read` tool.

### 4. Native Git-backed optimistic writes + single-line receipt (`wiki(action="upsert" | "revert")`)

- **Hard OS lock on behavior files:** `AGENTS.md` and `skills/**` are `chmod 444` (read-only), unlocked only on explicit user instruction.
- **Optimistic `upsert` under `wiki_git_lock`:**
  - Writes unconfirmed notes as drafts and verified conclusions as active/confirmed entries in the appropriate repository.
  - Every `upsert` creates an atomic Git commit **in that repository** and appends a one-line receipt to the reply footer:
    `📝 Wiki: workwiki:projects/tcc.md (active) · rev a1b2c3d`
  - If the user says *"撤了"*, `wiki(action="revert", repo="workwiki", rev="a1b2c3d")` runs `git revert` immediately.
- **Curator boundary:** `doc_research` is the primary structured Wiki maintainer; `top_talent` is forbidden from writing to canonical Wiki entries.
