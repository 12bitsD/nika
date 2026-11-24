from __future__ import annotations

import asyncio
import math
import os
import re
import signal
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nextloop import (
    Cancelled,
    Completed,
    ToolContext,
    ToolEffect,
    ToolExecutionMode,
    ToolOutcome,
    ToolSpec,
)

from .contracts import SpecialistId
from .tools import NikaToolRuntime, opt_str, req_str
from .wiki import PROTECTED_ANYWHERE, PROTECTED_LOWER

SECRET_PREFIXES = (
    "NIKA_",
    "FEISHU_",
    "POCKET_",
    "OPENAI_",
    "ANTHROPIC_",
    "MOONSHOT_",
    "KIMI_",
)
SECRET_SUFFIXES = (
    "_API_KEY",
    "_SECRET",
    "_SECRET_KEY",
    "_TOKEN",
    "_PASSWORD",
)


@dataclass(frozen=True)
class WorkspaceMount:
    roots: tuple[Path, ...]
    scratch_roots: tuple[Path, ...] = ()
    denied_write_roots: tuple[Path, ...] = ()


def _is_secret_env_key(key: str) -> bool:
    up = key.upper()
    return up.startswith(SECRET_PREFIXES) or up.endswith(SECRET_SUFFIXES)


def _sanitize_env(base_env: Mapping[str, str]) -> dict[str, str]:
    return {k: v for k, v in base_env.items() if not _is_secret_env_key(k)}


def _allowed_roots_for(
    runtime: NikaToolRuntime, session_id: str, mount: WorkspaceMount
) -> tuple[Path, ...]:
    ident = runtime.get_identity(session_id)
    if ident is not None and ident.specialist == SpecialistId.TOP_TALENT:
        return tuple(r.expanduser().resolve() for r in mount.scratch_roots)
    combined = (*mount.roots, *mount.scratch_roots)
    return tuple(r.expanduser().resolve() for r in combined)


def _has_symlink_below_root(matching_root: Path, lexical: Path) -> bool:
    ancestors = [lexical, *lexical.parents]
    base_anc = next(
        (
            a
            for a in ancestors
            if not a.is_symlink() and a.resolve() == matching_root
        ),
        None,
    )
    if base_anc is None:
        base_anc = next(
            (a for a in ancestors if a.resolve() == matching_root), None
        )
    if base_anc is None:
        return True
    rel_parts = lexical.relative_to(base_anc).parts
    chain = [
        base_anc.joinpath(*rel_parts[: idx + 1])
        for idx in range(len(rel_parts))
    ]
    return any(p.is_symlink() for p in chain)


def _resolve_ws_read(raw_path: str, allowed_roots: Sequence[Path]) -> Path:
    if not allowed_roots or not raw_path.strip():
        raise PermissionError("No workspace roots permitted for caller")
    raw = Path(raw_path).expanduser()
    base_candidate = raw if raw.is_absolute() else (allowed_roots[0] / raw)
    resolved = base_candidate.resolve()
    if any(
        resolved == root or root in resolved.parents for root in allowed_roots
    ):
        return resolved
    raise PermissionError(f"Path outside workspace roots: {raw_path}")


def _check_protected_rel(rel_parts: Sequence[str], raw_path: str) -> None:
    lowered = [p.lower() for p in rel_parts]
    if not lowered:
        raise PermissionError(f"Cannot overwrite workspace root: {raw_path}")
    if lowered[0] in PROTECTED_LOWER or any(
        p in PROTECTED_ANYWHERE for p in lowered
    ):
        raise PermissionError(f"Protected behavior path denied: {raw_path}")


def _resolve_ws_write(
    raw_path: str,
    allowed_roots: Sequence[Path],
    denied_roots: Sequence[Path] = (),
) -> Path:
    if not allowed_roots or not raw_path.strip():
        raise PermissionError("No writable workspace roots for caller")
    raw = Path(raw_path).expanduser()
    if ".." in raw.parts:
        raise PermissionError(f"Parent traversal '..' denied: {raw_path}")
    lexical = raw if raw.is_absolute() else (allowed_roots[0] / raw)
    resolved = lexical.resolve()
    matching_root = next(
        (r for r in allowed_roots if r in resolved.parents), None
    )
    if matching_root is None:
        raise PermissionError(f"Write target escapes workspace: {raw_path}")
    resolved_denied = [d.expanduser().resolve() for d in denied_roots]
    if any(resolved == d or d in resolved.parents for d in resolved_denied):
        raise PermissionError(
            f"Denied write root (use dedicated tool): {raw_path}"
        )
    if lexical.is_symlink() or _has_symlink_below_root(matching_root, lexical):
        raise PermissionError(f"Symlink write denied: {raw_path}")
    _check_protected_rel(resolved.relative_to(matching_root).parts, raw_path)
    return resolved


