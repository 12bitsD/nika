from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from nextloop import (
    Completed,
    ToolContext,
    ToolEffect,
    ToolExecutionMode,
    ToolSpec,
)

from .tools import NikaToolRuntime


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


def _parse_h2_blocks(markdown: str) -> tuple[str, list[tuple[str, str]]]:
    lines = markdown.splitlines()
    h2_indices = [
        idx for idx, line in enumerate(lines) if line.startswith("## ")
    ]
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


def register_feishu_doc_tools(
    runtime: NikaToolRuntime, store: FeishuDocTransport
) -> None:
    async def _handle_doc(
        args: Mapping[str, Any], _ctx: ToolContext
    ) -> Completed:
        action = str(args.get("action", ""))
        token = str(args.get("doc_token", "")).strip()
        if not token:
            return Completed("doc_token is required", is_error=True)
        before_md = await store.read_doc(token)
        if action == "read":
            return Completed(_format_doc_read(before_md))
        expected_md, err = _build_section_update(
            before_md,
            action,
            str(args.get("heading", "")),
            str(args.get("content", "")),
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
            f"Updated {token} section '## {_normalize_heading(str(args.get('heading', '')))}' (read-back verified)"
        )

    runtime.register(FEISHU_DOC_SPEC, _handle_doc)
