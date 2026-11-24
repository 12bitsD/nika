from __future__ import annotations

import asyncio
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
from .tools import NikaToolRuntime
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


def _has_symlink_along(root: Path, target: Path) -> bool:
    if target != root and root not in target.parents:
        return True
    rel_parts = target.relative_to(root).parts
    chain = [
        root.joinpath(*rel_parts[: idx + 1]) for idx in range(len(rel_parts))
    ]
    return any(p.is_symlink() for p in chain)


def _resolve_ws_read(raw_path: str, allowed_roots: Sequence[Path]) -> Path:
    if not allowed_roots:
        raise PermissionError("No workspace roots permitted for caller")
    raw = Path(raw_path).expanduser()
    base_candidate = raw if raw.is_absolute() else (allowed_roots[0] / raw)
    resolved = base_candidate.resolve()
    for root in allowed_roots:
        if resolved == root or root in resolved.parents:
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


def _resolve_ws_write(raw_path: str, allowed_roots: Sequence[Path]) -> Path:
    if not allowed_roots:
        raise PermissionError("No writable workspace roots for caller")
    raw = Path(raw_path).expanduser()
    lexical = raw if raw.is_absolute() else (allowed_roots[0] / raw)
    matching_root = next(
        (r for r in allowed_roots if r in lexical.resolve().parents),
        None,
    )
    if matching_root is None:
        raise PermissionError(f"Write target escapes workspace: {raw_path}")
    if lexical.is_symlink() or _has_symlink_along(matching_root, lexical):
        raise PermissionError(f"Symlink write denied: {raw_path}")
    resolved = lexical.resolve()
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


def _run_grep_sync(target: Path, pattern: str) -> Completed:
    if not pattern:
        return Completed("pattern must be non-empty", is_error=True)
    rx = re.compile(pattern)
    files = (
        [target]
        if target.is_file()
        else [
            f
            for f in sorted(target.rglob("*"))
            if f.is_file() and ".git" not in f.parts
        ]
    )
    hits: list[str] = []
    for f in files:
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
        out_b.decode("utf-8", errors="replace")
        + err_b.decode("utf-8", errors="replace")
    ).strip()
    return Completed(
        combined or f"(exit {returncode})", is_error=(returncode != 0)
    )


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
                "type": "number",
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


def register_workspace_tools(
    runtime: NikaToolRuntime,
    mount: WorkspaceMount,
    *,
    base_env: Mapping[str, str] | None = None,
) -> None:
    clean_env = _sanitize_env(
        base_env if base_env is not None else {"PATH": "/usr/bin:/bin"}
    )

    def _write_handler(args: Mapping[str, Any], ctx: ToolContext) -> Completed:
        roots = _allowed_roots_for(runtime, ctx.session_id, mount)
        target = _resolve_ws_write(str(args["path"]), roots)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(args["content"]), encoding="utf-8")
        return Completed(f"Wrote {target}")

    def _edit_handler(args: Mapping[str, Any], ctx: ToolContext) -> Completed:
        roots = _allowed_roots_for(runtime, ctx.session_id, mount)
        target = _resolve_ws_write(str(args["path"]), roots)
        return _apply_edit(target, str(args["old_text"]), str(args["new_text"]))

    async def _grep_handler(
        args: Mapping[str, Any], ctx: ToolContext
    ) -> Completed:
        roots = _allowed_roots_for(runtime, ctx.session_id, mount)
        raw_p = str(args.get("path") or (roots[0] if roots else ""))
        target = _resolve_ws_read(raw_p, roots)
        return await asyncio.to_thread(
            _run_grep_sync, target, str(args["pattern"])
        )

    async def _bash_handler(
        args: Mapping[str, Any], ctx: ToolContext
    ) -> ToolOutcome:
        roots = _allowed_roots_for(runtime, ctx.session_id, mount)
        raw_cwd = str(args.get("cwd") or (roots[0] if roots else ""))
        cwd = _resolve_ws_read(raw_cwd, roots)
        timeout = float(args.get("timeout_seconds", 30.0))
        return await _run_bash_command(
            str(args["command"]), cwd, clean_env, (ctx.cancel, timeout)
        )

    runtime.register(WRITE_SPEC, _write_handler)
    runtime.register(EDIT_SPEC, _edit_handler)
    runtime.register(GREP_SPEC, _grep_handler)
    runtime.register(BASH_SPEC, _bash_handler)
