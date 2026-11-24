from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Awaitable, Callable, Mapping, MutableMapping
from dataclasses import dataclass, field
from typing import Any

import httpx
from nextloop import (
    Completed,
    ToolContext,
    ToolEffect,
    ToolExecutionMode,
    ToolSpec,
    new_id,
)

from .contracts import (
    IngressEnvelope,
    IngressSource,
    ReplyKind,
    ReplyTarget,
)
from .feishu import FeishuTransport, StopAndIngestTarget
from .tools import POCKET_READ_METHODS, NikaToolRuntime

POCKET_METHODS = (
    "event.list",
    "event.set",
    "event.delete",
    "todo.list",
    "todo.set",
    "todo.toggle",
    "todo.delete",
)
FEISHU_NOTIFY_KEYWORDS = (
    "飞书提醒",
    "飞书私聊",
    "发飞书",
    "feishu alert",
    "ping me",
)


@dataclass(frozen=True)
class PocketWebhookRequest:
    delivery_id: str
    todo_id: str
    agent_id: str
    prompt: str
    scheduled_for: str
    result_callback_url: str
    callback_token: str = field(repr=False)


@dataclass(frozen=True)
class PocketAdapterDeps:
    webhook_secret: str
    http_client: httpx.AsyncClient
    feishu_transport: FeishuTransport
    owner_dm_channel: str = ""