def _apply_edit(target: Path, old_text: str, new_text: str) -> Completed:
    if not target.is_file():
        return Completed(f"File not found: {target}", is_error=True)
    if not old_text:
        return Completed("old_text must be non-empty", is_error=True)
    content = target.read_text(encoding="utf-8")
    occurrences = content.count(old_text)
    if occurrences == 0:
        return Completed("old_text not found in file", is_error=True)
    if occurrences > 1:
        return Completed(
            f"old_text matched {occurrences} times; add context", is_error=True
        )
    target.write_text(content.replace(old_text, new_text, 1), encoding="utf-8")
    return Completed(f"Edited {target}")


def _grep_single_file(file_path: Path, rx: re.Pattern[str]) -> list[str]:
    lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    return [
        f"{file_path}:L{idx}: {ln.strip()[:140]}"
        for idx, ln in enumerate(lines, start=1)
        if rx.search(ln)
    ]


def _collect_grep_files(target: Path) -> list[Path]:
    if target.is_file():
        return [] if target.is_symlink() else [target]
    root = target.resolve()
    return [
        f
        for f in sorted(root.rglob("*"))
        if not f.is_symlink()
        and not _has_symlink_below_root(root, f)
        and f.is_file()
        and ".git" not in f.relative_to(root).parts
    ]


def _run_grep_sync(target: Path, pattern: str) -> Completed:
    if not pattern:
        return Completed("pattern must be non-empty", is_error=True)
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        return Completed(f"Invalid regex pattern: {exc}", is_error=True)
    hits: list[str] = []
    for f in _collect_grep_files(target):
        hits.extend(_grep_single_file(f, rx))
    if not hits:
        return Completed(f"No matches for pattern: {pattern}")
    return Completed("\n".join(hits[:60]))


def _kill_process_group(pid: int) -> None:
    with suppress(ProcessLookupError, PermissionError):
        os.killpg(pid, signal.SIGKILL)


def _decode_bash_result(
    out_b: bytes, err_b: bytes, returncode: int | None
) -> Completed:
    combined = (
        out_b.decode("utf-8", errors="replace")[:32_000]
        + err_b.decode("utf-8", errors="replace")[:32_000]
    ).strip()
    return Completed(
        combined or f"(exit {returncode})", is_error=(returncode != 0)
    )


def _parse_bash_timeout(raw: Any) -> float | None:
    if raw is None:
        return 30.0
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    val = float(raw)
    if not math.isfinite(val) or val <= 0:
        return None
    return min(val, 300.0)


async def _run_bash_command(
    command: str,
    cwd: Path,
    clean_env: Mapping[str, str],
    ctx_and_timeout: tuple[asyncio.Event, float],
) -> ToolOutcome:
    cancel, timeout = ctx_and_timeout
    proc = await asyncio.create_subprocess_exec(
        "/bin/bash",
        "-lc",
        command,
        cwd=str(cwd),
        env=dict(clean_env),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    comm_task = asyncio.create_task(proc.communicate())
    cancel_task = asyncio.create_task(cancel.wait())
    try:
        done, _ = await asyncio.wait(
            {comm_task, cancel_task},
            timeout=timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancel.is_set() or cancel_task in done:
            _kill_process_group(proc.pid)
            await comm_task
            return Cancelled(
                settled=True, partial_content="Command cancelled; pgid killed"
            )
        if comm_task not in done:
            _kill_process_group(proc.pid)
            await comm_task
            return Completed(
                f"Command timed out after {timeout}s (process group killed)",
                is_error=True,
            )
        out_b, err_b = await comm_task
        return _decode_bash_result(out_b, err_b, proc.returncode)
    finally:
        cancel_task.cancel()
        with suppress(asyncio.CancelledError):
            await cancel_task


WRITE_SPEC = ToolSpec(
    name="write",
    description="Create or overwrite a file inside the allowed workspace.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    },
    mode=ToolExecutionMode.EXCLUSIVE,
    effect=ToolEffect.NON_IDEMPOTENT,
)

EDIT_SPEC = ToolSpec(
    name="edit",
    description="Replace an exact unique text block in a workspace file.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_text": {"type": "string"},
            "new_text": {"type": "string"},
        },
        "required": ["path", "old_text", "new_text"],
        "additionalProperties": False,
    },
    mode=ToolExecutionMode.EXCLUSIVE,
    effect=ToolEffect.NON_IDEMPOTENT,
)

