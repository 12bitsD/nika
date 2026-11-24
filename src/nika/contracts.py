from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from nextloop import API_VERSION, EVENT_SCHEMA_VERSION, HarnessError

EXPECTED_NEXTLOOP_API = "1.1.0rc1"
EXPECTED_EVENT_SCHEMA = "1.1"


def verify_nextloop_version(
    *,
    api_version: str = API_VERSION,
    event_schema: str = EVENT_SCHEMA_VERSION,
) -> None:
    if api_version != EXPECTED_NEXTLOOP_API:
        raise HarnessError(
            f"nextloop API mismatch: expected {EXPECTED_NEXTLOOP_API}, "
            f"got {api_version}"
        )
    if event_schema != EXPECTED_EVENT_SCHEMA:
        raise HarnessError(
            f"event schema mismatch: expected {EXPECTED_EVENT_SCHEMA}, "
            f"got {event_schema}"
        )


def _normalize_required(obj: object, attr: str) -> None:
    raw = getattr(obj, attr)
    cleaned = str(raw).strip()
    if not cleaned:
        raise ValueError(f"{attr} must be non-empty")
    object.__setattr__(obj, attr, cleaned)


def _normalize_optional(obj: object, attr: str) -> None:
    object.__setattr__(obj, attr, str(getattr(obj, attr)).strip())


class IngressSource(StrEnum):
    FEISHU = "feishu"
    POCKET = "pocket"


class ReplyKind(StrEnum):
    FEISHU_CARD = "feishu_card"
    FEISHU_COMMENT = "feishu_comment"
    POCKET_CALLBACK = "pocket_callback"


class TaskKind(StrEnum):
    INGRESS = "ingress"
    DISPATCH = "dispatch"
    CONSULT = "consult"


class SpecialistId(StrEnum):
    MAIN = "main"
    TOP_TALENT = "top_talent"
    CODER = "coder"
    DOC_RESEARCH = "doc_research"
    EVAL = "eval"


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    NEED_DECISION = "need_decision"
    BLOCKED = "blocked"
    DONE = "done"
    FAILED = "failed"


class ReportStatus(StrEnum):
    DONE = "done"
    NEED_DECISION = "need_decision"
    BLOCKED = "blocked"
    HANDOFF = "handoff"


@dataclass(frozen=True)
class ReplyTarget:
    kind: ReplyKind
    channel_id: str = ""
    callback_url: str = ""
    callback_token: str = field(default="", repr=False)
    notify_channel_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _normalize_optional(self, "channel_id")
        _normalize_optional(self, "callback_url")
        _normalize_optional(self, "callback_token")
        _normalize_optional(self, "notify_channel_id")
        object.__setattr__(
            self, "metadata", MappingProxyType(dict(self.metadata))
        )
        if self.kind in (ReplyKind.FEISHU_CARD, ReplyKind.FEISHU_COMMENT):
            _normalize_required(self, "channel_id")
        elif self.kind == ReplyKind.POCKET_CALLBACK:
            _normalize_required(self, "callback_url")
            _normalize_required(self, "callback_token")
        else:
            raise ValueError(f"Unsupported reply kind: {self.kind}")


@dataclass(frozen=True)
class IngressEnvelope:
    event_id: str
    source: IngressSource
    thread_key: str
    prompt: str
    reply_target: ReplyTarget
    actor_id: str = ""

    def __post_init__(self) -> None:
        _normalize_required(self, "event_id")
        _normalize_required(self, "thread_key")
        _normalize_required(self, "prompt")
        _normalize_optional(self, "actor_id")


@dataclass(frozen=True)
class SessionIdentity:
    session_id: str
    task_id: str
    specialist: SpecialistId
    kind: TaskKind
    depth: int = 0

    def __post_init__(self) -> None:
        _normalize_required(self, "session_id")
        _normalize_required(self, "task_id")
        if self.depth not in (0, 1):
            raise ValueError(f"depth must be 0 or 1, got {self.depth}")