class PocketRpcClient:
    def __init__(
        self, base_url: str, token: str, client: httpx.AsyncClient
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._client = client

    async def call(
        self,
        method: str,
        params: Mapping[str, Any],
        operation_id: str | None = None,
    ) -> Completed:
        if method not in POCKET_METHODS:
            return Completed(
                f"Unsupported Pocket method: {method}", is_error=True
            )
        body: dict[str, Any] = {"source": "agent", "params": dict(params)}
        if method not in POCKET_READ_METHODS:
            req_key = operation_id or new_id("op")
            body["request_id"] = f"nika_{req_key}"
        resp = await self._client.post(
            f"{self._base_url}/v1/rpc/{method}",
            headers={"Authorization": f"Bearer {self._token}"},
            json=body,
        )
        payload: dict[str, Any] = resp.json()
        if resp.status_code >= 400:
            err = payload.get("error") or {}
            code = err.get("code", "RPC_ERROR")
            msg = err.get("message", resp.text)
            return Completed(f"{resp.status_code} {code}: {msg}", is_error=True)
        return Completed(
            json.dumps(payload.get("data", payload), ensure_ascii=False)
        )


POCKET_TOOL_SPEC = ToolSpec(
    name="pocket",
    description=(
        "Call Pocket calendar/todo RPC ('event.list', 'event.set', "
        "'event.delete', 'todo.list', 'todo.set', 'todo.toggle', 'todo.delete')."
    ),
    parameters={
        "type": "object",
        "properties": {
            "method": {"type": "string", "enum": list(POCKET_METHODS)},
            "params": {"type": "object"},
        },
        "required": ["method"],
        "additionalProperties": False,
    },
    mode=ToolExecutionMode.EXCLUSIVE,
    effect=ToolEffect.IDEMPOTENT,
)


def register_pocket_tools(
    runtime: NikaToolRuntime, rpc: PocketRpcClient
) -> None:
    async def _handle_pocket(
        args: Mapping[str, Any], ctx: ToolContext
    ) -> Completed:
        method = str(args.get("method", ""))
        raw_params = args.get("params")
        params = raw_params if isinstance(raw_params, Mapping) else {}
        return await rpc.call(method, params, operation_id=ctx.operation_id)

    runtime.register(POCKET_TOOL_SPEC, _handle_pocket)


def _wants_feishu_notify(prompt: str) -> bool:
    low = prompt.lower()
    if "不要发飞书" in prompt or "不发飞书" in prompt:
        return False
    return any(kw in low for kw in FEISHU_NOTIFY_KEYWORDS)


def _should_escalate(target: ReplyTarget, text: str) -> bool:
    if target.metadata.get("notify_requested"):
        return True
    upper = text.upper()
    return (
        "CLOUD_LOCKED" in upper
        or upper.startswith("ERROR")
        or "NEED_DECISION" in upper
    )


class PocketAdapter:
    def __init__(self, deps: PocketAdapterDeps) -> None:
        self._secret = deps.webhook_secret.strip()
        self._client = deps.http_client
        self._feishu = deps.feishu_transport
        self._owner_dm = deps.owner_dm_channel.strip()
        self._scheduler: StopAndIngestTarget | None = None

    def bind_scheduler(self, scheduler: StopAndIngestTarget) -> None:
        self._scheduler = scheduler

    def _verify_bearer(self, auth_header: str) -> bool:
        if not self._secret or not auth_header.startswith("Bearer "):
            return False
        provided = auth_header[7:].strip()
        return hmac.compare_digest(provided, self._secret)

    async def handle_webhook(
        self, auth_header: str, req: PocketWebhookRequest
    ) -> bool:
        if not self._verify_bearer(auth_header) or self._scheduler is None:
            return False
        did = req.delivery_id.strip()
        target = ReplyTarget(
            kind=ReplyKind.POCKET_CALLBACK,
            callback_url=req.result_callback_url,
            callback_token=req.callback_token,
            notify_channel_id=self._owner_dm,
            metadata={
                "delivery_id": did,
                "todo_id": req.todo_id,
                "notify_requested": _wants_feishu_notify(req.prompt),
            },
        )
        envelope = IngressEnvelope(
            event_id=f"pocket:{did}",
            source=IngressSource.POCKET,
            thread_key=f"pocket:delivery:{did}",
            prompt=req.prompt,
            reply_target=target,
            actor_id=req.agent_id,
        )
        await self._scheduler.ingest(envelope)
        return True

    async def deliver_callback(self, target: ReplyTarget, text: str) -> None:
        resp = await self._client.post(
            target.callback_url,
            headers={"Authorization": f"Bearer {target.callback_token}"},
            json={"result_summary": text},
        )
        if resp.status_code == 409:
            return
        resp.raise_for_status()
        if target.notify_channel_id and _should_escalate(target, text):
            await self._feishu.send_card(target.notify_channel_id, text)


def _events_overlap(items: list[dict[str, Any]]) -> bool:
    ordered = sorted(items, key=lambda e: str(e["start_hhmm"]))
    pairs = zip(ordered, ordered[1:], strict=False)
    return any(str(a["end_hhmm"]) > str(b["start_hhmm"]) for a, b in pairs)


class LocalPocketContractServer:
    def __init__(self, *, agent_token: str) -> None:
        self._token = agent_token
        self.events: dict[str, dict[str, Any]] = {}
        self.todos: dict[str, dict[str, Any]] = {}
        self.deliveries: dict[str, dict[str, Any]] = {}
        self._idempotency: dict[
            tuple[str, str], tuple[str, dict[str, Any]]
        ] = {}

    def seed_event(
        self,
        event_id: str,
        event_date: str,
        slot: tuple[str, str, str],
    ) -> None:
        start_hhmm, end_hhmm, title = slot
        self.events[event_id] = {
            "event_id": event_id,
            "event_date": event_date,
            "start_hhmm": start_hhmm,
            "end_hhmm": end_hhmm,
            "title": title,
        }

    def seed_todo(
        self,
        todo_id: str,
        text: str,
        *,
        # bits:allow(BCS004): test contract fixture helper
        locked: bool = False,
    ) -> None:
        self.todos[todo_id] = {
            "todo_id": todo_id,
            "text": text,
            "done": False,
            "locked": locked,
        }

    def seed_delivery(
        self,
        delivery_id: str,
        callback_token: str,
        status: str = "DISPATCHING",
    ) -> None:
        self.deliveries[delivery_id] = {
            "delivery_id": delivery_id,
            "callback_token": callback_token,
            "status": status,
            "result_summary": None,
        }

    def asgi_transport(self) -> httpx.ASGITransport:
        return httpx.ASGITransport(app=self._asgi_app)

    async def _asgi_app(
        self,
        scope: MutableMapping[str, Any],
        receive: Callable[[], Awaitable[MutableMapping[str, Any]]],
        send: Callable[[MutableMapping[str, Any]], Awaitable[None]],
    ) -> None:
        msg = await receive()
        raw_body = msg.get("body", b"")
        body: dict[str, Any] = json.loads(raw_body.decode()) if raw_body else {}
        headers = {
            k.decode().lower(): v.decode() for k, v in scope.get("headers", [])
        }
        status, resp_obj = self._dispatch_http(
            str(scope.get("path", "")), headers.get("authorization", ""), body
        )
        encoded = json.dumps(resp_obj, ensure_ascii=False).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": encoded})

    def _dispatch_http(
        self, path: str, auth: str, body: dict[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        if path == "/healthz":
            return 200, {"status": "ok"}
        if path.startswith("/v1/deliveries/") and path.endswith("/result"):
            did = path.split("/")[3]
            return self._handle_delivery_result(did, auth, body)
        if path.startswith("/v1/rpc/"):
            if auth != f"Bearer {self._token}":
                return (
                    401,
                    {"error": {"code": "UNAUTHORIZED", "message": "bad token"}},
                )
            return self._handle_rpc(path[len("/v1/rpc/") :], body)
        return 404, {"error": {"code": "NOT_FOUND", "message": path}}

    def _handle_delivery_result(
        self, did: str, auth: str, body: dict[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        rec = self.deliveries.get(did)
        if rec is None or auth != f"Bearer {rec['callback_token']}":
            return (
                401,
                {"error": {"code": "UNAUTHORIZED", "message": "bad cbk"}},
            )
        if rec["status"] in ("CANCELLED", "EXPIRED"):
            code = f"DELIVERY_{rec['status']}"
            return 409, {"error": {"code": code, "message": "stale delivery"}}
        rec["status"] = "COMPLETED"
        rec["result_summary"] = body.get("result_summary", "")
        return 200, {"data": {"delivery_id": did, "status": "COMPLETED"}}

    def _handle_rpc(
        self, method: str, body: dict[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        params: dict[str, Any] = dict(body.get("params") or {})
        req_id = str(body.get("request_id", ""))
        p_hash = hashlib.sha256(
            json.dumps(params, sort_keys=True).encode()
        ).hexdigest()
        if req_id and (method, req_id) in self._idempotency:
            prev_hash, prev_resp = self._idempotency[(method, req_id)]
            if prev_hash != p_hash:
                return (
                    409,
                    {
                        "error": {
                            "code": "IDEMPOTENCY_CONFLICT",
                            "message": "mismatch",
                        }
                    },
                )
            return 200, prev_resp
        status, out = self._exec_rpc_method(method, params)
        if status == 200 and req_id:
            self._idempotency[(method, req_id)] = (p_hash, out)
        return status, out

    def _exec_rpc_method(
        self, method: str, params: dict[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        if method == "event.list":
            s_d = str(params.get("start_date", "0000-00-00"))
            e_d = str(params.get("end_date", "9999-99-99"))
            items = [
                e
                for e in self.events.values()
                if s_d <= str(e["event_date"]) <= e_d
            ]
            return 200, {
                "data": {
                    "events": items,
                    "has_conflict": _events_overlap(items),
                }
            }
        if method == "event.set":
            eid = str(params.get("event_id") or f"ev_{len(self.events) + 1}")
            self.events[eid] = {
                "event_id": eid,
                "event_date": params["event_date"],
                "start_hhmm": params["start_hhmm"],
                "end_hhmm": params["end_hhmm"],
                "title": params["title"],
            }
            return 200, {"data": self.events[eid]}
        if method == "todo.list":
            return 200, {"data": {"todos": list(self.todos.values())}}
        if method in ("todo.toggle", "todo.set", "todo.delete"):
            return self._mutate_todo(method, params)
        return 400, {"error": {"code": "BAD_METHOD", "message": method}}

    def _mutate_todo(
        self, method: str, params: dict[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        tid = str(params.get("todo_id") or f"td_{len(self.todos) + 1}")
        existing = self.todos.get(tid)
        if existing is not None and existing.get("locked"):
            return 409, {
                "error": {
                    "code": "CLOUD_LOCKED",
                    "message": f"Todo '{tid}' is locked on phone device",
                }
            }
        if method == "todo.delete":
            self.todos.pop(tid, None)
            return 200, {"data": {"deleted": tid}}
        if method == "todo.toggle" and existing is not None:
            existing["done"] = not bool(existing["done"])
            return 200, {"data": existing}
        self.todos[tid] = {
            "todo_id": tid,
            "text": str(params.get("text", "")),
            "done": bool(params.get("done", False)),
            "locked": False,
        }
        return 200, {"data": self.todos[tid]}
