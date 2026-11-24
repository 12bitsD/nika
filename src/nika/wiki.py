from __future__ import annotations

import asyncio
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nextloop import (
    Completed,
    ToolContext,
    ToolEffect,
    ToolExecutionMode,
    ToolSpec,
)

from .tools import NikaToolRuntime

PROTECTED_LOWER = frozenset(
    {"agents.md", "claude.md", ".agents", "skills", "specialists", ".git"}
)
PROTECTED_ANYWHERE = frozenset({"agents.md", "claude.md", ".git"})
HEX_REV_RE = re.compile(r"^[0-9a-fA-F]{6,40}$")


@dataclass(frozen=True)
class WikiMount:
    work: Path
    personal: Path

    def repo_map(self) -> dict[str, Path]:
        return {
            "work": self.work.expanduser().resolve(),
            "personal": self.personal.expanduser().resolve(),
        }


def _reject_symlinks_under(root_resolved: Path, cleaned: str) -> None:
    parts = [p for p in Path(cleaned).parts if p not in ("", ".")]
    chain = [
        root_resolved.joinpath(*parts[: idx + 1]) for idx in range(len(parts))
    ]
    if any(p.is_symlink() for p in chain):
        raise PermissionError(f"Symlink write denied: {cleaned}")


def _resolve_contained(root: Path, rel_path: str) -> Path:
    cleaned = rel_path.strip().lstrip("/")
    raw_parts = [p.lower() for p in Path(cleaned).parts if p not in ("", ".")]
    if not cleaned or not raw_parts:
        raise ValueError("path must point to a file inside repository")
    if raw_parts[0] in PROTECTED_LOWER or any(
        p in PROTECTED_ANYWHERE for p in raw_parts
    ):
        raise PermissionError(f"Protected behavior path denied: {rel_path}")
    root_resolved = root.expanduser().resolve()
    _reject_symlinks_under(root_resolved, cleaned)
    resolved = (root_resolved / cleaned).resolve()
    if root_resolved not in resolved.parents:
        raise PermissionError(f"Path escapes repository root: {rel_path}")
    rel_parts = [p.lower() for p in resolved.relative_to(root_resolved).parts]
    if rel_parts[0] in PROTECTED_LOWER or any(
        p in PROTECTED_ANYWHERE for p in rel_parts
    ):
        raise PermissionError(f"Protected behavior path denied: {rel_path}")
    return resolved


def _toc_span(headings: Sequence[tuple[int, str]], pos: int, total: int) -> str:
    start, title = headings[pos]
    end = headings[pos + 1][0] - 1 if pos + 1 < len(headings) else total
    return f"  L{start}-L{end} {title}"


def _h2_toc(lines: Sequence[str]) -> list[str]:
    headings = [
        (idx, line.strip())
        for idx, line in enumerate(lines, start=1)
        if line.startswith("## ")
    ]
    total = len(lines)
    return [_toc_span(headings, pos, total) for pos in range(len(headings))]


def _frontmatter_summary(lines: Sequence[str]) -> str:
    if not lines or lines[0].strip() != "---":
        return lines[0].strip() if lines else ""
    end_idx = next(
        (i for i in range(1, min(len(lines), 30)) if lines[i].strip() == "---"),
        0,
    )
    if end_idx == 0:
        return lines[0].strip()
    return " | ".join(ln.strip() for ln in lines[1:end_idx] if ln.strip())


def _matching_snippets(lines: Sequence[str], terms: Sequence[str]) -> str:
    hits = [
        f"  L{idx}: {line.strip()[:120]}"
        for idx, line in enumerate(lines, start=1)
        if any(t in line.lower() for t in terms)
    ]
    return "\n".join(hits[:3])


def _score_and_format_file(
    repo_name: str, root: Path, md_file: Path, terms: Sequence[str]
) -> tuple[int, str] | None:
    lines = md_file.read_text(encoding="utf-8", errors="ignore").splitlines()
    rel = str(md_file.relative_to(root))
    haystack = f"{rel.lower()}\n" + "\n".join(lines).lower()
    matched_count = sum(1 for t in terms if t in haystack)
    if matched_count == 0:
        return None
    toc = "\n".join(_h2_toc(lines)) or "  (no ## H2 sections)"
    body = _matching_snippets(lines, terms)
    entry = f"[{repo_name}:{rel}] {_frontmatter_summary(lines)}\nTOC:\n{toc}"
    return matched_count, (f"{entry}\nMatches:\n{body}" if body else entry)


