from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from nextloop import (
    Completed,
    ToolCall,
    ToolEffect,
    ToolExecutionMode,
    ToolOutcome,
    ToolRegistry,
    ToolSpec,
    ValidatedCall,
    ValidationIssue,
)
from nextloop.execute.tools import ToolHandler, validate_calls

from .contracts import SessionIdentity

POCKET_READ_METHODS = ("event.list", "todo.list")


def _refine_validated(
    validated: tuple[ValidatedCall, ...],
) -> tuple[ValidatedCall, ...]:
    refined: list[ValidatedCall] = []
    for item in validated:
        if (
            item.call.name == "pocket"
            and item.arguments.get("method") in POCKET_READ_METHODS
        ):
            read_spec = replace(
                item.spec,
                mode=ToolExecutionMode.PARALLEL,
                effect=ToolEffect.READ_ONLY,
            )
            refined.append(replace(item, spec=read_spec))
        else:
            refined.append(item)
    return tuple(refined)


class ScopedToolRuntime:
    def __init__(
        self,
        parent: NikaToolRuntime,
        identity: SessionIdentity,
        allowed_tools: frozenset[str],
    ) -> None:
        self._parent = parent
        self._identity = identity
        self._visible: dict[str, ToolSpec] = {
            spec.name: spec
            for spec in parent.catalog()
            if spec.name in allowed_tools
        }

    def catalog(self) -> Sequence[ToolSpec]:
        return tuple(self._visible.values())

    def validate(
        self, calls: Sequence[ToolCall]
    ) -> tuple[tuple[ValidatedCall, ...], tuple[ValidationIssue, ...]]:
        validated, issues = validate_calls(calls, self._visible)
        return _refine_validated(validated), issues

    # bits:allow(BCS004): nextloop ToolRuntime.execute protocol signature
    async def execute(
        self,
        call: ToolCall,
        arguments: Mapping[str, Any],
        *,
        session_id: str,
        turn: int,
        step: int,
        cancel: asyncio.Event,
    ) -> ToolOutcome:
        if session_id != self._identity.session_id:
            return Completed(
                f"Session identity mismatch: expected {self._identity.session_id}",
                is_error=True,
            )
        if call.name not in self._visible:
            return Completed(
                f"Tool '{call.name}' is not permitted for {self._identity.specialist.value}",
                is_error=True,
            )
        return await self._parent.execute(
            call,
            arguments,
            session_id=session_id,
            turn=turn,
            step=step,
            cancel=cancel,
        )


class NikaToolRuntime:
    def __init__(self) -> None:
        self._registry = ToolRegistry()
        self._sessions: dict[str, SessionIdentity] = {}
        self._wiki_receipts: dict[str, list[str]] = {}

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        self._registry.register(spec, handler)

    def catalog(self) -> Sequence[ToolSpec]:
        return self._registry.catalog()

    def validate(
        self, calls: Sequence[ToolCall]
    ) -> tuple[tuple[ValidatedCall, ...], tuple[ValidationIssue, ...]]:
        validated, issues = self._registry.validate(calls)
        return _refine_validated(validated), issues

    # bits:allow(BCS004): nextloop ToolRuntime.execute protocol signature
    async def execute(
        self,
        call: ToolCall,
        arguments: Mapping[str, Any],
        *,
        session_id: str,
        turn: int,
        step: int,
        cancel: asyncio.Event,
    ) -> ToolOutcome:
        return await self._registry.execute(
            call,
            arguments,
            session_id=session_id,
            turn=turn,
            step=step,
            cancel=cancel,
        )

    def bind_session(self, identity: SessionIdentity) -> None:
        self._sessions[identity.session_id] = identity

    def get_identity(self, session_id: str) -> SessionIdentity | None:
        return self._sessions.get(session_id)

    def record_wiki_receipt(self, session_id: str, receipt: str) -> None:
        self._wiki_receipts.setdefault(session_id, []).append(receipt)

    def pop_wiki_receipts(self, session_id: str) -> tuple[str, ...]:
        items = self._wiki_receipts.pop(session_id, [])
        return tuple(items)

    def cleanup_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        self._wiki_receipts.pop(session_id, None)

    def scope(
        self, identity: SessionIdentity, allowed_tools: frozenset[str]
    ) -> ScopedToolRuntime:
        self.bind_session(identity)
        return ScopedToolRuntime(self, identity, allowed_tools)

    async def invoke_direct(
        self,
        name: str,
        arguments: Mapping[str, Any],
        session_id: str = "direct",
    ) -> Completed:
        call = ToolCall(
            call_id="direct_call",
            name=name,
            arguments=json.dumps(dict(arguments), ensure_ascii=False),
            operation_id="op_direct",
        )
        outcome = await self.execute(
            call,
            arguments,
            session_id=session_id,
            turn=1,
            step=1,
            cancel=asyncio.Event(),
        )
        assert isinstance(outcome, Completed)
        return outcome
