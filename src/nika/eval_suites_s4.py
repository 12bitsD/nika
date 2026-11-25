from __future__ import annotations

import asyncio
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx
from nextloop import ModelProvider, SQLiteEventStore

from .cli import run_cli
from .db import NikaLedger
from .eval_runner import EvalCaseResult, run_cases_bounded
from .feishu import FeishuAdapter, RecordedFeishuTransport
from .feishu_doc import InMemoryFeishuDocStore, register_feishu_doc_tools
from .http_app import HttpDaemonDeps, NikaHttpServer
from .packs import load_specialist_packs
from .pocket import (
    LocalPocketContractServer,
    PocketAdapter,
    PocketAdapterDeps,
    PocketRpcClient,
    register_pocket_tools,
)
from .scheduler import ORCHESTRATION_TOOLS, NikaScheduler, SchedulerDeps
from .sessions import register_session_tools
from .tools import NikaToolRuntime
from .wiki import WikiMount, init_git_repo, register_wiki_tools
from .workspace import WorkspaceMount, register_workspace_tools


@dataclass(frozen=True)
class _DaemonCanaryEnv:
    db_path: Path
    ledger: NikaLedger
    store: SQLiteEventStore
    pocket_client: httpx.AsyncClient
    pocket_srv: LocalPocketContractServer
    tx: RecordedFeishuTransport
    sched: NikaScheduler
    daemon: NikaHttpServer

    async def close(self) -> None:
        await self.daemon.close()
        await self.sched.close()
        await self.pocket_client.aclose()
        self.store.close()
        await self.ledger.close()


def _build_canary_tools(
    tmp: Path,
    store: SQLiteEventStore,
    ledger: NikaLedger,
    client: httpx.AsyncClient,
) -> NikaToolRuntime:
    init_git_repo(
        tmp / "work",
        {"ops/port.md": "# Ops\n\n## CanaryPort\ndaemon_port=8791\n"},
    )
    init_git_repo(tmp / "personal", {"notes/n.md": "# N\n"})
    (tmp / "ws").mkdir(exist_ok=True)
    (tmp / "scratch").mkdir(exist_ok=True)
    runtime = NikaToolRuntime()
    register_wiki_tools(
        runtime,
        WikiMount(
            tmp / "work", tmp / "personal", scratch_roots=(tmp / "scratch",)
        ),
        extra_read_roots=(tmp / "ws", tmp / "scratch"),
    )
    register_session_tools(runtime, store, ledger)
    register_workspace_tools(
        runtime,
        WorkspaceMount(
            roots=(tmp / "ws",),
            scratch_roots=(tmp / "scratch",),
            denied_write_roots=(tmp / "work", tmp / "personal"),
        ),
    )
    register_feishu_doc_tools(runtime, InMemoryFeishuDocStore())
    register_pocket_tools(
        runtime, PocketRpcClient("http://pocket.local", "pkt_tok", client)
    )
    return runtime


def _make_canary_pocket(
    client: httpx.AsyncClient, tx: RecordedFeishuTransport
) -> PocketAdapter:
    return PocketAdapter(
        PocketAdapterDeps(
            webhook_secret="pkt_wh_canary",
            http_client=client,
            feishu_transport=tx,
            owner_dm_channel="oc_canary",
            allowed_callback_origin="http://pocket.local",
        )
    )


