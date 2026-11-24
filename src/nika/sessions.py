from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from nextloop import (
    Completed,
    Event,
    EventStore,
    EventType,
    ToolContext,
    ToolEffect,
    ToolExecutionMode,
    ToolSpec,
)
from nextloop.events.project import (
    make_clear_working_context_message,
    make_working_context_message,
)

from .db import NikaLedger
from .tools import NikaToolRuntime


def _record_turn_event(
    ev: Event,
    timestamps: dict[int, str],
    user_texts: dict[int, str],
    assistant_texts: dict[int, str],
) -> None:
    timestamps[ev.turn] = ev.occurred_at
    msg = ev.payload.get("message")
    if not isinstance(msg, Mapping):
        return
    raw_content = msg.get("content")
    if not isinstance(raw_content, str):
        return
    text = raw_content.strip()
    if not text:
        return
    if ev.event_type == EventType.USER_MESSAGE and not text.startswith(
        "[WorkingContext"
    ):
        user_texts.setdefault(ev.turn, text)
    elif ev.event_type == EventType.ASSISTANT_MESSAGE:
        assistant_texts[ev.turn] = text


def _extract_turns(events: Sequence[Event]) -> list[tuple[str, str, str]]:
    user_texts: dict[int, str] = {}
    assistant_texts: dict[int, str] = {}
    timestamps: dict[int, str] = {}
    for ev in events:
        _record_turn_event(ev, timestamps, user_texts, assistant_texts)
    turns = sorted(set(user_texts) | set(assistant_texts))
    return [
        (
            timestamps.get(t, ""),
            user_texts.get(t, ""),
            assistant_texts.get(t, ""),
        )
        for t in turns
    ]


async def _summarize_session(
    store: EventStore, ledger: NikaLedger, sid: str
) -> tuple[str, str] | None:
    events = await store.load_surface(sid)
    turns = _extract_turns(events)
    if not turns:
        return None
    updated_at = turns[-1][0]
    first_q = turns[0][1][:120]
    last_a = turns[-1][2][:120]
    identity = await _thread_label(ledger, sid)
    line = (
        f"- session_id={sid} | entry={identity} | updated={updated_at}\n"
        f"  first_user: {first_q}\n  last_reply: {last_a}"
    )
    return updated_at, line


async def _recent_sessions(
    store: EventStore,
    ledger: NikaLedger,
    current_session_id: str,
    limit: int,
) -> Completed:
    sids = [
        sid for sid in await store.session_ids() if sid != current_session_id
    ]
    raw_items = [await _summarize_session(store, ledger, sid) for sid in sids]
    summaries = [item for item in raw_items if item is not None]
    summaries.sort(key=lambda item: item[0], reverse=True)
    chosen = [line for _, line in summaries[: max(1, min(limit, 20))]]
    if not chosen:
        return Completed("No other recent sessions found.")
    return Completed("\n".join(chosen))


async def _thread_label(ledger: NikaLedger, session_id: str) -> str:
    task = await ledger.get_task_by_session(session_id)
    return task.thread_key if task is not None else session_id


async def _inspect_session(
    store: EventStore, session_id: str, last_turns: int
) -> Completed:
    cleaned = session_id.strip()
    if not cleaned:
        return Completed("session_id is required for inspect", is_error=True)
    events = await store.load_surface(cleaned)
    turns = _extract_turns(events)
    if not turns:
        return Completed(f"Session '{cleaned}' has no recorded turns.")
    selected = turns[-max(1, min(last_turns, 10)) :]
    blocks = [
        f"[Turn @ {ts}]\nUser: {u}\nAssistant: {a}" for ts, u, a in selected
    ]
    return Completed("\n\n".join(blocks))


def _update_working_context(content: str) -> Completed:
    if not content.strip():
        msg = make_clear_working_context_message(scope="session")
        return Completed("WorkingContext cleared.", additional_messages=(msg,))
    msg = make_working_context_message(content, scope="session")
    return Completed("WorkingContext updated.", additional_messages=(msg,))


def register_session_tools(
    runtime: NikaToolRuntime, store: EventStore, ledger: NikaLedger
) -> None:
    async def _handle_session_ctl(
        args: Mapping[str, Any], ctx: ToolContext
    ) -> Completed:
        action = str(args["action"])
        if action == "recent":
            limit = int(args.get("limit", 5))
            return await _recent_sessions(store, ledger, ctx.session_id, limit)
        if action == "inspect":
            sid = str(args.get("session_id", ""))
            turns = int(args.get("last_turns", 2))
            return await _inspect_session(store, sid, turns)
        if action == "working_context":
            return _update_working_context(str(args.get("content", "")))
        return Completed(
            f"Unsupported session_ctl action: {action}", is_error=True
        )

    runtime.register(
        ToolSpec(
            name="session_ctl",
            description=(
                "Recall recent cross-entry sessions ('recent' / 'inspect') "
                "or set/clear 'working_context'."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["recent", "inspect", "working_context"],
                    },
                    "session_id": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                    "last_turns": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                    },
                    "content": {"type": "string"},
                },
                "required": ["action"],
                "additionalProperties": False,
            },
            mode=ToolExecutionMode.PARALLEL,
            effect=ToolEffect.READ_ONLY,
        ),
        _handle_session_ctl,
    )
