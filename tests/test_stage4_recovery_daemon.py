from __future__ import annotations

import asyncio
import json
import plistlib
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from nextloop import (
    CandidateRequest,
    EventType,
    FinishReason,
    ModelResponse,
    NewEvent,
    SQLiteEventStore,
)

from nika.cli import main as cli_main
from nika.cli import run_cli
from nika.contracts import (
    IngressEnvelope,
    IngressSource,
    ReplyKind,
    ReplyTarget,
    SpecialistId,
    TaskStatus,
)
from nika.db import NikaLedger
from nika.feishu import FeishuAdapter, RecordedFeishuTransport
from nika.feishu_doc import InMemoryFeishuDocStore, register_feishu_doc_tools
from nika.http_app import HttpDaemonDeps, NikaHttpServer
from nika.packs import SpecialistPack, load_specialist_packs
from nika.pocket import (
    LocalPocketContractServer,
    PocketAdapter,
    PocketAdapterDeps,
    PocketRpcClient,
    register_pocket_tools,
)
from nika.scheduler import ORCHESTRATION_TOOLS, NikaScheduler, SchedulerDeps
from nika.sessions import register_session_tools
from nika.tools import NikaToolRuntime
from nika.wiki import WikiMount, init_git_repo, register_wiki_tools
from nika.workspace import WorkspaceMount, register_workspace_tools

REPO_ROOT = Path(__file__).resolve().parent.parent


class _EchoProvider:
    async def complete(
        self,
        request: CandidateRequest,
        *,
        attempt: int,
        cancel: asyncio.Event,
    ) -> ModelResponse:
        del attempt, cancel
        last = request.messages[-1].content or ""
        return ModelResponse(
            content=f"ACK:{last[:40]}", finish_reason=FinishReason.STOP
        )


@dataclass
class _Stage4Stack:
    db_path: Path
    ledger: NikaLedger
    store: SQLiteEventStore
    tx: RecordedFeishuTransport
    pocket_srv: LocalPocketContractServer
    pocket_adapter: PocketAdapter
    sched: NikaScheduler


def _build_runtime_and_packs(
    tmp_path: Path,
    store: SQLiteEventStore,
    ledger: NikaLedger,
    client: httpx.AsyncClient,
) -> tuple[NikaToolRuntime, dict[SpecialistId, SpecialistPack]]:
    init_git_repo(tmp_path / "work", {"a.md": "# A\n"})
    init_git_repo(tmp_path / "personal", {"b.md": "# B\n"})
    (tmp_path / "ws").mkdir(exist_ok=True)
    (tmp_path / "scratch").mkdir(exist_ok=True)
    runtime = NikaToolRuntime()
    register_wiki_tools(
        runtime,
        WikiMount(
            tmp_path / "work",
            tmp_path / "personal",
            scratch_roots=(tmp_path / "scratch",),
        ),
        extra_read_roots=(tmp_path / "ws", tmp_path / "scratch"),
    )
    register_session_tools(runtime, store, ledger)
    register_workspace_tools(
        runtime,
        WorkspaceMount(
            roots=(tmp_path / "ws",),
            scratch_roots=(tmp_path / "scratch",),
            denied_write_roots=(tmp_path / "work", tmp_path / "personal"),
        ),
    )
    register_feishu_doc_tools(runtime, InMemoryFeishuDocStore())
    register_pocket_tools(
        runtime, PocketRpcClient("http://pocket.local", "tok", client)
    )
    packs = load_specialist_packs(
        REPO_ROOT / "specialists",
        available_tools=[
            *(s.name for s in runtime.catalog()),
            *ORCHESTRATION_TOOLS,
        ],
        shared_skills_dir=REPO_ROOT / "skills",
    )
    return runtime, packs