@dataclass(frozen=True)
class WikiUpsertSpec:
    repo_name: str
    rel_path: str
    content: str
    message: str


def _search_single_repo(
    name: str, root: Path, terms: Sequence[str]
) -> list[tuple[int, str]]:
    if not root.is_dir():
        return []
    md_files = [
        f
        for f in sorted(root.rglob("*.md"))
        if ".git" not in f.parts and f.name != "INDEX.md"
    ]
    hits = [_score_and_format_file(name, root, f, terms) for f in md_files]
    return [h for h in hits if h is not None]


def _search_repos(mount: WikiMount, repo_filter: str, query: str) -> Completed:
    terms = [t.lower() for t in re.split(r"\s+", query.strip()) if t.strip()]
    if not terms:
        return Completed("query must be non-empty", is_error=True)
    repos = mount.repo_map()
    selected = (
        list(repos.items())
        if repo_filter == "all"
        else [(repo_filter, repos[repo_filter])]
    )
    scored: list[tuple[int, str]] = []
    for name, root in selected:
        scored.extend(_search_single_repo(name, root, terms))
    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored:
        return Completed(f"No Wiki matches for query: {query}")
    return Completed("\n\n".join(text for _, text in scored[:8]))


def _git_run(cwd: Path, args: Sequence[str]) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def git_head_sha(root: Path) -> str:
    return _git_run(root, ["rev-parse", "--short", "HEAD"])


def init_git_repo(root: Path, files: Mapping[str, str]) -> str:
    root.mkdir(parents=True, exist_ok=True)
    _git_run(root, ["init"])
    _git_run(root, ["config", "user.email", "nika-sandbox@example.com"])
    _git_run(root, ["config", "user.name", "Nika Sandbox"])
    for rel, body in files.items():
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(body, encoding="utf-8")
    _git_run(root, ["add", "."])
    _git_run(root, ["commit", "-m", "seed"])
    return git_head_sha(root)


def _upsert_sync(root: Path, spec: WikiUpsertSpec) -> str:
    target = _resolve_contained(root, spec.rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(spec.content, encoding="utf-8")
    rel_clean = str(target.relative_to(root))
    _git_run(root, ["add", "--", rel_clean])
    status = _git_run(root, ["status", "--porcelain", "--", rel_clean])
    if not status:
        sha = _git_run(root, ["rev-parse", "--short", "HEAD"])
        return f"📝 Wiki: {spec.repo_name}:{rel_clean} (unchanged) · rev {sha}"
    commit_msg = spec.message.strip() or f"wiki: update {rel_clean}"
    _git_run(root, ["commit", "-m", commit_msg, "--", rel_clean])
    sha = _git_run(root, ["rev-parse", "--short", "HEAD"])
    return f"📝 Wiki: {spec.repo_name}:{rel_clean} · rev {sha}"


def _revert_sync(root: Path, repo_name: str, rev: str) -> str:
    cleaned = rev.strip()
    if not HEX_REV_RE.fullmatch(cleaned):
        raise ValueError(f"Invalid git revision: {rev}")
    touched = _git_run(
        root,
        ["diff-tree", "--no-commit-id", "--name-only", "-r", "--root", cleaned],
    )
    for rel_line in touched.splitlines():
        if rel_line.strip():
            _resolve_contained(root, rel_line.strip())
    try:
        _git_run(root, ["revert", "--no-edit", cleaned])
    except subprocess.CalledProcessError:
        subprocess.run(
            ["git", "revert", "--abort"], cwd=root, capture_output=True
        )
        raise
    sha = _git_run(root, ["rev-parse", "--short", "HEAD"])
    return f"📝 Wiki reverted: {repo_name} ({cleaned}) · rev {sha}"


def _read_target_path(
    raw_path: str, mount: WikiMount, extra_roots: Sequence[Path]
) -> Path:
    repos = mount.repo_map()
    if ":" in raw_path:
        prefix, rel = raw_path.split(":", 1)
        if prefix in repos:
            root = repos[prefix].resolve()
            resolved = (root / rel.lstrip("/")).resolve()
            if resolved != root and root not in resolved.parents:
                raise PermissionError(f"Path escapes {prefix} wiki: {raw_path}")
            return resolved
    candidate = Path(raw_path).expanduser().resolve()
    allowed = [
        *(r.resolve() for r in repos.values()),
        *(r.expanduser().resolve() for r in extra_roots),
    ]
    if any(candidate == root or root in candidate.parents for root in allowed):
        return candidate
    raise PermissionError(f"Path outside allowed roots: {raw_path}")


def format_read_slice(
    target: Path, start_line: int | None, end_line: int | None
) -> str:
    if target.is_dir():
        entries = sorted(
            p.name + ("/" if p.is_dir() else "")
            for p in target.iterdir()
            if p.name != ".git"
        )
        return "\n".join(entries) if entries else "(empty directory)"
    if not target.is_file():
        raise FileNotFoundError(f"Not found: {target}")
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    lo = max(1, start_line or 1)
    hi = min(len(lines), end_line or len(lines))
    selected = [f"L{idx}: {lines[idx - 1]}" for idx in range(lo, hi + 1)]
    return "\n".join(selected)


WIKI_TOOL_SPEC = ToolSpec(
    name="wiki",
    description=(
        "Search (returns H2 line-range TOC), upsert (Git commit), "
        "or revert entries in 'work' or 'personal' Wiki repos."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["search", "upsert", "revert"],
            },
            "repo": {
                "type": "string",
                "enum": ["all", "work", "personal"],
            },
            "query": {"type": "string"},
            "path": {"type": "string"},
            "content": {"type": "string"},
            "message": {"type": "string"},
            "rev": {"type": "string"},
        },
        "required": ["action"],
        "additionalProperties": False,
    },
    mode=ToolExecutionMode.EXCLUSIVE,
    resources=("wiki_git_lock",),
    effect=ToolEffect.NON_IDEMPOTENT,
)

