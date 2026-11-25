from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any, Protocol

from nextloop import (
    Completed,
    ToolContext,
    ToolEffect,
    ToolExecutionMode,
    ToolSpec,
)

from .contracts import TaskKind
from .tools import NikaToolRuntime, opt_str, req_str


class FeishuDocTransport(Protocol):
    async def read_doc(self, doc_token: str) -> str: ...
    async def write_doc(self, doc_token: str, markdown: str) -> None: ...


class InMemoryFeishuDocStore:
    def __init__(self, docs: Mapping[str, str] | None = None) -> None:
        self._docs: dict[str, str] = dict(docs or {})
        self._drop = False

    def drop_writes(self) -> None:
        self._drop = True

    async def read_doc(self, doc_token: str) -> str:
        if doc_token not in self._docs:
            raise KeyError(f"Document not found: {doc_token}")
        return self._docs[doc_token]

    async def write_doc(self, doc_token: str, markdown: str) -> None:
        if doc_token not in self._docs:
            raise KeyError(f"Document not found: {doc_token}")
        if not self._drop:
            self._docs[doc_token] = markdown


def _normalize_heading(raw: str) -> str:
    return raw.strip().lstrip("#").strip()


def _fence_marker(stripped: str) -> str | None:
    if stripped.startswith("```"):
        return "```"
    if stripped.startswith("~~~"):
        return "~~~"
    return None


def _next_fence_state(active: str | None, line: str) -> str | None:
    marker = _fence_marker(line.lstrip())
    if marker is None:
        return active
    if active is None:
        return marker
    return None if marker == active else active


def _find_h2_indices(lines: Sequence[str]) -> list[int]:
    indices: list[int] = []
    fence: str | None = None
    for idx, line in enumerate(lines):
        prev_fence = fence
        fence = _next_fence_state(fence, line)
        if prev_fence is None and fence is None and line.startswith("## "):
            indices.append(idx)
    return indices


def _parse_h2_blocks(markdown: str) -> tuple[str, list[tuple[str, str]]]:
    lines = markdown.splitlines()
    h2_indices = _find_h2_indices(lines)
    if not h2_indices:
        return markdown.strip(), []
    preamble = "\n".join(lines[: h2_indices[0]]).strip()
    sections: list[tuple[str, str]] = []
    for pos, start in enumerate(h2_indices):
        end = h2_indices[pos + 1] if pos + 1 < len(h2_indices) else len(lines)
        title = _normalize_heading(lines[start])
        body = "\n".join(lines[start + 1 : end]).strip()
        sections.append((title, body))
    return preamble, sections


def _render_h2_blocks(preamble: str, sections: list[tuple[str, str]]) -> str:
    rendered = [
        f"## {title}\n{body}" if body else f"## {title}"
        for title, body in sections
    ]
    chunks = [preamble, *rendered] if preamble else rendered
    return "\n\n".join(chunks) + "\n"


def _format_doc_read(markdown: str) -> str:
    _, sections = _parse_h2_blocks(markdown)
    toc = ", ".join(title for title, _ in sections) or "(none)"
    numbered = "\n".join(
        f"L{i}: {ln}" for i, ln in enumerate(markdown.splitlines(), start=1)
    )
    return f"[H2 Sections: {toc}]\n{numbered}"


def _build_section_update(
    before_md: str, action: str, heading: str, content: str
) -> tuple[str | None, str | None]:
    clean_h = _normalize_heading(heading)
    clean_body = content.strip()
    if not clean_h:
        return None, "heading is required"
    preamble, sections = _parse_h2_blocks(before_md)
    if action == "append":
        sections.append((clean_h, clean_body))
        return _render_h2_blocks(preamble, sections), None
    matches = [i for i, (t, _) in enumerate(sections) if t == clean_h]
    if len(matches) != 1:
        return None, f"Section '## {clean_h}' not uniquely found"
    sections[matches[0]] = (clean_h, clean_body)
    return _render_h2_blocks(preamble, sections), None


FEISHU_DOC_SPEC = ToolSpec(
    name="feishu_doc",
    description=(
        "Read or edit a Feishu document by H2 section ('read', "
        "'replace_section', 'append') with mandatory read-back check."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["read", "replace_section", "append"],
            },
            "doc_token": {"type": "string"},
            "heading": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["action", "doc_token"],
        "additionalProperties": False,
    },
    mode=ToolExecutionMode.EXCLUSIVE,
    effect=ToolEffect.NON_IDEMPOTENT,
)


def _refine_doc_spec(spec: ToolSpec, args: Mapping[str, Any]) -> ToolSpec:
    if args.get("action") == "read":
        return replace(
            spec,
            mode=ToolExecutionMode.PARALLEL,
            effect=ToolEffect.READ_ONLY,
        )
    return spec


async def _mutate_doc_locked(
    store: FeishuDocTransport,
    lock: asyncio.Lock,
    token: str,
    spec: tuple[str, str, str],
) -> Completed:
    action, heading, content = spec
    async with lock:
        before_md = await store.read_doc(token)
        expected_md, err = _build_section_update(
            before_md, action, heading, content
        )
        if err is not None or expected_md is None:
            return Completed(err or "invalid doc edit", is_error=True)
        await store.write_doc(token, expected_md)
        after_md = await store.read_doc(token)
        if after_md.strip() != expected_md.strip():
            return Completed(
                f"Mandatory read-back verification failed on {token}",
                is_error=True,
            )
    return Completed(
        f"Updated {token} section '## {_normalize_heading(heading)}' (read-back verified)"
    )


def register_feishu_doc_tools(
    runtime: NikaToolRuntime, store: FeishuDocTransport
) -> None:
    doc_locks: dict[str, asyncio.Lock] = {}

    async def _handle_doc(
        args: Mapping[str, Any], ctx: ToolContext
    ) -> Completed:
        action = req_str(args, "action") or ""
        token = (req_str(args, "doc_token") or "").strip()
        if not token:
            return Completed(
                "doc_token must be a non-empty string", is_error=True
            )
        if action == "read":
            return Completed(_format_doc_read(await store.read_doc(token)))
        ident = runtime.get_identity(ctx.session_id)
        if ident is not None and ident.kind == TaskKind.CONSULT:
            return Completed("Consult peer review is read-only", is_error=True)
        heading = req_str(args, "heading")
        content = (
            req_str(args, "content")
            if "content" in args
            else opt_str(args, "content")
        )
        if heading is None or content is None:
            return Completed(
                "heading and content must be strings", is_error=True
            )
        lock = doc_locks.setdefault(token, asyncio.Lock())
        return await _mutate_doc_locked(
            store, lock, token, (action, heading, content)
        )

    runtime.register(FEISHU_DOC_SPEC, _handle_doc, refiner=_refine_doc_spec)