@asynccontextmanager
async def _stage4_stack(tmp_path: Path) -> AsyncIterator[_Stage4Stack]:
    db_path = tmp_path / "nika.db"
    ledger = NikaLedger(db_path)
    store = SQLiteEventStore(str(db_path))
    tx = RecordedFeishuTransport()
    srv = LocalPocketContractServer(agent_token="tok")
    async with httpx.AsyncClient(
        transport=srv.asgi_transport(), base_url="http://pocket.local"
    ) as client:
        runtime, packs = _build_runtime_and_packs(
            tmp_path, store, ledger, client
        )
        p_adapter = PocketAdapter(
            PocketAdapterDeps(
                webhook_secret="pkt_wh_sec",
                http_client=client,
                feishu_transport=tx,
                owner_dm_channel="oc_owner",
                allowed_callback_origin="http://pocket.local",
            )
        )
        sched = NikaScheduler(
            SchedulerDeps(
                ledger=ledger,
                store=store,
                provider=_EchoProvider(),
                runtime=runtime,
                packs=packs,
                feishu_transport=tx,
                pocket_callback_sender=p_adapter.deliver_callback,
            )
        )
        p_adapter.bind_scheduler(sched)
        try:
            yield _Stage4Stack(
                db_path=db_path,
                ledger=ledger,
                store=store,
                tx=tx,
                pocket_srv=srv,
                pocket_adapter=p_adapter,
                sched=sched,
            )
        finally:
            await sched.close()
    store.close()
    await ledger.close()


async def _seed_running_task(
    ledger: NikaLedger,
    store: SQLiteEventStore,
    event_id: str,
    events: list[NewEvent],
) -> str:
    dec = await ledger.accept_ingress(
        IngressEnvelope(
            event_id=event_id,
            source=IngressSource.FEISHU,
            thread_key=f"feishu:dm:{event_id}",
            prompt=f"prompt {event_id}",
            reply_target=ReplyTarget(ReplyKind.FEISHU_CARD, f"oc_{event_id}"),
        )
    )
    assert dec.task is not None
    await ledger.set_task_status(dec.task.task_id, TaskStatus.RUNNING)
    epoch, seq, _ = await store.attach_writer(dec.task.session_id, force=True)
    await store.append(dec.task.session_id, epoch, seq + 1, events)
    return dec.task.task_id


async def _seed_crash_states(
    ledger: NikaLedger, store: SQLiteEventStore
) -> tuple[str, str, str]:
    pend_id = await _seed_running_task(
        ledger,
        store,
        "ev_pend",
        [
            NewEvent(EventType.TURN_START, 1, 0, payload={"input_id": "e1"}),
            NewEvent(
                EventType.FINAL_MESSAGE,
                1,
                1,
                payload={
                    "final_message_id": "fm_crash_1",
                    "content": "RECOVERED_FINAL_OK",
                },
            ),
        ],
    )
    mid_id = await _seed_running_task(
        ledger,
        store,
        "ev_mid",
        [NewEvent(EventType.TURN_START, 1, 0, payload={"input_id": "e2"})],
    )
    d_q = await ledger.accept_ingress(
        IngressEnvelope(
            event_id="ev_queued",
            source=IngressSource.FEISHU,
            thread_key="feishu:dm:oc_q",
            prompt="queued before crash",
            reply_target=ReplyTarget(ReplyKind.FEISHU_CARD, "oc_q"),
        )
    )
    assert d_q.task is not None
    return pend_id, mid_id, d_q.task.task_id


async def test_crash_recovery_redelivers_unwedges_and_resumes_queued(
    tmp_path: Path,
) -> None:
    async with _stage4_stack(tmp_path) as st:
        pend_id, mid_id, q_id = await _seed_crash_states(st.ledger, st.store)
        report = await st.sched.recover()
        await st.sched.drain()
        assert (
            report.redelivered,
            report.failed_interrupted,
            report.resumed_queued,
        ) == (1, 1, 1)
        t_pend = await st.ledger.get_task(pend_id)
        t_mid = await st.ledger.get_task(mid_id)
        t_q = await st.ledger.get_task(q_id)
        assert t_pend is not None and t_pend.status == TaskStatus.DONE
        assert t_mid is not None and t_mid.status == TaskStatus.FAILED
        assert await st.ledger.get_active_task("feishu:dm:ev_mid") is None
        assert t_q is not None and t_q.status == TaskStatus.DONE
        assert any("RECOVERED_FINAL_OK" in t for t in st.tx.final_card_texts)
        assert any(
            "ACK:queued before crash" in t for t in st.tx.final_card_texts
        )