GREP_SPEC = ToolSpec(
    name="grep",
    description="Search regex pattern across allowed workspace files.",
    parameters={
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "path": {"type": "string"},
        },
        "required": ["pattern"],
        "additionalProperties": False,
    },
    mode=ToolExecutionMode.PARALLEL,
    effect=ToolEffect.READ_ONLY,
)

BASH_SPEC = ToolSpec(
    name="bash",
    description="Run a shell command in an isolated process group inside workspace.",
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "cwd": {"type": "string"},
            "timeout_seconds": {
                "type": ["number", "null"],
                "minimum": 0.1,
                "maximum": 300,
            },
        },
        "required": ["command"],
        "additionalProperties": False,
    },
    mode=ToolExecutionMode.EXCLUSIVE,
    effect=ToolEffect.NON_IDEMPOTENT,
)


class _WorkspaceToolSet:
    def __init__(
        self,
        runtime: NikaToolRuntime,
        mount: WorkspaceMount,
        clean_env: Mapping[str, str],
    ) -> None:
        self._runtime = runtime
        self._mount = mount
        self._env = clean_env

    def write(self, args: Mapping[str, Any], ctx: ToolContext) -> Completed:
        path_s = req_str(args, "path")
        content_s = req_str(args, "content")
        if path_s is None or content_s is None:
            return Completed("path and content must be strings", is_error=True)
        roots = _allowed_roots_for(self._runtime, ctx.session_id, self._mount)
        target = _resolve_ws_write(
            path_s, roots, self._mount.denied_write_roots
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content_s, encoding="utf-8")
        return Completed(f"Wrote {target}")

    def edit(self, args: Mapping[str, Any], ctx: ToolContext) -> Completed:
        path_s = req_str(args, "path")
        old_s = req_str(args, "old_text")
        new_s = req_str(args, "new_text")
        if path_s is None or old_s is None or new_s is None:
            return Completed(
                "path, old_text, and new_text must be strings", is_error=True
            )
        roots = _allowed_roots_for(self._runtime, ctx.session_id, self._mount)
        target = _resolve_ws_write(
            path_s, roots, self._mount.denied_write_roots
        )
        return _apply_edit(target, old_s, new_s)

    async def grep(
        self, args: Mapping[str, Any], ctx: ToolContext
    ) -> Completed:
        pat_s = req_str(args, "pattern")
        if pat_s is None:
            return Completed("pattern must be a string", is_error=True)
        roots = _allowed_roots_for(self._runtime, ctx.session_id, self._mount)
        raw_p = opt_str(args, "path") or (str(roots[0]) if roots else "")
        target = _resolve_ws_read(raw_p, roots)
        return await asyncio.to_thread(_run_grep_sync, target, pat_s)

    async def bash(
        self, args: Mapping[str, Any], ctx: ToolContext
    ) -> ToolOutcome:
        cmd_s = req_str(args, "command")
        timeout = _parse_bash_timeout(args.get("timeout_seconds"))
        if cmd_s is None or timeout is None:
            return Completed(
                "Invalid command or timeout_seconds", is_error=True
            )
        roots = _allowed_roots_for(self._runtime, ctx.session_id, self._mount)
        raw_cwd = opt_str(args, "cwd") or (str(roots[0]) if roots else "")
        cwd = _resolve_ws_read(raw_cwd, roots)
        if not cwd.is_dir():
            return Completed(f"cwd is not a directory: {cwd}", is_error=True)
        return await _run_bash_command(
            cmd_s, cwd, self._env, (ctx.cancel, timeout)
        )


def register_workspace_tools(
    runtime: NikaToolRuntime,
    mount: WorkspaceMount,
    *,
    base_env: Mapping[str, str] | None = None,
) -> None:
    clean_env = _sanitize_env(
        base_env if base_env is not None else {"PATH": "/usr/bin:/bin"}
    )
    toolset = _WorkspaceToolSet(runtime, mount, clean_env)
    runtime.register(WRITE_SPEC, toolset.write)
    runtime.register(EDIT_SPEC, toolset.edit)
    runtime.register(GREP_SPEC, toolset.grep)
    runtime.register(BASH_SPEC, toolset.bash)
