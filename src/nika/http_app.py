from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import h11

from .feishu import FeishuAdapter, FeishuInboundEvent
from .pocket import PocketAdapter, PocketWebhookRequest

MAX_BODY_BYTES = 1_048_576
READ_TIMEOUT_SECONDS = 15.0
SIGNATURE_MAX_SKEW_SECONDS = 300

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HttpDaemonDeps:
    feishu_adapter: FeishuAdapter
    pocket_adapter: PocketAdapter | None = None
    feishu_verification_token: str = ""
    feishu_encrypt_key: str = ""


@dataclass(frozen=True)
class _RawHttpRequest:
    method: str
    target: str
    headers: dict[str, str]
    body: bytes


def _str_field(mapping: Mapping[str, Any], key: str) -> str:
    val = mapping.get(key)
    return val.strip() if isinstance(val, str) else ""


def _bytes_eq(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def _parse_json_object(raw: bytes) -> tuple[dict[str, Any], bool]:
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {}, False
    if isinstance(parsed, dict):
        return parsed, True
    return {}, False


def _extract_feishu_token(payload: Mapping[str, Any]) -> str:
    hdr = payload.get("header")
    if isinstance(hdr, Mapping):
        tok = _str_field(hdr, "token")
        if tok:
            return tok
    return _str_field(payload, "token")


def _verify_lark_signature(
    encrypt_key: str, headers: Mapping[str, str], raw_body: bytes
) -> bool:
    ts = _str_field(headers, "x-lark-request-timestamp")
    nonce = _str_field(headers, "x-lark-request-nonce")
    sig = _str_field(headers, "x-lark-signature")
    if not ts.isdigit() or not nonce or not sig:
        return False
    ts_int = int(ts)
    if abs(time.time() - ts_int) > SIGNATURE_MAX_SKEW_SECONDS:
        return False
    prefix = f"{ts}{nonce}{encrypt_key}".encode()
    digest = hashlib.sha256(prefix + raw_body).hexdigest()
    return _bytes_eq(digest, sig)


def _verify_feishu_auth(
    deps: HttpDaemonDeps,
    headers: Mapping[str, str],
    raw_body: bytes,
    payload: Mapping[str, Any],
) -> bool:
    if not deps.feishu_encrypt_key and not deps.feishu_verification_token:
        return False
    if payload.get("type") == "url_verification":
        if not deps.feishu_verification_token:
            return False
        return _bytes_eq(
            _extract_feishu_token(payload), deps.feishu_verification_token
        )
    if deps.feishu_encrypt_key and not _verify_lark_signature(
        deps.feishu_encrypt_key, headers, raw_body
    ):
        return False
    if deps.feishu_verification_token:
        return _bytes_eq(
            _extract_feishu_token(payload), deps.feishu_verification_token
        )
    return True


def _extract_msg_text(raw_content: Any) -> str:
    if not isinstance(raw_content, str):
        return ""
    try:
        parsed = json.loads(raw_content)
    except ValueError:
        return raw_content
    return _str_field(parsed, "text") if isinstance(parsed, Mapping) else ""


def _parse_comment_event(
    ev: Mapping[str, Any], actor: str
) -> FeishuInboundEvent | None:
    doc_tok = _str_field(ev, "doc_token") or _str_field(ev, "file_token")
    cid = _str_field(ev, "comment_id")
    mid = _str_field(ev, "message_id") or cid
    text = _str_field(ev, "text") or _str_field(ev, "reply_text")
    raw_anc = ev.get("anchor_paragraphs")
    anchors = (
        tuple(x for x in raw_anc if isinstance(x, str))
        if isinstance(raw_anc, list)
        else ()
    )
    if not doc_tok or not cid or not actor:
        return None
    return FeishuInboundEvent(
        message_id=mid,
        actor_id=actor,
        chat_id=doc_tok,
        comment_id=cid,
        doc_token=doc_tok,
        anchor_paragraphs=anchors,
        text=text,
    )


def _parse_feishu_event(
    payload: Mapping[str, Any],
) -> FeishuInboundEvent | None:
    ev = payload.get("event")
    if not isinstance(ev, Mapping):
        return None
    sender = ev.get("sender")
    sid = sender.get("sender_id") if isinstance(sender, Mapping) else None
    actor = (
        _str_field(sid, "open_id")
        if isinstance(sid, Mapping)
        else _str_field(ev, "actor_id")
    )
    msg = ev.get("message")
    if not isinstance(msg, Mapping):
        return _parse_comment_event(ev, actor)
    mid = _str_field(msg, "message_id")
    cid = _str_field(msg, "chat_id")
    tid = _str_field(msg, "thread_id") or _str_field(msg, "root_id")
    if not mid or not cid or not actor:
        return None
    return FeishuInboundEvent(
        message_id=mid,
        actor_id=actor,
        chat_id=cid,
        thread_id=tid,
        text=_extract_msg_text(msg.get("content", "")),
    )


def _parse_pocket_payload(
    payload: Mapping[str, Any],
) -> PocketWebhookRequest | None:
    keys = (
        "delivery_id",
        "todo_id",
        "agent_id",
        "prompt",
        "scheduled_for",
        "result_callback_url",
        "callback_token",
    )
    vals = [_str_field(payload, k) for k in keys]
    if not all(vals):
        return None
    return PocketWebhookRequest(
        delivery_id=vals[0],
        todo_id=vals[1],
        agent_id=vals[2],
        prompt=vals[3],
        scheduled_for=vals[4],
        result_callback_url=vals[5],
        callback_token=vals[6],
    )


def _write_http_reply(
    conn: h11.Connection,
    writer: asyncio.StreamWriter,
    status: int,
    body_obj: Mapping[str, Any],
) -> None:
    raw_out = json.dumps(body_obj, ensure_ascii=False).encode("utf-8")
    if conn.our_state is h11.SEND_RESPONSE:
        res = h11.Response(
            status_code=status,
            headers=[
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(raw_out)).encode("ascii")),
                (b"connection", b"close"),
            ],
        )
        writer.write(conn.send(res) + conn.send(h11.Data(data=raw_out)))
        writer.write(conn.send(h11.EndOfMessage()))
        return
    head = (
        f"HTTP/1.1 {status} Error\r\n"
        "Content-Type: application/json; charset=utf-8\r\n"
        f"Content-Length: {len(raw_out)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    writer.write(head + raw_out)


async def _next_http_event(
    conn: h11.Connection, reader: asyncio.StreamReader
) -> h11.Event | None:
    while True:
        event = conn.next_event()
        if isinstance(event, h11.Event):
            return event
        if event is not h11.NEED_DATA:
            return None
        data = await asyncio.wait_for(
            reader.read(16384), timeout=READ_TIMEOUT_SECONDS
        )
        conn.receive_data(data)
        if not data:
            return None


async def _read_body_chunks(
    conn: h11.Connection, reader: asyncio.StreamReader
) -> tuple[bytes | None, int]:
    chunks: list[bytes] = []
    total = 0
    while True:
        event = await _next_http_event(conn, reader)
        if event is None:
            return None, 400
        if isinstance(event, h11.EndOfMessage):
            return b"".join(chunks), 200
        if isinstance(event, h11.Data):
            total += len(event.data)
            if total > MAX_BODY_BYTES:
                return None, 413
            chunks.append(bytes(event.data))


class NikaHttpServer:
    def __init__(self, deps: HttpDaemonDeps) -> None:
        self._deps = deps
        self._server: asyncio.Server | None = None

    async def start(self, host: str = "127.0.0.1", port: int = 8787) -> int:
        self._server = await asyncio.start_server(
            self._handle_conn, host=host, port=port
        )
        if not self._server.sockets:
            return port
        return int(self._server.sockets[0].getsockname()[1])

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _read_request(
        self, conn: h11.Connection, reader: asyncio.StreamReader
    ) -> tuple[_RawHttpRequest | None, int]:
        try:
            first = await _next_http_event(conn, reader)
            if first is None:
                return None, 0
            if not isinstance(first, h11.Request):
                return None, 400
            body, err_code = await _read_body_chunks(conn, reader)
        except h11.RemoteProtocolError:
            return None, 400
        if body is None:
            return None, err_code
        hdrs = {
            k.decode("latin1").lower(): v.decode("latin1")
            for k, v in first.headers
        }
        return (
            _RawHttpRequest(
                first.method.decode("ascii"),
                first.target.decode("ascii"),
                hdrs,
                body,
            ),
            200,
        )

    async def _dispatch_feishu(
        self, req: _RawHttpRequest
    ) -> tuple[int, dict[str, Any]]:
        payload, ok = _parse_json_object(req.body)
        if not ok:
            return 400, {"error": "invalid_json"}
        if not _verify_feishu_auth(self._deps, req.headers, req.body, payload):
            return 401, {"error": "unauthorized"}
        if payload.get("type") == "url_verification":
            return 200, {"challenge": _str_field(payload, "challenge")}
        parsed = _parse_feishu_event(payload)
        if parsed is None:
            return 200, {"accepted": False}
        accepted = await self._deps.feishu_adapter.handle_event(parsed)
        return 200, {"accepted": accepted}

    async def _dispatch_pocket(
        self, req: _RawHttpRequest
    ) -> tuple[int, dict[str, Any]]:
        adapter = self._deps.pocket_adapter
        if adapter is None:
            return 404, {"error": "pocket_not_configured"}
        auth = req.headers.get("authorization", "")
        if not adapter.verify_bearer(auth):
            return 401, {"error": "unauthorized"}
        payload, ok = _parse_json_object(req.body)
        parsed = _parse_pocket_payload(payload) if ok else None
        if parsed is None:
            return 400, {"error": "invalid_pocket_payload"}
        accepted = await adapter.handle_webhook(auth, parsed)
        if not accepted:
            return 400, {"error": "rejected_callback_origin"}
        return 202, {"accepted": True}

    async def _route_request(
        self, req: _RawHttpRequest
    ) -> tuple[int, dict[str, Any]]:
        path = req.target.split("?", 1)[0]
        if path == "/healthz":
            return (
                (200, {"status": "ok", "service": "nika"})
                if req.method == "GET"
                else (405, {"error": "method_not_allowed"})
            )
        if path == "/webhooks/feishu":
            return (
                await self._dispatch_feishu(req)
                if req.method == "POST"
                else (405, {"error": "method_not_allowed"})
            )
        if path == "/webhooks/pocket":
            return (
                await self._dispatch_pocket(req)
                if req.method == "POST"
                else (405, {"error": "method_not_allowed"})
            )
        return 404, {"error": "not_found"}

    async def _safe_route(
        self, req: _RawHttpRequest | None, err_code: int
    ) -> tuple[int, dict[str, Any]]:
        if req is None:
            err_name = "payload_too_large" if err_code == 413 else "bad_request"
            return err_code, {"error": err_name}
        try:
            return await self._route_request(req)
        except Exception:
            logger.exception(
                "Unhandled HTTP error on %s %s", req.method, req.target
            )
            return 500, {"error": "internal_error"}

    async def _handle_conn(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        conn = h11.Connection(h11.SERVER)
        try:
            req, err_code = await self._read_request(conn, reader)
            if req is None and err_code == 0:
                return
            status, body_obj = await self._safe_route(req, err_code)
            _write_http_reply(conn, writer, status, body_obj)
            await writer.drain()
        except (TimeoutError, h11.ProtocolError, OSError):
            writer.close()
        finally:
            writer.close()
            with suppress(OSError):
                await writer.wait_closed()