async def _exercise_feishu_http(http: httpx.AsyncClient) -> None:
    hz = await http.get("/healthz")
    assert hz.status_code == 200 and hz.json()["status"] == "ok"

    bad_fs = await http.post(
        "/webhooks/feishu",
        json={"type": "url_verification", "token": "wrong", "challenge": "c1"},
    )
    assert bad_fs.status_code == 401

    ok_ch = await http.post(
        "/webhooks/feishu",
        json={
            "type": "url_verification",
            "token": "fs_v_tok",
            "challenge": "c_ok",
        },
    )
    assert ok_ch.status_code == 200 and ok_ch.json() == {"challenge": "c_ok"}

    fs_msg = await http.post(
        "/webhooks/feishu",
        json={
            "header": {
                "token": "fs_v_tok",
                "event_type": "im.message.receive_v1",
            },
            "event": {
                "sender": {"sender_id": {"open_id": "ou_owner"}},
                "message": {
                    "message_id": "om_http_1",
                    "chat_id": "oc_http",
                    "content": json.dumps({"text": "hello http"}),
                },
            },
        },
    )
    assert fs_msg.status_code == 200


async def _exercise_pocket_http(http: httpx.AsyncClient) -> None:
    bad_pk = await http.post(
        "/webhooks/pocket",
        headers={"Authorization": "Bearer wrong"},
        json={},
    )
    assert bad_pk.status_code == 401

    ok_pk = await http.post(
        "/webhooks/pocket",
        headers={"Authorization": "Bearer pkt_wh_sec"},
        json={
            "delivery_id": "del_http_1",
            "todo_id": "td_1",
            "agent_id": "nika",
            "prompt": "quiet sync",
            "scheduled_for": "2026-11-25T09:00:00Z",
            "result_callback_url": (
                "http://pocket.local/v1/deliveries/del_http_1/result"
            ),
            "callback_token": "cb_tok_1",
        },
    )
    assert ok_pk.status_code == 202


async def test_h11_http_daemon_healthz_feishu_and_pocket_webhooks(
    tmp_path: Path,
) -> None:
    async with _stage4_stack(tmp_path) as st:
        st.pocket_srv.seed_delivery("del_http_1", "cb_tok_1")
        feishu = FeishuAdapter(
            scheduler=st.sched, allowlist=frozenset({"ou_owner"})
        )
        daemon = NikaHttpServer(
            HttpDaemonDeps(
                feishu_adapter=feishu,
                pocket_adapter=st.pocket_adapter,
                feishu_verification_token="fs_v_tok",
            )
        )
        port = await daemon.start("127.0.0.1", 0)
        try:
            async with httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{port}"
            ) as http:
                await _exercise_feishu_http(http)
                await _exercise_pocket_http(http)
            await st.sched.drain()
            assert "ACK:hello http" in st.tx.final_card_texts
            summary = st.pocket_srv.deliveries["del_http_1"]["result_summary"]
            assert summary == "ACK:quiet sync"
        finally:
            await daemon.close()


def _verify_cli_sync(tmp_path: Path, db_path: Path, fake_tok: str) -> None:
    assert callable(cli_main)
    bak_path = tmp_path / "backup.db"
    assert (
        run_cli(["backup", "--db", str(db_path), "--out", str(bak_path)]) == 0
    )
    with sqlite3.connect(str(bak_path)) as bconn:
        cnt = bconn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        assert cnt == 1

    exp_dir = tmp_path / "exports"
    assert run_cli(["export", "--db", str(db_path), "--out", str(exp_dir)]) == 0
    exported_raw = (exp_dir / "main.jsonl").read_text(encoding="utf-8")
    assert fake_tok not in exported_raw and "[REDACTED]" in exported_raw
    row = json.loads(exported_raw.splitlines()[0])
    assert row["specialist"] == "main" and len(row["messages"]) >= 2
    assert (
        run_cli(
            ["recover", "--db", str(db_path), "--repo-root", str(REPO_ROOT)]
        )
        == 0
    )


