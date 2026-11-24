from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Protocol

from nextloop import PreviewEvent, PreviewKind

from .contracts import (
    IngressEnvelope,
    IngressSource,
    ReplyKind,
    ReplyTarget,
)

CARD_THROTTLE_SECONDS = 2.0


@dataclass(frozen=True)
class FeishuInboundEvent:
    message_id: str
    actor_id: str
    chat_id: str
    thread_id: str = ""
    comment_id: str = ""
    doc_token: str = ""
    anchor_paragraphs: Sequence[str] = ()
    text: str = ""


class FeishuTransport(Protocol):
    async def send_card(self, channel_id: str, text: str) -> str: ...
    async def patch_card(self, card_id: str, text: str) -> None: ...
    async def reply_comment(
        self, doc_token: str, comment_id: str, text: str
    ) -> str: ...


class RecordedFeishuTransport:
    def __init__(self) -> None:
        self.created_cards: list[tuple[str, str, str]] = []
        self.patched_cards: list[tuple[str, str]] = []
        self.comment_replies: list[tuple[str, str, str]] = []
        self.final_card_texts: list[str] = []

    async def send_card(self, channel_id: str, text: str) -> str:
        card_id = f"card_{len(self.created_cards) + 1}"
        self.created_cards.append((card_id, channel_id, text))
        self.final_card_texts.append(text)
        return card_id

    async def patch_card(self, card_id: str, text: str) -> None:
        self.patched_cards.append((card_id, text))
        self.final_card_texts.append(text)

    async def reply_comment(
        self, doc_token: str, comment_id: str, text: str
    ) -> str:
        reply_id = f"reply_{len(self.comment_replies) + 1}"
        self.comment_replies.append((doc_token, comment_id, text))
        self.final_card_texts.append(text)
        return reply_id


@dataclass
class LiveStatusCardSession:
    transport: FeishuTransport
    channel_id: str
    clock: Callable[[], float] = time.monotonic
    card_id: str | None = None
    last_patch_at: float = -999.0
    _finalized: bool = field(default=False, init=False)
    _lock: asyncio.Lock = field(
        default_factory=asyncio.Lock, init=False, repr=False
    )

    async def emit_progress(self, status_line: str) -> str:
        async with self._lock:
            if self._finalized:
                return self.card_id or ""
            now = self.clock()
            if self.card_id is None:
                self.card_id = await self.transport.send_card(
                    self.channel_id, status_line
                )
                self.last_patch_at = now
                return self.card_id
            if now - self.last_patch_at >= CARD_THROTTLE_SECONDS:
                await self.transport.patch_card(self.card_id, status_line)
                self.last_patch_at = now
            return self.card_id

    async def finalize(self, final_text: str) -> str:
        async with self._lock:
            self._finalized = True
            if self.card_id is None:
                self.card_id = await self.transport.send_card(
                    self.channel_id, final_text
                )
            else:
                await self.transport.patch_card(self.card_id, final_text)
            self.last_patch_at = self.clock()
            return self.card_id


def format_feishu_prompt(event: FeishuInboundEvent) -> str:
    body = event.text.strip()
    if not event.anchor_paragraphs:
        return body
    sliced = "\n\n".join(
        p.strip() for p in event.anchor_paragraphs if p.strip()
    )
    return f"[Document Anchor Context]\n{sliced}\n\n[Comment]\n{body}"


def derive_feishu_thread_key(event: FeishuInboundEvent) -> str:
    if event.doc_token and event.comment_id:
        return f"feishu:comment:{event.doc_token}:{event.comment_id}"
    if event.thread_id.strip():
        return f"feishu:thread:{event.thread_id.strip()}"
    return f"feishu:dm:{event.chat_id.strip()}"


class PreviewProgressBridge:
    def __init__(self, card: LiveStatusCardSession) -> None:
        self.card = card
        self._loop = asyncio.get_running_loop()
        self._lock = threading.Lock()
        self._closed = False
        self._futures: list[Future[str]] = []

    def publish(self, event: PreviewEvent) -> None:
        if event.kind != PreviewKind.ATTEMPT_STARTED or event.step <= 1:
            return
        with self._lock:
            if self._closed:
                return
            fut = asyncio.run_coroutine_threadsafe(
                self.card.emit_progress(f"⏳ Step {event.step} running..."),
                self._loop,
            )
            self._futures.append(fut)

    async def flush(self) -> None:
        with self._lock:
            self._closed = True
            tracked = list(self._futures)
            self._futures.clear()
        if tracked:
            await asyncio.gather(
                *(asyncio.wrap_future(f) for f in tracked),
                return_exceptions=True,
            )


class StopAndIngestTarget(Protocol):
    async def stop(self, thread_key: str) -> bool: ...
    async def ingest(self, envelope: IngressEnvelope) -> str: ...


class FeishuAdapter:
    def __init__(
        self,
        *,
        scheduler: StopAndIngestTarget,
        allowlist: frozenset[str],
    ) -> None:
        self._scheduler = scheduler
        self._allowlist = frozenset(x.strip() for x in allowlist if x.strip())

    async def handle_event(self, event: FeishuInboundEvent) -> bool:
        actor = event.actor_id.strip()
        if not self._allowlist or actor not in self._allowlist:
            return False
        thread_key = derive_feishu_thread_key(event)
        cleaned_text = event.text.strip()
        if not cleaned_text:
            return False
        if cleaned_text == "/stop":
            await self._scheduler.stop(thread_key)
            return True
        target = self._build_reply_target(event)
        envelope = IngressEnvelope(
            event_id=f"feishu:{event.message_id.strip()}",
            source=IngressSource.FEISHU,
            thread_key=thread_key,
            prompt=format_feishu_prompt(event),
            reply_target=target,
            actor_id=actor,
        )
        await self._scheduler.ingest(envelope)
        return True

    @staticmethod
    def _build_reply_target(event: FeishuInboundEvent) -> ReplyTarget:
        if event.doc_token and event.comment_id:
            return ReplyTarget(
                kind=ReplyKind.FEISHU_COMMENT,
                channel_id=event.doc_token,
                metadata={"comment_id": event.comment_id},
            )
        channel = event.thread_id.strip() or event.chat_id.strip()
        return ReplyTarget(kind=ReplyKind.FEISHU_CARD, channel_id=channel)