def _setup_daemon_canary(
    tmp: Path, provider: ModelProvider, repo_root: Path
) -> _DaemonCanaryEnv:
    ledger = NikaLedger(tmp / "nika.db")
    store = SQLiteEventStore(str(tmp / "nika.db"))
    srv = LocalPocketContractServer(agent_token="pkt_tok")
    srv.seed_delivery("del_s4_canary", "cb_s4_tok")
    client = httpx.AsyncClient(
        transport=srv.asgi_transport(), base_url="http://pocket.local"
    )
    tx = RecordedFeishuTransport()
    runtime = _build_canary_tools(tmp, store, ledger, client)
    packs = load_specialist_packs(
        repo_root / "specialists",
        available_tools=[
            *(s.name for s in runtime.catalog()),
            *ORCHESTRATION_TOOLS,
        ],
        shared_skills_dir=repo_root / "skills",
    )
    p_adapter = _make_canary_pocket(client, tx)
    sched = NikaScheduler(
        SchedulerDeps(
            ledger=ledger,
            store=store,
            provider=provider,
            runtime=runtime,
            packs=packs,
            feishu_transport=tx,
            shared_skills_dir=repo_root / "skills",
            pocket_callback_sender=p_adapter.deliver_callback,
        )
    )
    p_adapter.bind_scheduler(sched)
    daemon = NikaHttpServer(
        HttpDaemonDeps(
            feishu_adapter=FeishuAdapter(
                scheduler=sched, allowlist=frozenset({"ou_eval"})
            ),
            pocket_adapter=p_adapter,
            feishu_verification_token="fs_canary_tok",
        )
    )
    return _DaemonCanaryEnv(
        tmp / "nika.db", ledger, store, client, srv, tx, sched, daemon
    )


async def _drive_canary_requests(port: int) -> tuple[int, int, int]:
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as http:
        hz = await http.get("/healthz")
        q = "查一下 work 知识库 ops/port.md 里 CanaryPort 章节的端口号是多少？"
        fs = await http.post(
            "/webhooks/feishu",
            json={
                "header": {
                    "token": "fs_canary_tok",
                    "event_type": "im.message.receive_v1",
                },
                "event": {
                    "sender": {"sender_id": {"open_id": "ou_eval"}},
                    "message": {
                        "message_id": "om_s4_1",
                        "chat_id": "oc_s4",
                        "content": json.dumps({"text": q}),
                    },
                },
            },
        )
        pk = await http.post(
            "/webhooks/pocket",
            headers={"Authorization": "Bearer pkt_wh_canary"},
            json={
                "delivery_id": "del_s4_canary",
                "todo_id": "td_s4",
                "agent_id": "nika",
                "prompt": "不要发飞书提醒，直接回复收到巡检任务 OK。",
                "scheduled_for": "2026-11-25T10:00:00Z",
                "result_callback_url": (
                    "http://pocket.local/v1/deliveries/del_s4_canary/result"
                ),
                "callback_token": "cb_s4_tok",
            },
        )
        return hz.status_code, fs.status_code, pk.status_code


def _verify_backup_and_export_sync(tmp: Path, db_path: Path) -> bool:
    exp_dir = tmp / "exp"
    bak_db = tmp / "bak.db"
    rc_bak = run_cli(["backup", "--db", str(db_path), "--out", str(bak_db)])
    rc_exp = run_cli(["export", "--db", str(db_path), "--out", str(exp_dir)])
    return rc_bak == 0 and rc_exp == 0 and (exp_dir / "main.jsonl").is_file()


async def _s4_live_daemon_webhooks_backup_and_export(
    provider: ModelProvider, repo_root: Path
) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        env = _setup_daemon_canary(tmp, provider, repo_root)
        try:
            await env.sched.recover()
            port = await env.daemon.start("127.0.0.1", 0)
            codes = await _drive_canary_requests(port)
            await env.sched.drain()
            fs_ok = any("8791" in t for t in env.tx.final_card_texts)
            pk_summary = str(
                env.pocket_srv.deliveries["del_s4_canary"]["result_summary"]
                or ""
            )
        finally:
            await env.close()
        cli_ok = await asyncio.to_thread(
            _verify_backup_and_export_sync, tmp, env.db_path
        )
        ok = codes == (200, 200, 202) and fs_ok and bool(pk_summary) and cli_ok
        return ok, f"http={codes} fs_8791={fs_ok} cli_ok={cli_ok}"


async def run_stage4_evals(
    provider: ModelProvider, repo_root: Path
) -> list[EvalCaseResult]:
    return await run_cases_bounded(
        (
            (
                "S4",
                "S4_http_daemon_live_canary_backup_export",
                lambda: _s4_live_daemon_webhooks_backup_and_export(
                    provider, repo_root
                ),
            ),
        )
    )