async def test_cli_check_backup_export_recover_and_launchd_plist(
    tmp_path: Path,
) -> None:
    plist_path = REPO_ROOT / "deploy" / "com.nika.daemon.plist"
    plist_data = plistlib.loads(plist_path.read_bytes())
    assert plist_data["Label"] == "com.nika.daemon"
    assert plist_data["KeepAlive"] is True

    db_check = tmp_path / "chk.db"
    rc = await asyncio.to_thread(
        run_cli, ["check", "--repo-root", str(REPO_ROOT), "--db", str(db_check)]
    )
    assert rc == 0

    fake_tok = "sk-" + ("redactme99" * 2)
    async with _stage4_stack(tmp_path) as st:
        await st.sched.ingest(
            IngressEnvelope(
                event_id="ev_exp",
                source=IngressSource.FEISHU,
                thread_key="feishu:dm:oc_exp",
                prompt=f"my token is {fake_tok}",
                reply_target=ReplyTarget(ReplyKind.FEISHU_CARD, "oc_exp"),
            )
        )
        await st.sched.drain()
        target_db = st.db_path
    await asyncio.to_thread(_verify_cli_sync, tmp_path, target_db, fake_tok)


async def _check_http_fail_closed(feishu: FeishuAdapter) -> None:
    unauth = NikaHttpServer(HttpDaemonDeps(feishu_adapter=feishu))
    p0 = await unauth.start("127.0.0.1", 0)
    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{p0}") as h0:
            r0 = await h0.post(
                "/webhooks/feishu",
                json={"type": "url_verification", "challenge": "x"},
            )
            assert r0.status_code == 401
    finally:
        await unauth.close()


async def _check_http_null_root(st: _Stage4Stack) -> None:
    feishu = FeishuAdapter(
        scheduler=st.sched, allowlist=frozenset({"ou_owner"})
    )
    await _check_http_fail_closed(feishu)
    srv = NikaHttpServer(
        HttpDaemonDeps(feishu_adapter=feishu, feishu_verification_token="fs_ok")
    )
    p1 = await srv.start("127.0.0.1", 0)
    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{p1}") as h1:
            bad_utf = await h1.post(
                "/webhooks/feishu",
                json={
                    "type": "url_verification",
                    "token": "坏token",
                    "challenge": "c",
                },
            )
            assert bad_utf.status_code == 401
            ok_null = await h1.post(
                "/webhooks/feishu",
                json={
                    "header": {"token": "fs_ok"},
                    "event": {
                        "sender": {"sender_id": {"open_id": "ou_owner"}},
                        "message": {
                            "message_id": "om_null_root",
                            "chat_id": "oc_dm_real",
                            "root_id": None,
                            "content": json.dumps(
                                {
                                    "text": 'cfg {"callback_token":"cbt_9988776655"}'
                                }
                            ),
                        },
                    },
                },
            )
            assert ok_null.status_code == 200
        await st.sched.drain()
        dm_tasks = await st.ledger.list_tasks_for_thread("feishu:dm:oc_dm_real")
        assert len(dm_tasks) == 1
    finally:
        await srv.close()


async def _verify_offline_recover_and_cli_guards(
    tmp_path: Path, target_db: Path, ids: tuple[str, str]
) -> None:
    rc_rec = await asyncio.to_thread(
        run_cli,
        ["recover", "--db", str(target_db), "--repo-root", str(REPO_ROOT)],
    )
    assert rc_rec == 0
    check_ledger = NikaLedger(target_db)
    try:
        q_after = await check_ledger.get_task(ids[1])
        p_after = await check_ledger.get_task(ids[0])
        assert q_after is not None and q_after.status == TaskStatus.QUEUED
        assert p_after is not None and p_after.status == TaskStatus.BLOCKED
    finally:
        await check_ledger.close()

    sym_out = tmp_path / "sym_bak.db"
    sym_out.symlink_to(tmp_path / "real_target.db")
    with pytest.raises(PermissionError):
        await asyncio.to_thread(
            run_cli, ["backup", "--db", str(target_db), "--out", str(sym_out)]
        )
    exp2 = tmp_path / "exp2"
    await asyncio.to_thread(
        run_cli, ["export", "--db", str(target_db), "--out", str(exp2)]
    )
    raw_jsonl = (exp2 / "main.jsonl").read_text(encoding="utf-8")
    assert "cbt_9988776655" not in raw_jsonl


async def test_stage4_blind_review_regressions(tmp_path: Path) -> None:
    async with _stage4_stack(tmp_path) as st:
        await _check_http_null_root(st)
        pend_id, _, q_id = await _seed_crash_states(st.ledger, st.store)
        target_db = st.db_path
    await _verify_offline_recover_and_cli_guards(
        tmp_path, target_db, (pend_id, q_id)
    )