READ_TOOL_SPEC = ToolSpec(
    name="read",
    description=(
        "Read file lines or directory entries. Use '<repo>:<rel_path>' "
        "with start_line/end_line for Wiki sections."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "start_line": {"type": "integer", "minimum": 1},
            "end_line": {"type": "integer", "minimum": 1},
        },
        "required": ["path"],
        "additionalProperties": False,
    },
    mode=ToolExecutionMode.PARALLEL,
    effect=ToolEffect.READ_ONLY,
)


async def _run_wiki_write(
    action: str, repo_name: str, root: Path, args: Mapping[str, Any]
) -> str | None:
    if action == "upsert":
        spec = WikiUpsertSpec(
            repo_name=repo_name,
            rel_path=str(args.get("path", "")),
            content=str(args.get("content", "")),
            message=str(args.get("message", "")),
        )
        return await asyncio.to_thread(_upsert_sync, root, spec)
    if action == "revert":
        return await asyncio.to_thread(
            _revert_sync, root, repo_name, str(args.get("rev", ""))
        )
    return None


def _optional_int(args: Mapping[str, Any], key: str) -> int | None:
    val = args.get(key)
    return int(val) if val is not None else None


def register_wiki_tools(
    runtime: NikaToolRuntime,
    mount: WikiMount,
    extra_read_roots: Sequence[Path] = (),
) -> None:
    wiki_lock = asyncio.Lock()

    async def _handle_wiki(
        args: Mapping[str, Any], ctx: ToolContext
    ) -> Completed:
        action = str(args["action"])
        repo_name = str(args.get("repo", "all"))
        if action == "search":
            query = str(args.get("query", ""))
            return await asyncio.to_thread(
                _search_repos, mount, repo_name, query
            )
        repos = mount.repo_map()
        if repo_name not in repos:
            return Completed("repo must be 'work' or 'personal'", is_error=True)
        async with wiki_lock:
            receipt = await _run_wiki_write(
                action, repo_name, repos[repo_name], args
            )
        if receipt is None:
            return Completed(f"Unknown action: {action}", is_error=True)
        runtime.record_wiki_receipt(ctx.session_id, receipt)
        return Completed(receipt)

    def _handle_read(args: Mapping[str, Any], _ctx: ToolContext) -> Completed:
        raw_path = args.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            return Completed("path must be a non-empty string", is_error=True)
        target = _read_target_path(raw_path, mount, extra_read_roots)
        return Completed(
            format_read_slice(
                target,
                _optional_int(args, "start_line"),
                _optional_int(args, "end_line"),
            )
        )

    runtime.register(WIKI_TOOL_SPEC, _handle_wiki)
    runtime.register(READ_TOOL_SPEC, _handle_read)
