---
name: wiki
description: Search, read by H2 line range, upsert, and revert entries across work and personal Git Wikis.
requires_tools: [wiki, read]
min_nextloop: 1.1.0rc1
---

# Dual-Repo Wiki Skill

1. Search first with `wiki(action="search", query="<keywords>", repo="all" | "work" | "personal")` to obtain matched files and `## H2` line ranges (`L<start>-L<end>`).
2. Read only the relevant section using `read(path="<repo>:<rel_path>", start_line=<start>, end_line=<end>)`.
3. Persist confirmed knowledge with `wiki(action="upsert", repo="work" | "personal", path="<rel_path>", content="<markdown>", message="<summary>")` and include the returned `rev <sha>` receipt in your reply.
4. Undo an erroneous commit immediately when asked via `wiki(action="revert", repo="<repo>", rev="<sha>")`.
